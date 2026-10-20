"""Shared pytest fixtures.

Database tests run against a dedicated `livepay_test` database so they never
touch dev data. Each test runs inside a transaction that is rolled back at the
end (via a SAVEPOINT), so tests are isolated and order-independent.
"""

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from livepay import models  # noqa: F401  (register tables on Base.metadata)
from livepay.config import settings
from livepay.db import Base


def _test_database_url() -> str:
    """Dev URL with the database name swapped to `<db>_test`."""
    url = make_url(settings.database_url)
    return url.set(database=f"{url.database}_test").render_as_string(hide_password=False)


def _ensure_database_exists(url: str) -> None:
    """Create the test database if it does not already exist."""
    target = make_url(url)
    admin = target.set(database="postgres")
    engine = create_engine(admin, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :name"),
            {"name": target.database},
        ).scalar()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{target.database}"'))
    engine.dispose()


@pytest.fixture(scope="session")
def engine():
    url = _test_database_url()
    _ensure_database_exists(url)
    engine = create_engine(url, future=True)
    # Build the schema directly from the models for fast test setup.
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def db_session(engine):
    """A Session wrapped in a transaction that is always rolled back."""
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, expire_on_commit=False)

    # Keep a SAVEPOINT alive so even explicit commits inside a test don't
    # persist past the outer rollback.
    session.begin_nested()

    @event.listens_for(session, "after_transaction_end")
    def _restart_savepoint(sess, trans):
        if trans.nested and not trans._parent.nested:
            sess.begin_nested()

    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
