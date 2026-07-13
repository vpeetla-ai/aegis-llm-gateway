# Agent Instructions — aegis-llm-gateway

Stack layer: **LLM gateway plane** (ADR-028).
Do not implement tool authorization here — that stays in AegisAI.
Do not embed cache storage — call `aegis-semantic-cache`.
