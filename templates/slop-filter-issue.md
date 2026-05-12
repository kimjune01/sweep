---
title: "Protect this repo from AI-generated PRs"
labels: []
---

Here's a GitHub Action that automatically closes AI-generated PRs before it reaches a human review: [PR Quality Gate](https://github.com/kimjune01/sweep/blob/master/action.yml)

This was developed after submitting 200 PRs at a 45% merge rate. It checks for:

1. Em dashes / double hyphens
2. Description depth (why, not what)
3. CONTRIBUTING.md / AGENTS.md compliance
4. Test presence
5. Contributor velocity
6. Three-strike ban

First-time contributors who fail get auto-closed. Established contributors get a warning.

Usage:

```yaml
# .github/workflows/pr-gate.yml
name: PR Quality Gate
on: [pull_request]
jobs:
  gate:
    runs-on: ubuntu-latest
    steps:
      - uses: kimjune01/sweep@master
        with:
          github-token: ${{ secrets.GITHUB_TOKEN }}
          # Optional: anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
```

No config, no API keys required. LLM optional.

Full writeup: https://june.kim/speedrunning-open-source

Disclosure: this issue was opened by an automated pipeline. We noticed this repo deals with AI-generated PRs and wanted to help.
