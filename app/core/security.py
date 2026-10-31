import re
import secrets
from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader
from app.core.config import Settings, get_settings

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

_SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|token|secret|password|authorization)(\"?\s*[:=]\s*\"?)((?:bearer\s+)?[^\s\",}]+)"),
    re.compile(r"(?i)bearer\s+[a-z0-9\-._~+/]+=*"),
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),
]


def redact(text: str) -> str:
    """Mask anything that looks like a credential before logging or returning."""
    out = str(text)
    out = _SECRET_PATTERNS[0].sub(lambda m: f"{m.group(1)}{m.group(2)}***", out)
    out = _SECRET_PATTERNS[1].sub("Bearer ***", out)
    out = _SECRET_PATTERNS[2].sub("***", out)
    return out


def require_api_key(
    provided: str | None = Depends(_api_key_header),
    settings: Settings = Depends(get_settings),
) -> None:
    if not settings.api_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "API_KEY is not configured on the server")
    if not provided or not secrets.compare_digest(provided, settings.api_key):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing API key")
