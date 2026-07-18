# Aegis LLM Gateway

<!-- vpeetla-tech-stack:start -->
[![Python 3.11](https://img.shields.io/badge/Python-3.11-3776AB?style=flat-square)]() [![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square)]() [![Render](https://img.shields.io/badge/Render-46E3B7?style=flat-square)]()
<!-- vpeetla-tech-stack:end -->
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Org](https://img.shields.io/badge/GitHub-vpeetla--ai-blue)](https://github.com/vpeetla-ai)
[![API](https://img.shields.io/badge/API-Render-blue)](https://aegis-llm-gateway-api.onrender.com/health)

**Shared OpenAI-shaped LLM gateway** for the vpeetla-ai federated control plane — apps **select** models; this plane **enforces + records** role-aware decisions, with hooks to semantic cache + FinOps.

> **Not AegisAI.** Tool governance stays in [aegisai-enterprise-agent-platform](https://github.com/vpeetla-ai/aegisai-enterprise-agent-platform). This repo owns model HTTP only.  
> ADRs: [ADR-028](https://github.com/vpeetla-ai/ai-architecture-portfolio/blob/main/adr/ADR-028-federated-ai-control-plane-k8s-analogy.md) · [ADR-029](https://github.com/vpeetla-ai/ai-architecture-portfolio/blob/main/adr/ADR-029-app-owned-role-aware-routing-contract.md) · Plan: [LLM_GATEWAY_PLANE.md](https://github.com/vpeetla-ai/ai-architecture-portfolio/blob/main/docs/plans/LLM_GATEWAY_PLANE.md)

**Live:** [aegis-llm-gateway-api.onrender.com](https://aegis-llm-gateway-api.onrender.com/health)

> **Default is not production.** Render ships `GATEWAY_MODE=stub` + `CONTROL_PLANE_MODE=demo` (fail-open). Machine truth: [`GET /v1/posture`](https://aegis-llm-gateway-api.onrender.com/v1/posture). BYOK / strict are explicit overrides — never silent.

## Implementation status (honest)

| Component | Status | Notes |
|-----------|--------|-------|
| `POST /v1/chat/completions` | ✅ | OpenAI-shaped; stub default, BYOK when keys + mode set |
| Role-aware enforce + record | ✅ | ADR-029 via [aegis-routing-contract](https://github.com/vpeetla-ai/aegis-routing-contract) |
| Routing audit | ✅ | `GET /v1/ops/routing-decisions` |
| Tenant allowlist | ✅ | `X-Tenant-Id` + optional `X-Principal-Id`; `TENANT_ENFORCEMENT=warn\|enforce` |
| Ops tenants | ✅ | `GET /v1/ops/tenants` |
| Semantic cache client | ✅ | Optional `SEMANTIC_CACHE_URL` |
| Stub-first mode | ✅ | Default on Render free tier; no paid keys |
| FinOps pre-check + meter | ✅ | Budget then usage when `AGENTFINOPS_URL` set |
| Budget breach (strict) | ✅ | HTTP **402** if already breached |
| FinOps down (strict) | ✅ | HTTP **503** |
| Demo fail-open toggle | ✅ | `CONTROL_PLANE_MODE=demo` — `/v1/posture` |
| BYOK live providers | ✅ | OpenAI / Anthropic / Groq / Cerebras / Gemini / Ollama / vLLM |
| Quotas RPM/TPM | ⬜ | Later block |
| Streaming | ⬜ | Rejected for now |

## Role-aware enforce + record (ADR-029)

Apps **select** models. This gateway **enforces** policy and **records** `RoutingDecision`:

- Headers: `X-Agent-Role`, `X-Thesis-Role`, `X-Data-Class`, `X-Selected-Provider`, `X-Generator-Provider`, `X-Model-Tier`, …
- Denies: `confidential→cloud`, `verifier.provider == generator.provider`
- Audit: `GET /v1/ops/routing-decisions`
- Wiring: [docs/DEPLOY_WIRING.md](docs/DEPLOY_WIRING.md)

```text
Client → tenant check → enforce RoutingHeaders → cache lookup
      → stub | BYOK → FinOps meter → record RoutingDecisionV2
```

## Quick start

```bash
# terminal A — cache
cd ../aegis-semantic-cache && pip install -e ".[dev]" && uvicorn aegis_semantic_cache.api.main:app --port 8101

# terminal B — gateway
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"   # pulls aegis-routing-contract (git) or sibling path
export SEMANTIC_CACHE_URL=http://127.0.0.1:8101
pytest -q
uvicorn aegis_llm_gateway.api.main:app --reload --port 8100
```

## Interview map

**Business function:** Shared LLM gateway plane — completions proxy with enforce+record, cache + metering hooks.

Staff+ prep crosswalk — [playbook](https://github.com/vpeetla-ai/ai-architect-interview-playbook) · [study UI](https://ai-architect-interview-playbook.vercel.app) · [Practice Arena](https://ai-architect-practice-arena.vercel.app) · [org matrix](https://github.com/vpeetla-ai/ai-architecture-portfolio/blob/main/docs/REPO_INTERVIEW_MAP.md). Only entries this repo honestly exercises.

| Category | Entry | Fit |
|----------|-------|-----|
| Cloud | [Enterprise LLM gateway + semantic cache](https://ai-architect-interview-playbook.vercel.app/q/cloud-architecture/07-llm-gateway-semantic-cache-model-router/) ([md](https://github.com/vpeetla-ai/ai-architect-interview-playbook/blob/main/cloud-architecture/07-llm-gateway-semantic-cache-model-router.md)) | Primary — apps select vs plane enforce; FinOps pre-flight; stub/BYOK |
| Trade-offs | [Cost vs latency vs safety](https://ai-architect-interview-playbook.vercel.app/q/scalability-governance-tradeoffs/01-cost-vs-latency-vs-safety/) ([md](https://github.com/vpeetla-ai/ai-architect-interview-playbook/blob/main/scalability-governance-tradeoffs/01-cost-vs-latency-vs-safety.md)) | Strict vs demo fail-open; confidential→private |

## Related

- Contract: https://github.com/vpeetla-ai/aegis-routing-contract
- Cache: https://github.com/vpeetla-ai/aegis-semantic-cache
- FinOps: https://github.com/vpeetla-ai/agent-finops
- AegisAI: https://github.com/vpeetla-ai/aegisai-enterprise-agent-platform

## Live BYOK on Render

1. Set `GATEWAY_MODE=byok` (dashboard override; repo default remains `stub`).
2. Sync at least one free/BYOK key: `GROQ_API_KEY`, `GOOGLE_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or `CEREBRAS_API_KEY`.
3. Consumers send `X-Selected-Provider` + model; apps still select (ADR-029).
