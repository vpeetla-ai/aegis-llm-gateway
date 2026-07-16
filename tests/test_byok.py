import respx
from fastapi.testclient import TestClient
from httpx import Response

from aegis_llm_gateway.api import main as gw_main
from aegis_llm_gateway.decisions import clear_decisions
from aegis_llm_gateway.settings import settings

client = TestClient(gw_main.app)


def setup_function() -> None:
    gw_main._STATS.clear()
    clear_decisions()
    settings.semantic_cache_url = None
    settings.agentfinops_url = None
    settings.gateway_mode = "byok"
    settings.control_plane_mode = "demo"
    settings.tenant_enforcement = "off"
    settings.require_principal = False
    settings.openai_api_key = "sk-test"
    settings.groq_api_key = None
    settings.anthropic_api_key = None
    settings.google_api_key = None
    settings.gemini_api_key = None


@respx.mock
def test_byok_openai_success() -> None:
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": "hello from openai"}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
            },
        )
    )
    r = client.post(
        "/v1/chat/completions",
        headers={
            "X-Tenant-Id": "t1",
            "X-Selected-Provider": "openai",
            "X-Data-Class": "internal",
        },
        json={
            "model": "openai/gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["choices"][0]["message"]["content"] == "hello from openai"
    assert body["gateway"]["provider"] == "openai"
    assert body["gateway"]["mode"] == "byok"


@respx.mock
def test_byok_demo_falls_back_to_stub() -> None:
    settings.control_plane_mode = "demo"
    settings.tenant_enforcement = "off"
    settings.require_principal = False
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=Response(500, text="boom")
    )
    r = client.post(
        "/v1/chat/completions",
        headers={"X-Tenant-Id": "t1", "X-Selected-Provider": "openai"},
        json={"model": "openai/gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert r.status_code == 200
    assert r.json()["gateway"]["provider"] == "stub"
    assert "byok_fallback" in r.json()["gateway"]


@respx.mock
def test_byok_strict_returns_502() -> None:
    settings.control_plane_mode = "strict"
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=Response(500, text="boom")
    )
    r = client.post(
        "/v1/chat/completions",
        headers={"X-Tenant-Id": "t1", "X-Selected-Provider": "openai"},
        json={"model": "openai/gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert r.status_code == 502
    assert r.json()["detail"]["error"] == "byok_provider_failed"
