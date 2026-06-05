#!/usr/bin/env bash
# ============================================================================
# Company Brain — git auto-snapshot daemon (crash-recovery feeder).
#
# Periodically takes a NON-DESTRUCTIVE snapshot of the working tree (via
# `git stash create`, which never touches your index or working files), saves
# it under refs/snapshots/<session>/<epoch>, and posts a checkpoint to the brain
# with the snapshot SHA + changed files. On a crash you can recover BOTH the
# context (brain resume) and the exact file state (git).
#
# Usage:
#   export BRAIN_URL=https://pazzy.store BRAIN_API_KEY=xxxx
#   ./scripts/brain-autosnapshot.sh /path/to/your/repo
#
# Env: BRAIN_PROJECT, BRAIN_SESSION (default: date), SNAPSHOT_INTERVAL (sec, 120)
#
# Recover later:
#   git for-each-ref refs/snapshots            # list snapshots
#   git stash apply <SHA>                      # restore a snapshot into worktree
#   git checkout <SHA> -- path/to/file         # restore a single file
# ============================================================================
set -euo pipefail

REPO="${1:-$PWD}"
cd "$REPO"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Not a git repository: $REPO" >&2
  exit 1
fi

PROJECT="${BRAIN_PROJECT:-default}"
SESSION="${BRAIN_SESSION:-$(date -u +%Y%m%d)}"
INTERVAL="${SNAPSHOT_INTERVAL:-120}"

echo "Auto-snapshot: repo=$REPO project=$PROJECT session=$SESSION every ${INTERVAL}s"
echo "Stop with Ctrl+C."

while true; do
  if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
    SHA="$(git stash create "brain-snapshot $(date -u +%FT%TZ)" 2>/dev/null || true)"
    if [ -n "${SHA:-}" ]; then
      git update-ref "refs/snapshots/${SESSION}/$(date -u +%s)" "$SHA"
      FILES="$(git status --porcelain | awk '{print $2}' | paste -sd, - 2>/dev/null || echo "")"
      if command -v brain >/dev/null 2>&1; then
        brain checkpoint "auto-snapshot ($(git rev-parse --short HEAD 2>/dev/null || echo nohead))" \
          --session "$SESSION" --git-ref "$SHA" --files "$FILES" \
          --next "git stash apply $SHA" --project "$PROJECT" >/dev/null 2>&1 || true
      fi
      echo "$(date -u +%FT%TZ) snapshot $SHA  files: ${FILES:-none}"
    fi
  fi
  sleep "$INTERVAL"
done
