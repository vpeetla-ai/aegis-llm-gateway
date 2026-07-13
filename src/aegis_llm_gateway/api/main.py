from __future__ import annotations

import time
import uuid
from collections import Counter

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from aegis_llm_gateway.cache_client import cache_lookup, cache_store
from aegis_llm_gateway.finops_client import (
    BudgetBreachedError,
    FinOpsUnavailableError,
    assert_budget_allows,
    meter_usage,
)
from aegis_llm_gateway.models import ChatCompletionRequest, ChatCompletionResponse
from aegis_llm_gateway.settings import settings
from aegis_llm_gateway.stub_provider import stub_complete

app = FastAPI(title="aegis-llm-gateway", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_STATS: Counter[str] = Counter()


def _check_key(x_api_key: str | None) -> None:
    if settings.gateway_api_key and x_api_key != settings.gateway_api_key:
        raise HTTPException(status_code=401, detail="invalid api key")


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": "aegis-llm-gateway",
        "gateway_mode": settings.gateway_mode,
        "control_plane_mode": settings.control_plane_mode,
        "cache_configured": bool(settings.semantic_cache_url),
        "finops_configured": bool(settings.agentfinops_url),
        "posture": (
            "fail-closed"
            if settings.control_plane_mode == "strict"
            else "fail-open (demo)"
        ),
    }


@app.get("/v1/posture")
def posture() -> dict:
    """Document demo vs strict for Control Room / interview demos."""
    strict = settings.control_plane_mode == "strict"
    return {
        "control_plane_mode": settings.control_plane_mode,
        "posture": "fail-closed" if strict else "fail-open",
        "gateway_mode": settings.gateway_mode,
        "behavior": {
            "finops_unavailable": "HTTP 503" if strict else "log + continue",
            "budget_already_breached": "HTTP 402" if strict else "log + continue with warning",
            "cache_unavailable": "raise/503 path" if strict else "log + continue",
            "byok_not_implemented": "HTTP 501" if strict else "fall back to stub",
        },
        "honesty": (
            "Architecture is fail-closed capable; demo mode is an explicit toggle "
            "for free-tier portfolio demos — never silent."
        ),
    }


@app.get("/v1/ops/metrics")
def metrics() -> dict:
    return {
        "service": "aegis-llm-gateway",
        "completions": _STATS["completions"],
        "cache_hits": _STATS["cache_hits"],
        "cache_misses": _STATS["cache_misses"],
        "stub_completions": _STATS["stub_completions"],
        "finops_meters": _STATS["finops_meters"],
        "finops_breaches_blocked": _STATS["finops_breaches_blocked"],
        "finops_errors": _STATS["finops_errors"],
        "control_plane_mode": settings.control_plane_mode,
    }


@app.post("/v1/chat/completions", response_model=ChatCompletionResponse)
async def chat_completions(
    body: ChatCompletionRequest,
    x_api_key: str | None = Header(default=None),
    x_tenant_id: str | None = Header(default=None),
) -> ChatCompletionResponse:
    _check_key(x_api_key)
    if body.stream:
        raise HTTPException(status_code=400, detail="streaming not supported yet")

    tenant_id = (x_tenant_id or settings.default_tenant_id).strip() or settings.default_tenant_id
    messages = [m.model_dump() for m in body.messages]
    t0 = time.perf_counter()
    finops_meta: dict = {"configured": bool(settings.agentfinops_url)}

    try:
        budget_status = await assert_budget_allows(tenant_id)
        if budget_status is not None:
            finops_meta["precheck"] = {
                "breached": bool(budget_status.get("breached")),
                "total_cost_usd": budget_status.get("total_cost_usd"),
                "budget_usd": budget_status.get("budget_usd"),
            }
    except BudgetBreachedError as exc:
        _STATS["finops_breaches_blocked"] += 1
        raise HTTPException(
            status_code=402,
            detail={
                "error": "budget_breached",
                "tenant_id": exc.tenant_id,
                "total_cost_usd": exc.total_cost_usd,
                "budget_usd": exc.budget_usd,
                "control_plane_mode": settings.control_plane_mode,
            },
        ) from exc
    except FinOpsUnavailableError as exc:
        _STATS["finops_errors"] += 1
        raise HTTPException(
            status_code=503,
            detail={
                "error": "finops_unavailable",
                "message": str(exc),
                "control_plane_mode": "strict",
            },
        ) from exc

    cached = await cache_lookup(tenant_id, body.model, messages)
    if cached and "content" in cached:
        _STATS["completions"] += 1
        _STATS["cache_hits"] += 1
        content = cached["content"]
        usage = cached.get("usage") or {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
        gateway_meta = {
            "tenant_id": tenant_id,
            "cache_hit": True,
            "provider": "cache",
            "latency_ms": int((time.perf_counter() - t0) * 1000),
            "mode": settings.gateway_mode,
            "control_plane_mode": settings.control_plane_mode,
            "finops": finops_meta,
        }
    else:
        _STATS["cache_misses"] += 1
        if settings.gateway_mode != "stub":
            if settings.control_plane_mode == "strict":
                raise HTTPException(status_code=501, detail="BYOK providers not enabled yet")
        content, usage = stub_complete(body.model, messages)
        _STATS["stub_completions"] += 1
        _STATS["completions"] += 1
        await cache_store(
            tenant_id,
            body.model,
            messages,
            {"content": content, "usage": usage},
        )
        try:
            meter = await meter_usage(tenant_id=tenant_id, model=body.model, usage=usage)
            if meter is not None:
                _STATS["finops_meters"] += 1
                finops_meta["meter"] = {
                    "cost_usd": meter.get("cost_usd"),
                    "total_cost_usd": meter.get("total_cost_usd"),
                    "budget_usd": meter.get("budget_usd"),
                    "breached": bool(meter.get("breached")),
                }
        except FinOpsUnavailableError as exc:
            _STATS["finops_errors"] += 1
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "finops_unavailable",
                    "message": str(exc),
                    "control_plane_mode": "strict",
                },
            ) from exc
        gateway_meta = {
            "tenant_id": tenant_id,
            "cache_hit": False,
            "provider": "stub",
            "latency_ms": int((time.perf_counter() - t0) * 1000),
            "mode": settings.gateway_mode,
            "control_plane_mode": settings.control_plane_mode,
            "finops": finops_meta,
        }

    return ChatCompletionResponse(
        id=f"chatcmpl-{uuid.uuid4().hex[:12]}",
        model=body.model,
        choices=[
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        usage=usage,
        gateway=gateway_meta,
    )
