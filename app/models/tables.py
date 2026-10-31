from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class JobStatus(str, Enum):
    queued = "queued"
    generating_script = "generating_script"
    generating_scenes = "generating_scenes"
    generating_audio = "generating_audio"
    rendering = "rendering"
    validating = "validating"
    awaiting_review = "awaiting_review"
    ready_to_publish = "ready_to_publish"
    uploading = "uploading"
    published = "published"
    retry_pending = "retry_pending"
    failed = "failed"


RECOVERABLE = {JobStatus.failed, JobStatus.retry_pending}


class Job(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    daily_key: str = Field(index=True, unique=True)  # e.g. "2026-11-01"
    status: JobStatus = Field(default=JobStatus.queued)
    error: Optional[str] = None
    retry_count: int = 0
    script_id: Optional[int] = None
    youtube_video_id: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class TopicHistory(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str = Field(index=True)
    category: str
    created_at: datetime = Field(default_factory=utcnow)


class ProviderEvent(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    provider: str = Field(index=True)
    task: str
    ok: bool
    error: Optional[str] = None  # always stored redacted
    created_at: datetime = Field(default_factory=utcnow)
