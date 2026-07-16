from __future__ import annotations

import time
import uuid
from collections import Counter

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from aegis_routing_contract import (
    InvalidRoutingHeader,
    ModelTier,
    RoutingDecisionV2,
    RoutingFactors,
    RoutingHeaders,
    enforce_routing_policy,
    map_agent_to_thesis_role,
    tier_for_bucket,
)

from aegis_llm_gateway.cache_client import cache_lookup, cache_store
from aegis_llm_gateway.decisions import clear_decisions, list_decisions, record_decision
from aegis_llm_gateway.finops_client import (
    BudgetBreachedError,
    FinOpsUnavailableError,
    assert_budget_allows,
    meter_usage,
)
from aegis_llm_gateway.models import ChatCompletionRequest, ChatCompletionResponse
from aegis_llm_gateway.provider_infer import infer_provider
from aegis_llm_gateway.settings import settings
from aegis_llm_gateway.byok_providers import ByokError, byok_complete, configured_providers
from aegis_llm_gateway.stub_provider import stub_complete
from aegis_llm_gateway.tenants import check_tenant

app = FastAPI(title="aegis-llm-gateway", version="0.3.0")
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
        "routing_contract": "aegis-routing-contract",
        "selection_sor": "app",
        "plane_role": "enforce_and_record",
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
            "byok_failure": "HTTP 502" if strict else "fall back to stub with byok_fallback note",
            "routing_policy_deny": "HTTP 403 (always — selection stays app-owned)",
            "unknown_tenant": (
                "HTTP 403 when TENANT_ENFORCEMENT=enforce or CONTROL_PLANE_MODE=strict"
            ),
        },
        "honesty": (
            "Architecture is fail-closed capable; demo mode is an explicit toggle "
            "for free-tier portfolio demos — never silent. "
            "Gateway enforces+records RoutingDecision; apps select models (ADR-029)."
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
        "routing_denies": _STATS["routing_denies"],
        "routing_decisions_recorded": _STATS["routing_decisions_recorded"],
        "byok_completions": _STATS["byok_completions"],
        "byok_fallbacks": _STATS["byok_fallbacks"],
        "control_plane_mode": settings.control_plane_mode,
    }


@app.get("/v1/ops/tenants")
def list_tenants() -> dict:
    return {
        "service": "aegis-llm-gateway",
        "tenant_enforcement": settings.tenant_enforcement,
        "enforce_active": settings.tenant_enforce_enabled(),
        "require_principal": settings.require_principal,
        "allowed_tenants": sorted(settings.allowed_tenant_set()),
        "default_tenant_id": settings.default_tenant_id,
        "honesty": (
            "Logical multi-tenant isolation via X-Tenant-Id (+ optional X-Principal-Id). "
            "Not a hard multi-tenant SLA claim."
        ),
    }


@app.get("/v1/ops/routing-decisions")
def routing_decisions(
    tenant_id: str | None = None,
    workflow_id: str | None = None,
    limit: int = 50,
) -> dict:
    return {
        "service": "aegis-llm-gateway",
        "selection_sor": "app",
        "plane_role": "enforce_and_record",
        "decisions": list_decisions(
            tenant_id=tenant_id, workflow_id=workflow_id, limit=limit
        ),
    }


@app.post("/v1/chat/completions", response_model=ChatCompletionResponse)
async def chat_completions(
    body: ChatCompletionRequest,
    x_api_key: str | None = Header(default=None),
    x_tenant_id: str | None = Header(default=None),
    x_agent_role: str | None = Header(default=None),
    x_thesis_role: str | None = Header(default=None),
    x_data_class: str | None = Header(default=None),
    x_workflow_id: str | None = Header(default=None),
    x_step_id: str | None = Header(default=None),
    x_generator_provider: str | None = Header(default=None),
    x_routing_decision: str | None = Header(default=None),
    x_identity_principal: str | None = Header(default=None),
    x_selected_provider: str | None = Header(default=None),
    x_model_tier: str | None = Header(default=None),
    x_cache_bypass: str | None = Header(default=None),
    x_principal_id: str | None = Header(default=None),
) -> ChatCompletionResponse:
    _check_key(x_api_key)
    if body.stream:
        raise HTTPException(status_code=400, detail="streaming not supported yet")

    try:
        headers = RoutingHeaders.from_http(
            x_tenant_id=x_tenant_id,
            x_agent_role=x_agent_role,
            x_thesis_role=x_thesis_role,
            x_data_class=x_data_class,
            x_workflow_id=x_workflow_id,
            x_step_id=x_step_id,
            x_generator_provider=x_generator_provider,
            x_routing_decision=x_routing_decision,
            x_identity_principal=x_identity_principal,
            x_principal_id=x_principal_id,
            default_tenant=settings.default_tenant_id,
        )
    except InvalidRoutingHeader as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_routing_header", "message": str(exc)},
        ) from exc
    tenant_id = headers.tenant_id
    principal_id = headers.principal_id or x_principal_id
    tenant_deny = check_tenant(
        settings, tenant_id=tenant_id, principal_id=principal_id
    )
    if tenant_deny is not None:
        _STATS["tenant_denies"] += 1
        raise HTTPException(
            status_code=tenant_deny.http_status,
            detail={
                "error": "tenant_policy_deny",
                "code": tenant_deny.code,
                "message": tenant_deny.message,
                "tenant_id": tenant_id,
            },
        )
    provider = infer_provider(
        body.model, x_selected_provider, gateway_mode=settings.gateway_mode
    )
    tier = tier_for_bucket(x_model_tier) if x_model_tier else (
        ModelTier.LOCAL_PRIVATE
        if provider in {"ollama", "vllm", "local"}
        else ModelTier.FAST
    )
    thesis = headers.thesis_role or map_agent_to_thesis_role(
        tenant_id, headers.agent_role
    )
    deny = enforce_routing_policy(
        headers,
        provider=provider,
        model_id=body.model,
        tier=tier,
        consumer=tenant_id,
        bypass_cache_requested=(x_cache_bypass or "").lower() in {"1", "true", "yes"},
    )
    if deny is not None:
        _STATS["routing_denies"] += 1
        decision = RoutingDecisionV2(
            tenant_id=tenant_id,
            workflow_id=headers.workflow_id,
            step_id=headers.step_id,
            factors=RoutingFactors(
                thesis_role=thesis,
                agent_role=headers.agent_role,
                data_class=headers.data_class,
                notes=[deny.message],
            ),
            tier=tier,
            provider=provider,
            model_id=body.model,
            reason="policy_deny",
            policy_allowed=False,
            policy_deny_code=deny.code,
            selected_by="app",
        )
        record_decision(decision.model_dump(mode="json"))
        _STATS["routing_decisions_recorded"] += 1
        raise HTTPException(
            status_code=deny.http_status,
            detail={
                "error": "routing_policy_deny",
                "code": deny.code,
                "message": deny.message,
                "decision_id": decision.decision_id,
                "selection_sor": "app",
                "plane_role": "enforce_and_record",
            },
        )

    messages = [m.model_dump() for m in body.messages]
    t0 = time.perf_counter()
    finops_meta: dict = {"configured": bool(settings.agentfinops_url)}
    bypass_cache = (x_cache_bypass or "").lower() in {"1", "true", "yes"}
    if thesis and thesis.value == "verifier":
        bypass_cache = True

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

    cached = None if bypass_cache else await cache_lookup(tenant_id, body.model, messages)
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
            "principal_id": principal_id,
            "cache_hit": True,
            "provider": "cache",
            "selected_provider": provider,
            "thesis_role": thesis.value if thesis else None,
            "agent_role": headers.agent_role,
            "data_class": headers.data_class.value,
            "tier": tier.value,
            "workflow_id": headers.workflow_id,
            "latency_ms": int((time.perf_counter() - t0) * 1000),
            "mode": settings.gateway_mode,
            "control_plane_mode": settings.control_plane_mode,
            "finops": finops_meta,
            "selection_sor": "app",
            "plane_role": "enforce_and_record",
        }
    else:
        _STATS["cache_misses"] += 1
        executed_provider = "stub"
        byok_error: str | None = None
        if settings.gateway_mode == "byok":
            try:
                content, usage, executed_provider = await byok_complete(
                    settings=settings,
                    provider=provider,
                    model=body.model,
                    messages=messages,
                )
                _STATS["byok_completions"] += 1
            except ByokError as exc:
                byok_error = f"{exc.provider}: {exc}"
                if settings.control_plane_mode == "strict":
                    raise HTTPException(
                        status_code=502,
                        detail={
                            "error": "byok_provider_failed",
                            "provider": exc.provider,
                            "message": str(exc),
                            "status": exc.status,
                        },
                    ) from exc
                # demo: fall back to stub with honesty
                content, usage = stub_complete(body.model, messages)
                executed_provider = "stub"
                _STATS["stub_completions"] += 1
                _STATS["byok_fallbacks"] += 1
        else:
            content, usage = stub_complete(body.model, messages)
            _STATS["stub_completions"] += 1
        _STATS["completions"] += 1
        if not bypass_cache:
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
            "principal_id": principal_id,
            "cache_hit": False,
            "provider": executed_provider,
            "selected_provider": provider,
            "thesis_role": thesis.value if thesis else None,
            "agent_role": headers.agent_role,
            "data_class": headers.data_class.value,
            "tier": tier.value,
            "workflow_id": headers.workflow_id,
            "latency_ms": int((time.perf_counter() - t0) * 1000),
            "mode": settings.gateway_mode,
            "control_plane_mode": settings.control_plane_mode,
            "finops": finops_meta,
            "selection_sor": "app",
            "plane_role": "enforce_and_record",
            "cache_bypassed": bypass_cache,
        }
        if byok_error:
            gateway_meta["byok_fallback"] = byok_error

    cost = float((finops_meta.get("meter") or {}).get("cost_usd") or 0.0)
    decision = RoutingDecisionV2(
        tenant_id=tenant_id,
        workflow_id=headers.workflow_id,
        step_id=headers.step_id,
        factors=RoutingFactors(
            thesis_role=thesis,
            agent_role=headers.agent_role,
            data_class=headers.data_class,
            notes=["app_selected", "gateway_enforced"],
        ),
        tier=tier,
        provider=provider,
        model_id=body.model,
        reason="app_selected_gateway_allowed",
        cost_usd=cost,
        latency_ms=float(gateway_meta.get("latency_ms") or 0),
        cache_bypassed=bypass_cache or bool(gateway_meta.get("cache_hit") is False and thesis and thesis.value == "verifier"),
        policy_allowed=True,
        selected_by="app",
    )
    record_decision(decision.model_dump(mode="json"))
    _STATS["routing_decisions_recorded"] += 1
    gateway_meta["decision_id"] = decision.decision_id

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


# test helper export
__all__ = ["app", "_STATS", "clear_decisions"]
