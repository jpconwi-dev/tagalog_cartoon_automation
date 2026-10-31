from app.core.security import redact


class ProviderError(Exception):
    retryable = True
    kind = "error"

    def __init__(self, message: str):
        super().__init__(redact(message))


class TransientError(ProviderError):
    kind = "transient"


class RateLimited(ProviderError):
    kind = "rate_limited"

    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class QuotaExhausted(ProviderError):
    retryable = False
    kind = "quota_exhausted"


class Misconfigured(ProviderError):
    retryable = False
    kind = "misconfigured"


class InvalidResponse(ProviderError):
    kind = "invalid_response"


class NoProviderAvailable(Exception):
    pass
