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
    settings.gateway_mode = "stub"
    settings.control_plane_mode = "demo"


def test_health() -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["service"] == "aegis-llm-gateway"


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
