"""Phase 2: identity, tenancy, RBAC, SaaS plans/subscriptions + app role and Row-Level Security.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-16 17:58:43.343167+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.config import get_settings

# Tables whose rows belong to exactly one tenant (column tenant_id NOT NULL).
TENANT_TABLES = ("branches", "memberships", "user_branches", "subscriptions")


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _security_upgrade() -> None:
    s = get_settings()
    app_role = s.db_user

    # 1. Runtime role: not the owner, not superuser → RLS always applies to it.
    if app_role != s.db_migration_user:
        if not s.db_password:
            raise RuntimeError("DB_PASSWORD (app role password) must be set before running migration 0002")
        pw = _sql_literal(s.db_password)
        op.execute(
            f"""
            DO $$
            BEGIN
              IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = {_sql_literal(app_role)}) THEN
                CREATE ROLE "{app_role}" LOGIN PASSWORD {pw} NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
              ELSE
                ALTER ROLE "{app_role}" WITH LOGIN PASSWORD {pw} NOSUPERUSER NOBYPASSRLS;
              END IF;
              EXECUTE format('GRANT CONNECT ON DATABASE %I TO "{app_role}"', current_database());
            END $$;
            """
        )
        op.execute(f'GRANT USAGE ON SCHEMA public TO "{app_role}"')
        op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO "{app_role}"')
        op.execute(f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{app_role}"')
        # Tables created by later migrations get the same grants automatically.
        op.execute(
            f'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "{app_role}"'
        )
        op.execute(f'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO "{app_role}"')

    # 2. Context helpers read by every policy (set per transaction by app.core.db).
    # (asyncpg runs one statement per execute)
    op.execute(
        """
        CREATE FUNCTION app_current_tenant() RETURNS uuid LANGUAGE sql STABLE AS $$
          SELECT nullif(current_setting('app.tenant_id', true), '')::uuid
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app_rls_bypass() RETURNS boolean LANGUAGE sql STABLE AS $$
          SELECT coalesce(current_setting('app.bypass_rls', true), 'off') = 'on'
        $$
        """
    )

    # 3. Tenant-owned tables: only the current tenant's rows are visible or writable.
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            "USING (app_rls_bypass() OR tenant_id = app_current_tenant()) "
            "WITH CHECK (app_rls_bypass() OR tenant_id = app_current_tenant())"
        )

    # tenants: a tenant sees itself; anyone may read active + published restaurants (public storefront).
    op.execute("ALTER TABLE tenants ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenants FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_read ON tenants FOR SELECT "
        "USING (app_rls_bypass() OR id = app_current_tenant() OR (status = 'active' AND is_published))"
    )
    op.execute(
        "CREATE POLICY tenant_write ON tenants FOR ALL "
        "USING (app_rls_bypass() OR id = app_current_tenant()) "
        "WITH CHECK (app_rls_bypass() OR id = app_current_tenant())"
    )

    # roles: system roles (tenant_id NULL) are readable by all tenants but writable only by the platform.
    op.execute("ALTER TABLE roles ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE roles FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY role_access ON roles "
        "USING (app_rls_bypass() OR tenant_id IS NULL OR tenant_id = app_current_tenant()) "
        "WITH CHECK (app_rls_bypass() OR tenant_id = app_current_tenant())"
    )
    op.execute("ALTER TABLE role_permissions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE role_permissions FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY role_permission_access ON role_permissions "
        "USING (app_rls_bypass() OR EXISTS (SELECT 1 FROM roles r WHERE r.id = role_id)) "
        "WITH CHECK (app_rls_bypass() OR EXISTS ("
        "  SELECT 1 FROM roles r WHERE r.id = role_id AND r.tenant_id = app_current_tenant()))"
    )

    # 4. A membership may only use a system role or a role of the same tenant.
    op.execute(
        """
        CREATE FUNCTION check_membership_role() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM roles WHERE id = NEW.role_id AND (tenant_id IS NULL OR tenant_id = NEW.tenant_id)
          ) THEN
            RAISE EXCEPTION 'role % does not belong to tenant %', NEW.role_id, NEW.tenant_id
              USING ERRCODE = 'foreign_key_violation';
          END IF;
          RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER memberships_role_tenant BEFORE INSERT OR UPDATE OF role_id, tenant_id ON memberships "
        "FOR EACH ROW EXECUTE FUNCTION check_membership_role()"
    )


def _security_downgrade() -> None:
    s = get_settings()
    op.execute("DROP TRIGGER IF EXISTS memberships_role_tenant ON memberships")
    op.execute("DROP FUNCTION IF EXISTS check_membership_role()")
    # Policies are dropped with their tables; the helper functions are dropped after the tables.
    if s.db_user != s.db_migration_user:
        op.execute(
            f'ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM "{s.db_user}"'
        )
        op.execute(f'ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE USAGE, SELECT ON SEQUENCES FROM "{s.db_user}"')


revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "otp_challenges",
        sa.Column("phone", sa.String(length=16), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("purpose", sa.String(length=30), nullable=False),
        sa.Column("attempts", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_otp_challenges")),
    )
    op.create_index(op.f("ix_otp_challenges_phone"), "otp_challenges", ["phone"], unique=False)
    op.create_table(
        "permissions",
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("module", sa.String(length=40), nullable=False),
        sa.Column("description", sa.String(length=200), nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_permissions")),
    )
    op.create_table(
        "plans",
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("price_monthly", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("price_yearly", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="INR", nullable=False),
        sa.Column("trial_days", sa.SmallInteger(), server_default="14", nullable=False),
        sa.Column("is_public", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("sort_order", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("price_monthly >= 0 AND price_yearly >= 0", name=op.f("ck_plans_price_non_negative")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plans")),
        sa.UniqueConstraint("code", name=op.f("uq_plans_code")),
    )
    op.create_table(
        "tenants",
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("slug", postgresql.CITEXT(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("status_reason", sa.Text(), nullable=True),
        sa.Column("is_published", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("alcohol_licensed", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("restaurant_type", sa.String(length=60), nullable=False),
        sa.Column("cuisines", postgresql.ARRAY(sa.String(length=60)), server_default="{}", nullable=False),
        sa.Column("declared_branch_count", sa.SmallInteger(), server_default="1", nullable=False),
        sa.Column("settings", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'", name=op.f("ck_tenants_slug_format")),
        sa.CheckConstraint(
            "status IN ('pending', 'active', 'suspended', 'deactivated', 'rejected')", name=op.f("ck_tenants_status")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenants")),
        sa.UniqueConstraint("slug", name=op.f("uq_tenants_slug")),
    )
    op.create_index("ix_tenants_status", "tenants", ["status"], unique=False)
    op.create_table(
        "users",
        sa.Column("phone", sa.String(length=16), nullable=True),
        sa.Column("email", postgresql.CITEXT(), nullable=True),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column("full_name", sa.String(length=120), server_default="", nullable=False),
        sa.Column("is_super_admin", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("phone_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("phone IS NOT NULL OR email IS NOT NULL", name=op.f("ck_users_has_contact")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
        sa.UniqueConstraint("phone", name=op.f("uq_users_phone")),
    )
    op.create_table(
        "branches",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("address_line", sa.String(length=300), nullable=False),
        sa.Column("city", sa.String(length=80), nullable=False),
        sa.Column("state", sa.String(length=80), nullable=False),
        sa.Column("country", sa.String(length=80), nullable=False),
        sa.Column("postal_code", sa.String(length=20), nullable=True),
        sa.Column("lat", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("lng", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("timezone", sa.String(length=60), server_default="Asia/Kolkata", nullable=False),
        sa.Column("phone", sa.String(length=16), nullable=True),
        sa.Column("is_primary", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_branches_tenant_id_tenants"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_branches")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_branches_tenant_id_id"),
    )
    op.create_index("uq_branches_one_primary", "branches", ["tenant_id"], unique=True, postgresql_where="is_primary")
    op.create_table(
        "plan_features",
        sa.Column("plan_id", sa.UUID(), nullable=False),
        sa.Column("feature_key", sa.String(length=60), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("limit_value", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["plan_id"], ["plans.id"], name=op.f("fk_plan_features_plan_id_plans"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("plan_id", "feature_key", name=op.f("pk_plan_features")),
    )
    op.create_table(
        "refresh_tokens",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("family_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_agent", sa.String(length=300), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_refresh_tokens_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refresh_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_refresh_tokens_token_hash")),
    )
    op.create_index(op.f("ix_refresh_tokens_family_id"), "refresh_tokens", ["family_id"], unique=False)
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"], unique=False)
    op.create_table(
        "roles",
        sa.Column("tenant_id", sa.UUID(), nullable=True),
        sa.Column("key", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("description", sa.String(length=200), nullable=True),
        sa.Column("is_system", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_roles_tenant_id_tenants"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_roles")),
        sa.UniqueConstraint("tenant_id", "key", name="uq_roles_tenant_id_key", postgresql_nulls_not_distinct=True),
    )
    op.create_table(
        "subscriptions",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("plan_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("billing_cycle", sa.String(length=10), server_default="monthly", nullable=False),
        sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("billing_cycle IN ('monthly', 'yearly')", name=op.f("ck_subscriptions_billing_cycle")),
        sa.CheckConstraint(
            "status IN ('trialing', 'active', 'past_due', 'cancelled', 'expired')", name=op.f("ck_subscriptions_status")
        ),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.id"], name=op.f("fk_subscriptions_plan_id_plans")),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_subscriptions_tenant_id_tenants"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_subscriptions")),
    )
    op.create_index(
        "uq_subscriptions_one_live_per_tenant",
        "subscriptions",
        ["tenant_id"],
        unique=True,
        postgresql_where="status IN ('trialing', 'active', 'past_due')",
    )
    op.create_table(
        "memberships",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("role_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("all_branches", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('active', 'invited', 'disabled')", name=op.f("ck_memberships_status")),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], name=op.f("fk_memberships_role_id_roles")),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_memberships_tenant_id_tenants"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_memberships_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_memberships")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_memberships_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_memberships_tenant_id_user_id"),
    )
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"], unique=False)
    op.create_table(
        "role_permissions",
        sa.Column("role_id", sa.UUID(), nullable=False),
        sa.Column("permission_key", sa.String(length=80), nullable=False),
        sa.Column("scope", sa.String(length=20), server_default="all", nullable=False),
        sa.ForeignKeyConstraint(
            ["permission_key"],
            ["permissions.key"],
            name=op.f("fk_role_permissions_permission_key_permissions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["role_id"], ["roles.id"], name=op.f("fk_role_permissions_role_id_roles"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("role_id", "permission_key", name=op.f("pk_role_permissions")),
    )
    op.create_table(
        "user_branches",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("membership_id", sa.UUID(), nullable=False),
        sa.Column("branch_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "branch_id"],
            ["branches.tenant_id", "branches.id"],
            name=op.f("fk_user_branches_tenant_id_branch_id_branches"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name=op.f("fk_user_branches_tenant_id_membership_id_memberships"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("membership_id", "branch_id", name=op.f("pk_user_branches")),
    )
    # ### end Alembic commands ###
    _security_upgrade()


def downgrade() -> None:
    _security_downgrade()
    op.drop_table("user_branches")
    op.drop_table("role_permissions")
    op.drop_index("ix_memberships_user_id", table_name="memberships")
    op.drop_table("memberships")
    op.drop_index(
        "uq_subscriptions_one_live_per_tenant",
        table_name="subscriptions",
        postgresql_where="status IN ('trialing', 'active', 'past_due')",
    )
    op.drop_table("subscriptions")
    op.drop_table("roles")
    op.drop_index("ix_refresh_tokens_user_id", table_name="refresh_tokens")
    op.drop_index(op.f("ix_refresh_tokens_family_id"), table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
    op.drop_table("plan_features")
    op.drop_index("uq_branches_one_primary", table_name="branches", postgresql_where="is_primary")
    op.drop_table("branches")
    op.drop_table("users")
    op.drop_index("ix_tenants_status", table_name="tenants")
    op.drop_table("tenants")
    op.drop_table("plans")
    op.drop_table("permissions")
    op.drop_index(op.f("ix_otp_challenges_phone"), table_name="otp_challenges")
    op.drop_table("otp_challenges")
    op.execute("DROP FUNCTION IF EXISTS app_current_tenant()")
    op.execute("DROP FUNCTION IF EXISTS app_rls_bypass()")
