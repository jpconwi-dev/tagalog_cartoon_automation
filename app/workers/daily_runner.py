"""Script-stage worker. Run: python -m app.workers.daily_runner [--key YYYY-MM-DD]

Exit codes: 0 stage complete, 1 failed, 3 deferred (retry_pending: no provider/quota available).
Phase 3 stops at status `generating_audio` (= script stage finished, audio is the next stage).
"""
import argparse
import asyncio
import json
import sys

from sqlmodel import Session

from app.core.config import get_settings
from app.db.session import get_engine, init_db
from app.models.tables import Job, JobStatus, Script
from app.services import job_service
from app.services.ai_router import AIRouter, get_router
from app.services.providers.errors import NoProviderAvailable
from app.services.script_generator import complete_script, generate_and_store
from app.services.topic_selector import DuplicateTopic, NoTopicAvailable

STARTABLE = {JobStatus.queued, JobStatus.retry_pending, JobStatus.generating_script, JobStatus.generating_scenes}


async def run_job(session: Session, settings, router: AIRouter, job: Job) -> Job:
    if job.status not in STARTABLE:
        return job  # already past this stage, or failed (use the retry endpoint)
    try:
        job_service.set_status(session, job, JobStatus.generating_script)
        if job.script_id is None:  # resume: never regenerate a script that is already saved
            await generate_and_store(session, settings, router, job=job)
        job_service.set_status(session, job, JobStatus.generating_scenes)
        row = session.get(Script, job.script_id)
        await complete_script(session, router, row)
        return job_service.set_status(session, job, JobStatus.generating_audio)
    except NoProviderAvailable as e:
        return job_service.set_status(session, job, JobStatus.retry_pending, str(e))
    except (NoTopicAvailable, DuplicateTopic) as e:
        return job_service.set_status(session, job, JobStatus.failed, str(e))
    except Exception as e:  # noqa: BLE001 - record and surface, never crash silently
        return job_service.set_status(session, job, JobStatus.failed, f"{type(e).__name__}: {e}")


async def main_async(key: str | None) -> int:
    settings = get_settings()
    init_db()
    with Session(get_engine()) as session:
        job, created = job_service.create_daily_job(session, settings, key)
        job = await run_job(session, settings, get_router(), job)
        print(json.dumps({"job_id": job.id, "daily_key": job.daily_key, "status": job.status.value,
                          "created": created, "script_id": job.script_id, "error": job.error}))
        return {JobStatus.failed: 1, JobStatus.retry_pending: 3}.get(job.status, 0)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", help="daily key, default: today in the configured timezone")
    sys.exit(asyncio.run(main_async(ap.parse_args().key)))


if __name__ == "__main__":
    main()
