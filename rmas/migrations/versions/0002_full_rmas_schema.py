"""full RMAS schema: reference data, ledgers, audit, staging, idempotency

Implements the supplied schema.sql (see DATABASE_OVERVIEW.md), with two
deliberate, documented departures restoring legacy fidelity — see
models/audit.py (action_type list) and models/staging.py (status vocabulary) —
plus app_user.password_hash, which schema.sql predates.

The existing `users` table from 0001 is superseded by `app_user`; its rows are
copied across before it is dropped, so accounts created before this migration
keep working.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-20

"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

_DATE_CHECK = "allocation_date IS strftime('%Y-%m-%d', allocation_date)"

_AUDIT_ACTIONS = (
    "'SAVE', 'REVISE', 'BLOCKED_DUPLICATE', 'FAILED_SAVE', 'FAILED_REVISION', "
    "'UNAUTHORIZED_REVISION', 'SUBMIT_REQUIREMENT', 'BLOCKED_RESUBMISSION', "
    "'FAILED_SUBMISSION'"
)


def upgrade() -> None:
    # ---------------------------------------------------------------- reference
    op.create_table(
        "party",
        sa.Column("party_id", sa.Integer(), primary_key=True),
        sa.Column("party_name", sa.Text(), nullable=False, unique=True),
        sa.Column("party_key", sa.Text(), nullable=False, unique=True),
        sa.Column("is_active", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "created_at", sa.Text(), nullable=False, server_default=sa.text("(datetime('now'))")
        ),
        sa.CheckConstraint("is_active IN (0, 1)", name="ck_party_is_active"),
    )

    op.create_table(
        "sector",
        sa.Column("sector_id", sa.Integer(), primary_key=True),
        sa.Column("sector_name", sa.Text(), nullable=False, unique=True),
        sa.Column("sector_key", sa.Text(), nullable=False, unique=True),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("purity", sa.Text(), nullable=False),
        sa.Column("party_id", sa.Integer(), sa.ForeignKey("party.party_id"), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "created_at", sa.Text(), nullable=False, server_default=sa.text("(datetime('now'))")
        ),
        sa.CheckConstraint("is_active IN (0, 1)", name="ck_sector_is_active"),
    )
    op.create_index("idx_sector_party", "sector", ["party_id"])
    op.create_index("idx_sector_priority", "sector", ["priority"])

    op.create_table(
        "flow_sector",
        sa.Column("flow_sector_id", sa.Integer(), primary_key=True),
        sa.Column("sector_name", sa.Text(), nullable=False, unique=True),
        sa.Column("sector_key", sa.Text(), nullable=False, unique=True),
        sa.Column("party_id", sa.Integer(), sa.ForeignKey("party.party_id"), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "created_at", sa.Text(), nullable=False, server_default=sa.text("(datetime('now'))")
        ),
        sa.CheckConstraint("is_active IN (0, 1)", name="ck_flow_sector_is_active"),
    )
    op.create_index("idx_flow_sector_party", "flow_sector", ["party_id"])

    # ------------------------------------------------------- identity and scope
    op.create_table(
        "app_user",
        sa.Column("user_id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.Text(), nullable=False, unique=True),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("is_admin", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("admin_denied", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("is_active", sa.Integer(), nullable=False, server_default=sa.text("1")),
        # Addition to schema.sql, which predates the username/password decision.
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.Text(), nullable=False, server_default=sa.text("(datetime('now'))")
        ),
        sa.CheckConstraint("is_admin IN (0, 1)", name="ck_app_user_is_admin"),
        sa.CheckConstraint("admin_denied IN (0, 1)", name="ck_app_user_admin_denied"),
        sa.CheckConstraint("is_active IN (0, 1)", name="ck_app_user_is_active"),
    )

    # Carry existing accounts across from 0001's `users` table before dropping it.
    op.execute(
        """
        INSERT INTO app_user (email, display_name, is_admin, admin_denied, is_active, password_hash)
        SELECT email,
               display_name,
               CASE WHEN UPPER(role) = 'ADMIN' THEN 1 ELSE 0 END,
               is_denied,
               1,
               password_hash
        FROM users
        """
    )
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")

    op.create_table(
        "user_party_scope",
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("app_user.user_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "party_id",
            sa.Integer(),
            sa.ForeignKey("party.party_id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )

    op.create_table(
        "user_flow_scope",
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("app_user.user_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "flow_sector_id",
            sa.Integer(),
            sa.ForeignKey("flow_sector.flow_sector_id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )

    # ----------------------------------------------------------------- ledgers
    op.create_table(
        "metal_master",
        sa.Column("allocation_id", sa.Integer(), primary_key=True),
        sa.Column("allocation_date", sa.Text(), nullable=False),
        sa.Column("sector_id", sa.Integer(), sa.ForeignKey("sector.sector_id"), nullable=False),
        sa.Column("party_id", sa.Integer(), sa.ForeignKey("party.party_id"), nullable=False),
        sa.Column("priority_snapshot", sa.Integer(), nullable=False),
        sa.Column("purity_snapshot", sa.Text(), nullable=False),
        sa.Column(
            "previous_requirement_g", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("today_required_g", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("alloted_g", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("balance_g", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("revision_number", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("saved_by", sa.Text(), nullable=False),
        sa.Column(
            "saved_at", sa.Text(), nullable=False, server_default=sa.text("(datetime('now'))")
        ),
        sa.CheckConstraint(_DATE_CHECK, name="ck_master_date_format"),
        sa.UniqueConstraint("allocation_date", "sector_id", name="uq_master_date_sector"),
    )
    op.create_index("idx_master_date", "metal_master", ["allocation_date"])
    op.create_index("idx_master_date_party", "metal_master", ["allocation_date", "party_id"])
    op.create_index("idx_master_party_date", "metal_master", ["party_id", "allocation_date"])
    op.create_index("idx_master_sector_date", "metal_master", ["sector_id", "allocation_date"])

    op.create_table(
        "metal_flow_master",
        sa.Column("flow_id", sa.Integer(), primary_key=True),
        sa.Column("allocation_date", sa.Text(), nullable=False),
        sa.Column(
            "flow_sector_id",
            sa.Integer(),
            sa.ForeignKey("flow_sector.flow_sector_id"),
            nullable=False,
        ),
        sa.Column("party_id", sa.Integer(), sa.ForeignKey("party.party_id"), nullable=False),
        sa.Column("acquired_g", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("revision_number", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("saved_by", sa.Text(), nullable=False),
        sa.Column(
            "saved_at", sa.Text(), nullable=False, server_default=sa.text("(datetime('now'))")
        ),
        sa.CheckConstraint(_DATE_CHECK, name="ck_flow_date_format"),
        sa.CheckConstraint("acquired_g >= 0", name="ck_flow_acquired_non_negative"),
        sa.UniqueConstraint("allocation_date", "flow_sector_id", name="uq_flow_date_sector"),
    )
    op.create_index("idx_flow_date", "metal_flow_master", ["allocation_date"])
    op.create_index("idx_flow_date_party", "metal_flow_master", ["allocation_date", "party_id"])
    op.create_index("idx_flow_party_date", "metal_flow_master", ["party_id", "allocation_date"])

    # --------------------------------------------------------------- audit log
    op.create_table(
        "metal_allocation_audit_log",
        sa.Column("audit_row_id", sa.Integer(), primary_key=True),
        sa.Column("audit_id", sa.Text(), nullable=False, unique=True),
        sa.Column("allocation_date", sa.Text(), nullable=False),
        sa.Column("action_type", sa.Text(), nullable=False),
        sa.Column("action_status", sa.Text(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("user_email", sa.Text(), nullable=False),
        sa.Column(
            "action_timestamp",
            sa.Text(),
            nullable=False,
            server_default=sa.text("(datetime('now'))"),
        ),
        sa.Column("revision_reason", sa.Text(), nullable=True),
        sa.Column("previous_allocation_data", sa.Text(), nullable=True),
        sa.Column("updated_allocation_data", sa.Text(), nullable=True),
        sa.Column("previous_metal_flow_data", sa.Text(), nullable=True),
        sa.Column("updated_metal_flow_data", sa.Text(), nullable=True),
        sa.Column("request_id", sa.Text(), nullable=True),
        sa.CheckConstraint(_DATE_CHECK, name="ck_audit_date_format"),
        sa.CheckConstraint(f"action_type IN ({_AUDIT_ACTIONS})", name="ck_audit_action_type"),
        sa.CheckConstraint(
            "action_status IN ('SUCCESS', 'BLOCKED', 'FAILED')", name="ck_audit_action_status"
        ),
    )
    op.create_index("idx_audit_date", "metal_allocation_audit_log", ["allocation_date"])
    op.create_index("idx_audit_timestamp", "metal_allocation_audit_log", ["action_timestamp"])
    op.create_index("idx_audit_user", "metal_allocation_audit_log", ["user_email"])
    op.create_index("idx_audit_action", "metal_allocation_audit_log", ["action_type"])
    op.create_index("idx_audit_request", "metal_allocation_audit_log", ["request_id"])

    # Append-only enforced by the database, not merely by convention (rule 13).
    op.execute(
        """
        CREATE TRIGGER trg_audit_no_update
        BEFORE UPDATE ON metal_allocation_audit_log
        BEGIN
            SELECT RAISE(ABORT, 'audit log is append-only: UPDATE is not permitted');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_audit_no_delete
        BEFORE DELETE ON metal_allocation_audit_log
        BEGIN
            SELECT RAISE(ABORT, 'audit log is append-only: DELETE is not permitted');
        END
        """
    )

    # ----------------------------------------------------------------- staging
    op.create_table(
        "metal_requirement_staging",
        sa.Column("staging_id", sa.Integer(), primary_key=True),
        sa.Column("submission_id", sa.Text(), nullable=False),
        sa.Column("allocation_date", sa.Text(), nullable=False),
        sa.Column("party_id", sa.Integer(), sa.ForeignKey("party.party_id"), nullable=False),
        sa.Column("operator_email", sa.Text(), nullable=False),
        sa.Column(
            "submitted_at", sa.Text(), nullable=False, server_default=sa.text("(datetime('now'))")
        ),
        sa.Column("record_type", sa.Text(), nullable=False),
        sa.Column("sector_id", sa.Integer(), sa.ForeignKey("sector.sector_id"), nullable=True),
        sa.Column(
            "flow_sector_id",
            sa.Integer(),
            sa.ForeignKey("flow_sector.flow_sector_id"),
            nullable=True,
        ),
        sa.Column("value_g", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'SUBMITTED'")),
        sa.CheckConstraint(_DATE_CHECK, name="ck_staging_date_format"),
        sa.CheckConstraint("record_type IN ('ALLOCATION', 'FLOW')", name="ck_staging_record_type"),
        sa.CheckConstraint("status IN ('SUBMITTED', 'CONSUMED')", name="ck_staging_status"),
        sa.CheckConstraint(
            "(record_type = 'ALLOCATION' AND sector_id IS NOT NULL AND flow_sector_id IS NULL)"
            " OR (record_type = 'FLOW' AND flow_sector_id IS NOT NULL AND sector_id IS NULL)",
            name="ck_staging_exactly_one_sector",
        ),
    )
    op.create_index("idx_staging_date", "metal_requirement_staging", ["allocation_date"])
    op.create_index(
        "idx_staging_date_party", "metal_requirement_staging", ["allocation_date", "party_id"]
    )
    op.create_index("idx_staging_operator", "metal_requirement_staging", ["operator_email"])

    # ------------------------------------------------------------- idempotency
    op.create_table(
        "request_log",
        sa.Column("request_id", sa.Text(), primary_key=True),
        sa.Column("user_email", sa.Text(), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("response_json", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.Text(), nullable=False, server_default=sa.text("(datetime('now'))")
        ),
    )
    op.create_index("idx_request_created", "request_log", ["created_at"])

    # ------------------------------------------------------------------- views
    op.execute(
        """
        CREATE VIEW v_allocation_kg AS
        SELECT
            m.allocation_id,
            m.allocation_date,
            s.sector_name,
            p.party_name,
            m.priority_snapshot                AS priority,
            m.purity_snapshot                  AS purity,
            m.previous_requirement_g / 1000.0  AS previous_requirement_kg,
            m.today_required_g       / 1000.0  AS today_required_kg,
            m.alloted_g              / 1000.0  AS alloted_kg,
            m.balance_g              / 1000.0  AS balance_kg,
            m.revision_number
        FROM metal_master m
        JOIN sector s ON s.sector_id = m.sector_id
        JOIN party  p ON p.party_id  = m.party_id
        """
    )
    op.execute(
        """
        CREATE VIEW v_flow_kg AS
        SELECT
            f.flow_id,
            f.allocation_date,
            fs.sector_name,
            p.party_name,
            f.acquired_g / 1000.0 AS acquired_kg,
            f.revision_number
        FROM metal_flow_master f
        JOIN flow_sector fs ON fs.flow_sector_id = f.flow_sector_id
        JOIN party       p  ON p.party_id        = f.party_id
        """
    )
    op.execute(
        """
        CREATE VIEW v_closing_balance_by_date AS
        SELECT
            allocation_date,
            party_id,
            SUM(balance_g)           AS balance_g,
            SUM(balance_g) / 1000.0  AS balance_kg
        FROM metal_master
        GROUP BY allocation_date, party_id
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS v_closing_balance_by_date")
    op.execute("DROP VIEW IF EXISTS v_flow_kg")
    op.execute("DROP VIEW IF EXISTS v_allocation_kg")

    op.drop_table("request_log")
    op.drop_table("metal_requirement_staging")

    op.execute("DROP TRIGGER IF EXISTS trg_audit_no_delete")
    op.execute("DROP TRIGGER IF EXISTS trg_audit_no_update")
    op.drop_table("metal_allocation_audit_log")

    op.drop_table("metal_flow_master")
    op.drop_table("metal_master")
    op.drop_table("user_flow_scope")
    op.drop_table("user_party_scope")

    # Recreate 0001's users table and copy accounts back, so a downgrade does
    # not silently discard logins.
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(length=320), nullable=False, unique=True),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("role", sa.Enum("admin", "operator", name="user_role"), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_denied", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.execute(
        """
        INSERT INTO users (email, display_name, role, password_hash, is_denied)
        SELECT email,
               COALESCE(display_name, email),
               CASE WHEN is_admin = 1 THEN 'ADMIN' ELSE 'OPERATOR' END,
               password_hash,
               admin_denied
        FROM app_user
        """
    )
    op.drop_table("app_user")

    op.drop_table("flow_sector")
    op.drop_table("sector")
    op.drop_table("party")
