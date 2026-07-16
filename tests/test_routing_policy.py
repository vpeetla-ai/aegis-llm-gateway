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


def test_confidential_cloud_denied() -> None:
    r = client.post(
        "/v1/chat/completions",
        headers={
            "X-Tenant-Id": "demo",
            "X-Data-Class": "confidential",
            "X-Selected-Provider": "openai",
        },
        json={
            "model": "openai/gpt-4o",
            "messages": [{"role": "user", "content": "secret"}],
        },
    )
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "confidential_requires_private"


def test_confidential_ollama_allowed() -> None:
    r = client.post(
        "/v1/chat/completions",
        headers={
            "X-Tenant-Id": "demo",
            "X-Data-Class": "confidential",
            "X-Selected-Provider": "ollama",
            "X-Model-Tier": "local_private",
        },
        json={
            "model": "ollama/mistral",
            "messages": [{"role": "user", "content": "secret"}],
        },
    )
    assert r.status_code == 200
    assert r.json()["gateway"]["selected_provider"] == "ollama"


def test_verifier_same_provider_denied() -> None:
    r = client.post(
        "/v1/chat/completions",
        headers={
            "X-Tenant-Id": "vap",
            "X-Thesis-Role": "verifier",
            "X-Generator-Provider": "groq",
            "X-Selected-Provider": "groq",
        },
        json={
            "model": "groq/llama",
            "messages": [{"role": "user", "content": "check"}],
        },
    )
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "verifier_same_provider"


def test_verifier_different_provider_ok() -> None:
    r = client.post(
        "/v1/chat/completions",
        headers={
            "X-Tenant-Id": "vap",
            "X-Agent-Role": "critic",
            "X-Thesis-Role": "verifier",
            "X-Generator-Provider": "groq",
            "X-Selected-Provider": "gemini",
            "X-Workflow-Id": "wf-1",
        },
        json={
            "model": "gemini/flash",
            "messages": [{"role": "user", "content": "check"}],
        },
    )
    assert r.status_code == 200
    assert r.json()["gateway"]["thesis_role"] == "verifier"
    listed = client.get("/v1/ops/routing-decisions", params={"workflow_id": "wf-1"})
    assert listed.status_code == 200
    assert len(listed.json()["decisions"]) >= 1
