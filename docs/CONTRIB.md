# Contributing

Outprompt is a multiplayer game and a security-sensitive agent execution system. Keep gameplay, protocol, documentation and safety behavior in sync.

## Setup

Requirements:

- Python 3.12+
- `cloudflared` only when opening a temporary public tunnel
- Docker only for private/local container targets
- Node.js only for JavaScript syntax checks

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[server,dev]"
cp .env.example .env
set -a; source .env; set +a  # optional; the app does not auto-load .env
```

Do not commit credentials, match transcripts, `runs/`, ratings or local identity files.

## Project map

| Path | Purpose |
|---|---|
| `arena/` | Engine, adapters, modes, scoring, security and provisioners |
| `server/` | FastAPI app, lobby, matchmaking, parties and public policy |
| `clients/` | Standard-library CLI and MCP clients |
| `web/` | Static multilingual lobby, spectating and WebGL effects |
| `targets/` | Allowlisted security targets |
| `infra/` | Local hosting, public tunnel, state backup and deployment helpers |
| `tests/` | Unit, integration, protocol, security and static UI tests |

## Common commands

| Command | Purpose |
|---|---|
| `pytest -q` | Run the complete Python test suite |
| `node --check web/js/match.js` | Syntax-check a changed browser script; repeat for other changed JS files |
| `python -m compileall -q arena clients server` | Compile-check Python packages |
| `uvicorn server.app:app --port 8799` | Start the local lobby at `http://127.0.0.1:8799/game/` |
| `python -m arena.run --config examples/quiz_mock.yaml` | Run a terminal-only mock match |
| `./infra/play-free.sh` | Start a public mock demo through a temporary tunnel |
| `ARENA_PRESET=three ./infra/play-free.sh` | Run local-only Claude, Codex and Grok host adapters |

## Change workflow

1. Confirm the current branch and preserve unrelated worktree changes.
2. Add or update a failing test before behavioral changes.
3. Keep public policy fail-closed. Never widen CTF targets, host adapters, credentials or egress as a side effect of another feature.
4. Update English and Traditional Chinese protocol or README text together when user-visible behavior changes.
5. Run the full suite, JavaScript syntax checks and `git diff --check`.
6. For release work, separately report local tests, CI, deployment, public API checks and browser acceptance.

## Pull-request checklist

- [ ] Tests cover the behavior and security boundary
- [ ] `pytest -q` passes
- [ ] Changed JavaScript parses successfully
- [ ] README, protocol, safety, roadmap and changelog are current where applicable
- [ ] No credential, flag, transcript or local state was added
- [ ] Public and private-server behavior remain clearly separated
