#!/usr/bin/env bash
# 把對戰伺服器架到「真正完全免費」的空間：
#   零帳號、零信用卡、零設定——用 Cloudflare quick tunnel 直接對外公開。
# 一局開始前跑這支，拿到公開網址，朋友/各家代理就能連進來對戰；Ctrl-C 自動拆除。
#
#   ./infra/serve-free.sh
set -euo pipefail
PORT="${ARENA_PORT:-8798}"
cd "$(dirname "$0")/.."

command -v cloudflared >/dev/null || { echo "需要 cloudflared（brew install cloudflared）"; exit 1; }
command -v uvicorn >/dev/null || { echo "需要 uvicorn（pip install -e '.[server]'）"; exit 1; }

LOG="$(mktemp -t arena_cf.XXXXXX)"
uvicorn server.app:app --host 127.0.0.1 --port "$PORT" --log-level warning &
SRV=$!
cloudflared tunnel --url "http://localhost:$PORT" --no-autoupdate >"$LOG" 2>&1 &
CF=$!
trap 'kill $SRV $CF 2>/dev/null; rm -f "$LOG"' EXIT

URL=""
for _ in $(seq 1 40); do
  URL="$(grep -oE 'https://[-a-z0-9]+\.trycloudflare\.com' "$LOG" | head -1 || true)"
  [ -n "$URL" ] && break
  sleep 1
done
[ -n "$URL" ] || { echo "取得公開網址逾時，見 $LOG"; exit 1; }

cat <<EOF

對戰伺服器已上線（免費、免信用卡、免帳號）：
  公開網址   $URL
  健康檢查   $URL/api/health
  像素遊戲   $URL/game/arena.html
  建房       POST $URL/api/rooms
  隨機配對   POST $URL/api/queue
  即時觀戰   $URL/game/arena.html?match=<id>&api=$URL

Ctrl-C 結束並自動拆除。
EOF
wait
