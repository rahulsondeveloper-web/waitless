"""Phase 12 security review: Row-Level Security on the platform tables that carry a tenant_id.

These tables are read through the platform (system) scope, so this changes nothing for the app — it is
defence in depth: a tenant-scoped query can never see another restaurant's WaitLess invoices, payments,
support tickets or audit entries, even by mistake. Audit inserts may carry no tenant (platform actions).

refresh_tokens and outbox_events stay platform-only (identity / delivery internals, never tenant-queried).

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-17 17:00:00+00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STRICT = ("saas_invoices", "saas_payments", "support_tickets")


def upgrade() -> None:
    for table in STRICT:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            "USING (app_rls_bypass() OR tenant_id = app_current_tenant()) "
            "WITH CHECK (app_rls_bypass() OR tenant_id = app_current_tenant())"
        )
    op.execute("ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_logs FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON audit_logs "
        "USING (app_rls_bypass() OR tenant_id = app_current_tenant()) "
        "WITH CHECK (app_rls_bypass() OR tenant_id IS NULL OR tenant_id = app_current_tenant())"
    )


def downgrade() -> None:
    for table in (*STRICT, "audit_logs"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
