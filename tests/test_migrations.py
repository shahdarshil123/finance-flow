"""Migrations must apply and reverse cleanly on a real PostgreSQL database."""

import uuid

import pytest
from alembic import command
from sqlalchemy import Engine, inspect, text

from tests.conftest import TEST_DATABASE_URL, alembic_config

pytestmark = pytest.mark.integration

SUPPLIERS_REVISION = "7f3851a76ffd"
INVOICES_REVISION = "75baa5d9d606"


def test_migrations_downgrade_and_upgrade_cleanly(db_engine: Engine) -> None:
    config = alembic_config(TEST_DATABASE_URL)

    command.downgrade(config, "base")
    assert {"suppliers", "invoices"}.isdisjoint(inspect(db_engine).get_table_names())

    # Leaves the schema at head for the rest of the test session.
    command.upgrade(config, "head")
    inspector = inspect(db_engine)
    assert {"suppliers", "invoices"} <= set(inspector.get_table_names())

    supplier_uniques = {
        c["name"]: c["column_names"] for c in inspector.get_unique_constraints("suppliers")
    }
    assert supplier_uniques["uq_suppliers_tax_id"] == ["tax_id"]
    assert supplier_uniques["uq_suppliers_external_erp_id"] == ["external_erp_id"]
    supplier_checks = {c["name"] for c in inspector.get_check_constraints("suppliers")}
    assert "ck_suppliers_external_erp_id_not_blank" in supplier_checks

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

    command.downgrade(config, SUPPLIERS_REVISION)
    tables = set(inspect(db_engine).get_table_names())
    command.upgrade(config, "head")

    assert "suppliers" in tables
    assert "invoices" not in tables


def test_external_erp_id_migration_preserves_suppliers_and_invoices(db_engine: Engine) -> None:
    """Upgrade and downgrade of the ERP-id column keep existing rows and their links."""
    config = alembic_config(TEST_DATABASE_URL)
    supplier_id, invoice_id = uuid.uuid4(), uuid.uuid4()

    command.downgrade(config, INVOICES_REVISION)
    try:
        with db_engine.begin() as connection:
            connection.execute(
                text("INSERT INTO suppliers (id, name) VALUES (:id, 'Migration Test Supplier')"),
                {"id": supplier_id},
            )
            connection.execute(
                text(
                    "INSERT INTO invoices (id, supplier_id, invoice_number, invoice_date, "
                    "due_date, currency, total_amount) VALUES (:id, :supplier_id, 'MIG-1', "
                    "'2026-01-01', '2026-01-31', 'EUR', 10.00)"
                ),
                {"id": invoice_id, "supplier_id": supplier_id},
            )

        command.upgrade(config, "head")
        with db_engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT i.supplier_id, s.external_erp_id FROM invoices i "
                    "JOIN suppliers s ON s.id = i.supplier_id WHERE i.id = :id"
                ),
                {"id": invoice_id},
            ).one()
        assert row.supplier_id == supplier_id
        assert row.external_erp_id is None  # existing suppliers start unmapped

        command.downgrade(config, INVOICES_REVISION)
        columns = {c["name"] for c in inspect(db_engine).get_columns("suppliers")}
        assert "external_erp_id" not in columns
        with db_engine.connect() as connection:
            linked = connection.scalar(
                text("SELECT supplier_id FROM invoices WHERE id = :id"), {"id": invoice_id}
            )
        assert linked == supplier_id
    finally:
        command.upgrade(config, "head")
        with db_engine.begin() as connection:
            connection.execute(text("DELETE FROM invoices WHERE id = :id"), {"id": invoice_id})
            connection.execute(text("DELETE FROM suppliers WHERE id = :id"), {"id": supplier_id})
