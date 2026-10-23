"""OpenAI-compatible adapter: one codebase covers Grok (api.x.ai), OpenAI and any compatible endpoint.

Switched by base_url + key + model name. params can override:
  base_url        the endpoint directly; or
  base_url_env    name of the env var holding base_url (default ARENA_OPENAI_BASE_URL; must look like *_BASE_URL)
  api_key_env     name of the env var holding the key (default ARENA_OPENAI_API_KEY; must look like *_API_KEY
                  and belong to the target endpoint's service, e.g. api.x.ai only accepts the XAI_/GROK_ prefixes;
                  the ARENA_ general-purpose key only pairs with a base_url from a server-side env var)

Security:
- base_url requires https + endpoint allowlist + blocks private networks/metadata (SSRF and key leak protection, see security.py).
  This check **can't be turned off via params**; local/self-hosted endpoints can only be allowed by the server-side
  env var ARENA_ALLOW_INSECURE_BASE_URL=1 (even then, cloud metadata endpoints stay blocked).
- Env var names are restricted: params can't name an arbitrary env var (e.g. GITHUB_TOKEN) to be sent as the bearer.
- Redirects are not followed (stops a 302 to metadata); the key is read only from env vars and never enters the transcript.
- A base_url given directly in participant settings (params.base_url) is always rejected when ARENA_ALLOW_INSECURE_BASE_URL=1
  (the relaxation only applies to endpoints named by server-side env vars).
- Fault attribution: connection failures, 401/403, 429 or 5xx from a server-specified endpoint -> AdapterUnavailable
  (infra, unrated); timeouts or errors from an endpoint the participant chose -> ordinary exception, attributed to
  that agent (forfeit), so a participant's self-hosted endpoint returning 503 can't void the match.
- The HTTP timeout is fixed and not controlled by params (the engine's per-step timeout fires first and is attributed to the agent).
"""

from __future__ import annotations

import os
import time

from ..security import (
    insecure_base_url_allowed,
    validate_api_key_env,
    validate_base_url,
    validate_env_name,
    validate_model_name,
)
from ..types import Action, Observation, Usage
from .base import Adapter, AdapterUnavailable, render_observation

_DEFAULT_BASE_URL_ENV = "ARENA_OPENAI_BASE_URL"
_DEFAULT_API_KEY_ENV = "ARENA_OPENAI_API_KEY"
_INFRA_STATUS = {401, 403, 429}
_HTTP_TIMEOUT = 300.0  # fixed cap; in practice the engine's per-step timeout cuts in first


class OpenAICompatAdapter(Adapter):
    def _resolve_base_url(self) -> tuple[str, bool]:
        """Return (base_url, whether it came from the server side)."""
        p = self.spec.params
        if p.get("base_url"):
            if insecure_base_url_allowed():
                raise ValueError("when the server relaxes base_url checks, participant settings must not set base_url directly (use base_url_env)")
            return str(p["base_url"]), False
        env_name = validate_env_name(p.get("base_url_env", _DEFAULT_BASE_URL_ENV), "base_url")
        return os.environ.get(env_name, ""), True

    def _resolve_key(self, base_url: str, server_side: bool) -> str:
        env_name = validate_api_key_env(
            self.spec.params.get("api_key_env", _DEFAULT_API_KEY_ENV), base_url, allow_arena_key=server_side
        )
        return os.environ.get(env_name, "")

    async def act(self, obs: Observation) -> Action:
        try:
            import httpx
        except ImportError as e:  # pragma: no cover
            raise AdapterUnavailable(f"httpx is missing: {e}") from e

        try:
            base_url, server_side = self._resolve_base_url()
            if not base_url:
                raise AdapterUnavailable("openai_compat needs a base_url (check env vars)")
            base_url = validate_base_url(base_url)
            api_key = self._resolve_key(base_url, server_side)
        except ValueError as e:
            # settings rejected by a security gate: a config/infra problem, not in-match performance
            raise AdapterUnavailable(f"openai_compat config rejected: {e}") from e
        if not api_key:
            raise AdapterUnavailable("openai_compat needs an api_key (check env vars)")
        validate_model_name(self.spec.model)

        messages = []
        if self.spec.system_prompt:
            messages.append({"role": "system", "content": self.spec.system_prompt})
        messages.append({"role": "user", "content": render_observation(obs)})
        payload = {
            "model": self.spec.model or "gpt-4o-mini",
            "messages": messages,
            "temperature": self.spec.params.get("temperature", 0.2),
        }

        t0 = time.monotonic()
        # only errors from a server-specified endpoint count as infra; errors from the participant's own endpoint are on the participant
        endpoint_fault = AdapterUnavailable if server_side else RuntimeError
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, follow_redirects=False) as client:
                resp = await client.post(
                    base_url.rstrip("/") + "/chat/completions",
                    json=payload,
                    headers={"Authorization": f"Bearer {api_key}"},
                )
        except httpx.TimeoutException as e:
            raise RuntimeError(f"endpoint timed out: {type(e).__name__}") from e
        except httpx.TransportError as e:
            raise endpoint_fault(f"endpoint unreachable: {type(e).__name__}") from e
        if resp.status_code in _INFRA_STATUS or resp.status_code >= 500:
            raise endpoint_fault(f"endpoint returned HTTP {resp.status_code}")
        resp.raise_for_status()
        data = resp.json()
        dt = time.monotonic() - t0

        content = (data["choices"][0]["message"].get("content") or "").strip()
        u = data.get("usage", {})
        return Action(
            content=content,
            usage=Usage(
                input_tokens=u.get("prompt_tokens", 0),
                output_tokens=u.get("completion_tokens", 0),
                wall_seconds=dt,
            ),
        )
