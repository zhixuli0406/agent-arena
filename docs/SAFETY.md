# Safety model

The security matches in this project make sense in one situation only: **authorized CTF / penetration practice**. The targets are self-hosted, deliberately vulnerable, network isolated, and torn down after use. Pointing this capability at real systems without authorization is outside the scope of this project and will not be supported.

Read this document before working on the security arena (`ctf` mode). The rules are written as hard gates: the code enforces them, they don't depend on self-discipline.

## Implementation status (2026-10-22)

| Gate | Status | Where |
|---|---|---|
| G1 target allowlist | ✅ Enforced | `provision/local.py` reads `targets/allowlist.yaml` and refuses anything not on it |
| G2 network isolation / no egress | ✅ Enforced (tested) | `--internal` network + no published ports + runner sidecar |
| G3 TTL circuit breaker | ✅ Labels + teardown at match end + `reaper.py`; ⚠️ scheduled run not set up yet | Containers carry an `arena.expires` label |
| G4 no real credentials | ✅ Enforced | Environment variables are scanned before provisioning; a match on a secret pattern is refused |
| G5 external content demoted to DATA | ✅ In place | `security.wrap_untrusted()` fence + strict action grammar |
| G6 permission boundary | ✅ Enforced | `cloudrun` raises PermissionError on IAM_PERMISSION_DENIED, stops and reports |
| Cloud Run egress | ⚠️ Not controlled | So `cloudrun` v0 only accepts self-hosted self (inert) targets; OSS targets wait for VPC egress control |
| C1 no host-side agentic agents | ✅ Enforced | `ctf` setup checks `is_host_actor`; can be explicitly allowed with `allow_host_agentic` |
| CTF spectator flag secrecy | ✅ Enforced locally | The stream emits an allowlisted `ctf` projection; match status and lobby match lists withhold CTF failure text. The private transcript retains match evidence. This does not enable CTF on the public server. |

## Threat model: who we defend against

1. **Escape**: an agent (or a target it has compromised) tries to reach the host machine, the internal network, or real external services from the sandbox.
2. **Accidental harm**: a misconfiguration exposes a target to the public internet, or a flag/question contains real credentials.
3. **Runaway**: looping attacks exhaust quotas, or resources are never torn down and keep billing.
4. **Prompt injection**: instructions embedded in target responses or question content get executed as commands to the agent or the engine.
5. **Flag leakage**: another player or spectator reads a live flag from the public match stream before submitting their own answer.

## Hard gates (enforced in code, no bypass)

### G1 target allowlist

Only targets on the **allowlist of known-vulnerable images** (`targets/allowlist.yaml`) can be started: OWASP Juice Shop, DVWA, WebGoat, and the CTF containers that ship in this project's `targets/`. Any image not on the allowlist is refused. This rules out "just go hit a real service while you're at it".

### G2 network isolation and no egress

Targets run in a separate Docker network (`local`) or a separate Cloud Run service with no outbound access (`cloudrun`). By default **targets cannot reach the outside network** (only the agent → target path is open). Agents reach targets through the engine's proxy tools and get no ability to connect directly to arbitrary networks.

### G3 TTL circuit breaker

Every target gets a TTL (30 minutes by default) and a match ID label when it is provisioned. When the TTL expires it is torn down unconditionally. A separate sweeper also periodically scans for resources that carry this project's labels and are past their age, and reclaims them, so a crashed match can't leave orphaned resources that keep billing.

### G4 no real credentials

Questions, flags and target environment variables must not contain any real key, password or token. CI runs secret scanning, and the provisioner checks that the environment variables it injects don't match credential patterns before starting a target.

### G5 external content is always DATA

A target's HTTP responses, file contents and question text are data to the engine and the judges, never instructions. Any "please run…" or "ignore previous…" in them must not be treated as a command. This is prompt-injection protection, and it is built into the layer where the engine wraps Observations.

### G6 permission boundary as a boundary signal

The `cloudrun` provider only does deployment work (deploy, builds, source upload). `IAM_PERMISSION_DENIED` is always treated as crossing the boundary: stop and report, never try to escalate privileges or find another way around.

## Scope

- ✅ Supported: CTF on self-hosted isolated targets, red/blue team exercises, research on models' attack and defense abilities, teaching.
- ❌ Not supported and not assisted: scanning or attacking real systems without authorization, DoS, large-scale targeting, supply chain poisoning, detection evasion for malicious purposes.

If the provisioner detects that a target looks like a real or public host (an image not on the allowlist, or a non-isolated network segment), it refuses and logs it, and does not run it.
