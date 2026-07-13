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


settings = Settings()
