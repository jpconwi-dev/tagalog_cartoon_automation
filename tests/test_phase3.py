import asyncio
import json

import pytest
from sqlmodel import Session, select

from app.models.tables import Job, JobStatus, Script, TopicHistory
from app.schemas.content import ScriptDoc, TopicRequest
from app.services import job_service
from app.services import topic_selector as ts
from app.services.ai_router import AIRouter
from app.services.providers.errors import InvalidResponse, NoProviderAvailable, TransientError
from app.services.providers.registry import build_providers
from app.services.providers.template import TemplateProvider
from app.services.script_generator import check_script_quality, generate_and_store, tagalog_ratio
from app.main import app
from app.services.ai_router import get_router
from app.workers.daily_runner import run_job
from tests.conftest import H
from tests.test_providers import mk
from tests.test_router import Fake, make

BANK = [
    {"title": "Bakit Asul ang Langit", "category": "science", "key_points": ["a", "b"]},
    {"title": "Bakit Maalat ang Dagat", "category": "nature", "key_points": ["a", "b"]},
    {"title": "Paano Gumagana ang Radyo", "category": "science", "key_points": ["a", "b"]},
]


def tpl_router(settings=None):
    s = settings or mk(provider_priority="template")
    return s, AIRouter(s, {"template": TemplateProvider(s)})


# ---------- topic selection & dedup ----------
def test_similarity_and_duplicates():
    assert ts.similarity("Bakit Maalat ang Dagat?", "bakit maalat ang dagat") == 1.0
    assert ts.similarity("Bakit Maalat ang Dagat", "Bakit Maalat ang Dagat at Ilog") == 1.0  # contained
    assert ts.similarity("Ano ang Gravity", "Paano Lumilipad ang Eroplano") < 0.3
    assert ts.find_duplicate("bakit maalat ang dagat", ["Bakit Maalat ang Dagat"], 0.8)
    assert ts.find_duplicate("Ano ang Gravity", ["Bakit Maalat ang Dagat"], 0.8) is None


def test_shipped_topic_bank_is_valid():
    bank = ts.load_bank()
    titles = [b["title"] for b in bank]
    assert len(titles) == len(set(titles)) >= 12
    for b in bank:
        assert len(b["key_points"]) >= 2 and b["category"] and b.get("subject")
        TopicRequest(**b)
    for i, a in enumerate(titles):  # no near-duplicates inside the bank itself
        assert ts.find_duplicate(a, titles[:i], 0.8) is None


def test_select_topic_rotates_categories_and_exhausts(engine, settings):
    with Session(engine) as s:
        picked = []
        for _ in range(3):
            t = ts.select_topic(s, settings, BANK)
            picked.append(t.title)
            ts.record_topics(s, t.category, t.title)
            s.commit()
        assert picked == ["Bakit Asul ang Langit", "Bakit Maalat ang Dagat", "Paano Gumagana ang Radyo"]
        with pytest.raises(ts.NoTopicAvailable):
            ts.select_topic(s, settings, BANK)


# ---------- quality checks ----------
def make_script(**over) -> ScriptDoc:
    return asyncio.run(TemplateProvider(mk()).generate_script(
        TopicRequest(title="Bakit Dumidikit ang Magnet?", subject="magnet", category="science",
                     key_points=["Ang magnet ay may dalawang pole.", "Nag-aakit ang magkaibang pole."]))).model_copy(update=over)


def test_tagalog_ratio():
    assert tagalog_ratio("Ang magnet ay may dalawang dulo na tinatawag na pole sa ating mundo.") > 0.3
    assert tagalog_ratio("The magnet has two poles and it attracts iron objects nearby.") < 0.05


def test_quality_hard_failures():
    s, topic = mk(), TopicRequest(title="Bakit Dumidikit ang Magnet?")
    ok = make_script()
    assert check_script_quality(ok, topic, s, []) == []
    eng = ok.model_copy(update={"hook": "Did you know how magnets really work in everyday life?",
                                "introduction": "Today we explain it in simple English words only.",
                                "conclusion": "Thanks for watching this video about magnets today."})
    eng.scenes = [sc.model_copy(update={"narration": f"This is English narration number {i} about magnets."})
                  for i, sc in enumerate(ok.scenes)]
    with pytest.raises(InvalidResponse):
        check_script_quality(eng, topic, s, [])
    with pytest.raises(InvalidResponse):
        check_script_quality(ok, topic, s, ["Bakit Dumidikit ang Magnet"])  # duplicate of history
    with pytest.raises(InvalidResponse):
        check_script_quality(ok, topic, mk(min_script_words=5000), [])


def test_quality_soft_warnings():
    s = mk()
    topic = TopicRequest(title="Magnet")
    doc = make_script(is_template=False, references=[])
    doc.scenes[0] = doc.scenes[0].model_copy(update={"narration": "Mga 9999 na beses itong nangyayari sa ating mundo araw-araw."})
    w = check_script_quality(doc, topic, s, [])
    assert any("figures" in x for x in w) and any("no references" in x for x in w)


# ---------- generation, storage, dedup over many runs ----------
def test_generate_store_and_never_repeat(engine):
    s, router = tpl_router()
    with Session(engine) as session:
        titles = []
        for _ in range(8):
            row = asyncio.run(generate_and_store(session, s, router))
            titles.append(row.topic_title)
        assert len(set(titles)) == 8
        assert len(session.exec(select(Script)).all()) == 8
        assert len(session.exec(select(TopicHistory)).all()) >= 8
        assert row.provider == "template" and row.is_template


def test_user_topic_duplicate_rejected(engine):
    s, router = tpl_router()
    with Session(engine) as session:
        t = TopicRequest(title="Bakit Bughaw ang Langit", subject="langit", key_points=["Nagkakalat ang hangin ng liwanag."])
        asyncio.run(generate_and_store(session, s, router, topic=t))
        with pytest.raises(ts.DuplicateTopic):
            asyncio.run(generate_and_store(session, s, router, topic=t))


def test_validator_triggers_fallback_inside_router():
    s = mk(provider_priority="cloudflare,gemini,template")
    cf, gem = Fake("cloudflare", ["bad"]), Fake("gemini", ["good"])
    r, _, _ = make(s, cloudflare=cf, gemini=gem)

    def validate(v):
        if v == "bad":
            raise InvalidResponse("rejected")

    res = asyncio.run(r.run("generate_script", "arg", validate=validate))
    assert res.provider == "gemini" and cf.calls == 3


# ---------- job runner: resumable & deferrable ----------
class CountingTemplate(TemplateProvider):
    def __init__(self, s):
        super().__init__(s)
        self.script_calls = 0

    async def generate_script(self, req):
        self.script_calls += 1
        return await super().generate_script(req)


def test_run_job_completes_and_is_idempotent(engine):
    s = mk(provider_priority="template")
    prov = CountingTemplate(s)
    router = AIRouter(s, {"template": prov})
    with Session(engine) as session:
        job, _ = job_service.create_daily_job(session, s, "2026-11-01")
        job = asyncio.run(run_job(session, s, router, job))
        assert job.status == JobStatus.generating_audio and job.script_id
        row = session.get(Script, job.script_id)
        assert row.scene_plan_json and row.metadata_json and row.job_id == job.id
        job = asyncio.run(run_job(session, s, router, job))  # past this stage: no-op
        assert prov.script_calls == 1


def test_run_job_resumes_without_regenerating_script(engine):
    s = mk(provider_priority="template")
    prov = CountingTemplate(s)
    router = AIRouter(s, {"template": prov})
    with Session(engine) as session:
        job, _ = job_service.create_daily_job(session, s, "2026-11-02")
        asyncio.run(generate_and_store(session, s, router, job=job))  # crash right after saving script
        job_service.set_status(session, job, JobStatus.retry_pending, "simulated crash")
        job = asyncio.run(run_job(session, s, router, job))
        assert job.status == JobStatus.generating_audio and prov.script_calls == 1
        assert len(session.exec(select(Script)).all()) == 1


def test_run_job_defers_when_no_provider(engine):
    s = mk(provider_priority="cloudflare,template")
    router = AIRouter(s, {"cloudflare": Fake("cloudflare", [TransientError("down")]),
                          "template": Fake("template", [TransientError("down")])},
                      sleep=lambda d: asyncio.sleep(0))
    with Session(engine) as session:
        job, _ = job_service.create_daily_job(session, s, "2026-11-03")
        job = asyncio.run(run_job(session, s, router, job))
        assert job.status == JobStatus.retry_pending and "no provider" in job.error and job.script_id is None
        assert session.exec(select(Script)).first() is None


def test_run_job_fails_cleanly_when_topics_exhausted(engine, monkeypatch):
    s, router = tpl_router()
    monkeypatch.setattr(ts, "load_bank", lambda *a, **k: [])
    with Session(engine) as session:
        job, _ = job_service.create_daily_job(session, s, "2026-11-04")
        job = asyncio.run(run_job(session, s, router, job))
        assert job.status == JobStatus.failed and "topics" in job.error


# ---------- API ----------
@pytest.fixture
def api(client, settings):
    settings.provider_priority = "template"
    app.dependency_overrides[get_router] = lambda: AIRouter(settings, build_providers(settings))
    return client


def test_scripts_endpoints(api):
    assert api.post("/api/scripts/generate").status_code == 401
    r = api.post("/api/scripts/generate", headers=H)
    assert r.status_code == 201
    body = r.json()
    assert body["is_template"] and body["scene_plan"] and body["metadata"]
    assert len(body["scene_plan"]["scenes"]) == len(body["script"]["scenes"])
    sid = body["id"]
    assert api.get(f"/api/scripts/{sid}", headers=H).json()["title"] == body["title"]
    assert [x["id"] for x in api.get("/api/scripts", headers=H).json()] == [sid]
    assert api.get("/api/scripts/9999", headers=H).status_code == 404
    second = api.post("/api/scripts/generate", headers=H).json()
    assert second["topic_title"] != body["topic_title"]


def test_scripts_custom_topic_and_duplicate(api):
    topic = {"title": "Bakit Bughaw ang Langit", "subject": "langit", "key_points": ["Nagkakalat ang hangin ng liwanag."]}
    assert api.post("/api/scripts/generate", headers=H, json=topic).status_code == 201
    assert api.post("/api/scripts/generate", headers=H, json=topic).status_code == 409
    assert api.post("/api/scripts/generate", headers=H, json={"title": "x"}).status_code == 422
