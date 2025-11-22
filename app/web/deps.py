"""FastAPI dependencies for the web layer."""
from contextlib import contextmanager
from typing import Generator

from sqlalchemy.orm import Session

from app.db.base import SessionLocal


@contextmanager
def _session_scope() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    finally:
        session.close()


def get_db() -> Generator[Session, None, None]:
    """Provide a database session for request handling."""

    with _session_scope() as session:
        yield session
