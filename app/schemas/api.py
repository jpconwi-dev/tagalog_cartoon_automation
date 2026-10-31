from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from app.models.tables import JobStatus


class HealthResponse(BaseModel):
    status: str = "ok"


class ProviderInfo(BaseModel):
    name: str
    configured: bool
    free_verified: bool
    eligible: bool
    reason: str = ""


class StatusResponse(BaseModel):
    env: str
    free_only: bool
    paid_fallback_allowed: bool
    review_mode: bool
    auto_publish: bool
    daily_video_limit: int
    jobs_total: int
    jobs_by_status: dict[str, int]


class VideoGenerateRequest(BaseModel):
    daily_key: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$",
                                     description="Defaults to today's date in the configured timezone")


class JobResponse(BaseModel):
    id: int
    daily_key: str
    status: JobStatus
    error: Optional[str] = None
    retry_count: int
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}
