# Roadmap

Every milestone has a definition of done (DoD). Per the playbook, finished code is not done: it must build, pass tests, be verified live, and have its docs updated in the same commit.

## M0: core engine vertical slice ✅ (verified 2026-10-22)

Run one quiz match end to end on the local machine.

- [x] Project skeleton, README (README-driven development), design/safety/roadmap docs
- [x] `types`: Observation / Action / MatchConfig / AgentSpec / Event / MatchResult
- [x] Adapter: `base` + `mock`
- [x] Mode: `base` + `quiz` (grading by exact/choice/contains/numeric; the substring false positive the reviewers flagged is fixed)
- [x] Engine: main loop + three circuit breakers + JSONL logging (try/finally, transcript 0600)
- [x] Two-axis ELO scoring (pre-match snapshot, order-invariant; updates skipped when status isn't COMPLETE)
- [x] CLI `arena.run` + example configs
- [x] Tests (quiz grading, circuit breakers, ELO order invariance)
- **DoD**: ✅ `python -m arena.run --config examples/quiz_mock.yaml` produces a full match report; pytest green; run for real on the local machine.

## M1: real adapters (partly done)

- [x] `claude_cli` (local `claude -p` headless, prompt over stdin, process group cleanup, marked host_actor) ✅ verified live
- [x] `codex_cli` (local `codex exec`, a real OpenAI agent using its own login) ✅ **a real cross-vendor Claude vs OpenAI match has been run and verified**
- [x] `grok_cli` (local `grok --prompt-file ... --output-format plain`, the real xAI Grok using its own login) ✅ **a real three-way Claude vs OpenAI vs Grok match has been run and verified**
- [x] All three native CLIs run with zero keys (Claude/OpenAI/Grok); `openai_compat` is kept for remote compatible endpoints (needs a key)
- [x] `openai_compat` (covers Grok / OpenAI / compatible endpoints, base_url allowlist validation): implemented, **not verified live for lack of a key**
- [x] usage (tokens/time) collected into the match report
- **DoD**: claude vs mock ✅ run for real; Grok vs Claude waits for a key. Without a key it degrades to mock and says so ✅.

## M2: security arena and local provisioner ✅ (verified 2026-10-22)

- [x] Provisioner `base` + `local` (Docker, runner sidecar isolation model; tested that the host is closed off and the target has no egress)
- [x] `targets/allowlist.yaml` + the bundled `arena-warmup` target (Juice Shop/DVWA/WebGoat are allowlisted, not yet wired in)
- [x] `ctf` mode: HTTP tools (strict GET/POST/SUBMIT grammar), constant-time check_flag, first blood, request budget
- [x] Safety gates G1–G5 in place + tests (allowlist refusal, C1 host agent refusal, isolation, DATA fence)
- **DoD**: ✅ local Docker starts the target, a mock attacker submits the flag through the engine tools, and teardown happens automatically at match end; the CLI match report and pytest both pass.
- Still to do: wire in OSS targets such as Juice Shop (bigger images, slower start), and an attacker-container shell mode (more realistic than HTTP, but harder to isolate).

## M3: cloud auto-provisioning (target deployment ✅ verified 2026-10-22)

> On 2026-10-22 the user asked for free hosting to be "truly, completely free (no credit card, no billing)". Cloud Run needs a card on file and bills overages, so it is **not completely free**, and the cloudrun work below is only one option. The research on choosing a "truly free host" was interrupted by the session usage limit (resets at 12am Taipei time) and is waiting to be rerun.
> Also note: the cloudrun provider was written by codex during the handover while the usage limit was hit. codex says it tested the deployment successfully, but it **has not yet been reviewed line by line locally**.

- [x] `cloudrun` provider: deploys the target as a Cloud Run service with an SA, calls it with an identity token, deletes it at match end; stops and reports on IAM_PERMISSION_DENIED (G6)
- [x] Live verification: `arena.run --config examples/ctf_warmup_cloudrun.yaml` really deploys → plays → deletes, 37.7s, nothing left behind
- [x] **Truly free public server**: `infra/serve-free.sh` uses a Cloudflare quick tunnel (no account, no credit card) to put the match server online with one command ✅ tested: the public `*.trycloudflare.com` URL is reachable, starts matches, and serves the pixel game
- [ ] Provider for a persistent free host (Render, needs your free account API key); or deploy to Cloud Run (not a free option)
- [ ] OSS targets (Juice Shop etc.) on Cloud Run need VPC egress control first (cloudrun currently only accepts self-hosted self targets)
- **DoD**: ✅ one command starts a target within the Cloud Run free tier, plays a match, tears it down automatically, and logs in non-interactively with an SA.

## M4: match server and pixel game front end

- [x] FastAPI match server `server/app.py`: start matches, live SSE transcript streaming, results, serves the front end ✅ run and verified locally
- [~] Pixel game front end `web/arena.html`: plays a match out as an 8-bit retro battle (fork in progress; affected by rate limiting, status to be confirmed)
- [ ] Prompt submission UI (operators upload a strategy prompt)
- **DoD**: watch a match live in the browser, with pixel animation and both rating axes; no layout breakage.

## M6: matchmaking, rooms, multiplayer and teams (added by the user 2026-10-22)

- [x] `AgentSpec.team` field; the engine's participants were already a list → N-player matches are supported
- [x] Random matchmaking `/api/queue`: a match starts automatically once enough players for the same mode have joined ✅ tested locally
- [x] Private rooms `/api/rooms` (room code, join, host starts) ✅ tested locally
- [x] Many-vs-many and teams: `team` grouping, aggregated team scoring, team ELO (team axis, order-invariant) ✅ 2v2 tested locally
- [ ] Wire rooms/matchmaking/teams into the pixel game front end (currently API only; the front-end UI is not wired up yet)
- **DoD**: ✅ the API can create rooms to invite friends, matchmake at random, and run 2v2 teams with correct team scoring; ⏳ the browser UI is not wired up yet.

## M5: wrap-up

- [ ] `swe` / `debate` modes
- [ ] License decision (owner decides)
- [ ] Release decision (owner decides)
- **DoD**: the owner tests it and signs off.

## Pending decisions (owner gates)

- License (MIT / Apache-2.0 / proprietary)
- Whether to release publicly, and under what name
- Priority order of match types for v1
