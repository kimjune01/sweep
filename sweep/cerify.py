"""Cerify — single-activity contract verifier.

Run an activity in isolation. Capture inputs, outputs, recorded
side-effects (inbox writes, signal calls, observe events, subprocess
calls), wall time. Run it twice and diff to check the monoidal
contract: the second run should produce the same returned value and
the same recorded outputs — that's idempotence under captured
semantics.

Not a substitute for production routing — by design. Cerify is a
developer/operator tool for asking "what does this activity *say* it
did?" without the noise of the actor loop, signal racing, dedup, or
the rest of the queue.

Read-only by default: any activity surface that mutates external
state (gh pr edit, git push, …) is stubbed to record-the-attempt
and return success. To exercise real mutations, run the activity
through the live worker instead.
"""

from __future__ import annotations

import asyncio
import dataclasses
import subprocess
import time
from contextlib import contextmanager
from typing import Any, Callable


@dataclasses.dataclass
class Capture:
    inbox_writes: list[dict] = dataclasses.field(default_factory=list)
    signals: list[dict] = dataclasses.field(default_factory=list)
    events: list[dict] = dataclasses.field(default_factory=list)
    subprocess: list[dict] = dataclasses.field(default_factory=list)
    stubbed: list[dict] = dataclasses.field(default_factory=list)

    def asdict(self) -> dict:
        return dataclasses.asdict(self)


@contextmanager
def sandbox(*, stub_mutations: bool = True):
    """Patch the routing/signaling/observe/mutation surfaces and yield
    a ``Capture``. All patches are reverted on exit.

    With ``stub_mutations=True`` (default), surfaces that change
    external state (``amend._pr_edit_body``, sweep-repo ``git push``)
    are replaced with no-op success returns whose attempts are
    recorded in ``capture.stubbed``.
    """
    cap = Capture()

    from sweep import observe
    from sweep.activities import pr_state
    from sweep.activities import attest as attest_mod
    from sweep.activities import amend as amend_mod
    from sweep.activities import check as check_mod
    from dataclasses import asdict as _asdict

    # _signal_actor — recorded, not sent.
    orig_signal = pr_state._signal_actor

    async def stub_signal(actor: str, msg):
        cap.signals.append({"actor": actor, "msg_id": msg.msg_id})
        return None

    pr_state._signal_actor = stub_signal

    # Per-module _append — captured instead of writing to ~/.sweep.
    orig_appends: dict[str, Callable] = {}
    for mod_name, mod in [("attest", attest_mod), ("amend", amend_mod), ("check", check_mod)]:
        orig_appends[mod_name] = mod._append

        def make_stub(_mod_name: str):
            def stub_append(inbox, msg) -> None:
                cap.inbox_writes.append({
                    "from": _mod_name, "inbox": str(inbox),
                    "msg": _asdict(msg),
                })
            return stub_append

        mod._append = make_stub(mod_name)

    # observe.event — capture each emit; suppress disk write.
    orig_event = observe.event

    def stub_event(kind: str, **payload) -> None:
        cap.events.append({"kind": kind, **payload})

    observe.event = stub_event

    # subprocess.run — passthrough with metering. Most activities call
    # subprocess for git/gh; we let them through so the activity body
    # actually exercises, just record what happened.
    orig_run = subprocess.run

    def metered_run(*args, **kwargs):
        t0 = time.time()
        r = orig_run(*args, **kwargs)
        cmd = args[0] if args else kwargs.get("args")
        cap.subprocess.append({
            "cmd": cmd if isinstance(cmd, list) else str(cmd)[:200],
            "rc": getattr(r, "returncode", None),
            "elapsed_ms": round((time.time() - t0) * 1000, 1),
        })
        return r

    subprocess.run = metered_run

    # Mutation stubs — only if requested.
    orig_pr_edit = amend_mod._pr_edit_body

    if stub_mutations:
        def stub_pr_edit(repo: str, pr: int, body: str) -> tuple[int, str]:
            cap.stubbed.append({
                "fn": "amend._pr_edit_body",
                "repo": repo, "pr": pr, "body_bytes": len(body),
            })
            return 0, ""
        amend_mod._pr_edit_body = stub_pr_edit

    try:
        yield cap
    finally:
        pr_state._signal_actor = orig_signal
        for mod_name, mod in [("attest", attest_mod), ("amend", amend_mod), ("check", check_mod)]:
            mod._append = orig_appends[mod_name]
        observe.event = orig_event
        subprocess.run = orig_run
        amend_mod._pr_edit_body = orig_pr_edit


_VOLATILE_MSG_KEYS = {"ts"}


def _normalize_msg(m: dict) -> dict:
    return {k: v for k, v in m.items() if k not in _VOLATILE_MSG_KEYS}


def _dedup_by_msg_id(writes: list[dict]) -> dict[str, dict]:
    """An inbox write's natural key is the msg_id — downstream actors
    dedup on it. Two writes with the same msg_id reach the same final
    state as one. Returns a dict keyed by msg_id with the normalized
    write (volatile fields stripped) as value, last-wins on key
    collision (semantically the same since normalized content matches).
    """
    out: dict[str, dict] = {}
    for w in writes:
        msg = _normalize_msg(w["msg"])
        out[msg["msg_id"]] = {**w, "msg": msg}
    return out


def _dedup_signals(signals: list[dict]) -> dict[tuple, dict]:
    """Signals dedup on (actor, msg_id) — Temporal's deliver signal is
    idempotent at the workflow's msg_id set."""
    return {(s["actor"], s["msg_id"]): s for s in signals}


def _dedup_stubbed_by_target(stubbed: list[dict]) -> dict[tuple, dict]:
    """A stubbed mutation's target state is what matters. Two mutations
    targeting the same (fn, repo, pr) with the same intended payload
    reach the same final state as one. We key on (fn, repo, pr) and
    keep the latest entry — if the entries themselves differ, that's a
    legitimate divergence and the per-activity equivalence handles it.
    """
    out: dict[tuple, dict] = {}
    for s in stubbed:
        key = (s.get("fn"), s.get("repo"), s.get("pr"))
        out[key] = s
    return out


# Per-activity returned-value equivalence. Default = strict equality;
# activities with non-trivial idempotents (f∘f = f, f ≠ I) override.
def _amend_returned_equiv(a: Any, b: Any) -> bool:
    """Amend's monoidal contract: applied and noop both signal "PR
    body is at target." So f∘f = f even when run 1 returns applied
    and run 2 returns noop — both leave the body in the splice's
    target state. Only the at-target boolean matters; kind / delta_bytes
    / reason are post-hoc descriptions of how we got there."""
    def at_target(r: Any) -> Any:
        if isinstance(r, dict) and r.get("status") in ("applied", "noop"):
            return "at_target"
        return r
    return at_target(a) == at_target(b)


_RETURNED_EQUIV: dict[str, Callable[[Any, Any], bool]] = {
    "amend_cycle": _amend_returned_equiv,
}


def _runs_equivalent(
    a: Capture, b: Capture, returned_a: Any, returned_b: Any,
    *, activity_name: str | None = None,
) -> tuple[bool, list[str]]:
    """Verify f∘f = f. State here = the deduplicated effect-set the
    activity would produce in the downstream system:

    - inbox writes deduplicate on msg_id (downstream dedup contract)
    - signals deduplicate on (actor, msg_id) (Temporal's deliver dedup)
    - stubbed mutations deduplicate on (fn, repo, pr) (target identity)

    Equivalence: ``dedup(cap_a) == dedup(cap_a + cap_b)``. If the
    second run adds no new distinct effects, the activity is
    monoidally idempotent. Returned-value comparison uses the
    activity's registered equivalence (default strict).

    Subprocess + observe events are excluded — they're noisy by design
    (timings drift, counters tick) and not part of the contract.
    """
    diffs: list[str] = []

    ret_equiv = _RETURNED_EQUIV.get(activity_name or "", lambda x, y: x == y)
    if not ret_equiv(returned_a, returned_b):
        diffs.append(f"returned: {returned_a!r} ≠ {returned_b!r}")

    a_writes = _dedup_by_msg_id(a.inbox_writes)
    ab_writes = _dedup_by_msg_id(a.inbox_writes + b.inbox_writes)
    if a_writes != ab_writes:
        new = set(ab_writes) - set(a_writes)
        diffs.append(f"inbox_writes: run 2 adds {len(new)} new msg_id(s) "
                     f"(would change downstream state): {sorted(new)[:3]}")

    a_sig = _dedup_signals(a.signals)
    ab_sig = _dedup_signals(a.signals + b.signals)
    if a_sig != ab_sig:
        new = set(ab_sig) - set(a_sig)
        diffs.append(f"signals: run 2 adds {len(new)} new signal(s): {sorted(new)[:3]}")

    a_stub = _dedup_stubbed_by_target(a.stubbed)
    ab_stub = _dedup_stubbed_by_target(a.stubbed + b.stubbed)
    if a_stub != ab_stub:
        new = set(ab_stub) - set(a_stub)
        diffs.append(f"stubbed mutations: run 2 adds {len(new)} new target(s): "
                     f"{sorted(new)[:3]}")

    return (not diffs, diffs)


async def cerify(activity, msg, *, stub_mutations: bool = True) -> dict:
    """Run ``activity(msg)`` twice in isolated sandboxes; return a
    report dict with both runs' captures, elapsed wall times, returned
    values, and the monoidal-equivalence verdict.
    """
    results: list[dict] = []
    for run_i in range(2):
        with sandbox(stub_mutations=stub_mutations) as cap:
            t0 = time.time()
            try:
                returned = await activity(msg)
                err = None
            except Exception as e:
                returned = None
                err = f"{type(e).__name__}: {e}"
            elapsed_ms = round((time.time() - t0) * 1000, 1)
        results.append({
            "returned": returned, "error": err,
            "elapsed_ms": elapsed_ms, "capture": cap,
        })

    # Activity name is used to look up per-activity returned-value
    # equivalence (amend's applied↔noop, etc.). Falls back to strict
    # equality for unregistered activities.
    activity_name = getattr(activity, "__name__", None)
    ok, diffs = _runs_equivalent(
        results[0]["capture"], results[1]["capture"],
        results[0]["returned"], results[1]["returned"],
        activity_name=activity_name,
    )
    return {
        "runs": results,
        "monoidal_ok": ok and results[0]["error"] is None,
        "monoidal_diffs": diffs,
    }


def render(report: dict) -> str:
    """Human-readable report. Two run blocks + a final monoidal verdict."""
    out: list[str] = []
    for i, r in enumerate(report["runs"], 1):
        cap: Capture = r["capture"]
        out.append(f"run {i}  ({r['elapsed_ms']}ms)")
        if r["error"]:
            out.append(f"  error:    {r['error']}")
        else:
            out.append(f"  returned: {r['returned']!r}")
        if cap.inbox_writes:
            out.append("  inbox writes:")
            for w in cap.inbox_writes:
                inbox = w["inbox"].rsplit("/", 1)[-1]
                m = w["msg"]
                out.append(
                    f"    {inbox:18s} intent={m.get('intent','?'):24s} "
                    f"sender={m.get('sender','?')}"
                )
        if cap.signals:
            out.append("  signals:")
            for s in cap.signals:
                out.append(f"    -> {s['actor']}  msg_id={s['msg_id']}")
        if cap.stubbed:
            out.append("  stubbed mutations:")
            for s in cap.stubbed:
                out.append(f"    {s['fn']}  {dict((k,v) for k,v in s.items() if k != 'fn')}")
        if cap.subprocess:
            n = len(cap.subprocess)
            tot = round(sum(s["elapsed_ms"] for s in cap.subprocess), 1)
            out.append(f"  subprocess: {n} call(s), {tot}ms")
        if cap.events:
            kinds = ", ".join(e["kind"] for e in cap.events[:5])
            more = "" if len(cap.events) <= 5 else f" +{len(cap.events)-5} more"
            out.append(f"  events:   {kinds}{more}")
        out.append("")

    if report["monoidal_ok"]:
        out.append("monoid check: ✓ idempotent (returned + writes + signals identical)")
    else:
        out.append("monoid check: ✗ NOT idempotent")
        for d in report["monoidal_diffs"]:
            out.append(f"  - {d}")
    return "\n".join(out)


def run(activity, msg, *, stub_mutations: bool = True) -> int:
    """Sync entry: cerify the activity, print the report, return exit
    code (0 ok, 2 monoidal failure, 3 first-run raised)."""
    report = asyncio.run(cerify(activity, msg, stub_mutations=stub_mutations))
    print(render(report))
    if report["runs"][0]["error"]:
        return 3
    if not report["monoidal_ok"]:
        return 2
    return 0
