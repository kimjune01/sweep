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


def write_attestation_files(
    prework_dir: Path,
    *,
    test_cmd: str,
    expected_test_name: str,
    head_sha: str,
    host: str,
    test_env: str,
    stdout: str,
    elapsed_seconds: float,
) -> dict:
    """Write the committable attestation pair (.json summary + .txt
    captured stdout) into `prework_dir`. The .json is small + diff-
    friendly; the .txt is truncated to 50KB so a maintainer can verify
    by re-running but the diff doesn't balloon.

    Returns the parsed summary dict (same as the .json content) so
    callers can both write to disk and decide push/no-push in one pass.
    """
    import hashlib

    prework_dir.mkdir(parents=True, exist_ok=True)
    truncated = stdout if len(stdout) <= 50_000 else stdout[-50_000:]
    sha = hashlib.sha256(stdout.encode()).hexdigest()

    result = verify_test_attestation(stdout, expected_test_name)
    facts = result.facts

    summary = {
        "kind": "test_attestation",
        "test_cmd": test_cmd,
        "expected_test_name": expected_test_name,
        "head_sha": head_sha,
        "host": host,
        "test_env": test_env,
        "elapsed_seconds": elapsed_seconds,
        "sha256_of_stdout": sha,
        "verified": result.ok,
        "verify_reason": result.reason,
        "tests_run": facts.tests_run if facts else 0,
        "tests_passed": facts.tests_passed if facts else 0,
        "tests_failed": facts.tests_failed if facts else 0,
        "tests_ignored": facts.tests_ignored if facts else 0,
        "expected_test_present": facts.expected_test_present if facts else False,
    }
    (prework_dir / "test-attestation.json").write_text(json.dumps(summary, indent=2) + "\n")
    (prework_dir / "test-attestation.txt").write_text(truncated)
    return summary


def gate_push(prework_dir: Path) -> tuple[bool, str]:
    """Submit-actor / respond-actor calls this before invoking gh.
    Returns (ok, reason). If the attestation file is missing or its
    `verified` field is False or its claimed facts disagree with a
    re-parse of the stored stdout, returns ok=False."""
    summary_path = prework_dir / "test-attestation.json"
    stdout_path = prework_dir / "test-attestation.txt"
    if not summary_path.exists():
        return False, f"no test-attestation.json at {summary_path}"
    if not stdout_path.exists():
        return False, f"no test-attestation.txt at {stdout_path}"
    try:
        summary = json.loads(summary_path.read_text())
    except json.JSONDecodeError as e:
        return False, f"attestation JSON malformed: {e}"
    if not summary.get("verified"):
        return False, f"attestation marked verified=False: {summary.get('verify_reason','?')}"
    # Re-parse stdout independently — don't trust the summary's claims.
    expected = summary.get("expected_test_name", "")
    result = verify_test_attestation(stdout_path.read_text(), expected)
    if not result.ok:
        return False, f"re-parse rejected attestation: {result.reason}"
    return True, "attestation verified"
