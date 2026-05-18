# Bootstrap — generic-improvements scan

Paste this into a fresh Claude Code session at `~/Documents/sweep` on branch `temporal-pipeline`. Self-contained; reads code, writes a queue, makes zero changes.

---

## Context

`kimjune01/sweep` is a Temporal-supervised PR pipeline that has grown rapidly. The codebase carries the usual accumulation: copy-pasted blocks, files past 500 lines, dead imports, stale TODOs, doc/code drift, naming inconsistencies (the retro→n rename half-landed; pokayoke half-migrated; etc.). The point of this pass is to surface, not to fix.

Read-only operation. Your job is to produce a structured queue an operator (or another agent in a later session) can triage and act on.

## Deliverable

One markdown file at `~/.sweep/remediation-prompts/refactor-overdue-<YYYYMMDD-HHMM>.md` with the format below. Print the path on completion. Do not modify any source file.

```markdown
# Refactor queue — <timestamp>

Total items: <N>, organized by class.

## Dead code (<count>)

- **<file>:<line>**: <one-line description>. Witness: `grep -n '<pattern>' <file>`.

## Duplication (<count>)

- **<file_a>:<line_a> ↔ <file_b>:<line_b>**: <what's duplicated>. Estimated lines of overlap.

## Long files (<count>)

- **<file>**: <N> lines. Likely split-points: <suggested section headers>.

## Stale docs / drift (<count>)

- **<file>:<line>**: comment/docstring says X, code does Y.
- **skills/<name>.md**: documents subcommand `<x>` that doesn't exist (CLI returns "no such command").

## Naming inconsistencies (<count>)

- **<concept>**: named `<A>` in <files...>, `<B>` in <files...>. Pick one.

## Stale TODOs (<count>)

- **<file>:<line>**: `# TODO: <text>` (git blame age: <months>).

## Half-migrations (<count>)

- **<feature>**: started in <files>, callers not migrated in <files>. See `<reference doc>`.
```

## Scan instructions

For each section, the heuristic you should run:

### Dead code

- `ruff check --select F401,F841 .` for unused imports and assignments
- For unused functions: `grep -c "def <name>" <file>` then `grep -rn "<name>(" .` — flag any function with exactly 1 definition and 0 callsites outside its own file
- Skip private helpers (leading underscore) that match nothing — they may be intentional stubs

### Duplication

- Look for blocks of 8+ lines that appear in two or more files. Ignore boilerplate (imports, decorators, repeated dataclass field declarations)
- Specifically check: subprocess wrappers, gh CLI invocations, atomic file writes, andon/observe boilerplate
- One pass over `sweep/activities/*.py` is the highest-yield target

### Long files

- `wc -l sweep/**/*.py | sort -rn | head -20`
- Anything > 500 lines is a candidate. Read the file, propose 2-4 section boundaries that map to coherent concepts. Don't propose splitting just for the sake of it — if the file is long because the topic is genuinely cohesive, note that and move on

### Stale docs / drift

- For each `skills/*.md`: extract subcommands it claims exist, then `sweep <subcommand> --help` to verify. Flag any that error
- For each module docstring: skim against the actual function set. Flag any docstring describing a function/class that no longer exists or has been renamed
- `git log --oneline -- <file> | head -3` for recent commits — if the file changed but the docstring hasn't, suspect drift

### Naming inconsistencies

- Known half-rename: retro → n in code, but skill markdown still says "retro". See [[project_retro_renamed_to_n]] in `~/.claude/projects/-Users-junekim-Documents-sweep/memory/`
- Other suspects: triaged vs triage, prospect vs sift, drip vs respond — check each pair across `sweep/cli/` and `sweep/activities/`

### Stale TODOs

- `grep -rn "TODO\|FIXME\|XXX\|HACK" sweep/`
- For each, run `git blame -L<line>,<line> <file>` to get the commit date
- Flag any older than 60 days; very old ones (180+) get a separate section

### Half-migrations

- Known: pokayoke module exists at `sweep/pokayoke.py` but callers (attest, qa, compose, SkillActor) still have ad-hoc inline checks. See `ROADMAP.md` "Pokayoke migration" entry
- Other suspects: any module that has both a "new" and "old" code path (search for `# legacy`, `# old`, `# DEPRECATED`)

## Guardrails

- **Do not edit any source file.** This pass is read-only. Writing a queue, not making changes
- **Do not run any actor or substrate command.** `sweep up`, `sweep qa backfill`, etc. are off-limits — the substrate is processing live work
- **Do not modify CLAUDE.md, skills/*, or any maintainer-facing prose** — those are separate-pass items
- **No false positives over-eagerness**: when uncertain whether something is dead/duplicated/drifted, skip it. The queue is for high-confidence items the operator can triage in seconds, not for ambiguous cases that need debate

## Output discipline

- One file at the path above. Print the path on completion
- No console preamble. The file IS the report
- Item count per section in the section header. Items sorted by file path within a section
- Witness commands (grep/wc/git blame) included verbatim so the operator can re-verify in one paste
