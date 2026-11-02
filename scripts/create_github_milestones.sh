#!/usr/bin/env bash
# After you create the GitHub repo and authenticate via `gh auth login`:
# bash scripts/create_github_milestones.sh
# Idempotent for the milestone titles listed below.
set -euo pipefail
repo="$(gh repo view --json nameWithOwner --jq '.nameWithOwner')"
existing="$(gh api "repos/$repo/milestones?state=all&per_page=100" --jq '.[].title')"

titles=(
  'M0 — Repository foundation'
  'M1 — Calendar decision graph'
  'M2 — Structured intent'
  'M3 — Tool execution'
  'M4 — Failure handling & replan'
  'M5 — Session & approval'
  'M6 — Backend integration'
  'M7 — Evaluation & portfolio'
)
for title in "${titles[@]}"; do
  if printf '%s\n' "$existing" | grep -Fqx "$title"; then
    echo "Exists: $title"
  else
    gh api -X POST "repos/$repo/milestones" \
      -f "title=$title" \
      -f 'description=See docs/milestones.md for deliverables and acceptance criteria.' \
      --silent
    echo "Created: $title"
  fi
done
