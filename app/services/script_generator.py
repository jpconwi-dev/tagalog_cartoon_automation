import json
import re
from typing import Any

from sqlmodel import Session

from app.core.config import Settings
from app.models.tables import Job, Script
from app.schemas.content import ScriptDoc, TopicRequest
from app.services import topic_selector as ts
from app.services.ai_router import AIRouter
from app.services.providers.errors import InvalidResponse

_TAGALOG = set("""ang ng sa mga na ay at ito ba mo ko natin namin kung para may ni si kay din rin pa lang po
iyon iyan dito doon ano bakit paano kapag kasi dahil pero o ka siya sila tayo kami kayo ating aking iyong nila
nito niyan ito yung isang ilang mas pang nang ang hindi walang meron mayroon ngayon lahat bawat""".split())


def tagalog_ratio(text: str) -> float:
    tokens = re.findall(r"[a-zñ']+", text.lower())
    return sum(1 for t in tokens if t in _TAGALOG) / len(tokens) if tokens else 0.0


def check_script_quality(script: ScriptDoc, topic: TopicRequest, settings: Settings,
                         used: list[str]) -> list[str]:
    """Raise InvalidResponse on hard failures (router then retries/falls back); return soft warnings."""
    narration = " ".join([script.hook, script.introduction, *(s.narration for s in script.scenes),
                          script.conclusion])
    if len(narration.split()) < settings.min_script_words:
        raise InvalidResponse("script is too short")
    ratio = tagalog_ratio(narration)
    if ratio < settings.min_tagalog_ratio:
        raise InvalidResponse(f"narration does not look like Tagalog (ratio {ratio:.2f})")
    if script.est_duration_seconds > settings.max_video_duration_seconds * 1.15:
        raise InvalidResponse("script exceeds MAX_VIDEO_DURATION_SECONDS")
    for t in {script.title, script.topic}:
        dup = ts.find_duplicate(t, used, settings.topic_similarity_threshold)
        if dup:
            raise InvalidResponse(f"duplicates an earlier video: {dup}")

    warnings: list[str] = []
    allowed = " ".join([topic.title, topic.subject or "", *topic.key_points, *script.references])
    unknown = sorted(n for n in set(re.findall(r"\d[\d.,]*", narration)) if n not in allowed)
    if unknown:
        warnings.append("figures not found in supplied key points: " + ", ".join(unknown[:5]))
    if not script.is_template and not script.references:
        warnings.append("AI script has no references; review facts before publishing")
    if not script.is_template and not topic.key_points:
        warnings.append("no verified key points were supplied; facts need review")
    return warnings


async def generate_and_store(session: Session, settings: Settings, router: AIRouter,
                             topic: TopicRequest | None = None, job: Job | None = None) -> Script:
    if topic is None:
        topic = ts.select_topic(session, settings)
    else:
        ts.ensure_not_duplicate(session, settings, topic.title)
    used = ts.used_titles(session)
    holder: dict[str, Any] = {"w": []}

    def validate(script: ScriptDoc) -> None:
        holder["w"] = check_script_quality(script, topic, settings, used)

    res = await router.run("generate_script", topic, validate=validate)
    doc: ScriptDoc = res.value
    row = Script(job_id=job.id if job else None, topic_title=topic.title, category=topic.category,
                 title=doc.title, provider=res.provider, is_template=doc.is_template,
                 warnings_json=json.dumps(holder["w"], ensure_ascii=False),
                 content_json=doc.model_dump_json())
    session.add(row)
    ts.record_topics(session, topic.category, topic.title, doc.title)
    session.commit()
    session.refresh(row)
    if job is not None:
        job.script_id = row.id
        session.add(job)
        session.commit()
    return row


async def complete_script(session: Session, router: AIRouter, row: Script) -> Script:
    """Fill in whatever is still missing (scene plan, metadata). Safe to call repeatedly."""
    doc = ScriptDoc.model_validate_json(row.content_json)
    if not row.scene_plan_json:
        res = await router.run("generate_scene_plan", doc)
        row.scene_plan_json, row.plan_provider = res.value.model_dump_json(), res.provider
        session.add(row)
        session.commit()
    if not row.metadata_json:
        res = await router.run("generate_metadata", doc)
        row.metadata_json, row.metadata_provider = res.value.model_dump_json(), res.provider
        session.add(row)
        session.commit()
    session.refresh(row)
    return row
