import pytest
from sqlmodel import Session
from app.core.config import Settings
from app.core.security import redact
from app.models.tables import JobStatus
from app.services import job_service
from tests.conftest import H


def test_health_public(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_auth_required(client):
    assert client.get("/api/status").status_code == 401
    assert client.get("/api/status", headers={"X-API-Key": "bad"}).status_code == 401
    assert client.get("/api/status", headers=H).status_code == 200


def test_server_without_api_key_rejects(client, settings):
    settings.api_key = ""
    assert client.get("/api/status", headers=H).status_code == 503


def test_providers_hide_secrets_and_gate_on_free_verification(client, settings):
    settings.gemini_api_key = "AIzaSECRETSECRETSECRETSECRET"
    r = client.get("/api/providers", headers=H)
    assert "SECRET" not in r.text
    gem = next(p for p in r.json() if p["name"] == "gemini")
    assert gem["configured"] and not gem["eligible"]
    settings.gemini_free_verified = True
    gem = next(p for p in client.get("/api/providers", headers=H).json() if p["name"] == "gemini")
    assert gem["eligible"]


def test_free_only_blocks_paid_fallback():
    with pytest.raises(RuntimeError):
        Settings(free_only=True, allow_paid_fallback=True).validate_safety()


def test_redaction():
    assert "abc123" not in redact("api_key=abc123 failed")
    assert "xyz" not in redact("Authorization: Bearer xyz")
    assert "AIza" not in redact("key AIzaSyA1234567890123456789012")


def test_daily_job_uniqueness(client):
    a = client.post("/api/videos/generate", json={"daily_key": "2026-11-01"}, headers=H)
    b = client.post("/api/videos/generate", json={"daily_key": "2026-11-01"}, headers=H)
    assert a.status_code == b.status_code == 202
    assert a.json()["id"] == b.json()["id"]


def test_invalid_daily_key_rejected(client):
    assert client.post("/api/videos/generate", json={"daily_key": "nope"}, headers=H).status_code == 422


def test_retry_only_recoverable(client, engine, settings):
    jid = client.post("/api/videos/generate", json={}, headers=H).json()["id"]
    assert client.post(f"/api/jobs/{jid}/retry", headers=H).status_code == 409
    with Session(engine) as s:
        job = s.get(job_service.Job, jid)
        job_service.set_status(s, job, JobStatus.failed, "token=abc failed")
    r = client.post(f"/api/jobs/{jid}/retry", headers=H)
    assert r.status_code == 200 and r.json()["status"] == "queued" and r.json()["retry_count"] == 1


def test_error_is_redacted_when_stored(client, engine):
    jid = client.post("/api/videos/generate", json={}, headers=H).json()["id"]
    with Session(engine) as s:
        job = job_service.set_status(s, s.get(job_service.Job, jid), JobStatus.failed, "api_key=SUPERSECRET")
        assert "SUPERSECRET" not in job.error


def test_body_size_limit(client):
    r = client.post("/api/videos/generate", content=b"x", headers={**H, "content-length": "999999"})
    assert r.status_code == 413
