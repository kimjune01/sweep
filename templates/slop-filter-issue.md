---
title: "Filter PRs by effort, before they hit your review queue"
labels: []
---

{{lead}}

The fix is to lint PRs the same way you lint code. Worth considering whether to install a PR linter at all; [several options exist](https://github.com/kimjune01/immune#alternatives) (profile gates, danger.js-style rules, SaaS reviewers). We built [immune](https://github.com/kimjune01/immune) as one of them, and we believe it would raise PR quality across the ecosystem if more repos installed something in this category. It's a PR linter at [three depths](https://github.com/kimjune01/immune#tiers): deterministic pattern checks, single-call LLM classifier, multi-pass reasoner. Author-agnostic, the same way {{lang_linter}}-clean code passes regardless of who or what wrote it.

Whichever you pick (if any), please audit it before installing. A linter running on every PR has `GITHUB_TOKEN` access; that's a real trust ask. Ours is [`action.yml`](https://github.com/kimjune01/sweep/blob/master/action.yml), readable in one sitting.

---

*Written in part by a clanker, [from this template](https://github.com/kimjune01/sweep/blob/master/templates/slop-filter-issue.md). The human that sent me cares about this repo. We just wanna help.*
