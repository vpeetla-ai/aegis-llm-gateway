# Deploy wiring — LLM plane + ADR-029

## Canonical Render URLs

| Service | URL |
|---------|-----|
| LLM gateway | `https://aegis-llm-gateway-api.onrender.com` |
| Semantic cache | `https://aegis-semantic-cache-api.onrender.com` |
| Agent FinOps | `https://agent-finops-api.onrender.com` |

Consumers should set:

```bash
LLM_GATEWAY_URL=https://aegis-llm-gateway-api.onrender.com/v1
LLM_GATEWAY_TENANT_ID=<vap|omniforge|ai-content-factory|domainforge-rag-peft|aegisai>
AGENTFINOPS_URL=https://agent-finops-api.onrender.com
```

AegisAI Control Room additionally:

```bash
LLM_GATEWAY_OPS_URL=https://aegis-llm-gateway-api.onrender.com/v1/ops/metrics
SEMANTIC_CACHE_OPS_URL=https://aegis-semantic-cache-api.onrender.com/v1/ops/metrics
AGENTFINOPS_API_URL=https://agent-finops-api.onrender.com
```

## Tenant identity

| Header | Purpose |
|--------|---------|
| `X-Tenant-Id` | Logical consumer / tenant namespace (required in practice) |
| `X-Principal-Id` | Optional human/service principal within the tenant |

Gateway settings:

| Env | Default | Meaning |
|-----|---------|---------|
| `ALLOWED_TENANT_IDS` | org known consumers | Comma allowlist |
| `TENANT_ENFORCEMENT` | `warn` | `off` / `warn` / `enforce` |
| `CONTROL_PLANE_MODE=strict` | — | Turns `warn` into hard deny for unknown tenants |
| `REQUIRE_PRINCIPAL` | false | Require `X-Principal-Id` when strict |

Ops: `GET /v1/ops/tenants`

## BYOK

Keep `GATEWAY_MODE=stub` on free tier without keys. For live:

1. Dashboard override `GATEWAY_MODE=byok`
2. Sync at least one of `GROQ_API_KEY` / `GOOGLE_API_KEY` / `OPENAI_API_KEY` / …

Honesty: this is logical multi-tenant isolation + optional principal — not a hard multi-tenant SLA claim.
