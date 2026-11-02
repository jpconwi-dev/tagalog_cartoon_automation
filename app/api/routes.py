import json

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlmodel import Session, select
from app.core.config import Settings, get_settings
from app.core.security import require_api_key
from app.db.session import get_session
from app.models.tables import Job, Script
from app.schemas.api import (HealthResponse, JobResponse, ProviderInfo,
                             ScriptDetail, ScriptSummary, StatusResponse, VideoGenerateRequest)
from app.schemas.content import TopicRequest
from app.services import job_service
from app.services.ai_router import AIRouter, get_router
from app.services.providers.errors import NoProviderAvailable
from app.services.script_generator import complete_script, generate_and_store
from app.services.topic_selector import DuplicateTopic, NoTopicAvailable
from app.services.providers.eligibility import check_eligibility, effective_priority

public = APIRouter()
router = APIRouter(prefix="/api", dependencies=[Depends(require_api_key)])


@public.get("/health", response_model=HealthResponse)
def health():
    return HealthResponse()


@router.get("/status", response_model=StatusResponse)
def api_status(session: Session = Depends(get_session), s: Settings = Depends(get_settings)):
    jobs = session.exec(select(Job)).all()
    by_status: dict[str, int] = {}
    for j in jobs:
        by_status[j.status.value] = by_status.get(j.status.value, 0) + 1
    return StatusResponse(env=s.app_env, free_only=s.free_only,
                          paid_fallback_allowed=s.allow_paid_fallback,
                          review_mode=s.review_mode, auto_publish=s.auto_publish,
                          daily_video_limit=s.daily_video_limit,
                          jobs_total=len(jobs), jobs_by_status=by_status)


@router.get("/providers", response_model=list[ProviderInfo])
def providers(s: Settings = Depends(get_settings)):
    out = []
    for name in effective_priority(s):
        e = check_eligibility(s, name)
        out.append(ProviderInfo(name=name, configured=e.configured, free_verified=e.free_verified,
                                eligible=e.eligible, reason=e.reason))
    return out


@router.post("/videos/generate", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
def generate_video(body: VideoGenerateRequest, session: Session = Depends(get_session),
                   s: Settings = Depends(get_settings)):
    try:
        job, _ = job_service.create_daily_job(session, s, body.daily_key)
    except job_service.DailyLimitReached:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Daily video limit reached")
    return job


@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: int, session: Session = Depends(get_session)):
    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@router.post("/jobs/{job_id}/retry", response_model=JobResponse)
def retry(job_id: int, session: Session = Depends(get_session)):
    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    try:
        return job_service.retry_job(session, job)
    except job_service.NotRecoverable as e:
        raise HTTPException(409, f"Job is not recoverable: {e}")


def _summary(r: Script) -> dict:
    return dict(id=r.id, title=r.title, topic_title=r.topic_title, category=r.category, provider=r.provider,
                is_template=r.is_template, warnings=json.loads(r.warnings_json), job_id=r.job_id,
                created_at=r.created_at)


def _detail(r: Script) -> ScriptDetail:
    load = lambda s: json.loads(s) if s else None
    return ScriptDetail(**_summary(r), script=json.loads(r.content_json), scene_plan=load(r.scene_plan_json),
                        metadata=load(r.metadata_json), plan_provider=r.plan_provider,
                        metadata_provider=r.metadata_provider)


@router.post("/scripts/generate", response_model=ScriptDetail, status_code=status.HTTP_201_CREATED)
async def generate_script(topic: TopicRequest | None = Body(default=None),
                          session: Session = Depends(get_session), s: Settings = Depends(get_settings),
                          ai: AIRouter = Depends(get_router)):
    """Create a script (and its scene plan + metadata). Optionally pass your own topic."""
    try:
        row = await generate_and_store(session, s, ai, topic=topic)
        row = await complete_script(session, ai, row)
    except DuplicateTopic as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    except NoTopicAvailable as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    except NoProviderAvailable as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e))
    return _detail(row)


@router.get("/scripts", response_model=list[ScriptSummary])
def list_scripts(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
                 session: Session = Depends(get_session)):
    rows = session.exec(select(Script).order_by(Script.id.desc()).offset(offset).limit(limit)).all()
    return [_summary(r) for r in rows]


@router.get("/scripts/{script_id}", response_model=ScriptDetail)
def get_script(script_id: int, session: Session = Depends(get_session)):
    row = session.get(Script, script_id)
    if not row:
        raise HTTPException(404, "Script not found")
    return _detail(row)
