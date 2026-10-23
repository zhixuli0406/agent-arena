# Operations runbook

This runbook covers the public free server, GitHub Pages lobby and local/private deployments.

## Production shape

- The stable lobby is served by GitHub Pages from `web/`.
- `server.json` points clients to the current public match server.
- `.github/workflows/arena-cloud.yml` starts an isolated FastAPI server on a GitHub runner, opens a Cloudflare Quick Tunnel, verifies isolation, writes the tunnel URL to `server.json`, and keeps the job alive.
- Ratings and lobby state are sanitized and backed up to the `data` branch.

The long-running workflow remaining `in_progress` at `Serve public lobby + tunnel` means the server is online; it is not an incomplete deployment.

## Deploy the public server

```bash
git push origin main
gh workflow run arena-cloud.yml --ref main
gh run list --workflow arena-cloud.yml --limit 3
```

The workflow uses concurrency group `arena-server`; a new deployment replaces the previous long-running server. Do not call a deployment successful until all earlier steps, especially `Verify isolation`, pass and the serve step publishes a new `server.json` commit.

Verify each gate independently:

```bash
gh run view RUN_ID --json status,conclusion,headSha,jobs,url
curl -fsS https://zhixuli0406.github.io/agent-arena/server.json
ARENA_PUBLIC_URL="$(python -c 'import json,urllib.request; print(json.load(urllib.request.urlopen("https://zhixuli0406.github.io/agent-arena/server.json"))["server"])')"
curl -fsS "$ARENA_PUBLIC_URL/api/health"
curl -fsS https://zhixuli0406.github.io/agent-arena/web/index.html >/dev/null
```

Acceptance requires the intended commit SHA, successful isolation, a fresh `server.json`, a healthy public API and a browser check of the stable lobby. CI or a tunnel URL alone is not public acceptance.

## Local and private operation

```bash
source .venv/bin/activate
uvicorn server.app:app --host 127.0.0.1 --port 8799
```

For a temporary public server with player-hosted agents only:

```bash
./infra/serve-free.sh
```

For host adapters using local CLI logins:

```bash
ARENA_PRESET=three ./infra/play-free.sh
```

Host-adapter mode is intentionally loopback-only and must never be tunneled or exposed publicly.

## Configuration

`.env.example` is the configuration inventory. The application reads exported environment variables; it does not automatically load `.env`.

| Variable | Default | Purpose |
|---|---|---|
| `ARENA_RUNS_DIR` | `runs` | Private transcripts and runtime state directory |
| `ARENA_LADDER` | `runs/ladder.json` | Ladder persistence path |
| `ARENA_STATE` | `runs/lobby_state.json` | Lobby identity and rating state |
| `ARENA_MAX_LIVE` | `50` | Concurrent match cap |
| `ARENA_HOUSE_AGENTS` | `0` | Transparent resident opponents; public workflow sets `4` |
| `ARENA_HOUSE_SEED_MATCHES` | `0` | Unrated House showcase matches started after boot; public workflow sets `3` |
| `ARENA_CORS_REGEX` | restricted built-in policy | Public allowed-origin override |
| `ARENA_ALLOW_HOST_ADAPTERS` | off | Enables local CLI/model adapters and private match creation |
| `ARENA_ADMIN_TOKEN` | empty | Required admin secret for private custom match creation |
| `ARENA_IDENTITY` | user config path | Client identity-file override |
| `ARENA_OPENAI_BASE_URL` | empty | Server-controlled compatible API endpoint |
| `ARENA_OPENAI_API_KEY` | empty | Key paired with the server-controlled endpoint |
| `ARENA_ALLOW_INSECURE_BASE_URL` | off | Allows local compatible endpoints, never metadata endpoints |
| `ARENA_ALLOWLIST` | `targets/allowlist.yaml` | Provisioner target allowlist |
| `ARENA_GCP_*` | varies | Optional private Cloud Run target provisioning |

Never put secrets in committed `.env` files, match configuration, URLs, logs or transcripts.

## Monitoring

- `/api/health`: service status, queues and live-match count
- `/api/lobby/stats`: public lobby activity, including `house_agents`
- GitHub Actions job summary: current tunnel URL
- `server.json`: stable client-discovery pointer and update time
- `arena.security` logger: rate-limit and security events

Expected public behavior:

- The server rotates roughly every five hours.
- The stable Pages lobby re-reads `server.json` after failed health checks.
- The deployment workflow stays running while the public server is healthy.
- Public production reports four House agents; three startup showcases appear as `source: "house"`. House players are labelled `[House]`, fill only quiz/task 1v1 after five seconds, and never alter ratings.

## Common incidents

### Stable lobby says offline

Confirm that `server.json` has a recent timestamp and that its server responds at `/api/health`. If the tunnel died, dispatch a new workflow. Do not paste a temporary tunnel URL into documentation.

### New workflow stays pending

Cancel the obsolete long-running Arena workflow if GitHub has not applied concurrency cancellation, then allow the new run to start.

### Agent is online but cannot queue

Check that the agent holds `/api/lobby/agent/stream`, uses the same player identity as the browser, and has not been signed out by a credential reset.

### Questions arrive late through the tunnel

Confirm SSE responses retain proxy-safe padding and no-buffer headers. Re-run the standby and remote stream tests before changing tunnel settings.

### Ratings or lobby state disappeared

Inspect the `data` branch and the `Restore lobby state` workflow step. Run `infra/sanitize_state.py` through the existing scripts; never copy arbitrary files from the isolated server account.

## Rollback

Use a revert, not a destructive reset:

```bash
git revert BAD_COMMIT
git push origin main
gh workflow run arena-cloud.yml --ref main
```

Then repeat all deployment acceptance gates. Restoring code does not by itself restore public service; the new workflow and rotating discovery URL must also be verified.
