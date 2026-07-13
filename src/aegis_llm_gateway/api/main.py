from __future__ import annotations

import time
import uuid
from collections import Counter

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from aegis_llm_gateway.cache_client import cache_lookup, cache_store
from aegis_llm_gateway.finops_client import meter_usage
from aegis_llm_gateway.models import ChatCompletionRequest, ChatCompletionResponse
from aegis_llm_gateway.settings import settings
from aegis_llm_gateway.stub_provider import stub_complete

app = FastAPI(title="aegis-llm-gateway", version="0.1.0")
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
    }


@app.get("/v1/ops/metrics")
def metrics() -> dict:
    return {
        "service": "aegis-llm-gateway",
        "completions": _STATS["completions"],
        "cache_hits": _STATS["cache_hits"],
        "cache_misses": _STATS["cache_misses"],
        "stub_completions": _STATS["stub_completions"],
    }


@app.post("/v1/chat/completions", response_model=ChatCompletionResponse)
async def chat_completions(
    body: ChatCompletionRequest,
    x_api_key: str | None = Header(default=None),
    x_tenant_id: str | None = Header(default=None),
) -> ChatCompletionResponse:
    _check_key(x_api_key)
    if body.stream:
        raise HTTPException(status_code=400, detail="streaming not supported in Block 1")

    tenant_id = (x_tenant_id or settings.default_tenant_id).strip() or settings.default_tenant_id
    messages = [m.model_dump() for m in body.messages]
    t0 = time.perf_counter()

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
        await meter_usage(tenant_id=tenant_id, model=body.model, usage=usage)
        gateway_meta = {
            "tenant_id": tenant_id,
            "cache_hit": False,
            "provider": "stub",
            "latency_ms": int((time.perf_counter() - t0) * 1000),
            "mode": settings.gateway_mode,
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
