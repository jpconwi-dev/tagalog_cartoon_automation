from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

PROVIDERS = ("cloudflare", "gemini", "huggingface", "grok", "local", "template")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    api_key: str = ""
    database_url: str = "sqlite:///./data/app.db"
    timezone: str = "Asia/Manila"

    free_only: bool = True
    allow_paid_fallback: bool = False
    daily_video_limit: int = 1
    max_retries_per_provider: int = 2
    max_script_tokens: int = 3000
    max_video_duration_seconds: int = 300

    video_width: int = 1920
    video_height: int = 1080
    video_fps: int = 24
    review_mode: bool = True
    auto_publish: bool = False

    provider_priority: str = "cloudflare,gemini,huggingface,grok,local,template"

    cloudflare_account_id: str = ""
    cloudflare_api_token: str = ""
    gemini_api_key: str = ""
    huggingface_api_key: str = ""
    grok_api_key: str = ""
    cloudflare_free_verified: bool = False
    gemini_free_verified: bool = False
    huggingface_free_verified: bool = False
    grok_free_verified: bool = False

    # --- provider routing / safety knobs ---
    provider_timeout_seconds: float = 60.0
    backoff_base_seconds: float = 1.0
    backoff_max_seconds: float = 30.0
    circuit_failure_threshold: int = 3
    circuit_cooldown_seconds: int = 900
    quota_cooldown_seconds: int = 21600
    provider_min_interval_seconds: float = 6.0

    # --- provider models/endpoints (no model defaults: models get deprecated) ---
    cloudflare_model: str = ""
    gemini_model: str = ""
    huggingface_model: str = ""
    huggingface_base_url: str = "https://router.huggingface.co/v1"
    grok_model: str = ""
    grok_base_url: str = "https://api.x.ai/v1"
    local_model: str = ""
    local_base_url: str = "http://localhost:11434/v1"

    def priority_list(self) -> list[str]:
        items = [p.strip().lower() for p in self.provider_priority.split(",") if p.strip()]
        return [p for p in items if p in PROVIDERS]

    def validate_safety(self) -> None:
        """Hard stop: refuse to run with paid fallback while FREE_ONLY is on."""
        if self.free_only and self.allow_paid_fallback:
            raise RuntimeError("FREE_ONLY=true conflicts with ALLOW_PAID_FALLBACK=true")


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.validate_safety()
    return s
