#!/usr/bin/env bash
# One command to "host on free infrastructure and start a match":
#   start the match server → get a free public URL via a Cloudflare quick tunnel → start a match → stay up for spectators.
# No account, no credit card. Ctrl-C stops everything and tears it down.
#
#   ./infra/play-free.sh                 # default offline demo (mock, no CLIs needed)
#   ARENA_PRESET=three ./infra/play-free.sh   # real Claude/OpenAI/Grok (each CLI must be logged in locally; local only, never public)
#   ARENA_MODE=task ./infra/play-free.sh      # mode: quiz (default) / task / ctf
#
# Security: whenever host adapters are enabled (ARENA_ALLOW_HOST_ADAPTERS=1, set automatically by PRESET=three),
# no tunnel is opened and the server binds only to 127.0.0.1. Otherwise anyone with the URL could play using your logged-in CLIs.
set -euo pipefail
PORT="${ARENA_PORT:-8798}"
PRESET="${ARENA_PRESET:-demo}"
MODE="${ARENA_MODE:-quiz}"
cd "$(dirname "$0")/.."
if [ "$PRESET" = "three" ]; then
  # For your own local use only: play with the three CLIs you are logged into. Public servers forbid this by default (the owner's keys never play for others).
  export ARENA_ALLOW_HOST_ADAPTERS=1
fi
PUBLIC=1
if [ "${ARENA_ALLOW_HOST_ADAPTERS:-}" = "1" ]; then
  PUBLIC=0
  {
    echo "[warning] Host adapters are enabled (ARENA_ALLOW_HOST_ADAPTERS=1); matches will use the CLIs logged in on this machine."
    echo "[warning] For safety, no Cloudflare tunnel this time: the server binds only to 127.0.0.1 and is visible only on this computer."
  } >&2
fi

command -v uvicorn >/dev/null || { echo "uvicorn is required (pip install -e '.[server]')"; exit 1; }
if [ "$PUBLIC" = "1" ]; then
  command -v cloudflared >/dev/null || { echo "cloudflared is required"; exit 1; }
fi

# Admin token, sent with every start-match request. If the server requires it in host mode, other local web pages (DNS rebinding / CORS) cannot start matches on your behalf.
export ARENA_ADMIN_TOKEN="${ARENA_ADMIN_TOKEN:-$(python3 -c 'import secrets;print(secrets.token_urlsafe(24))')}"
LOG="$(mktemp -t arena_cf.XXXXXX)"
uvicorn server.app:app --host 127.0.0.1 --port "$PORT" --log-level warning \
  --limit-concurrency 300 --timeout-keep-alive 5 &
SRV=$!
CF=""
trap 'kill $SRV ${CF:-} 2>/dev/null; rm -f "$LOG"' EXIT
trap 'exit 130' INT TERM   # interrupt/terminate also goes through the EXIT cleanup, leaving no tunnel or temp file

if [ "$PUBLIC" = "1" ]; then
  # Connect to 127.0.0.1 explicitly (not localhost, which may resolve to ::1 where another process could bind)
  cloudflared tunnel --url "http://127.0.0.1:$PORT" --no-autoupdate >"$LOG" 2>&1 &
  CF=$!
  URL=""
  for _ in $(seq 1 40); do
    URL="$(grep -oE 'https://[-a-z0-9]+\.trycloudflare\.com' "$LOG" | head -1 || true)"
    [ -n "$URL" ] && break; sleep 1
  done
  [ -n "$URL" ] || { echo "Timed out waiting for the public URL"; exit 1; }
else
  URL="http://127.0.0.1:$PORT"
fi
sleep 3

# Build the agent lineup from the preset
if [ "$PRESET" = "three" ]; then
  AGENTS='[{"id":"Claude","adapter":"claude_cli","prompt_author":"you"},{"id":"OpenAI","adapter":"codex_cli","prompt_author":"you"},{"id":"Grok","adapter":"grok_cli","prompt_author":"you"}]'
else
  AGENTS='[{"id":"Alpha","adapter":"mock","model":"demo-A","prompt_author":"x","params":{"reply":"Tokyo"}},{"id":"Beta","adapter":"mock","model":"demo-B","prompt_author":"y","params":{"reply":"Osaka"}}]'
fi
case "$MODE" in
  task) MC='{"tasks":[{"id":"t1","prompt":"Extract the email addresses as a JSON array","context":"ann@a.com and bob@b.com","check":{"kind":"json_keys","min_items":2}}]}' ;;
  ctf)  MC='{"provider":"local","target":"arena-warmup","flag":"FLAG{warmup_recon_ok}","first_blood":true}' ;;
  *)    MC='{"questions":[{"id":"q1","prompt":"What is the capital of Japan? Answer with the city name only.","answer":"Tokyo","kind":"contains"},{"id":"q2","prompt":"What is 17 times 23? Answer with the number only.","answer":"391","kind":"numeric"}]}' ;;
esac

if [ "$PUBLIC" = "1" ]; then
  # Public mode does not allow custom matches: start a fixed demo match (mock vs mock quiz)
  [ "$MODE" = "quiz" ] || echo "[note] Public mode can only run the demo quiz; for a task/ctf demo, set ARENA_ALLOW_HOST_ADAPTERS=1 and run locally." >&2
  MID="$(curl -s --max-time 25 -X POST "http://127.0.0.1:$PORT/api/demo" \
    | python3 -c "import sys,json;print(json.load(sys.stdin).get('match_id',''))" 2>/dev/null || true)"
else
  # Pass the admin token through a curl config on stdin (printf is a shell builtin, so it never shows in the process list), not as a command-line argument
  MID="$(printf 'header = "X-Admin-Token: %s"\n' "$ARENA_ADMIN_TOKEN" | curl -s --max-time 25 --config - \
    -X POST "http://127.0.0.1:$PORT/api/matches" -H 'content-type: application/json' \
    -d "{\"mode\":\"$MODE\",\"ratings_path\":\"\",\"timeout_seconds\":150,\"max_wall_seconds\":400,\"mode_config\":$MC,\"agents\":$AGENTS}" \
    | python3 -c "import sys,json;print(json.load(sys.stdin).get('match_id',''))" 2>/dev/null || true)"
fi
[ -n "$MID" ] || echo "[error] Failed to start the match; see the server output above" >&2

if [ "$PUBLIC" = "1" ]; then HEAD="Match is live on free hosting (no account, no credit card):"; else HEAD="Match is live locally (not public, visible only on this computer):"; fi
cat <<EOF

$HEAD
  URL          $URL
  Lobby        $URL/game/index.html
  Pixel arena  $URL/game/arena.html
  Match ID     ${MID:-(failed to start, see above)}
  Watch live   $URL/game/arena.html?match=$MID&api=$URL

Ctrl-C stops everything and tears it down.
EOF
wait
