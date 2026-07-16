"""Infer selected provider from header or model id — apps still select."""

from __future__ import annotations

_PREFIXES = (
    ("ollama/", "ollama"),
    ("vllm/", "vllm"),
    ("local/", "local"),
    ("openai/", "openai"),
    ("anthropic/", "anthropic"),
    ("groq/", "groq"),
    ("gemini/", "gemini"),
    ("google/", "gemini"),
    ("cerebras/", "cerebras"),
    ("openrouter/", "openrouter"),
    ("stub/", "stub"),
)


def infer_provider(model: str, x_selected_provider: str | None = None, *, gateway_mode: str = "stub") -> str:
    if x_selected_provider and x_selected_provider.strip():
        return x_selected_provider.strip().lower()
    m = (model or "").strip().lower()
    for prefix, provider in _PREFIXES:
        if m.startswith(prefix):
            return provider
    if gateway_mode == "stub":
        return "stub"
    return "unknown"
