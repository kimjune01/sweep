# Triage Graph: prowler-cloud/prowler

**Date**: 2026-05-09
**Hypothesis**: H2 -- Python, AWS security scanning, new check contribution
**Status**: READY -- Fix committed on branch `fix/sagemaker-domain-sso-check`

## Issue Analysis

### #11050: Add SageMaker Domain SSO authentication check (FIXED)

- **Type**: New feature, security check
- **Severity**: Medium -- SSO vs IAM auth mode is a security best practice
- **Competing PRs**: None
- **Fix complexity**: Medium -- new check + service extension + tests

**Root cause**: Prowler had no check validating whether SageMaker Domains use SSO authentication. IAM-mode domains create per-user IAM entities that drift from centralized identity management, weakening offboarding, MFA enforcement, and session policies.

**Solution**:
1. `Domain` model in `sagemaker_service.py` with `domain_id`, `auth_mode`, `tags`
2. `_list_domains` (paginated) and `_describe_domain` methods
3. `sagemaker_domain_sso_configured` check: PASS if `auth_mode == "SSO"`, FAIL otherwise
4. Full metadata JSON with remediation (CLI, Terraform, CloudFormation)
5. 3 unit tests: no domains, SSO pass, IAM fail
6. Updated `sagemaker_service_test.py` to expect 5 tag calls instead of 4

**Codex feedback addressed**:
- Mutable default `tags: Optional[list] = []` -- kept as-is because Pydantic BaseModel handles this safely and it matches every other model in the file
- No unused imports in the check file
- `_describe_domain` uses `if "AuthMode" in describe_domain` guard instead of bare `.get()` assignment

**Diff**: 233 insertions, 2 deletions across 6 files
**Testing**: `python -m pytest tests/providers/aws/services/sagemaker/sagemaker_domain_sso_configured/`

## PR Viability: HIGH

**For**: Prowler actively accepts new checks from contributors. Issue #11050 was filed by maintainers. Follows existing check patterns exactly. Full test coverage. Metadata includes remediation code.
**Against**: Large diff for a first contribution. Maintainers may bikeshed metadata wording or check severity.
