import os
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.db import get_db
from app.main import create_app
from app.suppliers.models import Supplier
from app.suppliers.schemas import SupplierCreate
from app.suppliers.service import create_supplier

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Tests use their own database, never DATABASE_URL.
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://financeflow:financeflow@localhost:5432/financeflow_test",
)


def alembic_config(database_url: str) -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.attributes["database_url"] = database_url
    return config


@pytest.fixture
def app() -> Iterator[FastAPI]:
    application = create_app()
    yield application
    application.dependency_overrides.clear()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def db_engine() -> Iterator[Engine]:
    """Test database migrated to head once per test session."""
    database_name = make_url(TEST_DATABASE_URL).database or ""
    if not database_name.endswith("_test"):
        raise RuntimeError(
            f"Refusing to run tests against database {database_name!r}: name must end in '_test'."
        )

    command.upgrade(alembic_config(TEST_DATABASE_URL), "head")
    engine = create_engine(TEST_DATABASE_URL)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine: Engine) -> Iterator[Session]:
    """Session inside an outer transaction that is rolled back after each test.

    Service-level commits become savepoint releases, so code under test keeps
    its real commit/rollback behavior while leaving no data behind.
    """
    connection = db_engine.connect()
    transaction = connection.begin()
    session = Session(
        bind=connection,
        join_transaction_mode="create_savepoint",
        autoflush=False,
        expire_on_commit=False,
    )
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def make_supplier(db_session: Session) -> Callable[..., Supplier]:
    """Factory creating synthetic suppliers through the real service."""

    def _make(name: str = "ACME Test Supplier") -> Supplier:
        return create_supplier(db_session, SupplierCreate(name=name))

    return _make


@pytest.fixture
def db_client(app: FastAPI, db_session: Session) -> Iterator[TestClient]:
    """API client whose requests use the per-test transactional session."""
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as test_client:
        yield test_client
