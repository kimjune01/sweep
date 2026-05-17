"""Deterministic attestation verifier.

The LLM-driven side (qa_one_entry, /investigate's local checks) writes
attestation artifacts and can be wrong about the verdict — most
infamously, it can read "0 tests failed" as "pass" when actually 0
tests ran (silent skip: filter mismatch, missing toolchain, test
collected as ignored). This module is the mechanical gate: pure
parser, no LLM, three checks. Submit-actor and respond-actor call
verify_test_attestation before pushing. No valid attestation → no
push.

This split — production is vibes, verification is mechanical — is the
load-bearing discipline. The vibes can drift, the parser doesn't.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


# Pattern: `running N tests` (libtest, libtest-mimic). Captures N.
_RUNNING_RE = re.compile(r"^running (\d+) tests?$", re.MULTILINE)
# Pattern: `test result: ok. P passed; F failed; I ignored; …` etc.
_RESULT_RE = re.compile(
    r"^test result:\s+\w+\.\s+"
    r"(?P<passed>\d+)\s+passed;\s+"
    r"(?P<failed>\d+)\s+failed;\s+"
    r"(?P<ignored>\d+)\s+ignored",
    re.MULTILINE,
)


@dataclass
class TestParsedFacts:
    """What the parser actually saw in the captured test stdout. These
    are the ground truth that overrides any verdict the LLM claimed."""

    tests_run: int
    tests_passed: int
    tests_failed: int
    tests_ignored: int
    expected_test_present: bool


@dataclass
class VerifyResult:
    ok: bool
    reason: str
    facts: TestParsedFacts | None


def verify_test_attestation(
    stdout_text: str,
    expected_test_name: str,
) -> VerifyResult:
    """Parse a captured test-run stdout and decide pass/fail by mechanical
    rules. Three must all hold:

      1. tests_run > 0 — the test runner actually executed something.
         Silent-skip case (1100 filtered, 0 ran) fails here.
      2. expected_test_name appears verbatim in stdout — the test we
         authored to demonstrate the bug was in the executed set.
      3. tests_failed == 0 — no failures.

    Anything else returns ok=False with a specific reason. Callers
    (submit-actor / respond-actor) use ok=True as the gate."""
    # Sum across multiple `running N tests` blocks (cargo test runs
    # multiple test binaries; each emits its own banner).
    tests_run = sum(int(m.group(1)) for m in _RUNNING_RE.finditer(stdout_text))

    # Sum results across all blocks too.
    passed = failed = ignored = 0
    found_any_result = False
    for m in _RESULT_RE.finditer(stdout_text):
        found_any_result = True
        passed += int(m.group("passed"))
        failed += int(m.group("failed"))
        ignored += int(m.group("ignored"))

    expected_present = expected_test_name in stdout_text

    facts = TestParsedFacts(
        tests_run=tests_run,
        tests_passed=passed,
        tests_failed=failed,
        tests_ignored=ignored,
        expected_test_present=expected_present,
    )

    if not found_any_result:
        return VerifyResult(False, "no `test result:` line in stdout — runner didn't complete", facts)
    if tests_run == 0:
        return VerifyResult(False, f"0 tests ran (parsed `running 0 tests`); silent-skip case", facts)
    if not expected_present:
        return VerifyResult(
            False,
            f"expected test {expected_test_name!r} not found in stdout — "
            f"filter or test-name mismatch",
            facts,
        )
    if failed > 0:
        return VerifyResult(False, f"{failed} test(s) failed", facts)
    return VerifyResult(True, f"verified: {passed} passed, {failed} failed, {ignored} ignored", facts)


def _parsed_facts_dict(stdout: str, expected_test_name: str) -> dict:
    """Run the parser and return its findings as a dict — used inside
    the manifest's before/after blocks."""
    import hashlib
    r = verify_test_attestation(stdout, expected_test_name)
    f = r.facts
    return {
        "verified": r.ok,
        "verify_reason": r.reason,
        "tests_run": f.tests_run if f else 0,
        "tests_passed": f.tests_passed if f else 0,
        "tests_failed": f.tests_failed if f else 0,
        "tests_ignored": f.tests_ignored if f else 0,
        "expected_test_present": f.expected_test_present if f else False,
        "sha256": hashlib.sha256(stdout.encode()).hexdigest(),
    }


def write_attestation_files(
    attestation_dir: Path,
    *,
    test_cmd: str,
    expected_test_name: str,
    head_sha: str,
    host: str,
    test_env: str,
    after_stdout: str,
    elapsed_seconds: float,
    before_stdout: str | None = None,
) -> dict:
    """Write the committable attestation set into `attestation_dir`.
    Layout:
      manifest.json       — machine-readable summary (small, diff-friendly)
      after.txt           — captured test_cmd stdout on the fix branch
      before.txt          — captured test_cmd stdout on master (if provided)

    The split is the "fail on master, pass with fix" discipline made
    visible: the maintainer can re-run on both refs and compare. When
    a PR adds the test itself (test didn't exist on master), the
    before.txt captures `running 0 tests` and the manifest's
    before.expected_test_present=False makes that visible too.

    Returns the manifest dict so callers can write + decide in one pass.
    """
    attestation_dir.mkdir(parents=True, exist_ok=True)

    def _truncate(s: str) -> str:
        return s if len(s) <= 50_000 else s[-50_000:]

    after_facts = _parsed_facts_dict(after_stdout, expected_test_name)
    (attestation_dir / "after.txt").write_text(_truncate(after_stdout))

    manifest = {
        "kind": "test_attestation",
        "test_cmd": test_cmd,
        "expected_test_name": expected_test_name,
        "head_sha": head_sha,
        "host": host,
        "test_env": test_env,
        "elapsed_seconds": elapsed_seconds,
        "after": after_facts,
    }
    if before_stdout is not None:
        before_facts = _parsed_facts_dict(before_stdout, expected_test_name)
        (attestation_dir / "before.txt").write_text(_truncate(before_stdout))
        manifest["before"] = before_facts

    (attestation_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def gate_push(attestation_dir: Path) -> tuple[bool, str]:
    """Submit-actor / respond-actor calls this before invoking gh.
    Returns (ok, reason). Refuses push when:
      - manifest.json or after.txt missing
      - manifest.after.verified is False
      - re-parsed after.txt fails the deterministic check
      - before.txt is present AND its parsed verdict shows the test
        passed on master (fix would be unnecessary) — but the
        before-was-added case (0 tests on master) does NOT fail
        because the PR is adding the test fresh."""
    manifest_path = attestation_dir / "manifest.json"
    after_path = attestation_dir / "after.txt"
    if not manifest_path.exists():
        return False, f"no manifest.json at {manifest_path}"
    if not after_path.exists():
        return False, f"no after.txt at {after_path}"
    try:
        manifest = json.loads(manifest_path.read_text())
    except json.JSONDecodeError as e:
        return False, f"manifest malformed: {e}"
    after = manifest.get("after", {})
    if not after.get("verified"):
        return False, f"after marked verified=False: {after.get('verify_reason','?')}"
    expected = manifest.get("expected_test_name", "")
    result = verify_test_attestation(after_path.read_text(), expected)
    if not result.ok:
        return False, f"re-parse rejected after.txt: {result.reason}"
    # Optional before.txt sanity: if it exists AND the test was present
    # AND verdict shows it passed, the fix is unnecessary — reject.
    before_path = attestation_dir / "before.txt"
    if before_path.exists() and "before" in manifest:
        before = manifest["before"]
        if (before.get("expected_test_present") and before.get("tests_run", 0) > 0
                and before.get("tests_failed", 0) == 0):
            return False, ("before.txt shows the test passes on master too — "
                           "fix is unnecessary")
    return True, "attestation verified"
