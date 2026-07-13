# Architecture — aegis-llm-gateway

OpenAI-shaped LLM proxy for the federated control plane.

```text
Client → /v1/chat/completions
       → resolve tenant
       → semantic-cache lookup
       → stub | BYOK provider
       → cache store on miss
       → optional FinOps meter
```

## Modes

| Mode | Behavior |
|------|----------|
| stub (default) | Deterministic completion; no paid keys |
| byok | Live providers when keys present (later block) |
| control_plane_mode=strict | Fail-closed: FinOps down → 503; budget breached → 402 |
| control_plane_mode=demo | Fail-open with warnings in `gateway.finops` (explicit toggle) |

## FinOps flow (Block 2)

1. Optional pre-check `GET {AGENTFINOPS_URL}/v1/budget/tenant/{tenant}`
2. Cache lookup → stub/BYOK completion on miss
3. Meter `POST /v1/usage` with `X-API-Key` when configured
4. Annotate response `gateway.finops` (precheck + meter)

See also `GET /v1/posture` for machine-readable honesty.

## Non-goals

- Tool HITL / OPA (AegisAI)
- In-process semantic cache (aegis-semantic-cache)
