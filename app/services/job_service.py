from datetime import datetime
from zoneinfo import ZoneInfo
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select
from app.core.config import Settings
from app.core.security import redact
from app.models.tables import Job, JobStatus, RECOVERABLE, utcnow


class DailyLimitReached(Exception):
    pass


class NotRecoverable(Exception):
    pass


def today_key(settings: Settings) -> str:
    return datetime.now(ZoneInfo(settings.timezone)).strftime("%Y-%m-%d")


def create_daily_job(session: Session, settings: Settings, daily_key: str | None = None) -> tuple[Job, bool]:
    """Return (job, created). Idempotent per daily key, so duplicate runs are harmless."""
    key = daily_key or today_key(settings)
    existing = session.exec(select(Job).where(Job.daily_key == key)).first()
    if existing:
        return existing, False
    total_today = len(session.exec(select(Job).where(Job.daily_key == key)).all())
    if total_today >= settings.daily_video_limit:
        raise DailyLimitReached(key)
    job = Job(daily_key=key)
    session.add(job)
    try:
        session.commit()
    except IntegrityError:  # lost a race with another trigger (GitHub vs Cloudflare)
        session.rollback()
        return session.exec(select(Job).where(Job.daily_key == key)).one(), False
    session.refresh(job)
    return job, True


def set_status(session: Session, job: Job, status: JobStatus, error: str | None = None) -> Job:
    job.status = status
    job.error = redact(error) if error else None
    job.updated_at = utcnow()
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def retry_job(session: Session, job: Job, max_retries: int = 5) -> Job:
    if job.status not in RECOVERABLE:
        raise NotRecoverable(job.status.value)
    if job.retry_count >= max_retries:
        raise NotRecoverable("retry limit reached")
    job.retry_count += 1
    return set_status(session, job, JobStatus.queued)
