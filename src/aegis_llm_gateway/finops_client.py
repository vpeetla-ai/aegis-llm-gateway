from __future__ import annotations

import logging

import httpx

from aegis_llm_gateway.settings import settings

log = logging.getLogger(__name__)


async def meter_usage(*, tenant_id: str, model: str, usage: dict) -> dict | None:
    if not settings.agentfinops_url:
        return None
    url = settings.agentfinops_url.rstrip("/") + "/v1/usage"
    payload = {
        "scope_type": "tenant",
        "scope_value": tenant_id,
        "provider": "gateway",
        "model": model,
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.post(url, json=payload)
            if r.status_code >= 400:
                if settings.control_plane_mode == "strict":
                    raise RuntimeError(f"finops meter failed: {r.status_code}")
                log.warning("finops meter failed: %s", r.status_code)
                return None
            return r.json()
    except Exception as exc:
        if settings.control_plane_mode == "strict":
            raise
        log.warning("finops meter error (demo fail-open): %s", exc)
        return None
