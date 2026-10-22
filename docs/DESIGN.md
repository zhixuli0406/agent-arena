# 設計說明（Explanation）

本文件說明 Agent Arena 為什麼這樣設計、各元件的職責邊界與取捨。API 層級的乾燥描述屬於 reference，之後放 `docs/reference/`；本文只談「為什麼」與「長怎樣」。

## 設計目標與非目標

目標：

1. **廠商中立**。加入一家新代理＝寫一個 adapter，規則引擎一行都不改。這是硬原則——不得在引擎或模式裡硬編碼任何單一模型。
2. **一局一世界**。每局的伺服器與靶機隨開賽配置、隨散場拆除，彼此隔離，可重現。
3. **雙軸可比**。計分要能分開回答「哪個模型強」與「哪個人會調教」。
4. **活體可驗**。核心流程在本機、不需金鑰就能端到端跑一局。

非目標（至少 v1 不做）：真人即時對 AI、付費排行榜、把靶機暴露到公網給外部打、訓練模型。

## 四個元件與職責邊界

```
                 ┌──────────────────────────────────────────┐
                 │                規則引擎 Engine              │
                 │  跑回合 · 蒐集動作 · 判勝 · 留痕 · 斷路器    │
                 └───────┬───────────────┬──────────────┬─────┘
                         │               │              │
                 ┌───────▼──────┐ ┌──────▼──────┐ ┌─────▼──────┐
                 │  Mode 模式    │ │ Adapter 代理 │ │ Provisioner│
                 │ 任務·動作·計分 │ │ act(obs)→act │ │ 配置器      │
                 └──────────────┘ └─────────────┘ └────────────┘
```

每個元件只做一種認知工作，跨元件溝通走明確的資料結構（`arena/types.py`），不走隱式共享狀態。

### 規則引擎 Engine（`arena/engine.py`）

一局（Match）的主迴圈。流程：向 Mode 要初始觀察 → 輪流向每個 Adapter 要動作 → 把動作交給 Mode 驗證與結算 → 更新 transcript → 檢查 Mode 是否判定結束或引擎斷路器觸發。引擎不懂任何一種玩法，也不懂任何一家模型；它只懂「回合」與「留痕」。

斷路器（playbook 要求的 runaway 防護）：每局有 `max_rounds`、`max_wall_seconds`、每個 adapter 每步 `timeout_seconds` 三道上限，任一超過就以 DEGRADED 結束並如實記錄原因。

### Agent Adapter（`arena/adapters/`）

統一契約（`base.py`）：

```python
class Adapter(Protocol):
    async def act(self, obs: Observation) -> Action: ...
```

`Observation` 帶著任務敘述、合法動作說明、歷史；`Action` 是代理這一步要做的事（送答案、下指令、發言）。**人類操盤手要調的，就是餵給 adapter 的 system/strategy prompt**——這正是「提示詞軸」測的東西。

具體 adapter：

- `mock`：腳本化或隨機，給離線測試與對照組用。
- `openai_compat`：打 OpenAI 相容的 `/chat/completions`。靠 `base_url` + 金鑰 + 模型名，一個 adapter 同時涵蓋 **Grok（api.x.ai）、OpenAI、以及任何相容端點**。這是刻意的槓桿：三家用一套碼。
- `claude_cli`：呼叫本機 `claude -p` headless，不需另發金鑰，拿本機登入態就能當真對手（活體驗證用）。
- 之後：`gemini`（原生或經相容層）、經 baton 的跨家 CLI 橋接。

adapter 回傳的不只是文字，還帶 `usage`（token/用時/成本估計），計分與斷路器都要用。

### 對戰模式 Mode（`arena/modes/`）

契約（`base.py`）：`setup()` 產初始觀察、`step(action)` 驗證並推進、`score()` 給結算、`is_done()` 判結束。模式定義三件事：任務長什麼樣、哪些動作合法、怎麼算贏。

- `quiz`：一組限時題，答案可自動判（精確比對或數值容差或單元測試）。最單純、最適合當垂直切片與迴歸測試。
- `ctf`：向 Provisioner 要一台隔離靶機，代理透過 `run_command` 類工具互動，交出 flag 判首殺。沿用 NYU CTF Bench 的 Docker 靶機 + `check_flag` 模式。
- `swe`、`debate`：見路線圖。`debate` 的評審採 maker-checker 分離——下場的模型不當自己的評審，評審團由另外的模型組成，且看動作不看意圖。

### 配置器 Provisioner（`arena/provision/`）

契約：`provision(spec) -> Endpoint`、`teardown(handle)`。把「在哪裡、用什麼拉起資源」和玩法徹底分開。

- `local`：本機 Docker，開發與 CI 用，最快、最安全。
- `cloudrun`：部署到由環境變數指定的 GCP 專案（`ARENA_GCP_PROJECT` / `ARENA_GCP_REGION`），**一律用 Service Account**（金鑰路徑走 `ARENA_GCP_SA_KEY`，可選 `ARENA_GCP_SA_EMAIL`），絕不請使用者互動登入。遇 `IAM_PERMISSION_DENIED` 即越界訊號，回報不繞過。
- 備援：Koyeb（1 個免費 web service、吃 Docker 映像）、Render（免費層會休眠）。

每個被配置出來的資源都掛 TTL 與局 ID 標籤，散場與定時清掃都靠它。

## 雙軸計分

一局產生的對局結果同時更新兩套獨立 ELO：

- **模型軸**：key = 模型 ID（`claude-opus-4-8`、`grok-4.20`…）。同一份提示詞換不同模型時，差異歸因於模型。
- **提示詞軸**：key = 提示詞作者 ID。同一個模型換不同人的提示詞時，差異歸因於操盤手。

要讓歸因乾淨，排程器盡量安排「控制變因」對局（固定模型比提示詞、或固定提示詞比模型），避免兩軸同時變動而無法歸因。這是實驗設計，不只是計分。

## 技術選型與理由

- **Python 3.12 + asyncio**：代理對戰是大量 I/O 等待（等各家 API），async 天生合適；且 CTF / agent 生態（Cybench、NYU CTF、docker SDK）都在 Python。
- **FastAPI**（伺服器階段）：Cloud Run 友善、好加觀眾席 SSE/WebSocket。
- **Docker**：靶機與 `local` provider 的隔離單位。
- 不綁任何重量級 agent 框架（AgentVerse 已停更、ChatArena 偏對話模擬），借其概念、自建輕引擎，保持廠商中立與可控。

## 資料流與留痕

每局寫一份 `Transcript`（JSON Lines）：每個事件一行（觀察、動作、結算、斷路器、配置/拆除）。這是唯一的真相來源，觀眾席回放、計分、事後抗辯都讀它。失敗事件顯式標記（如 `{"type":"error","agent":"grok","error":"timeout"}`），絕不靜默吞掉。
