"""In-memory routing decision audit (enforce+record plane)."""

from __future__ import annotations

from collections import deque
from threading import Lock
from typing import Any

_LOCK = Lock()
_DECISIONS: deque[dict[str, Any]] = deque(maxlen=2000)


def record_decision(payload: dict[str, Any]) -> dict[str, Any]:
    with _LOCK:
        _DECISIONS.appendleft(payload)
    return payload


def list_decisions(
    *,
    tenant_id: str | None = None,
    workflow_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    with _LOCK:
        items = list(_DECISIONS)
    if tenant_id:
        items = [d for d in items if d.get("tenant_id") == tenant_id]
    if workflow_id:
        items = [d for d in items if d.get("workflow_id") == workflow_id]
    return items[: max(1, min(limit, 200))]


def clear_decisions() -> None:
    with _LOCK:
        _DECISIONS.clear()
