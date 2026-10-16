"""Migrations must apply and reverse cleanly on a real PostgreSQL database."""

import pytest
from alembic import command
from sqlalchemy import Engine, inspect

from tests.conftest import TEST_DATABASE_URL, alembic_config

pytestmark = pytest.mark.integration


def test_migrations_downgrade_and_upgrade_cleanly(db_engine: Engine) -> None:
    config = alembic_config(TEST_DATABASE_URL)

    command.downgrade(config, "base")
    assert "suppliers" not in inspect(db_engine).get_table_names()

    # Leaves the schema at head for the rest of the test session.
    command.upgrade(config, "head")
    tables = inspect(db_engine).get_table_names()
    assert "suppliers" in tables

    constraints = {c["name"] for c in inspect(db_engine).get_unique_constraints("suppliers")}
    assert "uq_suppliers_tax_id" in constraints
