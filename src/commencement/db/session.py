"""Engine + session factory keyed off CONFIG.DB_URL."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from commencement.config import CONFIG
from commencement.db.models import Base


def _ensure_sqlite_parent_dir(db_url: str) -> None:
    if db_url.startswith("sqlite:///"):
        path = Path(db_url.removeprefix("sqlite:///"))
        path.parent.mkdir(parents=True, exist_ok=True)


_ensure_sqlite_parent_dir(CONFIG.DB_URL)

engine: Engine = create_engine(CONFIG.DB_URL, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_schema() -> None:
    Base.metadata.create_all(engine)


@contextmanager
def get_session() -> Session:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
