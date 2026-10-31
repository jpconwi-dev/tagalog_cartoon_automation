"""Free-only provider router: bounded retries, backoff+jitter, circuit breaker, quota cooldowns."""
import asyncio
import random
import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Callable

from app.core.config import Settings, get_settings
from app.core.security import redact
from app.services.providers.eligibility import check_eligibility, effective_priority
from app.services.providers.errors import (Misconfigured, NoProviderAvailable, ProviderError,
                                           QuotaExhausted, RateLimited, TransientError)

TASKS = {"generate_script", "generate_scene_plan", "generate_metadata"}
_FAIL = object()


@dataclass
class Attempt:
    provider: str
    ok: bool
    kind: str
    detail: str = ""


@dataclass
class RouterResult:
    value: Any
    provider: str
    used_template: bool
    attempts: list[Attempt] = field(default_factory=list)


@dataclass
class _State:
    failures: int = 0
    open_until: float = 0.0
    misconfigured: bool = False
    last_call: float = float("-inf")


class AIRouter:
    def __init__(self, settings: Settings, providers: dict | None = None, *,
                 sleep: Callable = asyncio.sleep, clock: Callable[[], float] = time.monotonic,
                 jitter: Callable[[], float] = random.random, recorder: Callable | None = None):
        self.settings = settings
        if providers is None:
            from app.services.providers.registry import build_providers
            providers = build_providers(settings)
        self.providers = providers
        self._sleep, self._clock, self._jitter, self._recorder = sleep, clock, jitter, recorder
        self.state: dict[str, _State] = {}

    def _st(self, name: str) -> _State:
        return self.state.setdefault(name, _State())

    def _record(self, name: str, task: str, ok: bool, err: Exception | None) -> None:
        if self._recorder:
            try:
                self._recorder(name, task, ok, redact(str(err)) if err else None)
            except Exception:  # logging must never break generation
                pass

    def _delay(self, attempt: int, err: ProviderError) -> float:
        s = self.settings
        base = min(s.backoff_max_seconds, s.backoff_base_seconds * 2 ** (attempt - 1))
        delay = base * (0.5 + self._jitter())
        if isinstance(err, RateLimited) and err.retry_after:
            delay = max(delay, err.retry_after)
        return min(delay, s.backoff_max_seconds)

    async def run(self, task: str, arg: Any) -> RouterResult:
        if task not in TASKS:
            raise ValueError(f"unknown task {task}")
        attempts: list[Attempt] = []
        for name in effective_priority(self.settings):
            elig = check_eligibility(self.settings, name)
            provider = self.providers.get(name)
            st = self._st(name)
            if not elig.eligible:
                attempts.append(Attempt(name, False, "skipped", elig.reason)); continue
            if provider is None:
                attempts.append(Attempt(name, False, "skipped", "not registered")); continue
            if st.misconfigured:
                attempts.append(Attempt(name, False, "skipped", "marked misconfigured")); continue
            if self._clock() < st.open_until:
                attempts.append(Attempt(name, False, "skipped", "cooling down")); continue
            value = await self._try(name, provider, task, arg, attempts)
            if value is not _FAIL:
                return RouterResult(value, name, name == "template", attempts)
        summary = "; ".join(f"{a.provider}:{a.kind}" for a in attempts)
        raise NoProviderAvailable(f"no provider could complete {task} ({summary})")

    async def _try(self, name, provider, task, arg, attempts):
        s = self.settings
        st = self._st(name)
        max_attempts = 1 if name == "template" else 1 + s.max_retries_per_provider
        spaced = name not in ("template", "local")
        for n in range(1, max_attempts + 1):
            if spaced:
                wait = st.last_call + s.provider_min_interval_seconds - self._clock()
                if wait > 0:
                    await self._sleep(wait)
                st.last_call = self._clock()
            try:
                value = await asyncio.wait_for(getattr(provider, task)(arg),
                                               timeout=s.provider_timeout_seconds + 5)
            except asyncio.TimeoutError:
                err: ProviderError = TransientError(f"{name} timed out")
            except ProviderError as e:
                err = e
            except Exception as e:  # bug or unexpected library error: treat as transient
                err = TransientError(f"{name} unexpected {type(e).__name__}: {e}")
            else:
                st.failures = 0
                self._record(name, task, True, None)
                attempts.append(Attempt(name, True, "ok"))
                return value
            self._record(name, task, False, err)
            attempts.append(Attempt(name, False, err.kind, str(err)))
            if isinstance(err, QuotaExhausted):
                st.open_until = self._clock() + s.quota_cooldown_seconds
                return _FAIL
            if isinstance(err, Misconfigured):
                st.misconfigured = True
                return _FAIL
            st.failures += 1
            if st.failures >= s.circuit_failure_threshold:
                st.open_until = self._clock() + s.circuit_cooldown_seconds
                st.failures = 0
                return _FAIL
            if n < max_attempts:
                await self._sleep(self._delay(n, err))
        return _FAIL


def db_recorder(engine=None) -> Callable:
    def _rec(provider: str, task: str, ok: bool, error: str | None) -> None:
        from sqlmodel import Session
        from app.db.session import get_engine
        from app.models.tables import ProviderEvent
        with Session(engine or get_engine()) as session:
            session.add(ProviderEvent(provider=provider, task=task, ok=ok, error=error))
            session.commit()
    return _rec


@lru_cache
def get_router() -> AIRouter:
    return AIRouter(get_settings(), recorder=db_recorder())
