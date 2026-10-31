import httpx
from app.core.config import Settings
from app.services.providers.cloudflare import CloudflareProvider
from app.services.providers.gemini import GeminiProvider
from app.services.providers.openai_compat import GrokProvider, HuggingFaceProvider, LocalProvider
from app.services.providers.template import TemplateProvider


def build_providers(settings: Settings, client: httpx.AsyncClient | None = None) -> dict:
    return {
        "cloudflare": CloudflareProvider(settings, client),
        "gemini": GeminiProvider(settings, client),
        "huggingface": HuggingFaceProvider(settings, client),
        "grok": GrokProvider(settings, client),
        "local": LocalProvider(settings, client),
        "template": TemplateProvider(settings),
    }
