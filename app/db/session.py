from functools import lru_cache
from pathlib import Path
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine
from app.core.config import get_settings
import app.models.tables  # noqa: F401  (register tables)


@lru_cache
def get_engine() -> Engine:
    url = get_settings().database_url
    kwargs = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        path = url.replace("sqlite:///", "", 1)
        if path and path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(url, **kwargs)


def init_db(engine: Engine | None = None) -> None:
    SQLModel.metadata.create_all(engine or get_engine())


def get_session():
    with Session(get_engine()) as session:
        yield session
