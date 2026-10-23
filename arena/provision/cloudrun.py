"""Cloud Run provisioner: deploys the target as a GCP Cloud Run service (free tier, deleted after use).

Always uses a Service Account (key given by ARENA_GCP_SA_KEY) and never asks the user for an interactive login;
IAM_PERMISSION_DENIED is a sign of overstepping, so stop and report instead of working around it (G6).

v0 security boundary:
- Only accepts allowlisted self-hosted targets with kind=self (OSS targets are rejected: egress control on Cloud Run isn't ready).
- --no-allow-unauthenticated by default: the target isn't public and the engine calls it with an SA identity token.
- Deleted after use (teardown at match end + configurable TTL cleaned up externally).
Note: Cloud Run services can reach the internet by default, so G2 "no egress" doesn't fully hold on Cloud Run yet.
That is why only self (inert) targets are accepted; OSS targets need VPC egress control first.
"""

from __future__ import annotations

import asyncio
import os

from ..security import looks_secret
from .base import Provisioner, Sandbox, TargetSpec
from .local import _load_allowlist, _run

_TARGETS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "targets")


async def _gcloud(*args: str, timeout: float = 120.0) -> tuple[int, bytes, bytes]:
    return await _run("gcloud", *args, timeout=timeout)


class CloudRunSandbox(Sandbox):
    def __init__(self, service: str, region: str, project: str, url: str, id_token: str):
        self._service = service
        self._region = region
        self._project = project
        self._url = url.rstrip("/")
        self._id_token = id_token
        self._down = False

    async def http(self, method: str, path: str, body: str | None = None, timeout: float = 15.0) -> tuple[int, str]:
        import httpx

        if not path.startswith("/"):
            path = "/" + path
        headers = {}
        if self._id_token:
            headers["Authorization"] = f"Bearer {self._id_token}"
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
                resp = await client.request(
                    method, self._url + path, content=(body.encode() if body else None), headers=headers
                )
                return (resp.status_code, resp.text)
        except Exception as e:  # noqa: BLE001
            return (-1, f"ERR: {type(e).__name__}: {e}")

    async def teardown(self) -> None:
        if self._down:
            return
        self._down = True
        await _gcloud(
            "run", "services", "delete", self._service,
            "--region", self._region, "--project", self._project, "--quiet",
            timeout=180,
        )


class CloudRunProvisioner(Provisioner):
    def __init__(self, allowlist_path: str | None = None):
        from .local import _DEFAULT_ALLOWLIST

        self.allowlist = _load_allowlist(allowlist_path or os.environ.get("ARENA_ALLOWLIST", _DEFAULT_ALLOWLIST))
        # GCP settings always come from env vars; project/SA details stay out of the source (this repo can be public)
        self.region = os.environ.get("ARENA_GCP_REGION", "asia-east1")
        self.project = os.environ.get("ARENA_GCP_PROJECT", "")
        self.sa_key = os.environ.get("ARENA_GCP_SA_KEY", "")
        self.sa_email = os.environ.get("ARENA_GCP_SA_EMAIL", "")

    async def provision(self, target: TargetSpec, match_id: str, ttl_seconds: int = 1800) -> Sandbox:
        # G1 allowlist; cloudrun v0 only accepts self-hosted self targets
        meta = self.allowlist.get(target.image)
        if meta is None:
            raise PermissionError(f"G1 rejected: image {target.image!r} is not on the allowlist")
        if meta.get("kind") != "self":
            raise PermissionError("cloudrun v0 only supports self-hosted self targets (egress control for OSS targets isn't ready)")

        # G4 secret scan
        for k, v in (target.env or {}).items():
            if k != "FLAG" and looks_secret(str(v)):
                raise PermissionError(f"G4 rejected: the value of env var {k} looks like a real credential")

        if not self.project:
            raise RuntimeError("cloudrun requires the ARENA_GCP_PROJECT env var")
        # activate the SA per the gcp-deploy rules (only if a key is set, otherwise use the existing credentials; never ask for an interactive login)
        if self.sa_key:
            rc, _, err = await _gcloud("auth", "activate-service-account", "--key-file", self.sa_key, timeout=60)
            if rc != 0:
                raise RuntimeError(f"activating the SA failed: {err.decode(errors='replace')[:200]}")

        service = ("arena-" + match_id).lower()[:63]
        src = os.path.join(_TARGETS_DIR, meta.get("dir", "warmup"))
        env_pairs = ",".join(f"{k}={v}" for k, v in (target.env or {}).items())

        deploy = [
            "run", "deploy", service, "--source", src,
            "--region", self.region, "--project", self.project,
            "--port", str(meta["port"]), "--memory", "512Mi", "--cpu", "1", "--max-instances", "1",
            "--labels", f"arena-match={match_id}".lower()[:63],
            "--no-allow-unauthenticated", "--quiet",
        ]
        if env_pairs:
            deploy += ["--set-env-vars", env_pairs]
        rc, _out, err = await _gcloud(*deploy, timeout=float(os.environ.get("ARENA_CLOUDRUN_DEPLOY_TIMEOUT", "480")))
        if rc != 0:
            msg = err.decode(errors="replace")
            if "PERMISSION_DENIED" in msg or "IAM_PERMISSION_DENIED" in msg:
                raise PermissionError(f"G6 out of bounds (insufficient IAM permissions; stopping and reporting, not working around it): {msg[:200]}")
            raise RuntimeError(f"Cloud Run deploy failed: {msg[:300]}")

        # deploy created the service: if any later step fails, delete it so an orphaned service doesn't keep billing (§billing safety)
        async def _delete_service() -> None:
            await _gcloud(
                "run", "services", "delete", service,
                "--region", self.region, "--project", self.project, "--quiet", timeout=120,
            )

        try:
            rc, out, err = await _gcloud(
                "run", "services", "describe", service,
                "--region", self.region, "--project", self.project, "--format", "value(status.url)",
                timeout=60,
            )
            url = out.decode(errors="replace").strip()
            if rc != 0 or not url:
                raise RuntimeError(f"getting the Cloud Run URL failed: {err.decode(errors='replace')[:200]}")

            # grant the SA invoker on this service (service-level IAM within run.admin), then mint an identity token
            if self.sa_email:
                await _gcloud(
                    "run", "services", "add-iam-policy-binding", service,
                    "--member", f"serviceAccount:{self.sa_email}", "--role", "roles/run.invoker",
                    "--region", self.region, "--project", self.project, "--quiet",
                    timeout=90,
                )
            rc, tok, _err = await _gcloud("auth", "print-identity-token", f"--audiences={url}", timeout=60)
            id_token = tok.decode(errors="replace").strip() if rc == 0 else ""

            sandbox = CloudRunSandbox(service, self.region, self.project, url, id_token)

            # readiness polling (Cloud Run cold start)
            for _ in range(30):
                status, _body = await sandbox.http("GET", "/", timeout=15)
                if status not in (-1, 500, 502, 503):
                    break
                await asyncio.sleep(2)
            return sandbox
        except Exception:
            await _delete_service()  # best-effort cleanup of the orphaned service
            raise
