#!/usr/bin/env bash
# CI only (arena-cloud workflow): copy lobby state out of the isolated server account and push it.
#
# The server account may be compromised, so:
#   - files are read AS that account (sudo -u arena), never as root: a symlink to the runner's
#     /proc/<pid>/environ or any other file it can't read itself gets nothing;
#   - reads are time-limited and size-capped (a FIFO or /dev/zero can't hang or fill the disk);
#   - the content is rebuilt by sanitize_state.py, so only expected fields reach the public data branch.
set -euo pipefail
cd "$(dirname "$0")/.."
SRC="${ARENA_ISOLATED_RUNS:-/opt/arena/runs}"
MAX=2000000
mkdir -p runs
for f in lobby_state.json ladder.json; do
  raw="$(mktemp)"; clean="$(mktemp)"
  if timeout 10 sudo -n -u arena head -c $((MAX + 1)) -- "$SRC/$f" > "$raw" 2>/dev/null \
     && [ "$(wc -c < "$raw")" -le "$MAX" ] \
     && python3 -I infra/sanitize_state.py "$f" "$raw" "$clean"; then
    mv "$clean" "runs/$f"
  else
    echo "Skipping $f (missing, too large, or malformed)"
  fi
  rm -f "$raw" "$clean"
done
# ARENA_BACKUP_DRY=1: copy and sanitize only (the workflow's isolation check runs it this way)
if [ "${ARENA_BACKUP_DRY:-}" != "1" ]; then ./infra/state-sync.sh push; fi
