# 2026-10-24 接入流程發布追蹤

更新時間：2026-10-24 02:47 Asia/Taipei

專案／分支／基線：`agent-arena`／`main`／功能提交 `3141ab5`；部署機器人以 `1eb060e` 更新 `server.json`

此次範圍：修正重複玩家接入流程、建立 CI、重新部署公開後端與 GitHub Pages、公開站點驗收。

授權：使用者明確要求「CI、線上部署與公開站點驗收，另外重新部署後端」。

工程進度：`COMPLETE`

發布就緒：`GO`

發布動作：已提交、推送、部署並驗證

## 阻擋清單

| ID | 類型／嚴重度 | 問題與阻擋理由 | 狀態 | 關單條件 |
|---|---|---|---|---|
| R1 | 程式缺陷／P1 | 未登入頁以 `--name` 建立另一玩家，導致代理已在線但原瀏覽器顯示離線 | VERIFIED | 目標回歸、全量測試與本機／公開瀏覽器流程通過 |
| R2 | 發布準備／P1 | 專案沒有獨立測試 CI，push 後無法取得可終止的全量測試 gate | VERIFIED | CI run `40005077748` 成功 |
| R3 | 外部狀態／P1 | 舊公開後端有測試代理在線且無法由不同玩家身分登出 | VERIFIED | 舊 run 取消；新 run `40005185610` 隔離驗證成功；煙霧代理停止後 `agent_online=false` |
| R4 | 驗收證據／P1 | 前端修正尚未經 GitHub Pages 與公開網址驗收 | VERIFIED | Pages runs `40005077106`、`40005390280` 成功；公開頁面與 API 通過 |

## 分層驗證

| 證據 | 層級／阻擋 | 範圍 | 結果 |
|---|---|---|---|
| E1 | L1／R1 | 新回歸測試與 JavaScript 語法 | PASS |
| E2 | L2／R1 | `.venv/bin/pytest -q`：242 passed、1 warning | PASS |
| E3 | L3／R1 | 本機 Chrome：未登入頁只顯示「先建立玩家身分」，按鈕聚焦名稱欄位 | PASS |
| E4 | L2／R2 | GitHub Actions CI `40005077748`：compile、242 tests、全 JS 語法、whitespace | PASS |
| E5 | L4／R3 | 後端 run `40005185610`：prepare／isolation success；新 Tunnel API healthy | PASS |
| E6 | L3-L4／R4 | Pages `40005077106`、`40005390280`；公開 Chrome 顯示新接入流程 | PASS |
| E7 | L4／R3 | 暫存代理 `0→1`，停止後認證 `/api/lobby/me` 為 `agent_online=false`；最近活動玩家數於 120 秒窗口後 `1→0` | PASS |

## 發布判定

R1–R4 均已驗證。後端 workflow 處於 `in_progress` 是服務在線的預期狀態；`Serve public lobby + tunnel` 已開始，新 `server.json` 與 `/api/health` 均已驗證。公開頁首的「目前在線」是最近 120 秒有活動的玩家數，不等同 `agent_online`；代理連線以帶身分的 `/api/lobby/me` 為準。GitHub Actions 的 Node 20／Ubuntu runner 遷移提醒不影響本次結果，列為非阻擋維護項。
