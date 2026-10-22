# 免費開源靶機來源（2026-10-22）

資安場的靶機全部可用「免費開源」映像，兩大來源：

## OWASP VWAD（Vulnerable Web Applications Directory）
目錄站 https://vwad.owasp.org/ ——合法安全測試/訓練用的已知脆弱應用登錄，分 offline / containerized / online。常用且有 Docker 映像：

| 應用 | 映像 | 說明 |
|---|---|---|
| OWASP Juice Shop | `bkimminich/juice-shop` | Node，涵蓋 OWASP Top 10 |
| DVWA | `vulnerables/web-dvwa` | PHP，難度可調 |
| OWASP WebGoat | `webgoat/webgoat` | Java |
| bWAPP | `raesene/bwapp` | PHP/MySQL，100+ web bugs |

## vulhub
https://github.com/vulhub/vulhub ——開源、預建的 dockerized 脆弱環境大全，用 docker-compose 重現大量 CVE（ActiveMQ 反序列化、Jolokia RCE、Spring 授權繞過、Django SQLi…）。社群工具 `vuln-runner` 可列舉/啟停且避免埠衝突。適合當 ctf 題庫的進階來源。

## 接法與安全邊界
- 這些映像加進 `targets/allowlist.yaml`（G1 白名單）即可被 `ctf` 模式拉起。
- **真正脆弱的 OSS 映像（kind=oss）只走 `local`（本機 Docker 隔離私有）**，不得用 freehost 公開上網——公開一台真能被打的箱子同時踩平台 ToS 與安全線（見 SAFETY.md）。
- **免費空間公開（freehost / Cloudflare tunnel）只給自架 benign 靶機**（arena-warmup，只吐假 flag）。
- vulhub 多為 docker-compose（多容器），目前 provisioner 支援單一映像；多容器 compose 靶機為後續工作。

## 來源
- OWASP VWAD：https://vwad.owasp.org/
- vulhub：https://github.com/vulhub/vulhub
