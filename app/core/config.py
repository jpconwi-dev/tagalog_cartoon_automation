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
