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


settings = Settings()
