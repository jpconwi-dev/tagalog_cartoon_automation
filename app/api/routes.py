from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select
from app.core.config import Settings, get_settings
from app.core.security import require_api_key
from app.db.session import get_session
from app.models.tables import Job
from app.schemas.api import (HealthResponse, JobResponse, ProviderInfo,
                             StatusResponse, VideoGenerateRequest)
from app.services import job_service
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
