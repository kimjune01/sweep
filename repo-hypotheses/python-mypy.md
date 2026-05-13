# Triage Graph: python/mypy (kimjune01)

**Scan date:** 2026-05-09
**Mode:** dry-run

## Scan Table

| # | Title | State | Score | Effort | Signal | Status |
|---|-------|-------|-------|--------|--------|--------|
| 8603 | Bad error message for object member as base class | OPEN | 6/10 | Small-Medium (~20 lines) | JelleZijlstra invited PR | INVESTIGATED |

## T8603: "Name 'b.a' is not defined" → better error for attribute-access base class

### Root Cause

When using an object member as a base class (`class C(b.a): ...`), mypy reports "Name 'b.a' is not defined" instead of something like "Cannot use attribute access as base class." The error path in `semanal.py` doesn't distinguish between undefined names and structurally invalid base class expressions.

### Fix (~20 lines)

Add a check in the base class analysis path (semanal.py or semanal_main.py) for `MemberExpr` nodes. When the base class expression is an attribute access, emit a specific error message instead of falling through to the generic "not defined" path. Add test case reproducing the bad message.

### History

- Open since April 2020, 37+ thumbs-up
- JelleZijlstra (member) explicitly invited a PR in 2020
- PrasanthChettri attempted, got stuck on semanal internals, no PR
- No competing PRs currently open

### PR Viability: MODERATE-GOOD

**For:** Member explicitly invited the PR. High community demand (37+ thumbs-up, Flask-SQLAlchemy users). Error-message-only change — minimal behavioral risk. Clean field — no competition.
**Against:** 1/15 external merge rate overall. Tight core team (JukkaL ~60%, ilevkivskyi ~20%). Core team races externals on bug fixes. semanal.py is complex — previous contributor got stuck.

### Competing PRs

None.

### Risk

Medium. The invited-PR signal from a member is strong but 6 years old. semanal complexity could expand scope beyond ~20 lines.

---

*Dry run — no remote side effects.*
