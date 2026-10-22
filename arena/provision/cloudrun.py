"""Cloud Run 配置器：把靶機部署成 GCP Cloud Run 服務（免費額度，用完即刪）。

一律用 Service Account（金鑰由 ARENA_GCP_SA_KEY 指定），絕不請使用者互動登入；
遇 IAM_PERMISSION_DENIED 即越界訊號，停工回報不繞過（G6）。

v0 安全邊界：
- 只接受白名單中 kind=self 的自架靶機（OSS 靶機在 Cloud Run 的出網控制尚未就緒，拒絕）。
- 預設 --no-allow-unauthenticated：靶機不公開，引擎以 SA 身分權杖呼叫。
- 用完即 delete（散場 teardown + 可配 TTL 由外部清掃）。
注意：Cloud Run 服務預設可對外出網，故 G2「封閉出網」在 Cloud Run 上尚未完全成立——
這是只收 self（inert）靶機的原因；要上 OSS 靶機須先補 VPC egress 控制。
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
        # GCP 設定一律由環境變數提供，不把專案/SA 細節寫進原始碼（本 repo 可公開）
        self.region = os.environ.get("ARENA_GCP_REGION", "asia-east1")
        self.project = os.environ.get("ARENA_GCP_PROJECT", "")
        self.sa_key = os.environ.get("ARENA_GCP_SA_KEY", "")
        self.sa_email = os.environ.get("ARENA_GCP_SA_EMAIL", "")

    async def provision(self, target: TargetSpec, match_id: str, ttl_seconds: int = 1800) -> Sandbox:
        # G1 白名單；cloudrun v0 僅收自架 self 靶機
        meta = self.allowlist.get(target.image)
        if meta is None:
            raise PermissionError(f"G1 拒絕：映像 {target.image!r} 不在白名單")
        if meta.get("kind") != "self":
            raise PermissionError("cloudrun v0 僅支援自架 self 靶機（OSS 靶機的出網控制未就緒）")

        # G4 祕密掃描
        for k, v in (target.env or {}).items():
            if k != "FLAG" and looks_secret(str(v)):
                raise PermissionError(f"G4 拒絕：環境變數 {k} 的值疑似真實憑證")

        if not self.project:
            raise RuntimeError("cloudrun 需要設定 ARENA_GCP_PROJECT 環境變數")
        # 依 gcp-deploy 規範啟用 SA（有金鑰才啟用，否則用環境既有認證；絕不請使用者互動登入）
        if self.sa_key:
            rc, _, err = await _gcloud("auth", "activate-service-account", "--key-file", self.sa_key, timeout=60)
            if rc != 0:
                raise RuntimeError(f"啟用 SA 失敗：{err.decode(errors='replace')[:200]}")

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
                raise PermissionError(f"G6 越界（IAM 權限不足，停工回報不繞過）：{msg[:200]}")
            raise RuntimeError(f"Cloud Run 部署失敗：{msg[:300]}")

        # deploy 已建立服務：後續任一步失敗都要把服務刪掉，避免孤兒服務持續計費（§金流安全）
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
                raise RuntimeError(f"取得 Cloud Run URL 失敗：{err.decode(errors='replace')[:200]}")

            # 授予 SA 對本服務的 invoker（run.admin 範圍內的服務層 IAM），再鑄 identity token
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

            # 就緒輪詢（Cloud Run 冷啟動）
            for _ in range(30):
                status, _body = await sandbox.http("GET", "/", timeout=15)
                if status not in (-1, 500, 502, 503):
                    break
                await asyncio.sleep(2)
            return sandbox
        except Exception:
            await _delete_service()  # best-effort 清理孤兒服務
            raise
