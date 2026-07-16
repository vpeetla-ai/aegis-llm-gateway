import respx
from fastapi.testclient import TestClient
from httpx import Response

from aegis_llm_gateway.api import main as gw_main
from aegis_llm_gateway.settings import settings


client = TestClient(gw_main.app)


def setup_function() -> None:
    gw_main._STATS.clear()
    settings.semantic_cache_url = None
    settings.agentfinops_url = None
    settings.agentfinops_api_key = None
    settings.gateway_mode = "stub"
    settings.control_plane_mode = "demo"
    settings.tenant_enforcement = "off"
    settings.require_principal = False


def test_health() -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["service"] == "aegis-llm-gateway"
    assert "posture" in r.json()


def test_posture_documents_demo_fail_open() -> None:
    settings.control_plane_mode = "demo"
    settings.tenant_enforcement = "off"
    settings.require_principal = False
    r = client.get("/v1/posture")
    assert r.status_code == 200
    body = r.json()
    assert body["posture"] == "fail-open"
    assert "continue" in body["behavior"]["finops_unavailable"]


def test_stub_completion() -> None:
    r = client.post(
        "/v1/chat/completions",
        headers={"X-Tenant-Id": "t1"},
        json={
            "model": "stub-small",
            "messages": [{"role": "user", "content": "Calculate 42 * 7"}],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["choices"][0]["message"]["content"].startswith("[stub:stub-small]")
    assert body["gateway"]["cache_hit"] is False
    assert body["gateway"]["tenant_id"] == "t1"


@respx.mock
def test_cache_hit_path() -> None:
    settings.semantic_cache_url = "http://cache.test"
    respx.post("http://cache.test/v1/cache/lookup").mock(
        return_value=Response(
            200,
            json={
                "hit": True,
                "score": 0.99,
                "response": {
                    "content": "cached answer",
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                },
            },
        )
    )
    r = client.post(
        "/v1/chat/completions",
        headers={"X-Tenant-Id": "t1"},
        json={
            "model": "stub-small",
            "messages": [{"role": "user", "content": "hello"}],
        },
    )
    assert r.status_code == 200
    assert r.json()["choices"][0]["message"]["content"] == "cached answer"
    assert r.json()["gateway"]["cache_hit"] is True


@respx.mock
def test_finops_meter_on_miss() -> None:
    settings.agentfinops_url = "http://finops.test"
    settings.agentfinops_api_key = "secret"
    respx.get("http://finops.test/v1/budget/tenant/t1").mock(
        return_value=Response(
            200,
            json={
                "scope_type": "tenant",
                "scope_value": "t1",
                "budget_usd": 10.0,
                "total_cost_usd": 0.01,
                "breached": False,
            },
        )
    )
    meter = respx.post("http://finops.test/v1/usage").mock(
        return_value=Response(
            200,
            json={
                "cost_usd": 0.001,
                "total_cost_usd": 0.011,
                "budget_usd": 10.0,
                "breached": False,
            },
        )
    )
    r = client.post(
        "/v1/chat/completions",
        headers={"X-Tenant-Id": "t1"},
        json={
            "model": "stub-small",
            "messages": [{"role": "user", "content": "meter me"}],
        },
    )
    assert r.status_code == 200
    assert meter.called
    assert r.json()["gateway"]["finops"]["meter"]["breached"] is False
    assert meter.calls[0].request.headers.get("x-api-key") == "secret"


@respx.mock
def test_strict_blocks_when_budget_breached() -> None:
    settings.control_plane_mode = "strict"
    settings.agentfinops_url = "http://finops.test"
    respx.get("http://finops.test/v1/budget/tenant/broke").mock(
        return_value=Response(
            200,
            json={
                "scope_type": "tenant",
                "scope_value": "broke",
                "budget_usd": 0.01,
                "total_cost_usd": 1.0,
                "breached": True,
            },
        )
    )
    r = client.post(
        "/v1/chat/completions",
        headers={"X-Tenant-Id": "broke"},
        json={
            "model": "stub-small",
            "messages": [{"role": "user", "content": "should block"}],
        },
    )
    assert r.status_code == 402
    assert r.json()["detail"]["error"] == "budget_breached"


@respx.mock
def test_demo_allows_when_budget_breached() -> None:
    settings.control_plane_mode = "demo"
    settings.tenant_enforcement = "off"
    settings.require_principal = False
    settings.agentfinops_url = "http://finops.test"
    respx.get("http://finops.test/v1/budget/tenant/broke").mock(
        return_value=Response(
            200,
            json={
                "scope_type": "tenant",
                "scope_value": "broke",
                "budget_usd": 0.01,
                "total_cost_usd": 1.0,
                "breached": True,
            },
        )
    )
    respx.post("http://finops.test/v1/usage").mock(
        return_value=Response(
            200,
            json={
                "cost_usd": 0.001,
                "total_cost_usd": 1.001,
                "budget_usd": 0.01,
                "breached": True,
            },
        )
    )
    r = client.post(
        "/v1/chat/completions",
        headers={"X-Tenant-Id": "broke"},
        json={
            "model": "stub-small",
            "messages": [{"role": "user", "content": "demo allows"}],
        },
    )
    assert r.status_code == 200
    assert r.json()["gateway"]["finops"]["precheck"]["breached"] is True


@respx.mock
def test_strict_finops_down_returns_503() -> None:
    settings.control_plane_mode = "strict"
    settings.agentfinops_url = "http://finops.test"
    respx.get("http://finops.test/v1/budget/tenant/t1").mock(return_value=Response(500))
    r = client.post(
        "/v1/chat/completions",
        headers={"X-Tenant-Id": "t1"},
        json={
            "model": "stub-small",
            "messages": [{"role": "user", "content": "strict"}],
        },
    )
    assert r.status_code == 503
    assert r.json()["detail"]["error"] == "finops_unavailable"
