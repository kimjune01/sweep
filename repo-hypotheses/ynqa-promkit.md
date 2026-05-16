# Triage Graph: ynqa/promkit

Stars: 460 | Language: Rust | Last pushed: 2026-04-20

## AI Policy
None stated. No restrictions.

## Contributing Policy
Standard fork-and-PR workflow. No special requirements.

## Issues Triaged

### #29 - Validator type doesn't allow capture of external variables [TRIAGED]
- **Type**: bug_fix (labeled enhancement but functionally a limitation fix)
- **Status**: Branch `fix-validator-closure-capture` pushed to fork
- **Mechanism**: `type Validator<T> = fn(&T) -> bool` prevents closure capture. Changed to `Box<dyn Fn + Send + Sync>` with `impl Fn` in public API for ergonomics.
- **Tests**: 3 unit tests (function pointer, owned data capture, Arc<Mutex> shared state)
- **Risk**: Breaking change for anyone importing the Validator/ErrorMessageGenerator type aliases directly. Method signatures use impl Fn so call sites are backward compatible.
- **Previous attempt**: qa_passed but branch was lost on fork. Clean redo.
- **Competing PRs**: None. Issue open 23+ months, 3 thumbs up.
- **Community signal**: 1 comment from JeanMertz confirming the limitation.

## Issues Evaluated but Not Selected

### #59 - Limit use of radix_trie
- Refactoring, not a bug fix. First contribution should be smaller.

### #43 - Checkbox filter
- Feature request, no community +1s.
