"""Engine, sessions and the tenant scope.

The application connects as a role without BYPASSRLS. Every transaction that
touches tenant data first calls ``set_tenant``; without it row level security
returns nothing and refuses every write.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

_engine: Engine | None = None
_factory: sessionmaker[Session] | None = None


def engine() -> Engine:
    global _engine, _factory
    if _engine is None:
        _engine = create_engine(get_settings().database_url, pool_pre_ping=True)
        _factory = sessionmaker(_engine, expire_on_commit=False)
    return _engine


def session_factory() -> sessionmaker[Session]:
    engine()
    assert _factory is not None
    return _factory


def reset_engine() -> None:
    global _engine, _factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _factory = None


def set_tenant(db: Session, business_id: uuid.UUID) -> None:
    db.execute(
        text("select set_config('app.current_business_id', :b, true)"),
        {"b": str(business_id)},
    )


def get_db() -> Iterator[Session]:
    """One transaction per request: commit on success, roll back on any error."""
    db = session_factory()()
    try:
        with db.begin():
            yield db
    finally:
        db.close()
