# 2026-10-24 接入流程發布追蹤

更新時間：2026-10-24 Asia/Taipei

專案／分支／基線：`agent-arena`／`main`／`718822a` 加本次工作樹

此次範圍：修正重複玩家接入流程、建立 CI、重新部署公開後端與 GitHub Pages、公開站點驗收。

授權：使用者明確要求「CI、線上部署與公開站點驗收，另外重新部署後端」。

工程進度：`IN_PROGRESS`

發布就緒：`NO-GO`

發布動作：待提交、推送與部署

## 阻擋清單

| ID | 類型／嚴重度 | 問題與阻擋理由 | 狀態 | 關單條件 |
|---|---|---|---|---|
| R1 | 程式缺陷／P1 | 未登入頁以 `--name` 建立另一玩家，導致代理已在線但原瀏覽器顯示離線 | VERIFIED | 目標回歸、全量測試與本機瀏覽器流程通過 |
| R2 | 發布準備／P1 | 專案沒有獨立測試 CI，push 後無法取得可終止的全量測試 gate | FIXED_PENDING_VERIFY | 新 CI workflow 在發布提交上完成且成功 |
| R3 | 外部狀態／P1 | 舊公開後端有測試代理在線且無法由不同玩家身分登出 | IN_PROGRESS | 新後端取代舊 Tunnel，公開 stats 回到無卡住狀態 |
| R4 | 驗收證據／P1 | 前端修正尚未經 GitHub Pages 與公開網址驗收 | IN_PROGRESS | Pages 指向發布提交，公開頁顯示新流程且 API 健康 |

## 分層驗證

| 證據 | 層級／阻擋 | 範圍 | 結果 |
|---|---|---|---|
| E1 | L1／R1 | 新回歸測試與 JavaScript 語法 | PASS |
| E2 | L2／R1 | `.venv/bin/pytest -q`：242 passed、1 warning | PASS |
| E3 | L3／R1 | 本機 Chrome：未登入頁只顯示「先建立玩家身分」，按鈕聚焦名稱欄位 | PASS |
| E4 | L2／R2 | GitHub Actions CI | NOT_RUN |
| E5 | L4／R3 | 新公開後端、隔離檢查、Tunnel 與狀態清理 | NOT_RUN |
| E6 | L3-L4／R4 | GitHub Pages、公開頁面與公開 API | NOT_RUN |

## 發布判定

R2、R3、R4 尚未解除前維持 `NO-GO`。長時間運行的後端 workflow 處於 `in_progress` 是預期狀態；必須逐項確認其安裝、狀態恢復、隔離檢查及新 `server.json` 已成功。
