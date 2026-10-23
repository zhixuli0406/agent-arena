# Free open-source CTF target sources (2026-10-22)

Every target for the security arena can be a free, open-source image. There are two main sources:

## OWASP VWAD (Vulnerable Web Applications Directory)
Directory site https://vwad.owasp.org/ is a registry of known-vulnerable applications meant for legitimate security testing and training, split into offline / containerized / online. Common ones with Docker images:

| App | Image | Notes |
|---|---|---|
| OWASP Juice Shop | `bkimminich/juice-shop` | Node, covers the OWASP Top 10 |
| DVWA | `vulnerables/web-dvwa` | PHP, adjustable difficulty |
| OWASP WebGoat | `webgoat/webgoat` | Java |
| bWAPP | `raesene/bwapp` | PHP/MySQL, 100+ web bugs |

## vulhub
https://github.com/vulhub/vulhub is a large open-source collection of prebuilt, dockerized vulnerable environments that use docker-compose to reproduce many CVEs (ActiveMQ deserialization, Jolokia RCE, Spring authorization bypass, Django SQLi, …). The community tool `vuln-runner` can list, start and stop them while avoiding port conflicts. A good advanced source for the ctf question pool.

## How to wire them in, and the safety boundary
- Adding these images to `targets/allowlist.yaml` (the G1 allowlist) lets the `ctf` mode start them.
- **Truly vulnerable OSS images (kind=oss) only go through `local` (private, isolated local Docker)**. They must not be put online through freehost: publishing a box that can actually be attacked breaks both the platform ToS and our safety line (see SAFETY.md).
- **Public free hosting (freehost / Cloudflare tunnel) is only for self-hosted benign targets** (arena-warmup, which only returns a fake flag).
- vulhub is mostly docker-compose (multiple containers), and the provisioner currently supports a single image. Multi-container compose targets are future work.

## Sources
- OWASP VWAD: https://vwad.owasp.org/
- vulhub: https://github.com/vulhub/vulhub
