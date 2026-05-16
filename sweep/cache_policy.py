"""Cache TTL tiers — one place to set, one place to debate.

Every `gh_io.*(ttl=...)` call site should pull a constant from here
instead of an inline number. The previous pattern was each author
picking a number that felt right; bug-hunt found three different
TTLs for the same query (`search_prs(author:@me, open)`) across
org_state, pr_state, and outcomes. This module is the single source.

Tiers by how often the underlying data changes:

  IDENTITY_TTL    — gh user identity, almost never changes.
  REPO_META_TTL   — repo description, star count, language. Days.
  AI_POLICY_TTL   — AGENTS.md / CONTRIBUTING content. Days.
  PR_STATE_TTL    — open PR review_decision / mergeable / ci. Hours-ish
                    (notification poller drives freshness on real changes).
  SEARCH_TTL      — search results. Drift fast; small window worth it.
  ISSUE_EVENTS_TTL — issue cross-references. Minutes.
  RATE_LIMIT_TTL  — gh api rate_limit. Snapshot for the display.

If a caller needs FRESH state, pass ttl=0 explicitly (and document why).
"""

from __future__ import annotations


# Bump these collectively when the system's tolerance for staleness shifts.
# Lower means more API calls and fresher data; higher means less burn and
# more lag between maintainer action and our reaction.

IDENTITY_TTL      = 86400           # 24h
REPO_META_TTL     = 6 * 3600        # 6h
AI_POLICY_TTL     = 24 * 3600       # 24h
PR_STATE_TTL      = 600             # 10min
SEARCH_TTL        = 300             # 5min
ISSUE_EVENTS_TTL  = 300             # 5min
RATE_LIMIT_TTL    = 60              # 1min (for the wasteboard display)
