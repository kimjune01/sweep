# Hypothesis Graph: open-telemetry/opentelemetry-python#5199

Target: `/Users/junekim/.sweep/worktrees/open-telemetry__opentelemetry-python`

Canonical QA environment from `sweep project-info open-telemetry/opentelemetry-python`: `docker:sweep-tester:latest`, test command `tox`.

Environment limitation: local Docker socket is not accessible in this sandbox (`operation not permitted`), host `tox` is not installed, and network access for `uv`/`pip` dependency resolution is unavailable. Verification used direct `unittest` probes with `PYTHONPATH` plus temporary entry-point metadata in `/private/tmp/otelmeta`.

Codex filter limitation: `codex` CLI is installed, but `codex exec` failed in this sandbox with `failed to initialize in-process app-server client: Operation not permitted`. Confidence on filtered conclusions is downgraded; a manual structural review was performed instead.

## Blind-Blind Merge

### Hypothesis A

`EventLogger.emit` constructs a new `LogRecord` from an `Event` using deprecated `trace_id`, `span_id`, and `trace_flags` constructor kwargs. The fix should pass a `context` to `LogRecord` instead. If the event has explicit trace fields that are not present in its captured context, synthesize a `NonRecordingSpan` with those fields and put it in the context.

### Hypothesis B

Independent pushout converged on the same root cause and fix shape. It flagged a residual behavior risk: the fix changes `LogRecord.context` from emit-time/current context to the event's captured or synthetic context. That is probably desirable because the record trace fields are event-derived, but it is still an observable context-shape change.

### Where A and B Diverge

The original test's runtime warning claim was over-broad. A parent-commit perturbation showed zero `LogRecord` trace-kwarg deprecation warnings at runtime, so the strongest failing test is not "warning appears on master." The decisive behavioral failure is that the old code can preserve explicit `record.trace_id`/`span_id`/`trace_flags` while leaving `record.context` without those explicit IDs. The fixed code preserves both.

## Graph State

| Node | Status | Shape | Summary |
| --- | --- | --- | --- |
| H0 | killed/refined | divergent | Runtime warning reproduction on parent did not fail; no `LogRecord` trace-kwarg warning was emitted in the local probe. |
| H1 | confirmed | divergent | `EventLogger.emit` still uses deprecated trace kwargs in parent code path; fix uses `context=`. |
| H2 | confirmed | divergent | Explicit event trace fields must be represented in `LogRecord.context`, not only copied into record scalar fields. Parent fails this; fix passes. |
| H3 | partial | convergent | Full QA should pass, but canonical Docker/tox environment was unavailable locally. Narrow event tests pass under direct `unittest`. |
| H4 | killed | divergent | Codex CLI filtering was unavailable in this sandbox; manual review found no additional code change beyond test tightening. |

## Nodes

### H0: Runtime LogRecord Deprecation Warning

- Hypothesis: Emitting an event on the parent commit produces a runtime warning from `LogRecord(trace_id=..., span_id=..., trace_flags=...)`.
- Null: No runtime warning is emitted; the deprecation may be static/type-checker-level or version-dependent.
- Perturbation: Archived `HEAD~2` into `/private/tmp/otelbase-5199` and ran a direct event emission probe with explicit trace IDs.
- Trajectory: `deprecated_logrecord_warnings 0` on parent and `0` on the fix branch.
- Shape: divergent against the runtime-warning framing.
- Kill condition: parent must emit at least one `LogRecord` trace-kwarg deprecation warning.
- Edge: Refine to observable behavior preserved by context, not runtime warning count.
- Reasoning mode: induction, 90% confidence in local environment; lower than canonical because Docker/tox unavailable.

### H1: Deprecated Trace Kwargs In EventLogger.emit

- Hypothesis: Parent `EventLogger.emit` constructs `LogRecord` with `trace_id`, `span_id`, and `trace_flags`; the fix should instead pass `context=...`.
- Null: The call path already uses `context`, or the deprecated kwargs are unavoidable.
- Perturbation: Read `opentelemetry-sdk/src/opentelemetry/sdk/_events/__init__.py` on parent and fix branch.
- Trajectory: Parent lines 54-64 pass scalar trace kwargs. Fix commit `a37b6f29` passes `context=context`.
- Shape: divergent in favor.
- Kill condition: existing implementation already routes event correlation through context.
- Edge: Verify explicit trace IDs still survive without scalar kwargs.
- Reasoning mode: deduction, 98% confidence.

#### Provenance

- Origin: events SDK introduced in `bd51fcb7` (`Implement events sdk (#4176)`, 2024-09-10). The current scalar-kwarg construction entered via `5ddb8e74` (`[logs-sdk] Remove LogData and extend SDK LogRecord to have instrumentation scope (#4676)`, 2025-11-13).
- Deprecation context: events API/SDK marked deprecated in `382fa466` (`Mark events API/SDK as deprecated (#4654)`, 2025-12-03). `LogRecord` overload marks trace kwargs deprecated in favor of `context`.
- Issue/PR search: `gh issue view` failed locally due GitHub API connectivity. Web search found package diffs showing the same `EventLogger` trace-kwarg path around the log deprecation work, but no directly accessible issue #5199 text.
- Risk assessment: This is an inherited migration gap, not a deliberate design choice to keep trace kwargs. Existing mechanism overlooked: `LogRecord(context=...)` already derives trace fields from current span in that context.

### H2: Explicit Event Trace IDs Must Survive In Context

- Hypothesis: Replacing scalar kwargs with `context` must preserve explicit `Event(trace_id=..., span_id=..., trace_flags=...)` values in both `LogRecord` scalar fields and `LogRecord.context`.
- Null: Preserving only scalar fields is enough; context contents are not part of the behavior.
- Perturbation: On parent archive and fix branch, emit an event with explicit IDs and inspect both emitted record fields and `trace.get_current_span(record.context).get_span_context()`.
- Trajectory:
  - Parent: `record_trace_id_preserved True`, `context_trace_id_preserved False`, exit 7.
  - Fix: direct probe passed; `trace_id`, `span_id`, `trace_flags`, and context span all match explicit values.
- Shape: divergent in favor of the fix.
- Kill condition: parent context already carries explicit IDs, or fixed context does not.
- Edge: Strengthen the unit test so it fails on parent and passes with the fix.
- Reasoning mode: induction, 93% confidence.

### H3: Regression Surface

- Hypothesis: The fix is narrowly scoped to event logging and does not regress existing event logger behavior.
- Null: Synthetic context changes behavior in a way current tests miss.
- Perturbation:
  - Ran `python -m unittest opentelemetry-sdk.tests.events.test_events -v` with local source paths.
  - Ran `ruff check opentelemetry-sdk/src/opentelemetry/sdk/_events/__init__.py opentelemetry-sdk/tests/events/test_events.py`.
- Trajectory: All 10 event tests pass; ruff passes on Python files. Direct `ruff` on `.changelog/5199.fixed` is invalid because it is not Python and should not be included in that command.
- Shape: convergent/partial.
- Kill condition: canonical Docker `tox` run fails on SDK event tests or typecheck.
- Edge: Run Docker/tox in QA-capable environment before external ship.
- Reasoning mode: induction, 90% confidence for local narrow scope, 75% for full QA.

### H4: Codex Filter Availability

- Hypothesis: Local `codex exec` can structurally filter the refined hypothesis and diff.
- Null: The CLI is installed but unusable under current sandbox permissions.
- Perturbation: Piped the refined hypothesis/evidence pack into `codex exec -`.
- Trajectory: CLI reported version successfully, then `codex exec` failed with `failed to initialize in-process app-server client: Operation not permitted`.
- Shape: divergent against availability.
- Kill condition: `codex exec` returns a review.
- Edge: Treat reviewer pass as unavailable; downgrade confidence and leave canonical Docker/tox plus external review as frontier.
- Reasoning mode: induction, 95% confidence.

## Frontier Edges

| Edge | Pending experiment | Predicted shape | Confidence |
| --- | --- | --- | --- |
| F1 | Run `docker run --rm -v $(sweep project-info open-telemetry/opentelemetry-python --field worktree):/work -w /work sweep-tester:latest tox -- opentelemetry-sdk/tests/events/test_events.py` or repo-equivalent tox target. | convergent | 75% |
| F2 | Run full `tox -e typecheck` in canonical env to confirm no remaining pyright deprecation report in non-excluded paths. | convergent | 70% |
| F3 | Check `gh pr list --repo open-telemetry/opentelemetry-python --search "EventLogger LogRecord context trace_id"` before creating/updating PR. | unknown | 60% |

## Reasoning Mode Table

| Claim | Mode | Confidence |
| --- | --- | --- |
| Parent code used scalar trace kwargs in `EventLogger.emit`. | deduction | 98% |
| Runtime warning does not reproduce in this local source checkout. | induction | 90% |
| Parent fails to encode explicit event IDs into `LogRecord.context`. | induction | 93% |
| Synthetic `NonRecordingSpan` preserves explicit event IDs through `context`. | induction | 93% |
| Full repo QA should pass. | abduction + partial induction | 75% |
| Codex structural filtering is unavailable locally. | induction | 95% |

## Pruning Log

- Pruned H0 runtime-warning test as the decisive regression proof. It did not fail on parent in the local probe.
- Kept H1 because code inspection confirms the deprecated-kwarg path.
- Refined H2 into the load-bearing test: explicit event trace IDs must survive in `LogRecord.context`.
- Pruned H4 codex-filter path locally because the CLI cannot initialize under sandbox permissions.

## Implemented Delta

- Existing branch fix: `opentelemetry-sdk/src/opentelemetry/sdk/_events/__init__.py` builds a trace-carrying context and passes `context=` to `LogRecord`.
- Existing branch test: `test_event_logger_emit_explicit_trace_ids` checks emitted scalar trace fields and absence of `LogRecord` trace-kwarg warning.
- Added refinement: the test now also checks `trace.get_current_span(emitted_record.context).get_span_context()` for the explicit trace ID, span ID, and flags. This creates a fail-on-parent/pass-with-fix assertion.

## Verification Log

- `PYTHONPATH=/private/tmp/otelmeta:... .venv/bin/python -m unittest opentelemetry-sdk.tests.events.test_events.TestEventLoggerProvider.test_event_logger_emit_explicit_trace_ids -v` passed.
- `PYTHONPATH=/private/tmp/otelmeta:... .venv/bin/python -m unittest opentelemetry-sdk.tests.events.test_events -v` passed: 10 tests.
- `ruff check opentelemetry-sdk/src/opentelemetry/sdk/_events/__init__.py opentelemetry-sdk/tests/events/test_events.py` passed.
- `git diff --check` passed.
- Canonical Docker/tox not run: Docker socket denied by sandbox; host `tox` not installed; network unavailable for dependency install.
- `codex exec` filter not run: in-process app-server client initialization denied by sandbox.
