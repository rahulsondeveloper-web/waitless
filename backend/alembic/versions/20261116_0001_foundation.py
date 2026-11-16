"""Phase 1 foundation: extensions, outbox, idempotency keys, audit log.

Revision ID: 0001
Revises:
Create Date: 2026-11-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def _id() -> sa.Column:
    return sa.Column("id", UUID, primary_key=True, server_default=sa.text("uuidv7()"))


def _created() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def upgrade() -> None:
    # Trusted extensions: the database owner can create them without superuser.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")  # reservation overlap exclusion (Phase 6)
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")  # case-insensitive emails/slugs (Phase 2)
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")  # fuzzy restaurant/menu search (Phase 4)

    op.create_table(
        "outbox_events",
        _id(),
        sa.Column("tenant_id", UUID, nullable=True),
        sa.Column("event", sa.String(100), nullable=False),
        sa.Column("room", sa.String(200), nullable=True),
        sa.Column("payload", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.SmallInteger, nullable=False, server_default="0"),
        _created(),
        sa.PrimaryKeyConstraint("id", name="pk_outbox_events"),
    )
    op.create_index(
        "ix_outbox_events_pending", "outbox_events", ["created_at"], postgresql_where=sa.text("dispatched_at IS NULL")
    )

    op.create_table(
        "idempotency_keys",
        _id(),
        sa.Column("scope", sa.String(200), nullable=False),
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("response_status", sa.SmallInteger, nullable=True),
        sa.Column("response_body", postgresql.JSONB, nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        _created(),
        sa.PrimaryKeyConstraint("id", name="pk_idempotency_keys"),
        sa.UniqueConstraint("scope", "key", name="uq_idempotency_keys_scope_key"),
    )

    op.create_table(
        "audit_logs",
        _id(),
        sa.Column("tenant_id", UUID, nullable=True),
        sa.Column("actor_user_id", UUID, nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("entity", sa.String(100), nullable=False),
        sa.Column("entity_id", sa.String(64), nullable=True),
        sa.Column("diff", postgresql.JSONB, nullable=True),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("ip", postgresql.INET, nullable=True),
        sa.Column("request_id", sa.String(64), nullable=True),
        _created(),
        sa.PrimaryKeyConstraint("id", name="pk_audit_logs"),
    )
    op.create_index("ix_audit_logs_tenant_id", "audit_logs", ["tenant_id"])
    op.create_index("ix_audit_logs_actor_user_id", "audit_logs", ["actor_user_id"])

    # Audit rows are append-only.
    op.execute(
        """
        CREATE FUNCTION forbid_update_delete() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION '% on % is not allowed (append-only table)', TG_OP, TG_TABLE_NAME
            USING ERRCODE = 'restrict_violation';
        END $$;
        """
    )
    op.execute(
        "CREATE TRIGGER audit_logs_append_only BEFORE UPDATE OR DELETE ON audit_logs "
        "FOR EACH ROW EXECUTE FUNCTION forbid_update_delete()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_logs_append_only ON audit_logs")
    op.execute("DROP FUNCTION IF EXISTS forbid_update_delete()")
    op.drop_table("audit_logs")
    op.drop_table("idempotency_keys")
    op.drop_index("ix_outbox_events_pending", table_name="outbox_events")
    op.drop_table("outbox_events")
    # Extensions are left installed; other objects may depend on them.
