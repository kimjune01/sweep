#!/bin/bash
# Update profile README merge rate. Called by monitor tick.

UPDATED=$(date -u +"%H:%M UTC")
EPOCH="2026-05-09T00:34:00Z"        # PR pipeline epoch — first PR via /sweep
ISSUE_EPOCH="2026-05-12T00:00:00Z"  # /distribute-slop-filter launch — first
                                    # day of issue-spam campaign. Pre-epoch
                                    # issues were /investigate companions
                                    # (test-first protocol) and skewed
                                    # ~89% positive; mixing them with the
                                    # campaign hides the actual cohort rate.
ISSUE_EPOCH_DATE="${ISSUE_EPOCH%T*}"

# PR outcomes from GitHub (ground truth)
Q_BASE="is:pr author:kimjune01 created:>$EPOCH"
MERGED=$(gh api graphql -f query="{ search(query: \"is:merged $Q_BASE\", type: ISSUE) { issueCount } }" --jq '.data.search.issueCount' 2>/dev/null)
CLOSED=$(gh api graphql -f query="{ search(query: \"is:closed is:unmerged $Q_BASE\", type: ISSUE) { issueCount } }" --jq '.data.search.issueCount' 2>/dev/null)
OPEN=$(gh api graphql -f query="{ search(query: \"is:open $Q_BASE\", type: ISSUE) { issueCount } }" --jq '.data.search.issueCount' 2>/dev/null)
RESOLVED=$((MERGED + CLOSED))
if [ "$RESOLVED" -gt 0 ]; then
  RATE=$((MERGED * 100 / RESOLVED))
else
  RATE=0
fi

# Pipeline-internal states from JSONL
eval $(python3 << 'STATSEOF'
import json, os, glob
from collections import defaultdict

drip_dir = os.path.expanduser("~/.sweep/drip-queue")
sc = defaultdict(int)

def attested(e):
    g = e.get("gates", {})
    return isinstance(g.get("bugs_found"), int)

for f in glob.glob(os.path.join(drip_dir, "*.jsonl")):
    issues = {}
    for line in open(f):
        line = line.strip()
        if not line: continue
        try:
            e = json.loads(line)
            issues[e.get("issue", e.get("branch", "?"))] = e
        except: pass
    for e in issues.values():
        s = e.get("status", "?")
        if s == "qa_passed" and not attested(e):
            sc["triaged"] += 1
        elif s in ("queued", "ready", "triaged"):
            sc["triaged"] += 1
        elif s == "qa_passed":
            sc["qa_passed"] += 1
        elif s == "dripped":
            sc["dripped"] += 1
        elif s == "gate_fail":
            sc["gate_fail"] += 1

print(f'TRIAGED={sc["triaged"]}')
print(f'DRIPPED={sc["dripped"]}')
print(f'GATE_FAIL={sc["gate_fail"]}')
STATSEOF
)

# Issues: positive reception scoreboard since ISSUE_EPOCH (campaign start)
ISSUE_STATS=$(~/.sweep/bin/scoreboard --since "$ISSUE_EPOCH_DATE" --json 2>/dev/null)
ISSUES_TOTAL=$(echo "$ISSUE_STATS" | jq -r '.issue_count // 0')
ISSUES_POS=$(echo "$ISSUE_STATS" | jq -r '.positive // 0')
ISSUES_NEG=$(echo "$ISSUE_STATS" | jq -r '.negative // 0')
ISSUES_BOT=$(echo "$ISSUE_STATS" | jq -r '.bot_closed // 0')
ISSUES_INC=$(echo "$ISSUE_STATS" | jq -r '.inconclusive // 0')
ISSUES_DECIDED=$((ISSUES_POS + ISSUES_NEG))
if [ "$ISSUES_DECIDED" -gt 0 ]; then
  IRATE=$((ISSUES_POS * 100 / ISSUES_DECIDED))
else
  IRATE=0
fi

# Build feed: last 10 resolved PRs (merged or closed, not own repos)
FEED=$(gh api graphql -f query="{ merged: search(query: \"is:pr is:merged author:kimjune01 -user:kimjune01 sort:updated-desc\", type: ISSUE, first: 10) { edges { node { ... on PullRequest { number title repository { nameWithOwner } mergedAt } } } } closed: search(query: \"is:pr is:closed is:unmerged author:kimjune01 -user:kimjune01 sort:updated-desc\", type: ISSUE, first: 10) { edges { node { ... on PullRequest { number title repository { nameWithOwner } closedAt } } } } }" --jq '"| | repo | PR |\n|---|------|----|\n" + (([.data.merged.edges[].node | {d: .mergedAt, s: "| ✅ | \(.repository.nameWithOwner) | [#\(.number)](https://github.com/\(.repository.nameWithOwner)/pull/\(.number)) \(.title[:45]) |"}] + [.data.closed.edges[].node | {d: .closedAt, s: "| ❌ | \(.repository.nameWithOwner) | [#\(.number)](https://github.com/\(.repository.nameWithOwner)/pull/\(.number)) \(.title[:45]) |"}]) | sort_by(.d) | reverse | .[:10] | map(.s) | join("\n"))' 2>/dev/null)

# Streak: consecutive merges from most recent resolved PR
STREAK=$(gh api graphql -f query="{ merged: search(query: \"is:pr is:merged author:kimjune01 created:>$EPOCH sort:updated-desc\", type: ISSUE, first: 20) { edges { node { ... on PullRequest { mergedAt } } } } closed: search(query: \"is:pr is:closed is:unmerged author:kimjune01 created:>$EPOCH sort:updated-desc\", type: ISSUE, first: 20) { edges { node { ... on PullRequest { closedAt } } } } }" --jq '([.data.merged.edges[].node | {t: "M", d: .mergedAt}] + [.data.closed.edges[].node | {t: "X", d: .closedAt}]) | sort_by(.d) | reverse | [.[] | .t] | if length == 0 then 0 else reduce .[] as $t ({"s":0,"done":false}; if .done then . elif $t == "M" then .s += 1 else .done = true end) | .s end' 2>/dev/null)

# Time series: cumulative merges by day
MERGE_DATES=$(gh api graphql -f query="{ search(query: \"is:pr is:merged author:kimjune01 created:>$EPOCH sort:created-asc\", type: ISSUE, first: 100) { edges { node { ... on PullRequest { mergedAt } } } } }" --jq '[.data.search.edges[].node.mergedAt]' 2>/dev/null)

# Time series: positive-reception issue dates from scoreboard cache,
# filtered to the slop-filter campaign cohort (created >= ISSUE_EPOCH).
# Pre-campaign issues were /investigate companions (~89% positive baseline);
# mixing them into the chart hides the campaign's actual reception trajectory.
# A "defense dispensed" event is an issue that landed positively. Date is
# closed_at when the maintainer closed it as completed, else created_at.
ISSUE_POS_DATES=$(ISSUE_EPOCH="$ISSUE_EPOCH" python3 << 'IPDEOF'
import json, os, sys
cache = os.path.expanduser("~/.sweep/cache/scoreboard-issues.json")
if not os.path.exists(cache):
    print("[]"); sys.exit(0)
issues = json.load(open(cache))
since = os.environ.get("ISSUE_EPOCH", "")
POSITIVE_LABELS = {"bug","accepted","confirmed","good first issue","help wanted","enhancement","ready","approved","triaged"}
BOT_LABELS = {"stale","auto-close","auto-closed","bot-closed","no-activity","abandoned","lifecycle/stale","lifecycle/rotten","needs-info","no-response"}
def is_bot(l):
    if not l: return False
    l = l.lower()
    return l.endswith("bot") or l.endswith("-bot") or "[bot]" in l
def positive(i):
    labels = {l.lower() for l in i.get("labels", [])}
    if is_bot(i.get("closer")): return False
    if labels & BOT_LABELS or "spam" in labels: return False
    if i["state"] == "closed":
        return i["state_reason"] == "completed"
    if labels & POSITIVE_LABELS: return True
    return i.get("comments", 0) > 0
dates = []
for i in issues:
    created = i.get("created_at", "")
    if since and created < since: continue  # filter to campaign cohort
    if not positive(i): continue
    d = i.get("closed_at") or created
    if d: dates.append(d)
print(json.dumps(dates))
IPDEOF
)

# Clone/update the profile repo
REPO_DIR="$HOME/Documents/kimjune01"
if [ ! -d "$REPO_DIR" ]; then
  gh repo clone kimjune01/kimjune01 "$REPO_DIR" 2>/dev/null
fi

cd "$REPO_DIR" && git pull --rebase origin main 2>/dev/null

# Generate per-day chart with two series: PRs merged + issues positively
# received (defenses dispensed). The two primary directives.
MERGE_CHART=$(python3 << CHARTEOF
import json
from datetime import datetime, timedelta
from collections import defaultdict

merge_raw = json.loads('''$MERGE_DATES''')
issue_raw = json.loads('''$ISSUE_POS_DATES''')

if not merge_raw and not issue_raw:
    exit()

merge_buckets = defaultdict(int)
for d in merge_raw:
    merge_buckets[d[:10]] += 1
issue_buckets = defaultdict(int)
for d in issue_raw:
    issue_buckets[d[:10]] += 1

all_days = set(merge_buckets) | set(issue_buckets)
start = datetime.strptime(min(all_days), "%Y-%m-%d")
end = datetime.strptime(max(all_days), "%Y-%m-%d")
cur = start
days, merges, defenses = [], [], []
while cur <= end:
    day = cur.strftime("%Y-%m-%d")
    days.append(cur.strftime("%m-%d"))
    merges.append(merge_buckets.get(day, 0))
    defenses.append(issue_buckets.get(day, 0))
    cur += timedelta(days=1)

x = ", ".join(f'"{d}"' for d in days)
ym = ", ".join(str(c) for c in merges)
yd = ", ".join(str(c) for c in defenses)
print(f'xychart-beta')
print(f'    title "PRs merged + defenses dispensed per day"')
print(f'    x-axis [{x}]')
print(f'    y-axis "count"')
print(f'    bar [{ym}]')
print(f'    bar [{yd}]')
CHARTEOF
)

# Sync hypothesis graphs
cp "$HOME/.sweep/HYPOTHESIS_GRAPH.md" "$REPO_DIR/HYPOTHESIS_GRAPH.md" 2>/dev/null
cp "$HOME/.sweep/ISSUE_HYPOTHESIS_GRAPH.md" "$REPO_DIR/ISSUE_HYPOTHESIS_GRAPH.md" 2>/dev/null

# Leaderboard: ClickHouse discovery + GitHub GQL verification.
# Threads $EPOCH from bash so the cutoff stays in sync with the rest of the
# profile (PR merge rate, hypothesis graph, sankey).
LEADERBOARD=$(EPOCH="${EPOCH%T*}" python3 << 'LBEOF'
import subprocess, json, sys, os, urllib.request, urllib.parse

EPOCH = os.environ["EPOCH"]  # YYYY-MM-DD form, threaded from bash $EPOCH

# Step 1: ClickHouse discovery — top 50 cross-repo PR openers globally
# Uses the public github_events dataset (same data as gharchive)
# Data is stale (days to weeks behind), but it's the only free cross-GitHub query we have
ch_query = """
SELECT
    actor_login AS candidate,
    count() AS prs_opened,
    count(DISTINCT repo_name) AS repos
FROM github_events
WHERE event_type = 'PullRequestEvent'
  AND action = 'opened'
  AND created_at > '2026-04-01'
  AND author_association NOT IN ('MEMBER', 'OWNER')
  AND actor_login NOT LIKE '%bot%'
  AND actor_login NOT LIKE '%Bot%'
  AND actor_login NOT LIKE '%[bot]%'
  AND actor_login NOT LIKE '%-bot'
  AND actor_login NOT LIKE '%Copilot%'
  AND actor_login != splitByChar('/', repo_name)[1]
GROUP BY candidate
HAVING repos >= 3 AND prs_opened >= 5
ORDER BY repos DESC, prs_opened DESC
LIMIT 50
FORMAT JSONEachRow
"""

candidates = []
SKIP = {'scala-steward', 'weblate', 'octo-patch', 'bt-admin', 'sast-qa',
        'nextcloud-command', 'conda-forge-admin', 'Claude', 'Codex',
        'avatar-sh827', 'NetcrackerCLPLCI'}

try:
    url = "https://play.clickhouse.com/?user=play"
    req = urllib.request.Request(url, data=ch_query.encode(), method='POST')
    with urllib.request.urlopen(req, timeout=30) as resp:
        for line in resp.read().decode().strip().split('\n'):
            if not line: continue
            row = json.loads(line)
            login = row['candidate']
            if login not in SKIP:
                candidates.append(login)
except Exception as e:
    print(f"ClickHouse error: {e}", file=sys.stderr)

# Always include kimjune01
if 'kimjune01' not in candidates:
    candidates.append('kimjune01')

# Step 2: GitHub GQL verification — merged/(merged+closed) + repo count
results = []
for user in candidates:
    gql = ('{ merged: search(query: "is:pr is:merged author:' + user
           + ' -user:' + user + ' created:>' + EPOCH
           + '", type: ISSUE, first: 1) { issueCount }'
           + ' closed: search(query: "is:pr is:closed is:unmerged author:' + user
           + ' -user:' + user + ' created:>' + EPOCH
           + '", type: ISSUE, first: 1) { issueCount }'
           + ' repos: search(query: "is:pr is:merged author:' + user
           + ' -user:' + user + ' created:>' + EPOCH
           + '", type: ISSUE, first: 100) { edges { node { ... on PullRequest {'
           + ' repository { nameWithOwner } } } } } }')
    try:
        r = subprocess.run(['gh', 'api', 'graphql', '-f', f'query={gql}'],
                           capture_output=True, text=True, timeout=15)
        data = json.loads(r.stdout).get('data', {})
        merged = data.get('merged', {}).get('issueCount', 0)
        closed = data.get('closed', {}).get('issueCount', 0)
        resolved = merged + closed
        if resolved == 0 or merged == 0: continue
        rate = merged * 100 // resolved
        if rate < 10 or rate >= 90: continue
        repo_set = set()
        for edge in data.get('repos', {}).get('edges', []):
            repo_set.add(edge['node']['repository']['nameWithOwner'])
        results.append((user, merged, rate, len(repo_set)))
    except: pass

results.sort(key=lambda x: (-x[1], -x[2], -x[3]))

print("| contributor | merged | rate | repos |")
print("|---|---|---|---|")
for user, m, rate, repos in results[:10]:
    print(f"| {user} | {m} | {rate}% | {repos} |")
LBEOF
)

cat > README.md << READMEEOF
## ${RATE}% merge rate · ${STREAK} streak (${UPDATED})

[Speedrunning Open Source](https://june.kim/speedrunning-open-source)

\`\`\`mermaid
sankey-beta
    triaged,    submitted, $((MERGED + CLOSED + OPEN + DRIPPED))
    triaged,    throttled, ${TRIAGED}
    triaged,    rejected,  ${GATE_FAIL}
    submitted,  resolved,  $((MERGED + CLOSED))
    submitted,  dripped,   ${DRIPPED}
    submitted,  open,      ${OPEN}
    resolved,   merged,    ${MERGED}
    resolved,   closed,    ${CLOSED}
\`\`\`

\`\`\`mermaid
${MERGE_CHART}
\`\`\`

*since ${EPOCH} (pipeline epoch)*

<details>
<summary>verify</summary>

\`\`\`graphql
{ merged: search(query: "is:pr is:merged author:kimjune01 created:>${EPOCH}", type: ISSUE) { issueCount }
  closed: search(query: "is:pr is:closed is:unmerged author:kimjune01 created:>${EPOCH}", type: ISSUE) { issueCount } }
\`\`\`

</details>

## Issues generated

**${IRATE}% positive reception** · [hypothesis graph](ISSUE_HYPOTHESIS_GRAPH.md)

${ISSUES_TOTAL} issues filed since ${ISSUE_EPOCH_DATE} (slop-filter campaign start) · ${ISSUES_POS} positive · ${ISSUES_NEG} negative · ${ISSUES_BOT} bot-closed (already protected) · ${ISSUES_INC} inconclusive

\`\`\`mermaid
sankey-beta
    filed,    decided,      ${ISSUES_DECIDED}
    filed,    bot-closed,   ${ISSUES_BOT}
    filed,    inconclusive, ${ISSUES_INC}
    decided,  positive,     ${ISSUES_POS}
    decided,  negative,     ${ISSUES_NEG}
\`\`\`

*positive = closed-as-completed, accepted/bug-labeled, or open with maintainer engagement. negative = maintainer rejected (closed-as-not-planned with engagement), or silent treatment (open with no engagement after 7-day grace — wrong target). bot-closed = closed by a bot account, spam-labeled, or stale-bot patterns — these repos already have automated handling, so the offer is redundant. inconclusive = open without engagement within 7-day grace, or closed as duplicate. rate = positive ÷ (positive + negative).*

<details>
<summary>verify</summary>

\`\`\`bash
~/.sweep/bin/scoreboard --since ${ISSUE_EPOCH_DATE}
\`\`\`

</details>

## Feed

${FEED}

## Leaderboard

*since ${EPOCH%T*} (pipeline epoch) | voluntary contributions to repos you don't own | non-owner only | [methodology](https://github.com/kimjune01/kimjune01)*

${LEADERBOARD}

[Join the leaderboard](https://github.com/kimjune01/sweep/blob/master/README.md) · [Protect your repo](https://github.com/kimjune01/sweep/blob/master/action.yml)

## AI SLOP

| PR | time to close | bugs | title |
|---|---|---|---|
| [uptime-kuma#7371](https://github.com/louislam/uptime-kuma/pull/7371) | <1 min | 0 | 🚨⚠️AI Slop⚠️🚨 cherry-picked |
| [uptime-kuma#7372](https://github.com/louislam/uptime-kuma/pull/7372) | <1 min | 0 | 🚨⚠️AI Slop⚠️🚨 cherry-picked |
| [litestar#4755](https://github.com/litestar-org/litestar/pull/4755) | 7 hrs | 0 | closed per AI policy |
| [ruff#25066](https://github.com/astral-sh/ruff/pull/25066) | 2 days | 0 | mainly produced by AI |
| [llama.cpp#22873](https://github.com/ggml-org/llama.cpp/pull/22873) | 2 days | 1 | AI-generated PR detected |

[hypothesis graph](HYPOTHESIS_GRAPH.md)

---

[june.kim](https://june.kim) · AGPL where it matters
READMEEOF

git add README.md HYPOTHESIS_GRAPH.md ISSUE_HYPOTHESIS_GRAPH.md
git diff --cached --quiet || git commit -m "stats: ${MERGED}/${RESOLVED} PRs = ${RATE}% · issues ${ISSUES_POS}/${ISSUES_DECIDED} = ${IRATE}% (${UPDATED})"
git push origin main 2>/dev/null

echo "README updated: ${MERGED}/${RESOLVED} = ${RATE}% at ${UPDATED}"
