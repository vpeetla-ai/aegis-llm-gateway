from fastapi.testclient import TestClient

from aegis_llm_gateway.api import main as gw_main
from aegis_llm_gateway.decisions import clear_decisions
from aegis_llm_gateway.settings import settings

client = TestClient(gw_main.app)


def setup_function() -> None:
    gw_main._STATS.clear()
    clear_decisions()
    settings.semantic_cache_url = None
    settings.agentfinops_url = None
    settings.gateway_mode = "stub"
    settings.control_plane_mode = "demo"
    settings.tenant_enforcement = "warn"
    settings.require_principal = False
    settings.allowed_tenant_ids = ""


def test_ops_tenants_lists_allowlist() -> None:
    r = client.get("/v1/ops/tenants")
    assert r.status_code == 200
    body = r.json()
    assert "omniforge" in body["allowed_tenants"]
    assert body["tenant_enforcement"] == "warn"


def test_strict_unknown_tenant_denied() -> None:
    settings.control_plane_mode = "strict"
    settings.tenant_enforcement = "warn"  # still enforces under strict
    r = client.post(
        "/v1/chat/completions",
        headers={"X-Tenant-Id": "evil-corp", "X-Selected-Provider": "stub"},
        json={"model": "stub-small", "messages": [{"role": "user", "content": "x"}]},
    )
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "unknown_tenant"


def test_demo_unknown_tenant_allowed_with_warn_mode() -> None:
    settings.control_plane_mode = "demo"
    settings.tenant_enforcement = "warn"
    r = client.post(
        "/v1/chat/completions",
        headers={"X-Tenant-Id": "evil-corp", "X-Selected-Provider": "stub"},
        json={"model": "stub-small", "messages": [{"role": "user", "content": "x"}]},
    )
    assert r.status_code == 200


def test_enforce_mode_denies_even_in_demo() -> None:
    settings.control_plane_mode = "demo"
    settings.tenant_enforcement = "enforce"
    r = client.post(
        "/v1/chat/completions",
        headers={"X-Tenant-Id": "not-registered", "X-Selected-Provider": "stub"},
        json={"model": "stub-small", "messages": [{"role": "user", "content": "x"}]},
    )
    assert r.status_code == 403


def test_known_tenant_with_principal() -> None:
    r = client.post(
        "/v1/chat/completions",
        headers={
            "X-Tenant-Id": "omniforge",
            "X-Principal-Id": "user-42",
            "X-Selected-Provider": "stub",
        },
        json={"model": "stub-small", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert r.status_code == 200
    assert r.json()["gateway"]["principal_id"] == "user-42"
    assert r.json()["gateway"]["tenant_id"] == "omniforge"
