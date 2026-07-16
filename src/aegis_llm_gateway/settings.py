from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gateway_mode: str = "stub"  # stub | byok
    # demo = fail-open when FinOps/cache deps error; strict = fail-closed
    control_plane_mode: str = "demo"
    semantic_cache_url: str | None = None
    agentfinops_url: str | None = None
    agentfinops_api_key: str | None = None
    gateway_api_key: str | None = None
    default_tenant_id: str = "demo"

    # Tenant identity hardening (ADR-026 / ADR-029)
    # Comma-separated allowlist; empty = use KNOWN_CONSUMER_TENANTS defaults
    allowed_tenant_ids: str = ""
    # off | warn | enforce — enforce always in CONTROL_PLANE_MODE=strict unless off
    tenant_enforcement: str = "warn"
    require_principal: bool = False

    # BYOK / free-tier keys (optional; gateway_mode=byok uses these)
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    groq_api_key: str | None = None
    cerebras_api_key: str | None = None
    google_api_key: str | None = None
    gemini_api_key: str | None = None
    ollama_base_url: str | None = "http://127.0.0.1:11434"
    ollama_api_key: str | None = None
    vllm_base_url: str | None = None
    vllm_api_key: str | None = None

    def allowed_tenant_set(self) -> set[str]:
        from aegis_routing_contract import KNOWN_CONSUMER_TENANTS

        raw = (self.allowed_tenant_ids or "").strip()
        if not raw:
            return set(KNOWN_CONSUMER_TENANTS)
        return {t.strip().lower() for t in raw.split(",") if t.strip()}

    def tenant_enforce_enabled(self) -> bool:
        mode = (self.tenant_enforcement or "warn").strip().lower()
        if mode == "off":
            return False
        if mode == "enforce":
            return True
        # warn: only hard-enforce in strict control plane
        return self.control_plane_mode == "strict"


settings = Settings()
