import asyncio
import json

import httpx
import pytest

from app.core.config import Settings
from app.schemas.content import ScriptDoc, TopicRequest
from app.services.providers.cloudflare import CloudflareProvider
from app.services.providers.eligibility import check_eligibility, effective_priority
from app.services.providers.errors import (InvalidResponse, Misconfigured, QuotaExhausted,
                                           RateLimited, TransientError)
from app.services.providers.gemini import GeminiProvider
from app.services.providers.openai_compat import HuggingFaceProvider
from app.services.providers.template import TemplateProvider


def mk(**kw) -> Settings:
    base = dict(api_key="k", database_url="sqlite://",
                provider_priority="cloudflare,gemini,huggingface,grok,local,template",
                cloudflare_account_id="acc", cloudflare_api_token="cf-secret-token", cloudflare_model="@cf/test/model",
                cloudflare_free_verified=True,
                gemini_api_key="gem-secret-key", gemini_model="gem-model", gemini_free_verified=True,
                huggingface_api_key="hf-secret", huggingface_model="org/model", huggingface_free_verified=True,
                max_video_duration_seconds=300)
    base.update(kw)
    return Settings(**base)


def script_json(**over) -> str:
    d = {"title": "Paano Gumagana ang Magnet", "topic": "Magnet", "category": "science",
         "target_audience": "Lahat", "hook": "Alam mo ba kung bakit dumidikit ang magnet?",
         "introduction": "Alamin natin ngayon kung paano gumagana ang magnet.",
         "scenes": [
             {"narration": "Ang magnet ay may dalawang dulo na tinatawag na poles.", "visual": "Juan holds a magnet", "est_seconds": 8},
             {"narration": "Ang magkaibang poles ay nag-aakit sa isa't isa.", "visual": "Two magnets attract", "est_seconds": 8},
             {"narration": "Ang magkaparehong poles naman ay nagtutulakan.", "visual": "Two magnets repel", "est_seconds": 8}],
         "conclusion": "Ayan, alam mo na kung paano gumagana ang magnet.",
         "call_to_action": "Mag-subscribe ka na!", "references": [], "est_duration_seconds": 24}
    d.update(over)
    return json.dumps(d)


def client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


REQ = TopicRequest(title="Paano gumagana ang magnet", category="science")


# ---------- Cloudflare ----------
def test_cloudflare_success_and_request_shape():
    seen = {}

    def h(request: httpx.Request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(200, json={"result": {"response": script_json()}, "success": True})

    doc = asyncio.run(CloudflareProvider(mk(), client(h)).generate_script(REQ))
    assert isinstance(doc, ScriptDoc) and doc.provider == "cloudflare"
    assert seen["url"].endswith("/accounts/acc/ai/run/@cf/test/model")
    assert seen["auth"] == "Bearer cf-secret-token"


def test_cloudflare_allocation_exhausted_is_quota():
    h = lambda r: httpx.Response(429, json={"errors": [{"message": "you have used up your daily free allocation of neurons"}]})
    with pytest.raises(QuotaExhausted):
        asyncio.run(CloudflareProvider(mk(), client(h)).generate_script(REQ))


# ---------- Gemini ----------
def test_gemini_key_in_header_not_url():
    def h(request: httpx.Request):
        assert request.headers["x-goog-api-key"] == "gem-secret-key"
        assert "gem-secret-key" not in str(request.url)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": script_json()}]}}]})

    assert asyncio.run(GeminiProvider(mk(), client(h)).generate_script(REQ)).provider == "gemini"


def test_gemini_accepts_fenced_json():
    fenced = "```json\n" + script_json() + "\n```"
    h = lambda r: httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": fenced}]}}]})
    assert asyncio.run(GeminiProvider(mk(), client(h)).generate_script(REQ)).title.startswith("Paano")


@pytest.mark.parametrize("status,exc", [(429, RateLimited), (500, TransientError), (503, TransientError),
                                         (401, Misconfigured), (404, Misconfigured)])
def test_http_status_classification(status, exc):
    h = lambda r: httpx.Response(status, text="nope", headers={"retry-after": "7"})
    with pytest.raises(exc) as ei:
        asyncio.run(GeminiProvider(mk(), client(h)).generate_script(REQ))
    if exc is RateLimited:
        assert ei.value.retry_after == 7.0


def test_gemini_per_day_429_is_quota():
    h = lambda r: httpx.Response(429, text='{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}')
    with pytest.raises(QuotaExhausted):
        asyncio.run(GeminiProvider(mk(), client(h)).generate_script(REQ))


def test_timeout_is_transient():
    def h(request):
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(TransientError):
        asyncio.run(GeminiProvider(mk(), client(h)).generate_script(REQ))


def test_malformed_ai_responses_are_invalid():
    for text in ["not json at all", '{"title": "x"}', "{broken json}"]:
        h = lambda r, t=text: httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": t}]}}]})
        with pytest.raises(InvalidResponse):
            asyncio.run(GeminiProvider(mk(), client(h)).generate_script(REQ))


def test_too_long_script_rejected():
    h = lambda r: httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": script_json(est_duration_seconds=9999)}]}}]})
    with pytest.raises(InvalidResponse):
        asyncio.run(GeminiProvider(mk(), client(h)).generate_script(REQ))


def test_duplicate_scene_narration_rejected():
    s = json.loads(script_json())
    s["scenes"][1]["narration"] = s["scenes"][0]["narration"]
    h = lambda r: httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps(s)}]}}]})
    with pytest.raises(InvalidResponse):
        asyncio.run(GeminiProvider(mk(), client(h)).generate_script(REQ))


def test_error_messages_never_contain_secrets():
    h = lambda r: httpx.Response(401, text="bad key api_key=gem-secret-key Authorization: Bearer gem-secret-key")
    with pytest.raises(Misconfigured) as ei:
        asyncio.run(GeminiProvider(mk(), client(h)).generate_script(REQ))
    assert "gem-secret-key" not in str(ei.value)


# ---------- OpenAI-compatible (Hugging Face) ----------
def test_huggingface_success_and_402_is_quota():
    ok = lambda r: httpx.Response(200, json={"choices": [{"message": {"content": script_json()}}]})
    assert asyncio.run(HuggingFaceProvider(mk(), client(ok)).generate_script(REQ)).provider == "huggingface"
    pay = lambda r: httpx.Response(402, text="You have exceeded your monthly included credits")
    with pytest.raises(QuotaExhausted):
        asyncio.run(HuggingFaceProvider(mk(), client(pay)).generate_script(REQ))


# ---------- eligibility / free-only ----------
def test_eligibility_rules():
    s = mk(grok_api_key="x", grok_model="m", grok_free_verified=False)
    assert not check_eligibility(s, "grok").eligible  # unverified -> never used
    assert check_eligibility(s, "cloudflare").eligible
    assert not check_eligibility(mk(gemini_model=""), "gemini").eligible
    assert not check_eligibility(mk(cloudflare_api_token=""), "cloudflare").eligible
    assert not check_eligibility(mk(), "local").eligible  # no LOCAL_MODEL
    assert check_eligibility(mk(local_model="llama"), "local").eligible
    assert check_eligibility(mk(), "template").eligible


def test_template_always_last():
    assert effective_priority(mk(provider_priority="template,gemini"))[-1] == "template"
    assert effective_priority(mk(provider_priority="")) == ["template"]


# ---------- template provider ----------
def test_template_provider_full_flow():
    async def flow():
        t = TemplateProvider(mk())
        script = await t.generate_script(TopicRequest(title="Paano gumagana ang magnet", category="science",
                                                      key_points=["Ang magnet ay may dalawang poles."]))
        plan = await t.generate_scene_plan(script)
        meta = await t.generate_metadata(script)
        return script, plan, meta

    script, plan, meta = asyncio.run(flow())
    assert script.is_template and script.provider == "template" and len(script.scenes) >= 3
    assert [s.index for s in script.scenes] == list(range(1, len(script.scenes) + 1))
    assert len(plan.scenes) == len(script.scenes)
    assert len(meta.title) <= 100 and meta.category_id == "27"


def test_template_without_key_points_makes_no_factual_claims():
    script = asyncio.run(TemplateProvider(mk()).generate_script(TopicRequest(title="Mga bulkan")))
    assert script.is_template and script.references == []
