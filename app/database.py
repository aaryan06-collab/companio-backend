"""SQLAlchemy engine/session wiring for the Companio backend."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session as SASession
from sqlalchemy.orm import sessionmaker

from . import config, models

_SESSION_FACTORIES: dict[str, sessionmaker] = {}


def _make_factory(url: str) -> sessionmaker:
    kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
    if not url.startswith("sqlite"):
        # Neon's pooled endpoints break psycopg's client-side prepared
        # statements; disable them and pre-ping to drop stale pooled conns.
        kwargs["connect_args"] = {
            "prepare_threshold": None,
            # TCP keepalives + pool_recycle below Neon's ~5-min idle close
            # so pooled connections are never handed out dead.
            "keepalives": 1,
            "keepalives_idle": 300,
            "keepalives_interval": 60,
            "keepalives_count": 8,
        }
        kwargs["pool_pre_ping"] = True
        kwargs["pool_recycle"] = 300
    engine = create_engine(url, future=True, **kwargs)
    models.Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _factory_for(url: str) -> sessionmaker:
    if url not in _SESSION_FACTORIES:
        _SESSION_FACTORIES[url] = _make_factory(url)
    return _SESSION_FACTORIES[url]


def make_session(url: str) -> SASession:
    """Opens a session bound to an arbitrary DSN (used to read the train DB)."""
    return _factory_for(url)()


def session_factory() -> sessionmaker:
    return _factory_for(config.DATABASE_URL)


def init_db() -> None:
    """Creates the live database schema. Idempotent."""
    _make_factory(config.DATABASE_URL)


def get_db():
    """FastAPI dependency yielding a live-database session."""
    db = session_factory()()
    try:
        yield db
    finally:
        db.close()