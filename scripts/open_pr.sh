#!/usr/bin/env bash
#
# Open a pull request for the work in your tree, in one command.
#
#   ./scripts/open_pr.sh "short description of the change"
#   make pr m="short description of the change"
#
# `dev` and `main` are protected, so changes reach them through a pull
# request. That is what runs the test suite before anything is built or
# deployed. This script removes the busywork: it makes the branch, commits,
# pushes, opens the PR, and turns on auto-merge so the PR merges itself the
# moment the checks go green. You do not have to sit and watch it.
#
set -euo pipefail

BASE="${BASE:-dev}"
MSG="${1:-}"

if [[ -z "$MSG" ]]; then
  echo "usage: $0 \"short description of the change\"" >&2
  echo "   or: make pr m=\"short description of the change\"" >&2
  exit 2
fi

command -v gh >/dev/null || { echo "GitHub CLI (gh) is not installed." >&2; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "Run 'gh auth login' first." >&2; exit 1; }

current="$(git rev-parse --abbrev-ref HEAD)"

# Turn the description into a usable branch name: lowercase, non-alphanumerics
# collapsed to hyphens, trimmed.
slug="$(printf '%s' "$MSG" \
  | tr '[:upper:]' '[:lower:]' \
  | sed -E 's/[^a-z0-9]+/-/g; s/^-+|-+$//g' \
  | cut -c1-50)"
[[ -n "$slug" ]] || slug="change"

# Decide which branch this work belongs on. We start a fresh branch when we are
# sitting on a protected branch, and also when the current branch's PR has
# already been merged or closed -- pushing more commits to a merged branch is a
# silent no-op that strands your work.
new_branch=0
if [[ "$current" == "$BASE" || "$current" == "main" ]]; then
  new_branch=1
else
  pr_state="$(gh pr view --json state --jq .state 2>/dev/null || echo NONE)"
  if [[ "$pr_state" == "MERGED" || "$pr_state" == "CLOSED" ]]; then
    echo "==> The PR for $current is already $pr_state; starting a fresh branch"
    new_branch=1
  fi
fi

if (( new_branch )); then
  branch="${slug}-$(date +%m%d-%H%M%S)"
  echo "==> Creating branch $branch"
  git checkout -q -b "$branch"
else
  branch="$current"
  echo "==> Adding to existing branch $branch"
fi

if [[ -n "$(git status --porcelain)" ]]; then
  echo "==> Committing your changes"
  git add -A
  git commit -q -m "$MSG"
else
  echo "==> Nothing new to commit"
fi

if git diff --quiet "origin/$BASE...HEAD" 2>/dev/null; then
  echo "No changes compared to $BASE — nothing to open a PR for." >&2
  exit 1
fi

echo "==> Pushing $branch"
git push -q -u origin "$branch"

if [[ "$(gh pr view --json state --jq .state 2>/dev/null || echo NONE)" == "OPEN" ]]; then
  echo "==> Updated the open pull request"
else
  echo "==> Opening pull request against $BASE"
  gh pr create --base "$BASE" --head "$branch" --title "$MSG" --body "$MSG" >/dev/null
fi
pr_url="$(gh pr view --json url --jq .url)"

# Merge on green rather than on a human refreshing the page. If auto-merge is
# not enabled on the repo this is a no-op and the PR simply waits.
gh pr merge --auto --squash >/dev/null 2>&1 \
  && echo "==> Auto-merge is on: this merges once the checks pass" \
  || echo "==> Auto-merge unavailable; merge manually once the checks pass"

echo
echo "Pull request: $pr_url"
echo "Watch the checks with:  gh pr checks --watch"
