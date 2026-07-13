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
| control_plane_mode=strict | Fail-closed if required deps down |
| control_plane_mode=demo | Fail-open with warnings |

## Non-goals

- Tool HITL / OPA (AegisAI)
- In-process semantic cache (aegis-semantic-cache)
