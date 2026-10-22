#!/usr/bin/env bash
# 一鍵「開賽即在免費空間自動架站並開打」：
#   起對戰伺服器 → Cloudflare quick tunnel 取得免費公開網址 → 自動開一局 → 保持上線供觀戰。
# 零帳號、零信用卡。Ctrl-C 結束並自動拆除。
#
#   ./infra/play-free.sh                 # 預設離線 demo（mock，免任何 CLI）
#   ARENA_PRESET=three ./infra/play-free.sh   # 真實三家 Claude/OpenAI/Grok（需本機各家 CLI 已登入）
#   ARENA_MODE=task ./infra/play-free.sh      # 題型：quiz(預設)/task/ctf
set -euo pipefail
PORT="${ARENA_PORT:-8798}"
PRESET="${ARENA_PRESET:-demo}"
MODE="${ARENA_MODE:-quiz}"
cd "$(dirname "$0")/.."

command -v cloudflared >/dev/null || { echo "需要 cloudflared"; exit 1; }
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
  [ -n "$URL" ] && break; sleep 1
done
[ -n "$URL" ] || { echo "取得公開網址逾時"; exit 1; }
sleep 3

# 依 preset 組出參賽代理
if [ "$PRESET" = "three" ]; then
  AGENTS='[{"id":"Claude","adapter":"claude_cli","prompt_author":"you"},{"id":"OpenAI","adapter":"codex_cli","prompt_author":"you"},{"id":"Grok","adapter":"grok_cli","prompt_author":"you"}]'
else
  AGENTS='[{"id":"Alpha","adapter":"mock","model":"demo-A","prompt_author":"x","params":{"reply":"東京"}},{"id":"Beta","adapter":"mock","model":"demo-B","prompt_author":"y","params":{"reply":"大阪"}}]'
fi
case "$MODE" in
  task) MC='{"tasks":[{"id":"t1","prompt":"抽出 email 成 JSON 陣列","context":"ann@a.com 與 bob@b.com","check":{"kind":"json_keys","min_items":2}}]}' ;;
  ctf)  MC='{"provider":"local","target":"arena-warmup","flag":"FLAG{warmup_recon_ok}","first_blood":true}' ;;
  *)    MC='{"questions":[{"id":"q1","prompt":"日本的首都是哪座城市？只回答城市名。","answer":"東京","kind":"contains"},{"id":"q2","prompt":"17 乘以 23 等於多少？只回答數字。","answer":"391","kind":"numeric"}]}' ;;
esac

MID="$(curl -s --max-time 25 -X POST "http://127.0.0.1:$PORT/api/matches" -H 'content-type: application/json' \
  -d "{\"mode\":\"$MODE\",\"ratings_path\":\"\",\"timeout_seconds\":150,\"max_wall_seconds\":400,\"mode_config\":$MC,\"agents\":$AGENTS}" \
  | python3 -c "import sys,json;print(json.load(sys.stdin).get('match_id',''))" 2>/dev/null || true)"

cat <<EOF

對戰已在免費空間開打（零帳號、零信用卡）：
  公開網址   $URL
  大眾介面   $URL/game/index.html
  像素劇場   $URL/game/arena.html
  本局 ID    ${MID:-（開賽失敗，請見上）}
  即時觀戰   $URL/game/arena.html?match=$MID&api=$URL

Ctrl-C 結束並自動拆除。
EOF
wait
