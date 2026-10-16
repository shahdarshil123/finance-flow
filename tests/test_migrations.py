"""Migrations must apply and reverse cleanly on a real PostgreSQL database."""

import pytest
from alembic import command
from sqlalchemy import Engine, inspect

from tests.conftest import TEST_DATABASE_URL, alembic_config

pytestmark = pytest.mark.integration


def test_migrations_downgrade_and_upgrade_cleanly(db_engine: Engine) -> None:
    config = alembic_config(TEST_DATABASE_URL)

    command.downgrade(config, "base")
    assert {"suppliers", "invoices"}.isdisjoint(inspect(db_engine).get_table_names())

    # Leaves the schema at head for the rest of the test session.
    command.upgrade(config, "head")
    inspector = inspect(db_engine)
    assert {"suppliers", "invoices"} <= set(inspector.get_table_names())

    supplier_uniques = {c["name"] for c in inspector.get_unique_constraints("suppliers")}
    assert "uq_suppliers_tax_id" in supplier_uniques

    invoice_uniques = {
        c["name"]: c["column_names"] for c in inspector.get_unique_constraints("invoices")
    }
    assert invoice_uniques["uq_invoices_supplier_id_invoice_number_normalized"] == [
        "supplier_id",
        "invoice_number_normalized",
    ]
    (foreign_key,) = inspector.get_foreign_keys("invoices")
    assert foreign_key["name"] == "fk_invoices_supplier_id_suppliers"
    assert foreign_key.get("options", {}).get("ondelete") == "RESTRICT"


def test_invoices_downgrade_keeps_suppliers(db_engine: Engine) -> None:
    config = alembic_config(TEST_DATABASE_URL)

    command.downgrade(config, "-1")
    tables = set(inspect(db_engine).get_table_names())
    command.upgrade(config, "head")

    assert "suppliers" in tables
    assert "invoices" not in tables
