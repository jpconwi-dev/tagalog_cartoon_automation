import os
os.environ["API_KEY"] = "test-key"
os.environ["DATABASE_URL"] = "sqlite://"
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine
from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.main import app


@pytest.fixture
def engine():
    e = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(e)
    return e


@pytest.fixture
def settings():
    return Settings(api_key="test-key", database_url="sqlite://")


@pytest.fixture
def client(engine, settings):
    def _session():
        with Session(engine) as s:
            yield s
    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


H = {"X-API-Key": "test-key"}
