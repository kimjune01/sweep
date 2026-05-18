# Work Log

## 2026-05-16

### 17:57 — prospect budget andon: knobs, window, wasteboard cache

prospect budget andon (178% of 20% share). Cost driver: `_has_related_pr` × warm-org fan-out — _merge_warm_org_issues hit every warm org per pass, ~400 issue_events calls/pass × 2 passes/hr = 1775 calls/hr vs 1000 cap. Fixes: (a) externalized three prospect cost knobs to ~/.sweep/control/ — prospect_search_limit, prospect_warm_org_fan_out_cap (new, default 3, round-robin via ~/.sweep/cursors/prospect_warm_org.json), prospect_warm_org_issue_limit; surfaced in cockpit _knob_line. (b) Pinned search_limit=50 temporarily so first post-clear pass is conservative. (c) Switched per-actor budget window from 1h global to 15min local (HOURLY_LIMIT × share × 15/60) so overshoots trip and recover fast; global 1h remains the hard ceiling. (d) Fixed wasteboard cache: outcomes.json now keyed by `days` instead of single-slot, so the score/pick double-call doesn't always miss — cold-cold was 7.3s, now 130ms. Memories updated: post-hoc andon (kept), local-vs-global window (new).

## 2026-05-17

### 22:55 — retro pass --since 2026-05-10

Substrate mid-rename (prospect→sift, drip→respond, respondable→human, ship→done, takt→rope, qa→qa+attest, retro→n, plus actor splits) — no-science-before-humming applies; window metrics deferred. Obvious compressions: (1) /retro skill spec references 7 sweep retro subcommands that don't exist (missing-calls, mid-run-edits, skill-stats, ref-drift, em-dash-audit, evict, fix-ready); saved as feedback_retro_skill_cli_drift. (2) `retro` renamed to `n` in code (n_params, n_state, inbox/n.jsonl) but skill+MEMORY still say "retro"; saved as project_retro_renamed_to_n. (3) `cockpit --plain` reached 6× — operator demand for non-TUI cockpit view. (4) `~/.sweep/retros/` empty across window — `sweep retro record` may be unwired post-rename, worth verifying. Compressed 2 → memory; deferred: skill markdown trim, retro→n doc rename, cockpit --plain flag.
