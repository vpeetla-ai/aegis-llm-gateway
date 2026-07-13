from __future__ import annotations

import logging

import httpx

from aegis_llm_gateway.settings import settings

log = logging.getLogger(__name__)


async def cache_lookup(tenant_id: str, model: str, messages: list[dict]) -> dict | None:
    if not settings.semantic_cache_url:
        return None
    url = settings.semantic_cache_url.rstrip("/") + "/v1/cache/lookup"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.post(
                url,
                json={"tenant_id": tenant_id, "model": model, "messages": messages},
            )
            if r.status_code != 200:
                if settings.control_plane_mode == "strict":
                    raise RuntimeError(f"cache lookup failed: {r.status_code}")
                log.warning("cache lookup failed: %s", r.status_code)
                return None
            body = r.json()
            if body.get("hit"):
                return body.get("response")
    except Exception as exc:
        if settings.control_plane_mode == "strict":
            raise
        log.warning("cache lookup error (demo fail-open): %s", exc)
    return None


async def cache_store(tenant_id: str, model: str, messages: list[dict], response: dict) -> None:
    if not settings.semantic_cache_url:
        return
    url = settings.semantic_cache_url.rstrip("/") + "/v1/cache/store"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                url,
                json={
                    "tenant_id": tenant_id,
                    "model": model,
                    "messages": messages,
                    "response": response,
                },
            )
    except Exception as exc:
        if settings.control_plane_mode == "strict":
            raise
        log.warning("cache store error (demo fail-open): %s", exc)
