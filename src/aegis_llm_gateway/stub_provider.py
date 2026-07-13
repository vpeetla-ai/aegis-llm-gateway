from __future__ import annotations

import hashlib


def stub_complete(model: str, messages: list[dict]) -> tuple[str, dict]:
    last = ""
    for m in messages:
        if m.get("role") == "user":
            last = str(m.get("content", ""))
    digest = hashlib.sha256(f"{model}:{last}".encode()).hexdigest()[:8]
    text = f"[stub:{model}] Deterministic reply for: {last[:120]} ({digest})"
    usage = {
        "prompt_tokens": max(1, len(last) // 4),
        "completion_tokens": max(1, len(text) // 4),
        "total_tokens": max(2, (len(last) + len(text)) // 4),
    }
    return text, usage
