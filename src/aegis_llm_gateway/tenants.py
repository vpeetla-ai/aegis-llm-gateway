"""Gateway tenant enforcement wrappers."""

from __future__ import annotations

from aegis_routing_contract import TenantDeny, enforce_tenant_identity

from aegis_llm_gateway.settings import Settings


def check_tenant(
    settings: Settings,
    *,
    tenant_id: str,
    principal_id: str | None,
) -> TenantDeny | None:
    return enforce_tenant_identity(
        tenant_id=tenant_id,
        allowed_tenants=settings.allowed_tenant_set(),
        enforce=settings.tenant_enforce_enabled(),
        principal_id=principal_id,
        require_principal=bool(settings.require_principal)
        and settings.control_plane_mode == "strict",
    )
