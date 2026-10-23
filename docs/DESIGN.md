# Design notes (explanation)

This document explains why Outprompt is built the way it is: what each component is responsible for, where the boundaries sit, and which trade-offs were made. The dry API-level description is reference material and will go in `docs/reference/` later. This page covers only the "why" and the "what it looks like".

## Goals and non-goals

Goals:

1. **Vendor neutral**. Adding a new agent means writing one adapter, with zero changes to the rules engine. This is a hard rule: no single model may be hard-coded into the engine or the modes.
2. **One world per match**. Each match's servers and targets are provisioned when it starts and torn down when it ends. They are isolated from each other and reproducible.
3. **Two comparable axes**. Scoring must answer two separate questions: which model is stronger, and which person tunes agents better.
4. **Verifiable live**. The core flow can run a full match end to end on a local machine without any keys.

Non-goals (at least for v1): humans playing against AI in real time, paid leaderboards, exposing targets to the public internet for outsiders to attack, training models.

## Four components and their boundaries

```
                 ┌──────────────────────────────────────────┐
                 │               Rules engine                 │
                 │  rounds · collect actions · judge · log ·  │
                 │  circuit breakers                          │
                 └───────┬───────────────┬──────────────┬─────┘
                         │               │              │
                 ┌───────▼──────┐ ┌──────▼──────┐ ┌─────▼──────┐
                 │  Mode         │ │ Adapter     │ │ Provisioner│
                 │ task·actions· │ │ act(obs)→act│ │            │
                 │ scoring       │ │             │ │            │
                 └──────────────┘ └─────────────┘ └────────────┘
```

Each component does one kind of cognitive work. Components talk through explicit data structures (`arena/types.py`), never through implicit shared state.

### Rules engine (`arena/engine.py`)

The main loop of one match. The flow: ask the Mode for the initial observation → ask each Adapter for an action in turn → hand the action to the Mode to validate and settle → update the transcript → check whether the Mode says the match is over or an engine circuit breaker has tripped. The engine knows nothing about any particular game or any particular model. It only knows about rounds and logging.

Circuit breakers (the runaway protection the playbook requires): every match has three limits, `max_rounds`, `max_wall_seconds`, and a per-step `timeout_seconds` for each adapter.

Failures have to be attributed to the right party. If a single agent times out, errors or disconnects, only that agent forfeits that round (0 points); the match still settles and ELO still counts. Three failed rounds in a row and the agent is withdrawn, and the engine stops waiting for it. A match ends as DEGRADED/PARTIAL with no ELO update only when `max_rounds` or `max_wall_seconds` trips, or on infrastructure failure (`AdapterUnavailable`: the CLI can't be found, a key isn't set, or an endpoint the server picked is down; a mode crash; every agent failing at once and staying failed to the end). Early versions treated any timeout as an infrastructure problem and voided the whole match, so a losing player could disconnect on purpose to erase the loss. The security review caught this.

### Agent adapters (`arena/adapters/`)

The shared contract (`base.py`):

```python
class Adapter(Protocol):
    async def act(self, obs: Observation) -> Action: ...
```

`Observation` carries the task description, a description of the legal actions, and the history. `Action` is what the agent does this step (submit an answer, issue a command, speak). **The thing a human operator tunes is the system/strategy prompt fed to the adapter.** That is exactly what the prompt axis measures.

Concrete adapters:

- `mock`: scripted or random, for offline tests and control groups.
- `openai_compat`: calls an OpenAI-compatible `/chat/completions`. With `base_url` + key + model name, one adapter covers **Grok (api.x.ai), OpenAI, and any compatible endpoint**. This is deliberate reuse: three vendors, one piece of code.
- `claude_cli`: calls the local `claude -p` headless. It needs no separate key; it uses the local login, so it can act as a real opponent (for live verification).
- Later: `gemini` (native or through a compatibility layer), and cross-vendor CLI bridging through baton.

An adapter returns more than text. It also returns `usage` (tokens, time, estimated cost), which scoring and the circuit breakers both need.

### Game modes (`arena/modes/`)

The contract (`base.py`): `setup()` produces the initial observation, `step(action)` validates and advances, `score()` gives the result, `is_done()` decides when it ends. A mode defines three things: what the task looks like, which actions are legal, and how you win.

- `quiz`: a set of timed questions with automatically gradable answers (exact match, numeric tolerance, or unit tests). The simplest mode, and the best fit for a vertical slice and regression tests.
- `ctf`: asks the Provisioner for an isolated target. The agent interacts through `run_command`-style tools and submits a flag; first blood wins. It follows the NYU CTF Bench pattern of Docker targets plus `check_flag`.
- `swe`, `debate`: see the roadmap. `debate` judging uses maker-checker separation: a model that plays never judges itself, the judging panel is made up of other models, and judges grade what a model did, ignoring what it says it meant to do.

### Provisioners (`arena/provision/`)

The contract: `provision(spec) -> Endpoint`, `teardown(handle)`. This fully separates "where and with what resources are brought up" from the gameplay.

- `local`: local Docker, for development and CI. Fastest and safest.
- `cloudrun`: deploys to a GCP project given by environment variables (`ARENA_GCP_PROJECT` / `ARENA_GCP_REGION`), **always with a service account** (key path in `ARENA_GCP_SA_KEY`, optional `ARENA_GCP_SA_EMAIL`), and never asks the user for an interactive login. `IAM_PERMISSION_DENIED` is treated as a boundary signal: report it, don't work around it.
- Fallbacks: Koyeb (1 free web service, takes Docker images), Render (the free tier sleeps).

Every provisioned resource gets a TTL and a match ID label. Teardown at match end and the scheduled sweep both rely on them.

## Two-axis scoring

The result of one match updates two independent ELO ratings at the same time:

- **Model axis**: key = model ID (`claude-opus-4-8`, `grok-4.20`, …). When the same prompt is run on different models, the difference is attributed to the model.
- **Prompt axis**: key = prompt author ID. When the same model is run with different people's prompts, the difference is attributed to the operator.

### Speed bonus

A correct answer is worth 1 point, plus `0.5 × (1 − elapsed ÷ limit)`. The reasoning: a player who turns the model and thinking effort all the way up will almost always be right, so scoring on accuracy alone penalizes agents that are both fast and accurate. Speed is also a proxy for cost. Token usage is self-reported and the server can't verify it, but elapsed time is measured by the server's own clock (from sending the question to receiving the answer), so a player can only make it slower, never fake it faster. Only correct answers count, and a wrong answer gets no speed bonus, so guessing doesn't pay. Only the first answer per round is accepted, so guessing first and correcting later doesn't work either.

The trade-off: you can have "accuracy comes first, absolutely" or "speed can make up for a miss", and you have to pick one. The 0.5 cap means a single correct answer always beats a wrong one, but summed over a match, speed can make up for one miss (4 right at 5 s each ≈ 5.92 points beats 5 right averaging 80 s ≈ 5.83). Putting accuracy first absolutely would mean keeping the total speed bonus for a match under 1 point, which leaves speed as nothing more than a tie-breaker. The cap can be changed with the mode setting `speed_bonus` (0 turns it off).

To keep attribution clean, the scheduler tries to arrange "controlled" matches (fix the model and compare prompts, or fix the prompt and compare models), so that both axes don't change at once and become impossible to attribute. This is experiment design as much as scoring.

## Technology choices and reasons

- **Python 3.12 + asyncio**: agent matches are mostly I/O waits (waiting on each vendor's API), which suits async. The CTF and agent ecosystem (Cybench, NYU CTF, docker SDK) is also in Python.
- **FastAPI** (server phase): friendly to Cloud Run, and easy to add spectator SSE/WebSocket.
- **Docker**: the isolation unit for targets and the `local` provider.
- No heavyweight agent framework (AgentVerse is no longer maintained, ChatArena leans toward conversation simulation). We borrow their ideas and build a light engine of our own, which keeps the project vendor neutral and under control.

## Data flow and logging

Each match writes one private `Transcript` (JSON Lines), one line per event (observation, action, settlement, circuit breaker, provision/teardown). The public spectator stream reads it, but CTF matches publish only an allowlisted projection: no observations, submitted flag text, request paths, target responses, or error text. The mode scores actions before the engine writes events. Failure events remain explicit in the transcript.

## Online lobby and player connections (public version)

### Why players bring their own agents

The earliest version had the server play on behalf of each vendor (`claude_cli`, `codex_cli`, `grok_cli` ran on the server's machine). In public this has two fundamental problems: every match spends the server owner's quota and keys, and only the vendors the server can afford to install get to play.

Once players bring their own agents, the server does three things: matchmaking, questions, grading. The player's agent runs on the player's own computer and uses a connection token to receive questions and send answers. The server holds zero keys, and anything that can read and write text can take part (vendor APIs, local models, products with no public API relayed by the player). It also turns "humans writing prompts" into the actual contest between players. Public servers therefore allow only the `remote` and `mock` adapters; `ARENA_ALLOW_HOST_ADAPTERS=1` is only for private self-hosted servers.

### Agents are required; the website only operates

Early lobby builds let a human answer in the browser and had a separate pixel-art "theater" page for replays. Both went away. A human typing answers measures nothing the game is about, and a browser seat made it easy to queue with no agent at all and leave the opponent waiting on a timeout. Now every seat is played by the player's own agent, and the website is a remote control: it queues, forms parties, accepts, spectates.

That is enforced on the server, not in the page. Each agent keeps one standby stream open (`GET /api/lobby/agent/stream`). The stream is the presence signal (queueing, accepting and readying up are refused while it's closed, with a 20 s grace for reconnects), and it is the only channel that ever carries a seat's connection token. Ticket and room views stopped returning tokens, so the browser can't take a seat even if someone edits the page.

To get the agent onto the same player as the browser without copying a secret around, the browser asks for a one-time link code (8 characters, 10 minutes). Redeeming it mints a **separate** credential for that player, so the browser and the agent never hold each other's secret, and either can be revoked. "Sign out all agents and other browsers" keeps only the caller's credential and immediately takes the others offline (no grace period). A client whose saved credential stops working exits with an explanation instead of quietly registering a new player; otherwise the website would keep queueing one player while the agent played as another.

Two things came out of the security review of this flow. The browser keeps credentials per server, so a link that points the page at another server (`?api=`) never sends it your lobby account. The clients only treat a server as "the public lobby" (shared saved identity) when `server.json` actually points to it, since anyone can open a `*.trycloudflare.com` tunnel. Link codes from the server are checked against `[A-Z0-9]` before they go into copy-paste shell commands or printed URLs.

### Connecting agents over MCP

The command-line client needs the agent to be a command that reads stdin and writes stdout. That restarts the agent for every question, and the agent can't see that it is in a match. The MCP bridge (`clients/arena_mcp.py`) turns this around: the agent itself calls `arena_queue`, `arena_next_question` and `arena_answer`. Any agent that supports MCP can play, with no tie to one vendor, and the human's prompting skill acts directly on the agent.

The bridge runs on the player's computer (stdio) instead of being a remote MCP endpoint on the server, for three reasons. The public server's URL rotates every 5 hours, so a remote configuration would keep breaking; the server doesn't need another long-lived connection entry point; and the player's identity secret stays on their own machine. The bridge looks up the live server from the public lobby's `server.json` every time.

In testing, Claude Code 2.1.300 uses the 2026-07-28 version: it sends `server/discover` first and never sends `initialize`. That version requires the results of discover and of every list call to include `ttlMs` and `cacheScope`. Without those two fields, the client keeps re-fetching the tool list and ends up loading no tools at all. Older clients still use `initialize`, and the bridge supports both.

### Question delivery: broadcast state, no queue

A connection slot stores only "current question, version number, finished or not". Every SSE connection reads the same state and sends when the version changes. The first version delivered through a queue. When the browser's EventSource reconnected on its own, a leftover old connection would take the question or the end signal, and the new connection would wait forever. This was caught in headless browser testing. With broadcast, reconnects, two windows open at once, and leftover connections no longer steal messages, and a reconnect gets the current question right away. Answers carry the round number, only the current round is accepted, and clients deduplicate by round.

### Matchmaking: the way mainstream online games do it

| Mechanism | Parameters | Reason |
|---|---|---|
| Rating window | starts at ±100, +20 per second, up to ±800 | Nobody waits forever when few people are online; matches are close when many are |
| First come first served, smaller gaps first | — | Whoever has waited longest gets a match first |
| Ready check | everyone accepts within 15 s | Avoids starting a match with someone absent |
| Decline/timeout cooldown | 30 s | Discourages dodging to pick opponents |
| Others go back first | keep their original queue time | Someone else dodging shouldn't penalize those who accepted |
| Custom rooms | host starts, everyone ready, host leaving hands over automatically | Basic etiquette for games with friends |
| Party queueing (2v2, 3v3) | up to 3 per party, ratings within 300, team formats only | As in League of Legends: friends play rated games together without becoming opponents |

### Parties and team queues

At first, to stop people from playing their own second account, matchmaking simply refused to let two tickets from the same IP meet. The cost was that family and friends behind one home network could never get a rated game. This was later changed to follow League of Legends: friends form a party first, the whole party is one queue ticket, and it is always placed on the same side. People on the same network can still be teammates; they just can never be opponents, so the farming route stays closed.

Team matchmaking (`server/teammatch.py`) treats each ticket (1 for solo, 2 to 3 for a party) as an indivisible unit. From the 10 candidates closest in rating, it finds a combination that forms two teams of n each, with the smallest gap between the two teams' average ratings and no shared network across the two sides. Parties can only queue team formats, because in free-for-all teammates would take points from each other.

Rating changed too. If team games kept the free-for-all rule of comparing everyone pairwise, teammates would take points from each other, and a player who carried the team would drag teammates down. Now each player is compared once against the other team's average rating, and the winner is decided by team total score. When two teammates on the same side report the same agent name, the agent ladder counts that match only once (averaged). Red and blue teams in the lobby are formed at random, so there is no team-axis ladder (`MatchConfig.team_ladder=False`); that is only needed for fixed-name team competitions.

The matchmaking logic (`server/lobby.py`) is pure logic with an injected clock. A server background loop calls `tick()` once a second, so it can be tested deterministically with a fake clock.

### Lobby UI: a game client in the browser

The lobby was rebuilt after a research pass over League of Legends, VALORANT, Overwatch 2, Fortnite, Rocket League and chess.com/lichess. The decisions that came out of it:

- The home screen is Play: game-type tiles, format tiles (free-for-all 2–4, 2v2, 3v3) and one large "Find match" button. Ranked and unranked are labelled everywhere.
- A queue bar stays docked at the bottom of every screen while you search: elapsed time, players in queue, rating window and Cancel. We show the recent average wait only, never an "estimate"; inaccurate estimates are one of the most criticised lobby patterns (Overwatch 2).
- The ready check is the only modal: a countdown ring with the seconds as text, accepted-count pips, a short sound and a flashing tab title when the tab is in the background (missed match pops are another common complaint).
- After a decline or miss, the Find match button itself shows "Cooldown 0:23".
- The party rail on the right shows member slots, the leader's crown, empty "+ Invite" slots that copy an invite link (`?party=CODE` pre-fills the join box; joining is still the player's click).
- Teams are never told apart by colour alone: every side carries a label and a shape (▲ red, ■ blue), my side is listed first, and a colour-blind palette (orange/blue) is one switch away.
- In a match: a red-vs-blue score bar, a per-question countdown (number and bar), and a feed that spells out the speed bonus ("+1 +0.48 speed"). After the match: VICTORY / DEFEAT / DRAW from your side, the rating change counting up, Play again as the main button.
- Tiers (Bronze to Master) are display only, derived from the ELO rating; the first 5 ranked matches show as placement with a "?" after the rating, the way lichess marks provisional ratings.
- Everything else is a toast, one at a time.

The backdrop and particles are hand-written WebGL (`web/js/fx.js`), because the page's CSP only allows our own scripts: an arena floor grid running to the horizon that speeds up while searching, sends a shockwave when a match is found, takes the team colours in a team match and lights up on a win. It renders at 60% resolution, pauses in background tabs, draws a single still frame under `prefers-reduced-motion`, and falls back to a CSS background when WebGL is missing or switched off.

### Persistence and known limits

- State lives in memory in a single process. Player ratings (secrets stored only as hashes) and ladders are written to JSON periodically. The free cloud version restarts every 5 hours: on start it restores from the repo's `data` branch, and it backs up there every 10 minutes. Ranks carry over, but any match in progress at restart is interrupted, and up to 10 minutes of rating changes can be lost.
- The free tunnel's URL changes on every restart. The lobby page finds the live server through `server.json`; clients should use the URL shown on the lobby page.
- A disconnect timeout counts as a forfeit for that player and the match is still rated. Players with unstable connections lose points because of this. That is a deliberate trade-off (otherwise disconnecting on purpose would void a losing match).
- Only quick match games are rated. Custom rooms aren't, and the same group of players gets only its first 3 matches per day rated. Agent ladder names are self-reported and the server can't verify them.

### Languages

Server messages, web pages, the player client and questions all support Traditional Chinese (the original), Simplified Chinese, English and Japanese. Questions are generated at random for each match by the generators in `server/question_bank.py`. Every question's text and attached documents exist in all four languages. Answers are either language independent (numbers, codes) or list the accepted forms in each language (weekdays, sentiment labels). The Mode puts all language versions in `Observation.state["i18n"]`, and the connection layer picks one by the player's `?lang=`, so players in one match can each use their own language and still compete on the same questions. Errors are raised as message keys (`I18nError`), and the API layer translates them according to `Accept-Language`.

### Protection on the public server

Anyone can play on the public server, so every entry point has limits (`server/guard.py`): per-IP rate limiting, separate quotas for entering, creating rooms and queueing, body size, SSE connection counts, and site-wide caps on queue entries and demo matches. A background loop reclaims idle guests, rooms, expired matches and transcripts. Behind a Cloudflare tunnel, every TCP source is localhost, so the real source comes from `CF-Connecting-IP`. Custom matches are disabled on the public server. Private servers (where host adapters play using the owner's local logins) always require an admin token, accept only local Host headers to block DNS rebinding, and allow CORS only for local pages.
