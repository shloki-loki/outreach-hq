#!/bin/bash
# One-time: turn ./data into a checkout of the repo's `data` branch, so every writer shares it.
# Safe to re-run. Needs the GitHub remote `origin` to exist.
set -euo pipefail
cd "$(dirname "$0")/.."

if git -C data rev-parse --is-inside-work-tree >/dev/null 2>&1 && [ -e data/.git ]; then
  echo "data/ is already a git checkout."; exit 0
fi

if git ls-remote --exit-code --heads origin data >/dev/null 2>&1; then
  # The branch exists on GitHub: keep any local files aside and check it out.
  [ -d data ] && mv data "data.local.$(date +%s)"
  git fetch origin data
  git worktree add data data 2>/dev/null || git worktree add -B data data origin/data
else
  # First time: publish the local files as the data branch.
  tmp="$(mktemp -d)"
  [ -d data ] && cp -R data/. "$tmp"/ && mv data "data.local.$(date +%s)"
  git worktree add --detach data
  git -C data checkout --orphan data
  git -C data rm -rf --quiet . >/dev/null 2>&1 || true
  cp -R "$tmp"/. data/
  git -C data add -A
  git -C data -c user.name=outreach-hq -c user.email=outreach-hq@users.noreply.github.com commit --quiet -m "data: initial import"
  git -C data push --quiet -u origin data
fi
echo "data/ now tracks origin/data."
