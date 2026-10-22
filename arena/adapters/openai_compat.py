"""OpenAI 相容 adapter：一套碼同時涵蓋 Grok（api.x.ai）、OpenAI、及任何相容端點。

靠 base_url + 金鑰 + 模型名切換。params 可覆寫：
  base_url        直接指定端點；或
  base_url_env    指定存 base_url 的環境變數名（預設 ARENA_OPENAI_BASE_URL）
  api_key_env     指定存金鑰的環境變數名（預設 ARENA_OPENAI_API_KEY）
  allow_insecure  本機/自架相容端點 opt-in（略過 https+白名單校驗，自負其責）

安全：base_url 預設強制 https + 端點白名單 + 阻擋私網/metadata（防 SSRF 與金鑰外洩，見 security.py）；
不跟隨轉址（防 302 跳 metadata）；金鑰只從環境變數讀，不進 transcript。
"""

from __future__ import annotations

import os
import time

from ..security import validate_base_url, validate_model_name
from ..types import Action, Observation, Usage
from .base import Adapter, AdapterUnavailable, render_observation


class OpenAICompatAdapter(Adapter):
    def _resolve_base_url(self) -> str:
        p = self.spec.params
        if p.get("base_url"):
            return str(p["base_url"])
        return os.environ.get(p.get("base_url_env", "ARENA_OPENAI_BASE_URL"), "")

    def _resolve_key(self) -> str:
        return os.environ.get(self.spec.params.get("api_key_env", "ARENA_OPENAI_API_KEY"), "")

    async def act(self, obs: Observation) -> Action:
        try:
            import httpx
        except ImportError as e:  # pragma: no cover
            raise AdapterUnavailable(f"缺少 httpx：{e}") from e

        base_url = self._resolve_base_url()
        api_key = self._resolve_key()
        if not base_url or not api_key:
            raise AdapterUnavailable("openai_compat 需要 base_url 與 api_key（檢查環境變數）")
        base_url = validate_base_url(base_url, self.spec.params.get("allow_insecure"))
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
        async with httpx.AsyncClient(
            timeout=self.spec.params.get("http_timeout", 120.0), follow_redirects=False
        ) as client:
            resp = await client.post(
                base_url.rstrip("/") + "/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {api_key}"},
            )
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
