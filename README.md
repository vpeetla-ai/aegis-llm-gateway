# Aegis LLM Gateway

<!-- vpeetla-tech-stack:start -->
[![Python 3.11](https://img.shields.io/badge/Python-3.11-3776AB?style=flat-square)]() [![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square)]() [![Render](https://img.shields.io/badge/Render-46E3B7?style=flat-square)]()
<!-- vpeetla-tech-stack:end -->
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Org](https://img.shields.io/badge/GitHub-vpeetla--ai-blue)](https://github.com/vpeetla-ai)

**Shared OpenAI-shaped LLM gateway** for the vpeetla-ai federated control plane — routing, quotas (next), stub/BYOK, hooks to semantic cache + FinOps.

> **Not AegisAI.** Tool governance stays in [aegisai-enterprise-agent-platform](https://github.com/vpeetla-ai/aegisai-enterprise-agent-platform). This repo owns model HTTP only.  
> ADR: [ADR-028](https://github.com/vpeetla-ai/ai-architecture-portfolio/blob/main/adr/ADR-028-federated-ai-control-plane-k8s-analogy.md) · Plan: [LLM_GATEWAY_PLANE.md](https://github.com/vpeetla-ai/ai-architecture-portfolio/blob/main/docs/plans/LLM_GATEWAY_PLANE.md)

## Implementation status (honest)

| Component | Status | Notes |
|-----------|--------|-------|
| `POST /v1/chat/completions` | ✅ | OpenAI-shaped stub responses |
| Tenant header | ✅ | `X-Tenant-Id` (logical isolation) |
| Semantic cache client | ✅ | Optional `SEMANTIC_CACHE_URL` |
| Stub-first mode | ✅ | Default; no paid keys |
| FinOps pre-check + meter | ✅ | `GET /v1/budget` then `POST /v1/usage` when URL set |
| Budget breach (strict) | ✅ | HTTP **402** if already breached |
| FinOps down (strict) | ✅ | HTTP **503** |
| Demo fail-open toggle | ✅ | `CONTROL_PLANE_MODE=demo` — documented in `/v1/posture` + `demo/` |
| BYOK live providers | ⬜ | Later block |
| Quotas RPM/TPM | ⬜ | Later block |
| Streaming | ⬜ | Rejected for now |

## Quick start

```bash
# terminal A — cache
cd ../aegis-semantic-cache && pip install -e ".[dev]" && uvicorn aegis_semantic_cache.api.main:app --port 8101

# terminal B — gateway
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
export SEMANTIC_CACHE_URL=http://127.0.0.1:8101
pytest -q
uvicorn aegis_llm_gateway.api.main:app --reload --port 8100
```

## Interview map

**Business function:** Shared LLM gateway plane — completions proxy with cache + metering hooks.

Staff+ prep crosswalk — [playbook](https://github.com/vpeetla-ai/ai-architect-interview-playbook) · [study UI](https://ai-architect-interview-playbook.vercel.app) · [Practice Arena](https://ai-architect-practice-arena.vercel.app) · [org matrix](https://github.com/vpeetla-ai/ai-architecture-portfolio/blob/main/docs/REPO_INTERVIEW_MAP.md). Only entries this repo honestly exercises.

| Category | Entry | Fit |
|----------|-------|-----|
| Cloud | [Enterprise LLM gateway + semantic cache](https://ai-architect-interview-playbook.vercel.app/q/cloud-architecture/07-llm-gateway-semantic-cache-model-router/) ([md](https://github.com/vpeetla-ai/ai-architect-interview-playbook/blob/main/cloud-architecture/07-llm-gateway-semantic-cache-model-router.md)) | Primary — gateway vs sidecar; FinOps pre-flight; stub/BYOK |
| Trade-offs | [Cost vs latency vs safety](https://ai-architect-interview-playbook.vercel.app/q/scalability-governance-tradeoffs/01-cost-vs-latency-vs-safety/) ([md](https://github.com/vpeetla-ai/ai-architect-interview-playbook/blob/main/scalability-governance-tradeoffs/01-cost-vs-latency-vs-safety.md)) | Strict vs demo fail-open; cache freshness |

## Related

- Cache: https://github.com/vpeetla-ai/aegis-semantic-cache
- FinOps: https://github.com/vpeetla-ai/agent-finops
- AegisAI: https://github.com/vpeetla-ai/aegisai-enterprise-agent-platform
