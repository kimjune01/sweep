"""Attestation verifier — gate side. DO NOT IMPORT FROM PRODUCER CODE.

Holds the parser rules that decide whether a captured test-run
attestation is honest. Three checks: a runner actually ran something
(tests_run > 0), the expected test name appears in stdout, no test
failed. This is the authoritative gate; the producer-side manifest
records facts but no verdict.

Fabrication-resistance ([[O10]]): the regex shapes and threshold
logic here are the rules an adversarial producer would need to
satisfy. Keeping them out of the producer's import graph means a
fresh-context agent that reads sweep/attestation_writer.py learns
that stdout gets hashed and committed, but not what shape of stdout
the gate accepts. To fabricate, the agent must guess.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path


_RUNNING_RE = re.compile(r"^running (\d+) tests?$", re.MULTILINE)
_RESULT_RE = re.compile(
    r"^test result:\s+\w+\.\s+"
    r"(?P<passed>\d+)\s+passed;\s+"
    r"(?P<failed>\d+)\s+failed;\s+"
    r"(?P<ignored>\d+)\s+ignored",
    re.MULTILINE,
)


@dataclass
class _Facts:
    tests_run: int
    tests_passed: int
    tests_failed: int
    tests_ignored: int
    expected_test_present: bool


@dataclass
class VerifyResult:
    ok: bool
    reason: str


def _parse(stdout: str, expected_test_name: str) -> _Facts:
    tests_run = sum(int(m.group(1)) for m in _RUNNING_RE.finditer(stdout))
    passed = failed = ignored = 0
    for m in _RESULT_RE.finditer(stdout):
        passed += int(m.group("passed"))
        failed += int(m.group("failed"))
        ignored += int(m.group("ignored"))
    return _Facts(
        tests_run=tests_run,
        tests_passed=passed,
        tests_failed=failed,
        tests_ignored=ignored,
        expected_test_present=expected_test_name in stdout,
    )


def _verify(stdout: str, expected_test_name: str) -> VerifyResult:
    if not _RESULT_RE.search(stdout):
        return VerifyResult(False, "no `test result:` line — runner didn't complete")
    f = _parse(stdout, expected_test_name)
    if f.tests_run == 0:
        return VerifyResult(False, "0 tests ran — silent-skip")
    if not f.expected_test_present:
        return VerifyResult(False, f"expected test {expected_test_name!r} not in stdout")
    if f.tests_failed > 0:
        return VerifyResult(False, f"{f.tests_failed} test(s) failed")
    return VerifyResult(True, f"{f.tests_passed} passed, {f.tests_ignored} ignored")


def gate_push(attestation_dir: Path, name: str) -> tuple[bool, str]:
    """Decide whether the attestation triple under `attestation_dir`
    permits a push. Returns (ok, reason). Refuses when:

      - manifest or after.txt missing
      - manifest malformed
      - producer-recorded sha256 of after doesn't match disk (tamper)
      - after.txt doesn't show a real successful test run
      - before.txt (if present) shows the test already passing on master
        (fix is unnecessary)

    This is the only function gate-callers (submit / respond) need.
    """
    manifest_path = attestation_dir / f"{name}-manifest.json"
    after_path = attestation_dir / f"{name}-after.txt"
    if not manifest_path.exists():
        return False, f"no {name}-manifest.json"
    if not after_path.exists():
        return False, f"no {name}-after.txt"
    try:
        manifest = json.loads(manifest_path.read_text())
    except json.JSONDecodeError as e:
        return False, f"manifest malformed: {e}"

    expected = manifest.get("expected_test_name", "")
    if not expected:
        return False, "manifest missing expected_test_name"

    after_body = after_path.read_text()
    recorded_sha = (manifest.get("after") or {}).get("sha256", "")
    if recorded_sha and hashlib.sha256(after_body.encode()).hexdigest() != recorded_sha:
        return False, "after.txt sha256 doesn't match manifest (tampered or rewritten)"

    after_check = _verify(after_body, expected)
    if not after_check.ok:
        return False, f"after rejected: {after_check.reason}"

    before_path = attestation_dir / f"{name}-before.txt"
    if before_path.exists():
        before_body = before_path.read_text()
        recorded_before_sha = (manifest.get("before") or {}).get("sha256", "")
        if recorded_before_sha and hashlib.sha256(before_body.encode()).hexdigest() != recorded_before_sha:
            return False, "before.txt sha256 doesn't match manifest (tampered)"
        before_facts = _parse(before_body, expected)
        if (before_facts.expected_test_present
                and before_facts.tests_run > 0
                and before_facts.tests_failed == 0):
            return False, "before.txt shows the test passes on master too — fix unnecessary"

    return True, f"attestation verified ({after_check.reason})"
