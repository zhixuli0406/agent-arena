# 真正完全免費架站方案（2026-10-22）

> 使用者要求免費架站要「真正完全免費（免信用卡、不會計費）」。
> 本文由主執行緒查證補寫——原規劃的深度研究子代理被 session 用量上限（429，台北 12am 重置）中斷。
> 標示：✅=官方頁面確認、⚠️=僅二手來源/有衝突、❓=未確認。深度 ToS 逐條查證待限制重置後補。

## 一個關鍵判斷：靶機不該上公開免費 host

把「故意留洞的 CTF 靶機」部署到任何共享免費 PaaS 有兩個問題：

1. **ToS 風險**：多數平台禁止 host「intentionally vulnerable / exploit / malware」類內容。
2. **安全風險**：公開可達的脆弱容器＝真的能被任何人打的箱子，違背 docs/SAFETY.md 的隔離精神。

所以建議的架構分工：

- **對戰伺服器（無害 web 服務）** → 上「免信用卡」免費 PaaS。
- **CTF 靶機** → 預設留在**本機 Docker**（已實作、本就完全免費且網路隔離）。雲端靶機只在「私有 require-auth＋ToS 允許」的前提下才考慮，列為進階/延後。

這樣「免費自動架設伺服器」成立，又不踩 ToS/安全雷。

## 候選比較（對戰伺服器用途）

| 平台 | 免信用卡 | 任意 Docker | API/CLI 佈建 | 免費限制 | 一手來源 |
|---|---|---|---|---|---|
| **Render（free web service）** | ✅ 官方 pricing 確認 | ✅（支援 Docker） | ⚠️ 有 REST API 與 render.yaml，免費層細節未逐一確認 | 512MB/0.1CPU、750hr/月、15 分無流量休眠、~1 分冷啟 | render.com/pricing |
| **Back4App Containers** | ✅ 官方確認 | ✅ 自訂 Docker | ❓ CLI/API 未確認 | 0.25CPU/256MB；免費容器疑每次僅 60 分/deploy（⚠️ 二手，未一手確認） | back4app.com/pricing/container-as-a-service |
| **Hugging Face Spaces（Docker）** | ✅ 註冊免卡 | ✅ Docker SDK | ✅ `HfApi.create_repo(space_sdk=docker)` | ⚠️ 論壇報 Docker Space 可能已需 PRO（付費）；出網僅 80/443/8080；閒置休眠 | discuss.huggingface.co（未一手確認） |
| **Fly.io** | ❌ 新戶需卡 | ✅ | ✅ | 已非免費 | — |
| **Koyeb** | ⚠️ 疑需卡/預設付費 | ✅ | ✅ | 1 service、scale-to-zero | koyeb.com/pricing（衝突） |
| **Cloud Run** | ❌ 需綁卡 | ✅ | ✅ | 免費額度內不計費但**非完全免費** | （本專案已有 cloudrun provider，列選項） |

## 建議（待你拍板）

- **零憑證即驗證的選擇（已實作＋實測）：Cloudflare quick tunnel**——`infra/serve-free.sh` 直接把對戰伺服器對外公開，零帳號、零信用卡、零設定，已實測公開 `*.trycloudflare.com` 網址可達並服務 API 與像素遊戲。適合「開賽即起、散場即拆」的臨時公開。限制：網址每次隨機、非持久。
- **持久化主選：Render 免費 web service**（免卡一手確認、支援 Docker、有 API、750hr/月，需你的免費帳號 API 金鑰才能自動佈建）。備援：Back4App。
- **CTF 靶機：維持本機 Docker**（完全免費＋隔離）；雲端靶機延後。
- 休眠/冷啟對「開賽才拉起」可接受；若要常駐可用外部 ping 保活（注意別違反 ToS 的 keep-alive 規定）。

## 待辦（限制重置後補）
- 一手讀 Render API / render.yaml 免費層佈建細節，確認能用 API 自動 create/destroy。
- 一手讀各平台 ToS 對「脆弱應用/安全測試」的條款（決定雲端靶機是否可能）。
- HF Docker Space 是否仍免費、Koyeb 是否已需卡，以官方頁/論壇一手確認。
- 選定後實作對應 provider（需你提供該平台的 API 金鑰／帳號，類似 Grok 金鑰的關卡）。

## 來源
- Render 定價：https://render.com/pricing
- Back4App 容器定價：https://www.back4app.com/pricing/container-as-a-service
- HF Spaces（Docker 轉付費討論）：https://discuss.huggingface.co/t/docker-sdk-now-marked-as-paid-when-creating-a-new-space/177580
- 免費層彙整（二手，需查證）：https://snapdeploy.dev/state-of-free-hosting
