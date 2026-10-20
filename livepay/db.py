"""Database engine, session factory, and declarative base.

We use SQLAlchemy 2.x style: a typed `DeclarativeBase` and `Session` objects
created per unit of work. FastAPI endpoints get a session via `get_db`.
"""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from livepay.config import settings

engine = create_engine(settings.database_url, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


class Base(DeclarativeBase):
    """Declarative base all ORM models inherit from."""


def get_db() -> Iterator[Session]:
    """FastAPI dependency: yield a session and always close it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
