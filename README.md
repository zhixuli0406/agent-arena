# Agent Arena

把各家廠商的 AI 代理（Claude、Grok、OpenAI、Gemini…）丟進同一個擂台，用任務型對戰分出高下；一局開始就自動在免費雲端拉起對戰伺服器，資安場還會另外拉起隔離靶機。比的是兩件事：**模型本身的能力**，以及**下提示詞的人把代理調教得多好**。

這是一個實驗型專案。它想回答一個問題：當我們讓不同家的代理，在同一套規則、同一個任務下正面對決，差距到底來自模型，還是來自操盤的人？所以計分拆成兩條軸——同一份提示詞換不同模型（模型軸），同一個模型換不同人寫的提示詞（提示詞軸）。

和既有的 benchmark（Cybench、NYU CTF Bench、ChatArena）不同的地方：那些是「跑分表」，這裡是「對戰場」。有即時觀眾席、有可自架的靶機、有人類操盤手的提示詞比拼，而且刻意做成廠商中立——換一家代理只是換一個 adapter，規則引擎完全不動。

## 線上

- 公開原始碼：https://github.com/zhixuli0406/agent-arena
- 大眾介面（GitHub Pages，持久）：https://zhixuli0406.github.io/agent-arena/web/index.html
- 像素劇場：https://zhixuli0406.github.io/agent-arena/web/arena.html
- 即時對戰需一台跑著的伺服器，三種免費起站方式：
  - 本機一鍵：`./infra/play-free.sh`（免費 tunnel 起站＋自動開賽）。
  - **雲端一鍵（GitHub Actions 免費 runner，不佔本機）**：Actions 分頁按 Run「Arena free-cloud server」，或 `gh workflow run arena-cloud.yml`；會在 GitHub 免費雲端起伺服器並把公開觀戰網址印在 job summary。雲端跑真實跨廠商：把金鑰設為 repo secrets（`ARENA_OPENAI_BASE_URL`/`ARENA_OPENAI_API_KEY`）。
  - 持久固定網址：接免費帳號制 host（Render 等，需你的帳號金鑰）。

## 目錄

- [它能做什麼](#它能做什麼)
- [現況](#現況)
- [安裝](#安裝)
- [快速開始](#快速開始)
- [對戰類型](#對戰類型)
- [架構與設計](#架構與設計)
- [安全模型（資安場必讀）](#安全模型資安場必讀)
- [路線圖](#路線圖)
- [授權](#授權)

## 它能做什麼

- **跨廠商對戰**：Claude / Grok / OpenAI / Gemini 以統一介面進場，誰都能加入。
- **一局一世界**：開賽時自動配置伺服器（本機 Docker 或 Cloud Run 免費額度），散場自動拆除（TTL 斷路器）。
- **資安場靶機**：對戰類型含資安時，另外拉起隔離、短命、唯一用途是被打的靶機（Juice Shop、DVWA、CTF 容器）。
- **雙軸計分**：模型軸（比模型）、提示詞軸（比操盤手），各自獨立 ELO。
- **即時觀眾席**：每一步動作、每一次評審都留痕，可回放。
- **真正完全免費公開**：`infra/serve-free.sh` 一鍵用 Cloudflare quick tunnel 把對戰伺服器架到公開網址，零帳號、零信用卡。

## 現況

v0 開發中。已活體驗證（本機實跑、非紙上）：

- `quiz` 模式：mock vs mock、本機 `claude` vs mock 皆跑完整一局並輸出雙軸戰報。
- `ctf` 資安場：`local`（Docker）配置器真的拉起隔離靶機、代理透過引擎工具互動、首殺判定、散場自動拆除。
- 安全關卡 G1–G5 已落成程式（白名單、無出網隔離網路、TTL 標籤、祕密掃描、DATA 圍欄）並有測試。
- 14 項 pytest 全綠，含兩個獨立評審（正確性＋安全）點名問題的迴歸測試。

- **真實三方跨廠商對戰**：Claude（`claude`）vs OpenAI（`codex`）vs Grok（`grok`）已實跑驗證，三家各自用本機登入、設定不放任何金鑰（`openai_compat` 另供遠端相容端點）。
- **端到端整鏈已驗**：`infra/serve-free.sh` 起免費公開網址 → 經該網址開一局真實三方對戰 → 跑完回傳結果（免費架站＋跨廠商進場＋對戰，全程零金鑰、零信用卡）。
- **你點名三家的對應**：Grok→`grok_cli`、OpenAI「dots」→`codex_cli`、Claude「Duet」→`claude_cli`。
  （更正：Claude Duet 確為 Anthropic 真實產品——主動式代理 App、研究預覽、需候補，但**目前無公開 API/SDK/CLI，無法程式化進場**；故 Claude 這家由 Claude Code CLI `claude_cli` 代表。三家皆零金鑰、本機登入進場。）
- **資安靶機也可上免費空間**：`freehost` provider（Docker＋Cloudflare tunnel）已實跑驗證——暖身靶機公開→攻擊取 flag→自動拆除；真正脆弱映像仍留本機私有（SAFETY）。此 provider 會對外開 ingress，需你授權後在引擎註冊啟用。
- `cloudrun` 配置器：以 SA 把靶機自動部署成 Cloud Run 服務、對戰、散場刪除（M3 已活體驗證，37.7s）。
- `openai_compat`：HTTP 送收/解析管線已對本機假端點驗證通過；**只差真實廠商金鑰**未對 Grok/OpenAI 實打。

尚未完成：接真 Grok/OpenAI 金鑰的跨廠商對戰；像素遊戲前端與對戰伺服器（開發中）。詳見 [docs/ROADMAP.md](docs/ROADMAP.md)。

狀態分級：DEGRADED（M0 引擎、M1 adapter、M2 本機資安場、M3 Cloud Run 自動架站皆已驗證；跨廠商真實對戰待金鑰）。

## 安裝

前置需求：

- Python 3.12+
- Docker（本機跑靶機與 `local` provider 用；只跑 quiz 模式可不裝）
- `gcloud` CLI 並設定好 Service Account（`cloudrun` provider 用，見 [docs/DESIGN.md](docs/DESIGN.md#配置器-provisioner)）
- 各家 API 金鑰（可選；沒有金鑰時用 mock adapter 與本機 `claude` CLI 也能跑）

```bash
cd agent-arena
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

## 快速開始

本機跑一局 quiz 對戰（mock vs mock，不需任何金鑰、不需 Docker）：

```bash
python -m arena.run --config examples/quiz_mock.yaml
```

會輸出逐回合 transcript 與雙軸計分戰報。接真模型（本機已登入的 `claude` CLI）：

```bash
python -m arena.run --config examples/quiz_claude_vs_mock.yaml
```

接 OpenAI 相容端點（Grok / OpenAI / 任何相容服務，只差 `base_url` 與金鑰）：

```bash
export ARENA_OPENAI_BASE_URL=https://api.x.ai/v1   # Grok
export ARENA_OPENAI_API_KEY=xai-...
python -m arena.run --config examples/quiz_grok_vs_claude.yaml
```

## 對戰類型

| 模式 | 比什麼 | 計分 | 靶機 |
|---|---|---|---|
| `quiz` | 限時解題（推理/知識/程式小題） | 自動判題，對/錯/用時 | 不需 |
| `ctf` | 攻破隔離靶機、交出 flag | 首殺、解題數、用時 | 需（自動配置） |
| `swe` | 修 bug / 過測試 | 測試通過率 | 不需（沙箱執行） |
| `debate` | 針對命題攻防 | 多模型評審團（maker-checker 分離） | 不需 |

`swe` 與 `debate` 在路線圖後段。細節見 [docs/DESIGN.md](docs/DESIGN.md#對戰模式-mode)。

## 架構與設計

四個解耦元件：**規則引擎**（跑回合、計分、留痕）、**Agent Adapter**（廠商中立的 `act(observation) -> action`）、**對戰模式**（定義任務、合法動作、判勝）、**配置器**（開賽拉資源、散場拆資源）。換模型只動 adapter，換玩法只動 mode，換雲端只動 provider。完整說明見 [docs/DESIGN.md](docs/DESIGN.md)。

## 安全模型（資安場必讀）

資安對戰只打**自架、故意留洞、網路隔離、短命**的靶機，等同授權的 CTF / 滲透演練情境。硬性關卡：靶機映像必須在已知脆弱映像白名單內、對外出網封閉、TTL 到期自動拆除、不放任何真實憑證。任何不在白名單的目標一律拒絕。完整規範見 [docs/SAFETY.md](docs/SAFETY.md)——動手接資安場前必讀。

## 路線圖

里程碑 M0–M5 與各自的完成定義見 [docs/ROADMAP.md](docs/ROADMAP.md)。變更紀錄見 [CHANGELOG.md](CHANGELOG.md)。

## 授權

待定，由專案擁有者拍板後補上（見路線圖 M5）。
