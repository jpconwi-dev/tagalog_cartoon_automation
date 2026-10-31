import asyncio

import pytest

from app.services.ai_router import AIRouter
from app.services.providers.errors import (InvalidResponse, Misconfigured, NoProviderAvailable,
                                           QuotaExhausted, RateLimited, TransientError)
from tests.test_providers import mk


class Fake:
    def __init__(self, name, outcomes):
        self.name, self.outcomes, self.calls = name, list(outcomes), 0

    async def generate_script(self, arg):
        self.calls += 1
        o = self.outcomes[min(self.calls - 1, len(self.outcomes) - 1)]
        if isinstance(o, BaseException):
            raise o
        return o


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


def make(settings, **fakes):
    clock, sleeps = Clock(), []

    async def sleep(d):
        sleeps.append(d)
        clock.t += d

    providers = dict(fakes)
    providers.setdefault("template", Fake("template", ["TEMPLATE"]))
    r = AIRouter(settings, providers, sleep=sleep, clock=clock, jitter=lambda: 0.5)
    return r, clock, sleeps


def S(**kw):
    base = dict(provider_priority="cloudflare,gemini,template", provider_min_interval_seconds=0.0,
                max_retries_per_provider=2, circuit_failure_threshold=3, circuit_cooldown_seconds=900,
                quota_cooldown_seconds=3600, backoff_base_seconds=1.0, backoff_max_seconds=30.0)
    base.update(kw)
    return mk(**base)


def run(r, task="generate_script"):
    return asyncio.run(r.run(task, "arg"))


@pytest.mark.parametrize("err", [RateLimited("429"), TransientError("503"), TransientError("timeout"),
                                 InvalidResponse("bad json"), asyncio.TimeoutError()])
def test_falls_back_on_recoverable_errors(err):
    cf, gem = Fake("cloudflare", [err]), Fake("gemini", ["GEMINI"])
    r, _, _ = make(S(), cloudflare=cf, gemini=gem)
    res = run(r)
    assert res.value == "GEMINI" and res.provider == "gemini" and not res.used_template
    assert cf.calls == 3  # 1 attempt + MAX_RETRIES_PER_PROVIDER(2): bounded


def test_backoff_is_exponential_and_bounded():
    cf = Fake("cloudflare", [TransientError("x")])
    r, _, sleeps = make(S(), cloudflare=cf, gemini=Fake("gemini", ["ok"]))
    run(r)
    assert sleeps == [1.0, 2.0]


def test_retry_after_is_honored_but_capped():
    cf = Fake("cloudflare", [RateLimited("429", retry_after=10), "OK"])
    r, _, sleeps = make(S(), cloudflare=cf)
    assert run(r).value == "OK" and sleeps == [10.0]
    cf = Fake("cloudflare", [RateLimited("429", retry_after=999), "OK"])
    r, _, sleeps = make(S(), cloudflare=cf)
    run(r)
    assert sleeps == [30.0]


def test_quota_exhausted_not_retried_and_cools_down():
    cf = Fake("cloudflare", [QuotaExhausted("quota")])
    r, clock, _ = make(S(), cloudflare=cf, gemini=Fake("gemini", ["G"]))
    assert run(r).provider == "gemini" and cf.calls == 1
    run(r)
    assert cf.calls == 1  # skipped during cooldown
    clock.t += 3601
    run(r)
    assert cf.calls == 2


def test_misconfigured_never_retried():
    cf = Fake("cloudflare", [Misconfigured("401")])
    r, clock, _ = make(S(), cloudflare=cf, gemini=Fake("gemini", ["G"]))
    run(r)
    clock.t += 10 ** 7
    run(r)
    assert cf.calls == 1


def test_circuit_breaker_opens_then_recovers():
    cf = Fake("cloudflare", [TransientError("x")] * 3 + ["BACK"])
    r, clock, _ = make(S(), cloudflare=cf, gemini=Fake("gemini", ["G"]))
    run(r)
    assert cf.calls == 3
    assert run(r).provider == "gemini" and cf.calls == 3  # circuit open
    clock.t += 901
    assert run(r).value == "BACK"


def test_unverified_provider_is_never_called():
    grok = Fake("grok", ["PAID?"])
    s = S(provider_priority="grok,template", grok_api_key="x", grok_model="m", grok_free_verified=False)
    r, _, _ = make(s, grok=grok)
    res = run(r)
    assert grok.calls == 0 and res.used_template
    assert any(a.provider == "grok" and "not verified" in a.detail for a in res.attempts)


def test_free_only_overrides_cannot_enable_unverified():
    grok = Fake("grok", ["X"])
    s = S(provider_priority="grok,template", grok_api_key="x", grok_model="m", free_only=True)
    r, _, _ = make(s, grok=grok)
    run(r)
    assert grok.calls == 0


def test_all_ai_fail_uses_template():
    r, _, _ = make(S(), cloudflare=Fake("cloudflare", [TransientError("x")]),
                   gemini=Fake("gemini", [Misconfigured("bad")]))
    res = run(r)
    assert res.used_template and res.value == "TEMPLATE"


def test_nothing_available_raises():
    r, _, _ = make(S(), template=Fake("template", [TransientError("boom")]),
                   cloudflare=Fake("cloudflare", [Misconfigured("x")]), gemini=Fake("gemini", [Misconfigured("x")]))
    with pytest.raises(NoProviderAvailable):
        run(r)


def test_min_interval_spacing_between_calls():
    cf = Fake("cloudflare", ["A", "B"])
    r, _, sleeps = make(S(provider_min_interval_seconds=6.0), cloudflare=cf)
    run(r)
    run(r)
    assert sleeps == [6.0]


def test_unexpected_exception_is_contained():
    r, _, _ = make(S(), cloudflare=Fake("cloudflare", [KeyError("bug")]), gemini=Fake("gemini", ["G"]))
    assert run(r).provider == "gemini"


def test_recorder_gets_redacted_errors():
    events = []
    r, _, _ = make(S(), cloudflare=Fake("cloudflare", [TransientError("api_key=SECRET123 failed")]),
                   gemini=Fake("gemini", ["G"]))
    r._recorder = lambda p, t, ok, e: events.append((p, ok, e))
    run(r)
    assert any(p == "cloudflare" and not ok for p, ok, _ in events)
    assert all("SECRET123" not in (e or "") for _, _, e in events)
