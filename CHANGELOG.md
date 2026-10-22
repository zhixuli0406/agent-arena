# Changelog

本檔案記錄本專案所有值得注意的變更。格式依 [Keep a Changelog](https://keepachangelog.com/zh-TW/1.1.0/)，版本遵循 [Semantic Versioning](https://semver.org/lang/zh-TW/)。

## [Unreleased]

### Added
- 專案骨架與設計文件：README（READMEDD）、`docs/DESIGN.md`、`docs/SAFETY.md`、`docs/ROADMAP.md`。
- 廠商中立的四元件架構（Engine / Adapter / Mode / Provisioner）。
- 規則引擎：回合主迴圈、三道斷路器（max_rounds / max_wall_seconds / per-step timeout）、JSONL 留痕。
- Adapter：`mock`、`claude_cli`（本機 headless）、`openai_compat`（Grok/OpenAI/相容端點共用一套碼）。
- Mode：`quiz`（限時解題，四種判題）、`ctf`（資安場，攻打隔離靶機、首殺判定）。
- Provisioner：`local`（Docker runner-sidecar 隔離模型）與 `cloudrun`（以 SA 部署 Cloud Run 靶機、identity token 呼叫、散場刪除）；`targets/warmup` 自帶暖身靶機與白名單。
- 雙軸 ELO：模型軸與提示詞軸，賽前快照、order-invariant。
- 安全層 `security.py`：秘密遮蔽、DATA 圍欄、base_url 白名單校驗、模型名校驗；清掃程序 `provision/reaper.py`。
- 安全模型 G1–G6 與硬性關卡；14 項 pytest（含雙評審點名問題的迴歸測試）。
- 對戰伺服器房間與隨機配對端點（`/api/rooms`、`/api/rooms/{code}/join|start`、`/api/queue`）：私人房間揪朋友、隨機配對、多人/組隊、不限 1v1。
- 組隊計分與團隊 ELO（team 軸，賽前快照 order-invariant）；`AgentSpec.team` 欄位。
- 像素型對戰遊戲前端 `web/arena.html`（8-bit transcript replayer；組隊上色、團隊 ELO 結算、`?match=` 即時 SSE 觀戰）。
- `infra/serve-free.sh`：一鍵把對戰伺服器架到真正完全免費的空間（Cloudflare quick tunnel，零帳號／零信用卡），已實測公開網址端到端可用。
- `codex_cli`（OpenAI，`codex exec`）與 `grok_cli`（xAI，`grok --prompt-file ... --output-format plain`）adapter：用各家本機登入驅動真正的代理，設定不放任何金鑰。
- **已實跑驗證真實三方跨廠商對戰：Claude vs OpenAI vs Grok**（三家各答對、約 16–18s），零金鑰。

### Security
- 資安場預設禁用宿主側 agentic 代理（C1）；靶機跑在無出網隔離網路（G2）；transcript 以 0600 建立並遮蔽疑似憑證（M1）。
