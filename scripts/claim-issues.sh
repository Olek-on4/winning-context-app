#!/usr/bin/env bash
# Claim this side's issues and leave the branch-side ones unassigned.
#
# Main side takes the self-contained retrieval/graph/golden work (03, 04, 05, 07): each is
# provable with a local command and touches no fixture data. The extraction-coverage issues
# (01, 02) and the branch landing (06) stay for the feat/quality-filter owner, who owns the
# gate layer and the second implementation.
#
#   bash scripts/claim-issues.sh            # claim
#   DRY_RUN=1 bash scripts/claim-issues.sh  # print
set -euo pipefail
cd "$(dirname "$0")/.."

command -v gh >/dev/null || { echo "gh is not installed"; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "gh is not authenticated: run 'gh auth login'"; exit 1; }

repo=$(gh repo view --json nameWithOwner --jq .nameWithOwner)
claimed=(03 04 05 07)
left_for_branch=(01 02 06)

json=$(gh issue list --repo "$repo" --state all --limit 500 --json number,title,assignees)

number_for() {  # title -> issue number, exact match on the title
  python3 - "$1" "$json" <<'PY'
import json, sys
title, raw = sys.argv[1], sys.argv[2]
for issue in json.loads(raw):
    if issue["title"] == title:
        print(issue["number"])
        break
PY
}

for prefix in "${claimed[@]}"; do
  file=$(ls scripts/issues/"$prefix"-*.md 2>/dev/null | head -1)
  [ -n "$file" ] || { echo "skip  $prefix: no issue file"; continue; }
  title=$(sed -n '1s/^# //p' "$file")
  number=$(number_for "$title")
  if [ -z "$number" ]; then
    echo "skip  $prefix: not filed yet ($title)"
    continue
  fi
  if [ "${DRY_RUN:-}" = "1" ]; then
    echo "would claim #$number $title"
    continue
  fi
  gh issue edit "$number" --repo "$repo" --add-assignee @me >/dev/null
  gh issue comment "$number" --repo "$repo" --body \
    "Claimed from the \`main\` side. Interface it builds on: \`graph/chunks.py\`, \`retrieval/hybrid.py\`, \`retrieval/service.py\`; \`main\` owns those seams, so this lands here and the branch rebases onto it." >/dev/null
  echo "claimed #$number $title"
done

for prefix in "${left_for_branch[@]}"; do
  file=$(ls scripts/issues/"$prefix"-*.md 2>/dev/null | head -1)
  [ -n "$file" ] || continue
  title=$(sed -n '1s/^# //p' "$file")
  number=$(number_for "$title")
  [ -n "$number" ] && echo "left    #$number $title"
done
