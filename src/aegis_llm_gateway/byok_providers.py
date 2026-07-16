"""BYOK / free-tier provider completions — apps select model; gateway executes.

Uses httpx only (no SDK lock-in). Supports OpenAI-compatible APIs (OpenAI, Groq,
Cerebras, Gemini OpenAI-compat) and Anthropic Messages API.
"""

from __future__ import annotations

from typing import Any

import httpx

from aegis_llm_gateway.settings import Settings


class ByokError(Exception):
    def __init__(self, provider: str, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.provider = provider
        self.status = status


def _strip_prefix(model: str) -> str:
    m = (model or "").strip()
    if "/" in m:
        return m.split("/", 1)[1]
    return m


def _normalize_messages(messages: list[dict]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for m in messages:
        role = str(m.get("role") or "user")
        content = m.get("content")
        if isinstance(content, list):
            # flatten multimodal to text for providers without vision path here
            parts = []
            for p in content:
                if isinstance(p, dict) and p.get("type") == "text":
                    parts.append(str(p.get("text") or ""))
                elif isinstance(p, str):
                    parts.append(p)
            content = "\n".join(parts)
        out.append({"role": role, "content": str(content or "")})
    return out


def _usage_from_openai(data: dict[str, Any]) -> dict[str, int]:
    u = data.get("usage") or {}
    pt = int(u.get("prompt_tokens") or u.get("input_tokens") or 0)
    ct = int(u.get("completion_tokens") or u.get("output_tokens") or 0)
    return {
        "prompt_tokens": max(0, pt),
        "completion_tokens": max(0, ct),
        "total_tokens": max(0, int(u.get("total_tokens") or (pt + ct))),
    }


async def _openai_compatible(
    *,
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict],
    provider: str,
    timeout: float = 60.0,
) -> tuple[str, dict]:
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": _strip_prefix(model),
        "messages": _normalize_messages(messages),
        "temperature": 0.2,
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, headers=headers, json=payload)
    if resp.status_code >= 400:
        raise ByokError(provider, resp.text[:300], resp.status_code)
    data = resp.json()
    content = data["choices"][0]["message"]["content"] or ""
    return content, _usage_from_openai(data)


async def _anthropic(
    *,
    api_key: str,
    model: str,
    messages: list[dict],
    timeout: float = 60.0,
) -> tuple[str, dict]:
    url = "https://api.anthropic.com/v1/messages"
    norm = _normalize_messages(messages)
    system = ""
    chat: list[dict[str, str]] = []
    for m in norm:
        if m["role"] == "system":
            system = (system + "\n" + m["content"]).strip()
        else:
            role = "assistant" if m["role"] == "assistant" else "user"
            chat.append({"role": role, "content": m["content"]})
    if not chat:
        chat = [{"role": "user", "content": " "}]
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "model": _strip_prefix(model),
        "max_tokens": 1024,
        "messages": chat,
    }
    if system:
        payload["system"] = system
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, headers=headers, json=payload)
    if resp.status_code >= 400:
        raise ByokError("anthropic", resp.text[:300], resp.status_code)
    data = resp.json()
    blocks = data.get("content") or []
    text = "".join(b.get("text", "") for b in blocks if isinstance(b, dict))
    usage = data.get("usage") or {}
    pt = int(usage.get("input_tokens") or 0)
    ct = int(usage.get("output_tokens") or 0)
    return text, {
        "prompt_tokens": pt,
        "completion_tokens": ct,
        "total_tokens": pt + ct,
    }


async def _gemini(
    *,
    api_key: str,
    model: str,
    messages: list[dict],
    timeout: float = 60.0,
) -> tuple[str, dict]:
    mid = _strip_prefix(model)
    # Accept gemini-2.0-flash style ids
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{mid}:generateContent"
        f"?key={api_key}"
    )
    norm = _normalize_messages(messages)
    system = ""
    contents = []
    for m in norm:
        if m["role"] == "system":
            system = (system + "\n" + m["content"]).strip()
            continue
        role = "model" if m["role"] == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": m["content"]}]})
    if not contents:
        contents = [{"role": "user", "parts": [{"text": " "}]}]
    payload: dict[str, Any] = {"contents": contents}
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, json=payload)
    if resp.status_code >= 400:
        raise ByokError("gemini", resp.text[:300], resp.status_code)
    data = resp.json()
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ByokError("gemini", f"unexpected response: {str(data)[:200]}") from exc
    meta = data.get("usageMetadata") or {}
    pt = int(meta.get("promptTokenCount") or 0)
    ct = int(meta.get("candidatesTokenCount") or 0)
    return text, {
        "prompt_tokens": pt,
        "completion_tokens": ct,
        "total_tokens": pt + ct,
    }


def resolve_provider_for_model(model: str, selected: str | None) -> str:
    if selected and selected.strip():
        return selected.strip().lower()
    m = (model or "").lower()
    for p in ("openai", "anthropic", "groq", "cerebras", "gemini", "google", "ollama", "vllm"):
        if m.startswith(p + "/") or m.startswith(p + "-"):
            return "gemini" if p == "google" else p
    return "openai"


async def byok_complete(
    *,
    settings: Settings,
    provider: str,
    model: str,
    messages: list[dict],
) -> tuple[str, dict, str]:
    """Return (content, usage, executed_provider). Raises ByokError on failure."""
    p = (provider or "").strip().lower()
    if p in {"stub", "mock", "cache"}:
        raise ByokError(p, "not a live BYOK provider")

    if p == "openai":
        key = settings.openai_api_key
        if not key:
            raise ByokError("openai", "OPENAI_API_KEY not configured")
        text, usage = await _openai_compatible(
            base_url="https://api.openai.com/v1",
            api_key=key,
            model=model,
            messages=messages,
            provider="openai",
        )
        return text, usage, "openai"

    if p == "groq":
        key = settings.groq_api_key
        if not key:
            raise ByokError("groq", "GROQ_API_KEY not configured")
        text, usage = await _openai_compatible(
            base_url="https://api.groq.com/openai/v1",
            api_key=key,
            model=model,
            messages=messages,
            provider="groq",
        )
        return text, usage, "groq"

    if p == "cerebras":
        key = settings.cerebras_api_key
        if not key:
            raise ByokError("cerebras", "CEREBRAS_API_KEY not configured")
        text, usage = await _openai_compatible(
            base_url="https://api.cerebras.ai/v1",
            api_key=key,
            model=model,
            messages=messages,
            provider="cerebras",
        )
        return text, usage, "cerebras"

    if p == "anthropic":
        key = settings.anthropic_api_key
        if not key:
            raise ByokError("anthropic", "ANTHROPIC_API_KEY not configured")
        text, usage = await _anthropic(api_key=key, model=model, messages=messages)
        return text, usage, "anthropic"

    if p in {"gemini", "google"}:
        key = settings.google_api_key or settings.gemini_api_key
        if not key:
            raise ByokError("gemini", "GOOGLE_API_KEY / GEMINI_API_KEY not configured")
        text, usage = await _gemini(api_key=key, model=model, messages=messages)
        return text, usage, "gemini"

    if p in {"ollama", "local", "local_private"}:
        base = (settings.ollama_base_url or "http://127.0.0.1:11434").rstrip("/")
        # Ollama OpenAI-compatible
        text, usage = await _openai_compatible(
            base_url=f"{base}/v1",
            api_key=settings.ollama_api_key or "ollama",
            model=model,
            messages=messages,
            provider="ollama",
        )
        return text, usage, "ollama"

    if p == "vllm":
        base = (settings.vllm_base_url or "").rstrip("/")
        if not base:
            raise ByokError("vllm", "VLLM_BASE_URL not configured")
        text, usage = await _openai_compatible(
            base_url=base if base.endswith("/v1") else f"{base}/v1",
            api_key=settings.vllm_api_key or "vllm",
            model=model,
            messages=messages,
            provider="vllm",
        )
        return text, usage, "vllm"

    raise ByokError(p, f"unsupported provider: {p}")


def configured_providers(settings: Settings) -> list[str]:
    out = []
    if settings.openai_api_key:
        out.append("openai")
    if settings.anthropic_api_key:
        out.append("anthropic")
    if settings.groq_api_key:
        out.append("groq")
    if settings.cerebras_api_key:
        out.append("cerebras")
    if settings.google_api_key or settings.gemini_api_key:
        out.append("gemini")
    if settings.ollama_base_url:
        out.append("ollama")
    if settings.vllm_base_url:
        out.append("vllm")
    return out
