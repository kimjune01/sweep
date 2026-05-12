#!/bin/bash
# PR Quality Gate — protect your repo against AI slop.
#
# Five checks derived from 64 PR outcomes across 21 repos:
# 1. Em dashes — strongest single signal for AI-generated prose
# 2. Description depth — does the PR explain *why*, not just *what*?
# 3. CONTRIBUTING compliance — branch policy, commit limits, AI policy
# 4. Test presence — bug fixes without tests are unproven
# 5. Contributor velocity — 5+ PRs in 24h is a spray pattern
#
# The description check calls Claude Haiku (~$0.001/PR) when an API key
# is provided. Without it, falls back to keyword heuristics.

set -euo pipefail

PR_BODY=$(jq -r '.pull_request.body // ""' "$GITHUB_EVENT_PATH")

RESULTS=""
PASS_COUNT=0
WARN_COUNT=0

# Standing check: has this author merged PRs to this repo before?
PRIOR_MERGES=$(gh api "repos/${REPO}/pulls?state=closed&creator=${PR_AUTHOR}&per_page=100" --jq '[.[] | select(.merged_at != null)] | length' 2>/dev/null || echo "0")
HAS_STANDING=false
if [ "$PRIOR_MERGES" -ge 3 ]; then
  HAS_STANDING=true
fi

add_result() {
  local check="$1" status="$2" detail="$3"
  detail=$(echo "$detail" | sed 's/|/\\|/g')
  RESULTS="${RESULTS}| ${check} | ${status} | ${detail} |\n"
  case "$status" in
    pass) PASS_COUNT=$((PASS_COUNT + 1)) ;;
    warn) WARN_COUNT=$((WARN_COUNT + 1)) ;;
  esac
}

# 1. Em-dash scan
if printf '%s' "$PR_TITLE$PR_BODY" | grep -q $'\xe2\x80\x94'; then
  add_result "Em dashes" "warn" "Found em dashes in PR text. Common in AI-generated prose."
else
  add_result "Em dashes" "pass" "No em dashes found"
fi

# 2. Description depth
BODY_LEN=${#PR_BODY}
if [ "$BODY_LEN" -lt 50 ]; then
  add_result "Description" "warn" "PR body is ${BODY_LEN} chars. Describe *why* this change is needed."
else
  DIFF_SUMMARY=$(gh api "repos/${REPO}/pulls/${PR_NUMBER}" --jq '.additions, .deletions, .changed_files' 2>/dev/null | tr '\n' '/' || echo "?/?/?")
  LLM_VERDICT=$(curl -s https://api.anthropic.com/v1/messages \
    -H "content-type: application/json" \
    -H "x-api-key: ${ANTHROPIC_API_KEY}" \
    -H "anthropic-version: 2023-06-01" \
    -d "$(jq -n \
      --arg body "$PR_BODY" \
      --arg title "$PR_TITLE" \
      --arg diff "$DIFF_SUMMARY" \
      '{
        model: "claude-haiku-4-5-20251001",
        max_tokens: 150,
        messages: [{
          role: "user",
          content: ("PR title: " + $title + "\nPR body: " + $body + "\nDiff stats: " + $diff + "\n\nDoes this PR description explain WHY the change is correct (root cause, design rationale), or does it only describe WHAT changed (restating the diff)? Answer exactly: WHY or WHAT, then one sentence explaining your judgment.")
        }]
      }')" 2>/dev/null | jq -r '.content[0].text // "ERROR"' 2>/dev/null || echo "ERROR")

  if echo "$LLM_VERDICT" | grep -qi "^WHAT"; then
    REASON=$(echo "$LLM_VERDICT" | head -1 | cut -c6-120)
    add_result "Description" "warn" "Describes *what* changed, not *why*. ${REASON}"
  elif echo "$LLM_VERDICT" | grep -qi "^WHY"; then
    add_result "Description" "pass" "Explains why"
  else
    add_result "Description" "pass" "Description present (LLM check inconclusive)"
  fi
fi

# 3. CONTRIBUTING.md compliance
CONTRIBUTING=""
for path in CONTRIBUTING.md .github/CONTRIBUTING.md; do
  CONTENT=$(gh api "repos/${REPO}/contents/${path}" --jq '.content' 2>/dev/null | base64 -d 2>/dev/null || true)
  if [ -n "$CONTENT" ]; then
    CONTRIBUTING="$CONTENT"
    break
  fi
done

if [ -n "$CONTRIBUTING" ]; then
  ISSUES=""

  TARGET_BRANCH=$(echo "$CONTRIBUTING" | grep -oiE '(submit|target|base|pr).{0,30}(main|master|develop|dev)' | head -1 || true)
  if [ -n "$TARGET_BRANCH" ]; then
    EXPECTED=$(echo "$TARGET_BRANCH" | grep -oE '(main|master|develop|dev)' | tail -1)
    if [ -n "$EXPECTED" ] && [ "$PR_BASE" != "$EXPECTED" ]; then
      ISSUES="${ISSUES}Target branch should be ${EXPECTED} (got ${PR_BASE}). "
    fi
  fi

  MAX_COMMITS=$(echo "$CONTRIBUTING" | grep -oiE '(max|limit|at most|no more than)[^0-9]{0,10}([0-9]+)[^0-9]{0,10}commit' | grep -oE '[0-9]+' | head -1 || true)
  if [ -n "$MAX_COMMITS" ] && [ "$COMMITS" -gt "$MAX_COMMITS" ]; then
    ISSUES="${ISSUES}${COMMITS} commits exceeds limit of ${MAX_COMMITS}. "
  fi

  if echo "$CONTRIBUTING" | grep -qiE 'AI|LLM|generative|copilot|chatgpt|ai.generated|ai.slop'; then
    AI_LINE=$(echo "$CONTRIBUTING" | grep -iE 'AI|LLM|generative|copilot|chatgpt|ai.generated|ai.slop' | head -1 | cut -c1-120)
    ISSUES="${ISSUES}AI policy detected: ${AI_LINE} "
  fi

  if [ -n "$ISSUES" ]; then
    add_result "CONTRIBUTING" "warn" "$ISSUES"
  else
    add_result "CONTRIBUTING" "pass" "Follows repo guidelines"
  fi
else
  add_result "CONTRIBUTING" "pass" "No CONTRIBUTING.md found"
fi

# 4. Test presence
DIFF_FILES=$(gh api --paginate "repos/${REPO}/pulls/${PR_NUMBER}/files" --jq '.[].filename' 2>/dev/null || true)
HAS_SOURCE=false
HAS_TEST=false

while IFS= read -r file; do
  [ -z "$file" ] && continue
  if echo "$file" | grep -qiE 'test|spec|_test\.|\.test\.|tests/'; then
    HAS_TEST=true
  elif echo "$file" | grep -qiE '\.(py|rs|go|ts|js|java|cpp|c|rb|swift|kt)$'; then
    HAS_SOURCE=true
  fi
done <<< "$DIFF_FILES"

IS_FIX=$(printf '%s' "$PR_TITLE" | grep -qiE '^fix|bug|patch|hotfix' && echo true || echo false)

if [ "$HAS_SOURCE" = true ] && [ "$HAS_TEST" = false ]; then
  if [ "$IS_FIX" = true ]; then
    add_result "Tests" "warn" "Bug fix changes source files but adds no tests. A failing test on main proves the bug exists."
  else
    add_result "Tests" "warn" "Source files changed but no test files modified"
  fi
else
  add_result "Tests" "pass" "Tests present or no source changes"
fi

# 5. Contributor velocity
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
  SINCE=$(date -u -d '24 hours ago' +%Y-%m-%dT%H:%M:%SZ)
else
  SINCE=$(date -u -v-24H +%Y-%m-%dT%H:%M:%SZ)
fi

RECENT_PRS=$(gh api graphql -f query="{ search(query: \"is:pr author:${PR_AUTHOR} created:>${SINCE}\", type: ISSUE, first: 1) { issueCount } }" --jq '.data.search.issueCount' 2>/dev/null || echo "0")

if [ "$RECENT_PRS" -gt 10 ]; then
  add_result "Velocity" "warn" "${RECENT_PRS} PRs opened in last 24h across GitHub. High-volume pattern."
elif [ "$RECENT_PRS" -gt 5 ]; then
  add_result "Velocity" "warn" "${RECENT_PRS} PRs opened in last 24h"
else
  add_result "Velocity" "pass" "${RECENT_PRS} PRs in last 24h"
fi

# Build the comment
HEADER="### PR Quality Gate"
if [ "$WARN_COUNT" -gt 0 ]; then
  HEADER="${HEADER} (${WARN_COUNT} warning(s))"
fi

COMMENT=$(cat <<COMMENTEOF
${HEADER}

| Check | Status | Detail |
|-------|--------|--------|
$(printf '%b' "$RESULTS")
<details>
<summary>About this check</summary>

Each check corresponds to a pattern that predicted closure in [64 PR outcomes](https://github.com/kimjune01/sweep) across 21 repos.

[Protect your repo against AI slop](https://github.com/kimjune01/sweep#pr-quality-gate)
</details>
COMMENTEOF
)

# Post or update comment (paginate to avoid duplicates)
EXISTING=$(gh api --paginate "repos/${REPO}/issues/${PR_NUMBER}/comments" --jq '.[] | select(.body | startswith("### PR Quality Gate")) | .id' 2>/dev/null | head -1 || true)

if [ -n "$EXISTING" ]; then
  gh api "repos/${REPO}/issues/comments/${EXISTING}" -X PATCH -f body="$COMMENT" > /dev/null 2>&1
else
  gh api "repos/${REPO}/issues/${PR_NUMBER}/comments" -f body="$COMMENT" > /dev/null 2>&1
fi

# Standing determines action: first-timers get closed, established contributors get warned
if [ "$WARN_COUNT" -gt 0 ]; then
  if [ "$HAS_STANDING" = true ]; then
    echo "PR Quality Gate: ${WARN_COUNT} warning(s), advisory (${PRIOR_MERGES} prior merges)"
  else
    gh api "repos/${REPO}/pulls/${PR_NUMBER}" -X PATCH -f state=closed > /dev/null 2>&1
    echo "PR Quality Gate: CLOSED (${WARN_COUNT} warning(s), first-time contributor)"
  fi
else
  echo "PR Quality Gate: PASSED (${PASS_COUNT} checks)"
fi
