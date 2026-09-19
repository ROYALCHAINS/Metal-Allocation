"""Initial schema

Hand-authored (no live Postgres connection was available in the environment
this port was written in to run `alembic revision --autogenerate`), built
directly from rmas/models/. Run `alembic upgrade head` against a real
database and confirm it matches before relying on it; regenerate with
autogenerate against a running instance if anything drifts.

Revision ID: 0001
Revises:
Create Date: 2026-09-19

"""

from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

WEIGHT = sa.Numeric(12, 3)


def upgrade() -> None:
    op.create_table(
        "parties",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("party_key", sa.String(200), nullable=False),
        sa.Column("party_name", sa.String(200), nullable=False),
    )
    op.create_index("ix_parties_party_key", "parties", ["party_key"], unique=True)

    op.create_table(
        "allocation_sectors",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("sector_key", sa.String(200), nullable=False),
        sa.Column("sector_name", sa.String(200), nullable=False),
        sa.Column("priority", sa.String(50), nullable=False, server_default=""),
        sa.Column("purity", sa.String(100), nullable=False, server_default="Any"),
        sa.Column("party_id", sa.Integer, sa.ForeignKey("parties.id"), nullable=True),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_index("ix_allocation_sectors_sector_key", "allocation_sectors", ["sector_key"], unique=True)

    op.create_table(
        "flow_sectors",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("sector_key", sa.String(200), nullable=False),
        sa.Column("sector_name", sa.String(200), nullable=False),
        sa.Column("party_id", sa.Integer, sa.ForeignKey("parties.id"), nullable=True),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_index("ix_flow_sectors_sector_key", "flow_sectors", ["sector_key"], unique=True)

    op.create_table(
        "allocations",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("allocation_date", sa.Date, nullable=False),
        sa.Column("sector_id", sa.Integer, sa.ForeignKey("allocation_sectors.id"), nullable=False),
        sa.Column("priority", sa.String(50), nullable=False, server_default=""),
        sa.Column("purity", sa.String(100), nullable=False, server_default="Any"),
        sa.Column("previous_requirement", WEIGHT, nullable=False),
        sa.Column("today_required", WEIGHT, nullable=False),
        sa.Column("alloted", WEIGHT, nullable=False),
        sa.Column("balance", WEIGHT, nullable=False),
        sa.UniqueConstraint("allocation_date", "sector_id", name="uq_allocation_date_sector"),
        sa.CheckConstraint("today_required >= 0", name="ck_allocation_today_required_nonneg"),
        sa.CheckConstraint("alloted >= 0", name="ck_allocation_alloted_nonneg"),
    )
    op.create_index("ix_allocations_allocation_date", "allocations", ["allocation_date"])

    op.create_table(
        "metal_flow",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("flow_date", sa.Date, nullable=False),
        sa.Column("flow_sector_id", sa.Integer, sa.ForeignKey("flow_sectors.id"), nullable=False),
        sa.Column("acquired", WEIGHT, nullable=False),
        sa.UniqueConstraint("flow_date", "flow_sector_id", name="uq_flow_date_sector"),
        sa.CheckConstraint("acquired >= 0", name="ck_flow_acquired_nonneg"),
    )
    op.create_index("ix_metal_flow_flow_date", "metal_flow", ["flow_date"])

    op.create_table(
        "staging_requirements",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("submission_id", sa.String(80), nullable=False),
        sa.Column("allocation_date", sa.Date, nullable=False),
        sa.Column("party_id", sa.Integer, sa.ForeignKey("parties.id"), nullable=False),
        sa.Column("operator_email", sa.String(320), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("record_type", sa.String(20), nullable=False),
        sa.Column("sector_key", sa.String(200), nullable=False),
        sa.Column("value", WEIGHT, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="SUBMITTED"),
    )
    op.create_index("ix_staging_requirements_submission_id", "staging_requirements", ["submission_id"])
    op.create_index("ix_staging_requirements_allocation_date", "staging_requirements", ["allocation_date"])

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("audit_id", sa.String(40), nullable=False),
        sa.Column("allocation_date", sa.Date, nullable=True),
        sa.Column("action_type", sa.String(40), nullable=False),
        sa.Column("revision_number", sa.Integer, nullable=False, server_default="0"),
        sa.Column("user_email", sa.String(320), nullable=False),
        sa.Column("action_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.Text, nullable=False, server_default=""),
        sa.Column("previous_allocation_data", sa.JSON, nullable=True),
        sa.Column("updated_allocation_data", sa.JSON, nullable=True),
        sa.Column("previous_flow_data", sa.JSON, nullable=True),
        sa.Column("updated_flow_data", sa.JSON, nullable=True),
        sa.Column("request_id", sa.String(120), nullable=False, server_default=""),
        sa.Column("action_status", sa.String(20), nullable=False),
    )
    op.create_index("ix_audit_log_audit_id", "audit_log", ["audit_id"], unique=True)
    op.create_index("ix_audit_log_allocation_date", "audit_log", ["allocation_date"])
    op.create_index("ix_audit_log_action_type", "audit_log", ["action_type"])
    op.create_index("ix_audit_log_action_timestamp", "audit_log", ["action_timestamp"])
    op.create_index("ix_audit_log_request_id", "audit_log", ["request_id"])

    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("role", sa.String(20), nullable=False, server_default="OPERATOR"),
        sa.Column("admin_denied", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "user_party_scope",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("party_id", sa.Integer, sa.ForeignKey("parties.id"), nullable=False),
        sa.UniqueConstraint("user_id", "party_id", name="uq_user_party_scope"),
    )

    op.create_table(
        "user_flow_scope",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("flow_sector_id", sa.Integer, sa.ForeignKey("flow_sectors.id"), nullable=False),
        sa.UniqueConstraint("user_id", "flow_sector_id", name="uq_user_flow_scope"),
    )

    op.create_table(
        "idempotency_keys",
        sa.Column("request_id", sa.String(120), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("idempotency_keys")
    op.drop_table("user_flow_scope")
    op.drop_table("user_party_scope")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
    op.drop_index("ix_audit_log_request_id", table_name="audit_log")
    op.drop_index("ix_audit_log_action_timestamp", table_name="audit_log")
    op.drop_index("ix_audit_log_action_type", table_name="audit_log")
    op.drop_index("ix_audit_log_allocation_date", table_name="audit_log")
    op.drop_index("ix_audit_log_audit_id", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_index("ix_staging_requirements_allocation_date", table_name="staging_requirements")
    op.drop_index("ix_staging_requirements_submission_id", table_name="staging_requirements")
    op.drop_table("staging_requirements")
    op.drop_index("ix_metal_flow_flow_date", table_name="metal_flow")
    op.drop_table("metal_flow")
    op.drop_index("ix_allocations_allocation_date", table_name="allocations")
    op.drop_table("allocations")
    op.drop_index("ix_flow_sectors_sector_key", table_name="flow_sectors")
    op.drop_table("flow_sectors")
    op.drop_index("ix_allocation_sectors_sector_key", table_name="allocation_sectors")
    op.drop_table("allocation_sectors")
    op.drop_index("ix_parties_party_key", table_name="parties")
    op.drop_table("parties")
