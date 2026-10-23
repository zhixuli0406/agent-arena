#!/usr/bin/env bash
# Host the match server on truly free infrastructure:
#   no account, no credit card, no setup. A Cloudflare quick tunnel makes it public directly.
# Run this before a match to get a public URL that friends and agents from any vendor can join; Ctrl-C tears it down.
#
#   ./infra/serve-free.sh
#
# Security: a public server never enables host adapters (refuses to open a tunnel when ARENA_ALLOW_HOST_ADAPTERS=1).
set -euo pipefail
PORT="${ARENA_PORT:-8798}"
cd "$(dirname "$0")/.."

if [ "${ARENA_ALLOW_HOST_ADAPTERS:-}" = "1" ]; then
  echo "[warning] Refusing to go public: ARENA_ALLOW_HOST_ADAPTERS=1 would let anyone play using the CLIs logged in on this machine." >&2
  echo "[warning] Unset ARENA_ALLOW_HOST_ADAPTERS before going public; for local use, run ARENA_PRESET=three ./infra/play-free.sh instead." >&2
  exit 1
fi

command -v cloudflared >/dev/null || { echo "cloudflared is required (brew install cloudflared)"; exit 1; }
command -v uvicorn >/dev/null || { echo "uvicorn is required (pip install -e '.[server]')"; exit 1; }

LOG="$(mktemp -t arena_cf.XXXXXX)"
uvicorn server.app:app --host 127.0.0.1 --port "$PORT" --log-level warning \
  --limit-concurrency 300 --timeout-keep-alive 5 &
SRV=$!
# Connect to 127.0.0.1 explicitly (not localhost, which may resolve to ::1 where another process could bind)
cloudflared tunnel --url "http://127.0.0.1:$PORT" --no-autoupdate >"$LOG" 2>&1 &
CF=$!
trap 'kill $SRV $CF 2>/dev/null; rm -f "$LOG"' EXIT
trap 'exit 130' INT TERM   # interrupt/terminate also goes through the EXIT cleanup, leaving no tunnel or temp file

URL=""
for _ in $(seq 1 40); do
  URL="$(grep -oE 'https://[-a-z0-9]+\.trycloudflare\.com' "$LOG" | head -1 || true)"
  [ -n "$URL" ] && break
  sleep 1
done
[ -n "$URL" ] || { echo "Timed out waiting for the public URL; see $LOG"; exit 1; }

cat <<EOF

Match server is live (free, no credit card, no account):
  Public URL   $URL
  Health       $URL/api/health
  Lobby        $URL/game/index.html
  Join         python -m clients.arena_connect --server $URL --name your-name --cmd "your agent command"
  Watch live   $URL/game/index.html?match=<id>&api=$URL

Ctrl-C stops everything and tears it down.
EOF
wait
