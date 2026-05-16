# Triage Graph: open-telemetry/opentelemetry-collector

Repo: Go, CNCF, ~4 good-first-issues. Institutional governance (CNCF SIGs, code owners per module).
Maintainers: @mx-psi, @bogdandrutu, @dmitryax, @dmathieu, @axw, @evan-bradley

## Scanned Issues

### #14698 — Ensure templates are properly tab-formatted
- **Status**: Assigned to ThyTran1402, open PR #15031, plus 2 closed PRs
- **Verdict**: SKIP — contested, active work

### #14501 — [mdatagen] README badges template uses shortnames
- **Status**: Assigned to RealAnna, open PR #14503 by assignee, plus 2 closed PRs
- **Verdict**: SKIP — contested, assignee owns it

### #9676 — [CI] Changes to workflows are not tested on PRs
- **Status**: Assigned to priyendang (March 2026), no PR opened in 2 months. Actionlint PR #12721 merged but doesn't solve the core issue (testing workflow changes on PRs)
- **Verdict**: SKIP — assigned, stale but not abandoned enough. BryanAndy also asked to take it April 14.

### #5675 — Provide examples on how to create components
- **Status**: OPEN, unassigned. Meta-issue with sub-issues. Previous contributor (heitorganzeli) did xconfmap, receiver, exporter, processor. mx-psi encouraged adding testable examples to any 1.x module.
- **Stable modules without examples**: client, pdata, config/configauth, config/configopaque, config/configoptional, config/configcompression, config/configretry, config/configtls, config/confignet, config/configmiddleware, consumer, extension/extensionauth, pipeline
- **Verdict**: PICKED — consumer module. Clean, uncontested, maintainer-encouraged.

### #14326 — mdatagen cannot generate histogram correctly
- **Status**: Unassigned but 2 open competing PRs (#14986, #15057), 2 closed
- **Verdict**: SKIP — heavily contested

### #14196 — [mdatagen] Invalid generated tests for conditionally_required enum attribute
- **Status**: 1 open competing PR (#15029), 2 closed
- **Verdict**: SKIP — contested

### #14587 — ${env:VAR:-} with empty default resolves to nil
- **Status**: 2 open competing PRs (#15131, #15149)
- **Verdict**: SKIP — contested

### #15237 — Panic in grpccompression/snappy
- **Status**: Open PR #15238 in active review (axw reviewing)
- **Verdict**: SKIP — contested, fix in progress

### #14674 — exporter queue batch send_size_bytes records wrong metric
- **Status**: Maintainer said "requires consensus on which fix we want" — blocked on design decision
- **Verdict**: SKIP — blocked on human consensus

## Selected: #5675 — consumer module testable examples

**Branch**: add-consumer-testable-example
**Commit**: 52bacb4a7
**What**: Two Go testable examples in `consumer/example_test.go`:
1. `Example()` — create a Logs consumer with `NewLogs`, verify default capabilities, send data through it
2. `Example_withCapabilities()` — create a consumer with `WithCapabilities(MutatesData: true)`

**Why this issue**: Bug fix PRs are the fastest path to trust at CNCF repos, but every approachable bug had 1-3 competing PRs. The testable examples issue is explicitly maintainer-encouraged, the consumer module is stable (1.x), and no one is working on it. Follows the exact pattern established by heitorganzeli's merged PRs.

**Next opportunities** (if this lands):
- Add testable examples to `pipeline` module (simplest: just signal types)
- Add testable examples to `config/configretry` or `config/configtls` (practical, users benefit from seeing usage)
- Watch #14674 for consensus — once approach is decided, implement
