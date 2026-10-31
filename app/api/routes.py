from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select
from app.core.config import PROVIDERS, Settings, get_settings
from app.core.security import require_api_key
from app.db.session import get_session
from app.models.tables import Job
from app.schemas.api import (HealthResponse, JobResponse, ProviderInfo,
                             StatusResponse, VideoGenerateRequest)
from app.services import job_service

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


def _provider_state(s: Settings, name: str) -> ProviderInfo:
    if name == "template":
        return ProviderInfo(name=name, configured=True, free_verified=True, eligible=True)
    if name == "local":
        return ProviderInfo(name=name, configured=False, free_verified=True, eligible=False)
    configured = {
        "cloudflare": bool(s.cloudflare_account_id and s.cloudflare_api_token),
        "gemini": bool(s.gemini_api_key),
        "huggingface": bool(s.huggingface_api_key),
        "grok": bool(s.grok_api_key),
    }[name]
    verified = getattr(s, f"{name}_free_verified")
    eligible = configured and (verified or not s.free_only)
    return ProviderInfo(name=name, configured=configured, free_verified=verified, eligible=eligible)


@router.get("/providers", response_model=list[ProviderInfo])
def providers(s: Settings = Depends(get_settings)):
    return [_provider_state(s, n) for n in s.priority_list()]


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
