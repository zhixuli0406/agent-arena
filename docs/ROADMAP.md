# 路線圖

每個里程碑都附完成定義（DoD）。依 playbook：code 寫完不是完成，要 build 過、測試過、活體驗證過，文件同 commit 更新。

## M0 — 核心引擎垂直切片 ✅（已驗證 2026-10-22）

讓一局 quiz 對戰在本機端到端跑通。

- [x] 專案骨架、README（READMEDD）、設計/安全/路線圖文件
- [x] `types`：Observation / Action / MatchConfig / AgentSpec / Event / MatchResult
- [x] Adapter：`base` + `mock`
- [x] Mode：`base` + `quiz`（判題 exact/choice/contains/numeric，已修評審點名的子字串假陽性）
- [x] Engine：主迴圈 + 三道斷路器 + JSONL 留痕（try/finally、transcript 0600）
- [x] 雙軸 ELO 計分（賽前快照、order-invariant；狀態非 COMPLETE 跳過更新）
- [x] CLI `arena.run` + 範例設定
- [x] 測試（quiz 判題、斷路器、ELO 順序不變性）
- **DoD**：✅ `python -m arena.run --config examples/quiz_mock.yaml` 跑出完整戰報；pytest 綠燈；本機實跑過。

## M1 — 真實 adapter（部分完成）

- [x] `claude_cli`（本機 `claude -p` headless，stdin 傳 prompt、process group 回收、標記 host_actor）✅ 活體驗證
- [x] `codex_cli`（本機 `codex exec`，真正的 OpenAI 代理，用其自身登入）✅ **Claude vs OpenAI 真實跨廠商對戰已實跑驗證**
- [x] `grok_cli`（本機 `grok --prompt-file ... --output-format plain`，真正的 xAI Grok，用其自身登入）✅ **真實三方 Claude vs OpenAI vs Grok 已實跑驗證**
- [x] 三家原生 CLI 皆零金鑰驅動（Claude/OpenAI/Grok）；`openai_compat` 仍保留給遠端相容端點（需金鑰）
- [x] `openai_compat`（涵蓋 Grok / OpenAI / 相容端點，base_url 白名單校驗）— 已實作，**缺金鑰未活體驗證**
- [x] usage（token/用時）回收進戰報
- **DoD**：claude vs mock ✅ 已實跑；Grok vs Claude 待金鑰。無金鑰時以 mock 降級並明示 ✅。

## M2 — 資安場與本機配置器 ✅（已驗證 2026-10-22）

- [x] Provisioner `base` + `local`（Docker，runner sidecar 隔離模型，實測主機封閉/靶機無出網）
- [x] `targets/allowlist.yaml` + 自帶 `arena-warmup` 靶機（Juice Shop/DVWA/WebGoat 已列白名單待接）
- [x] `ctf` 模式：HTTP 工具（GET/POST/SUBMIT 嚴格文法）、常數時間 check_flag、首殺判定、請求預算
- [x] 安全關卡 G1–G5 落地 + 測試（白名單拒絕、C1 宿主代理拒絕、隔離、DATA 圍欄）
- **DoD**：✅ 本機 Docker 拉起靶機，mock 攻擊者透過引擎工具交 flag、散場自動拆除；CLI 戰報與 pytest 皆通過。
- 待補：接 Juice Shop 等 OSS 靶機（映像較大、啟動較久）、attacker-container shell 模式（比 HTTP 更真實但隔離更複雜）。

## M3 — 雲端自動配置（靶機部署 ✅ 已驗證 2026-10-22）

> 使用者 2026-10-22 指示免費架站要「真正完全免費（免信用卡、不計費）」。Cloud Run 需綁卡＋超額計費，**非完全免費**，故以下 cloudrun 僅為選項之一；「真正免費 host」選型研究被 session 用量上限中斷（台北 12am 重置），待重跑。
> 另註：cloudrun provider 為用量上限交棒期間由 codex 代筆，codex 宣稱已自測部署成功，但**尚未經本機逐行覆核**。

- [x] `cloudrun` provider：以 SA 把靶機部署成 Cloud Run 服務、identity token 呼叫、散場刪除；遇 IAM_PERMISSION_DENIED 停工回報（G6）
- [x] 活體驗證：`arena.run --config examples/ctf_warmup_cloudrun.yaml` 真的部署→對戰→刪除，37.7s，無殘留
- [x] **真正完全免費公開伺服器**：`infra/serve-free.sh` 用 Cloudflare quick tunnel（零帳號／零信用卡）一鍵把對戰伺服器對外公開 ✅ 已實測公開 `*.trycloudflare.com` 網址可達、開局、並服務像素遊戲
- [ ] 持久免費 host 的 provider（Render，需你的免費帳號 API 金鑰）；或部署上 Cloud Run（非免費選項）
- [ ] OSS 靶機（Juice Shop 等）上 Cloud Run 需先補 VPC egress 控制（目前 cloudrun 只收自架 self 靶機）
- **DoD**：✅ 一道指令在 Cloud Run 免費額度內拉起靶機、跑完一局、自動拆除、用 SA 非互動登入。

## M4 — 對戰伺服器與像素遊戲前端

- [x] FastAPI 對戰伺服器 `server/app.py`：開局、SSE 即時串流 transcript、查結果、托管前端 ✅ 本機實跑驗證
- [~] 像素型遊戲前端 `web/arena.html`：把對局演成 8-bit 復古對戰（fork 進行中；受限流影響，狀態待確認）
- [ ] 提示詞提交介面（操盤手上傳 strategy prompt）
- **DoD**：瀏覽器即時觀戰一局、看到像素演出與雙軸排行；視覺無跑版。

## M6 — 配對、房間與多人/組隊（2026-10-22 使用者追加）

- [x] `AgentSpec.team` 欄位；引擎參賽者本為 list → N 人對戰結構已支援
- [x] 隨機配對 `/api/queue`：同 mode 湊滿人數自動開賽 ✅ 本機實測
- [x] 私人房間 `/api/rooms`（建房碼、加入、房主開賽）✅ 本機實測
- [x] 多對多與組隊：`team` 分組、團隊聚合計分、團隊 ELO（team 軸，order-invariant）✅ 2v2 本機實測
- [ ] 把房間/配對/組隊接進像素遊戲前端（目前為 API 層，前端 UI 待接）
- **DoD**：✅ API 已可建房邀友/隨機配對/2v2 組隊並正確團隊計分；⏳ 瀏覽器端介面待接。

## M5 — 收尾

- [ ] `swe` / `debate` 模式
- [ ] 授權條款拍板（擁有者決定）
- [ ] 發佈決策（擁有者決定）
- **DoD**：擁有者親測放行。

## 待拍板（擁有者關卡）

- 授權條款（MIT / Apache-2.0 / 私有）
- 是否公開發佈、用什麼名義
- v1 先做哪些對戰類型的優先序
