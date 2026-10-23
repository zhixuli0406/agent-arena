#!/usr/bin/env bash
# Back up / restore lobby state: player ratings (only a hash of each secret) and the ladder are stored
# on the repo's data branch and restored after each free-server restart (scheduled every 5 hours),
# so ranks and leaderboards carry over.
#
#   ./infra/state-sync.sh restore   # before the server starts: data branch → runs/
#   ./infra/state-sync.sh push      # on a schedule: runs/ → data branch
set -euo pipefail
cd "$(dirname "$0")/.."
FILES=(lobby_state.json ladder.json)
mkdir -p runs
has_remote() { git ls-remote --exit-code --heads origin data >/dev/null 2>&1; }

case "${1:-}" in
  restore)
    if has_remote; then
      git fetch -q origin data
      for f in "${FILES[@]}"; do
        raw="$(mktemp)"
        # Rebuild on restore too: the data branch is part of a public repo, so accept only expected fields
        if git show "FETCH_HEAD:$f" > "$raw" 2>/dev/null && python3 -I infra/sanitize_state.py "$f" "$raw" "runs/$f"; then :; else rm -f "runs/$f"; fi
        rm -f "$raw"
      done
      echo "Restored state from the data branch"
    else
      echo "No data branch yet; starting from empty state"
    fi ;;
  push)
    tmp="$(mktemp -d)"
    trap 'git worktree remove -f "$tmp" >/dev/null 2>&1 || true' EXIT
    if has_remote; then
      git fetch -q origin data
      git worktree add -q -f --detach "$tmp" FETCH_HEAD
    else
      git worktree add -q -f --detach "$tmp"
      (cd "$tmp" && git checkout -q --orphan data-tmp && git rm -rq --cached . && find . -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +)
    fi
    for f in "${FILES[@]}"; do [ -f "runs/$f" ] && cp "runs/$f" "$tmp/$f"; done
    (cd "$tmp" && git add -A -- "${FILES[@]}" 2>/dev/null || true
     if git diff --cached --quiet; then echo "State unchanged"; else
       git commit -q -m "chore: back up lobby state $(date -u +%FT%TZ)" && git push -q origin HEAD:refs/heads/data && echo "Backed up to the data branch"; fi) ;;
  *) echo "Usage: $0 restore|push"; exit 2 ;;
esac
