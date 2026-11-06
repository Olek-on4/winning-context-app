#!/usr/bin/env bash
# File the work queue as GitHub issues. Idempotent: an issue whose exact title already
# exists in any state is skipped, so re-running after adding a file only adds the new one.
#
#   bash scripts/file-issues.sh            # check and create
#   DRY_RUN=1 bash scripts/file-issues.sh  # print what would be created
set -euo pipefail
cd "$(dirname "$0")/.."

command -v gh >/dev/null || { echo "gh is not installed"; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "gh is not authenticated: run 'gh auth login'"; exit 1; }

repo=$(gh repo view --json nameWithOwner --jq .nameWithOwner)
existing=$(gh issue list --repo "$repo" --state all --limit 500 --json title --jq '.[].title')
created=0
skipped=0

for file in scripts/issues/*.md; do
  title=$(sed -n '1s/^# //p' "$file")
  if [ -z "$title" ]; then
    echo "skip   $file: first line must be '# <title>'"
    continue
  fi
  if grep -Fxq "$title" <<<"$existing"; then
    echo "exists $title"
    skipped=$((skipped + 1))
    continue
  fi
  if [ "${DRY_RUN:-}" = "1" ]; then
    echo "would  $title"
    continue
  fi
  gh issue create --repo "$repo" --title "$title" --body "$(tail -n +2 "$file")" >/dev/null
  echo "filed  $title"
  created=$((created + 1))
done

echo "created=$created already_present=$skipped repo=$repo"
