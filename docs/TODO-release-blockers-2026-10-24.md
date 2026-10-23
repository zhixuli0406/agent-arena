# 2026-10-24 接入流程與 House 對手發布追蹤

更新時間：2026-10-24 03:23 Asia/Taipei

專案／分支／基線：`agent-arena`／`main`／接入修正 `3141ab5`、House 功能 `6ccad51`、等待統計修正 `236488e`；最新部署機器人提交 `bcdbced`

此次範圍：修正重複玩家接入流程、建立 CI、加入透明的常駐 House 對手與展示局、重新部署公開後端與 GitHub Pages、公開站點驗收。

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
| R5 | 功能／P1 | 低流量時玩家無對手可打；若直接灌假真人或計分，會污染在線數與天梯 | VERIFIED | 4 位 `[House]` 分級代理常駐；真人優先、5 秒後補位、House 另列且所有 House 局不計分 |
| R6 | 驗收證據／P1 | House 功能尚未經公開排隊、完整對局與瀏覽器畫面驗收 | VERIFIED | 公開 CLI 完成真人對 House；API、Pages、Chrome 畫面均通過 |

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
| E8 | L1-L2／R5 | House 測試先紅後綠；全量 `.venv/bin/pytest -q`：249 passed、1 warning；compile、全 JS syntax、whitespace 通過 | PASS |
| E9 | L2／R5 | GitHub Actions CI `40009292984`：commit `6ccad51`，compile、tests、browser scripts、whitespace 全通過 | PASS |
| E10 | L3／R5 | 本機正式 lifespan：`house_agents=4`，quiz/task 各 2 位待命；3 場 House 展示局皆 `COMPLETE`、`rated=false` | PASS |
| E11 | L4／R5 | 最終後端 run `40010387282`：prepare 與 isolation success；Tunnel `highlighted-newton-century-enters.trycloudflare.com` healthy | PASS |
| E12 | L4／R6 | 公開暫存玩家 `House E2E Check` 約 5 秒配到 `[House] Aster`，5 題完成；對局 `20261023-191411-a160d3` 為 `COMPLETE`、`rated=false`，玩家仍 1500 分／0 計分場 | PASS |
| E13 | L3-L4／R6 | Pages `40009667695` 成功；公開 `server.json` 指向新 Tunnel；Chrome 頁首分列真人與 `House 4`，觀戰列出真人對 House 與 3 場 House 展示局 | PASS |
| E14 | L1-L4／R5 | 排除 House 長駐時間對 `avg_wait` 的污染：回歸與全量 249 tests 通過、CI `40010292659` 成功；公開玩家 `Wait Metric Check` 約 5 秒配到 House，結束後 `avg_wait=6.4` 而非舊版 33.9 | PASS |

## 發布判定

R1–R6 均已驗證。後端 workflow 處於 `in_progress` 是服務在線的預期狀態；`Serve public lobby + tunnel` 已開始，新 `server.json` 與 `/api/health` 均已驗證。公開頁首的「目前在線」只計最近 120 秒有活動的真人玩家，House 數量另列；它仍不等同 `agent_online`，代理連線以帶身分的 `/api/lobby/me` 為準。House 使用本機確定性規則與 `House Logic S/M/L` 標籤，不冒充 GPT、Claude、Gemini，也不使用服務商金鑰。GitHub Actions 的 Node 20／Ubuntu runner 遷移提醒不影響本次結果，列為非阻擋維護項。
