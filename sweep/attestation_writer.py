"""Attestation writer — producer side.

Writes the committable test-attestation triple
(`<name>-manifest.json`, `<name>-after.txt`, `<name>-before.txt`)
into a directory. Records WHAT was run; says NOTHING about whether
it passed. The gate at push time decides that.

This split is load-bearing for fabrication-resistance ([[O10]]).
If the producer module also knew the verdict rules, an agent that
read this file could synthesize a stdout shape that satisfies them.
By design this module has no parser, no regex, no "verified" bit.
A fabricated after.txt would have to guess the gate's rules blind.

The gate lives in `sweep._gate` and is intentionally not imported
here. Do not add a verify/parser call to this module. If you find
yourself wanting to "double-check before writing," that check
belongs in the gate, not the producer.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


_TRUNCATE_BYTES = 50_000


def _truncate(s: str) -> str:
    return s if len(s) <= _TRUNCATE_BYTES else s[-_TRUNCATE_BYTES:]


def _facts(stdout: str) -> dict:
    """Per-stdout descriptive facts the producer is allowed to record:
    just byte-length and sha256. No parser output, no verdict — those
    belong in the gate."""
    body = _truncate(stdout)
    return {
        "bytes": len(body),
        "sha256": hashlib.sha256(body.encode()).hexdigest(),
    }


def write_attestation_files(
    attestation_dir: Path,
    name: str,
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
    """Write the attestation triple. Convention: `name` is
    `"issue-<n>"`, dir is `attestations/<org>-<repo>/`, so a repo
    reads as a flat list of all issues we've attested:

        attestations/wild-linker-wild/
          issue-1915-manifest.json
          issue-1915-after.txt
          issue-1915-before.txt
          issue-2000-manifest.json
          ...

    Returns the manifest dict (also written to disk)."""
    attestation_dir.mkdir(parents=True, exist_ok=True)

    after_body = _truncate(after_stdout)
    (attestation_dir / f"{name}-after.txt").write_text(after_body)

    manifest = {
        "kind": "test_attestation",
        "name": name,
        "test_cmd": test_cmd,
        "expected_test_name": expected_test_name,
        "head_sha": head_sha,
        "host": host,
        "test_env": test_env,
        "elapsed_seconds": elapsed_seconds,
        "after": _facts(after_body),
    }
    if before_stdout is not None:
        before_body = _truncate(before_stdout)
        (attestation_dir / f"{name}-before.txt").write_text(before_body)
        manifest["before"] = _facts(before_body)

    (attestation_dir / f"{name}-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n"
    )
    return manifest


_REMOTE_RE = re.compile(
    r"(?:git@github\.com[:/]|https?://github\.com/)([^/]+/[^/.]+)(?:\.git)?/?$"
)


def _parse_owner_repo(remote_url: str) -> str | None:
    m = _REMOTE_RE.search(remote_url.strip())
    return m.group(1) if m else None


def render_attestation_links_md(
    *,
    remote_url: str,
    commit_sha: str,
    org_repo: str,
    name: str,
    has_before: bool = True,
) -> str | None:
    """Render the triple-link footer pinned to ``commit_sha`` in the
    sweep repo at ``remote_url``. Returns None if the remote URL can't
    be parsed — the caller should treat that as "no public link."
    """
    owner_repo = _parse_owner_repo(remote_url)
    if not owner_repo:
        return None
    base = f"https://github.com/{owner_repo}/blob/{commit_sha}/attestations/{org_repo}"
    parts = []
    if has_before:
        parts.append(f"[Failing tests before]({base}/{name}-before.txt)")
    parts.append(f"[Passing tests after]({base}/{name}-after.txt)")
    parts.append(f"[How the tests ran]({base}/{name}-manifest.json)")
    return " / ".join(parts)
