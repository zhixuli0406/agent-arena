# Truly free hosting decision record (2026-10-22, adopted 2026-10-23)

> **Current status:** Outprompt now uses a stable GitHub Pages lobby plus a long-running GitHub Actions job and rotating Cloudflare Quick Tunnel. The workflow verifies an isolated unprivileged server account, publishes the current URL through `server.json`, and restores sanitized state from the `data` branch. Render is no longer a pending launch decision. See [the operations runbook](../RUNBOOK.md) for the deployed architecture.

> The user asked for free hosting that is "truly, completely free (no credit card, never billed)".
> This document was checked and written by the main thread after the planned deep-research subagent was cut off by the session usage limit (429, resets at 12am Taipei time).
> Markers: ✅ = confirmed on the official page, ⚠️ = secondhand sources only or conflicting, ❓ = unconfirmed. A clause-by-clause ToS check is still to be done after the limit resets.

## One key judgment: targets don't belong on public free hosts

Deploying "deliberately vulnerable CTF targets" to any shared free PaaS has two problems:

1. **ToS risk**: most platforms forbid hosting "intentionally vulnerable / exploit / malware" content.
2. **Security risk**: a publicly reachable vulnerable container is a box that anyone can actually attack, which goes against the isolation principle in docs/SAFETY.md.

So the suggested split is:

- **Match server (a harmless web service)** → a free PaaS that needs no credit card.
- **CTF targets** → stay on **local Docker** by default (already implemented, completely free, and network isolated). Cloud targets are only considered when they can be "private, require-auth, and allowed by the ToS", and are marked advanced/deferred.

That way "free automatic server hosting" works without running into ToS or safety problems.

## Candidate comparison (for the match server)

| Platform | No credit card | Any Docker | API/CLI provisioning | Free tier limits | Primary source |
|---|---|---|---|---|---|
| **Render (free web service)** | ✅ confirmed on official pricing | ✅ (supports Docker) | ⚠️ has a REST API and render.yaml; free tier details not checked one by one | 512MB/0.1CPU, 750hr/month, sleeps after 15 min with no traffic, ~1 min cold start | render.com/pricing |
| **Back4App Containers** | ✅ officially confirmed | ✅ custom Docker | ❓ CLI/API unconfirmed | 0.25CPU/256MB; free containers reportedly limited to 60 min per deploy (⚠️ secondhand, not confirmed firsthand) | back4app.com/pricing/container-as-a-service |
| **Hugging Face Spaces (Docker)** | ✅ sign-up without a card | ✅ Docker SDK | ✅ `HfApi.create_repo(space_sdk=docker)` | ⚠️ forum reports say Docker Spaces may now need PRO (paid); egress only on 80/443/8080; sleeps when idle | discuss.huggingface.co (not confirmed firsthand) |
| **Fly.io** | ❌ new accounts need a card | ✅ | ✅ | No longer free | — |
| **Koyeb** | ⚠️ may need a card / defaults to paid | ✅ | ✅ | 1 service, scale-to-zero | koyeb.com/pricing (conflicting) |
| **Cloud Run** | ❌ needs a card | ✅ | ✅ | No charge within the free tier, but **not completely free** | (this project already has a cloudrun provider; listed as an option) |

## Original recommendation and adopted result

- **Adopted:** Cloudflare Quick Tunnel hosts the harmless match API. GitHub Actions keeps it running and commits the rotating URL to `server.json`; the stable Pages lobby follows that pointer. `infra/serve-free.sh` remains the one-command temporary option.
- **Not adopted:** Render and Back4App are no longer required for the public alpha. They remain alternatives if the runner-based service stops meeting capacity or availability needs.
- **CTF targets: keep them on local Docker** (completely free and isolated); cloud targets are deferred.

## Further work, not a launch blocker

- Read each platform's ToS firsthand for clauses on "vulnerable applications / security testing" (this decides whether cloud targets are possible at all).
- Re-evaluate persistent hosts only if the current GitHub Actions and tunnel model no longer meets availability or capacity needs.

## Sources
- Render pricing: https://render.com/pricing
- Back4App container pricing: https://www.back4app.com/pricing/container-as-a-service
- HF Spaces (discussion of Docker becoming paid): https://discuss.huggingface.co/t/docker-sdk-now-marked-as-paid-when-creating-a-new-space/177580
- Free tier roundup (secondhand, needs checking): https://snapdeploy.dev/state-of-free-hosting
