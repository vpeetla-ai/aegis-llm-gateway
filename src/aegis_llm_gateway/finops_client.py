from __future__ import annotations

import logging
from typing import Any

import httpx

from aegis_llm_gateway.settings import settings

log = logging.getLogger(__name__)


class FinOpsUnavailableError(RuntimeError):
    """FinOps dependency failed while control_plane_mode=strict."""


class BudgetBreachedError(RuntimeError):
    """Tenant budget already breached; gateway refuses new paid completions in strict mode."""

    def __init__(self, *, tenant_id: str, total_cost_usd: float, budget_usd: float | None):
        self.tenant_id = tenant_id
        self.total_cost_usd = total_cost_usd
        self.budget_usd = budget_usd
        super().__init__(
            f"budget breached for tenant={tenant_id} total={total_cost_usd} budget={budget_usd}"
        )


def _headers() -> dict[str, str]:
    headers: dict[str, str] = {}
    if settings.agentfinops_api_key:
        headers["X-API-Key"] = settings.agentfinops_api_key
    return headers


def _fail_closed() -> bool:
    return settings.control_plane_mode == "strict"


async def get_budget_status(tenant_id: str) -> dict[str, Any] | None:
    """GET /v1/budget/tenant/{tenant_id}. Returns None if FinOps not configured."""
    if not settings.agentfinops_url:
        return None
    url = f"{settings.agentfinops_url.rstrip('/')}/v1/budget/tenant/{tenant_id}"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(url, headers=_headers())
            if r.status_code >= 400:
                if _fail_closed():
                    raise FinOpsUnavailableError(f"finops budget get failed: {r.status_code}")
                log.warning("finops budget get failed (demo fail-open): %s", r.status_code)
                return None
            return r.json()
    except FinOpsUnavailableError:
        raise
    except Exception as exc:
        if _fail_closed():
            raise FinOpsUnavailableError(str(exc)) from exc
        log.warning("finops budget get error (demo fail-open): %s", exc)
        return None


async def assert_budget_allows(tenant_id: str) -> dict[str, Any] | None:
    """Pre-flight: in strict mode, refuse when FinOps reports breached=true."""
    status = await get_budget_status(tenant_id)
    if not status:
        return None
    if status.get("breached"):
        if _fail_closed():
            raise BudgetBreachedError(
                tenant_id=tenant_id,
                total_cost_usd=float(status.get("total_cost_usd") or 0),
                budget_usd=status.get("budget_usd"),
            )
        log.warning(
            "finops budget already breached for %s (demo fail-open — allowing)",
            tenant_id,
        )
    return status


async def meter_usage(*, tenant_id: str, model: str, usage: dict) -> dict[str, Any] | None:
    """POST /v1/usage. Demo fail-open on errors; strict raises FinOpsUnavailableError."""
    if not settings.agentfinops_url:
        return None
    url = settings.agentfinops_url.rstrip("/") + "/v1/usage"
    payload = {
        "scope_type": "tenant",
        "scope_value": tenant_id,
        "provider": "gateway",
        "model": model,
        "prompt_tokens": int(usage.get("prompt_tokens", 0)),
        "completion_tokens": int(usage.get("completion_tokens", 0)),
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.post(url, json=payload, headers=_headers())
            if r.status_code >= 400:
                if _fail_closed():
                    raise FinOpsUnavailableError(f"finops meter failed: {r.status_code}")
                log.warning("finops meter failed (demo fail-open): %s", r.status_code)
                return None
            body = r.json()
            if body.get("breached") and not _fail_closed():
                log.warning(
                    "finops reports breach after meter tenant=%s total=%s",
                    tenant_id,
                    body.get("total_cost_usd"),
                )
            return body
    except FinOpsUnavailableError:
        raise
    except Exception as exc:
        if _fail_closed():
            raise FinOpsUnavailableError(str(exc)) from exc
        log.warning("finops meter error (demo fail-open): %s", exc)
        return None
