from dataclasses import dataclass
from app.core.config import Settings


@dataclass(frozen=True)
class Eligibility:
    name: str
    configured: bool
    free_verified: bool
    eligible: bool
    reason: str


def check_eligibility(s: Settings, name: str) -> Eligibility:
    if name == "template":
        return Eligibility(name, True, True, True, "built-in deterministic fallback")
    if name == "local":
        ok = bool(s.local_model)
        return Eligibility(name, ok, True, ok, "ok" if ok else "LOCAL_MODEL not set")
    if name == "cloudflare":
        has_creds = bool(s.cloudflare_account_id and s.cloudflare_api_token)
    elif name == "gemini":
        has_creds = bool(s.gemini_api_key)
    elif name == "huggingface":
        has_creds = bool(s.huggingface_api_key)
    elif name == "grok":
        has_creds = bool(s.grok_api_key)
    else:
        return Eligibility(name, False, False, False, "unknown provider")

    model = getattr(s, f"{name}_model")
    verified = bool(getattr(s, f"{name}_free_verified"))
    configured = has_creds and bool(model)
    upper = name.upper()
    if not has_creds:
        return Eligibility(name, False, verified, False, "missing credentials")
    if not model:
        return Eligibility(name, False, verified, False, f"{upper}_MODEL not set")
    paid_override = (not s.free_only) and s.allow_paid_fallback
    if not verified and not paid_override:
        return Eligibility(name, configured, False, False,
                           f"free eligibility not verified (set {upper}_FREE_VERIFIED=true "
                           "after checking the provider's current terms)")
    return Eligibility(name, configured, verified, True, "ok")


def effective_priority(s: Settings) -> list[str]:
    """Configured order, with the deterministic template always last."""
    order = [p for p in s.priority_list() if p != "template"]
    return order + ["template"]
