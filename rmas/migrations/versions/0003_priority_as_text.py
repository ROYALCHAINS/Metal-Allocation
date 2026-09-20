"""store priority verbatim as TEXT instead of INTEGER

Resolved 2026-09-20. The Metal Generator sheet writes priority as
'Priority 1'…'Priority 6', and legacy keeps it a string and shows it to users
unchanged — ReportService.gs uses it as the filter-dropdown label (line 204),
the "by priority" dashboard grouping key (line 587) and in text search
(line 107). Storing an integer meant reconstructing that wording for display, so
both `sector.priority` and `metal_master.priority_snapshot` become TEXT and hold
exactly what the sheet says. A departure from schema.sql's INTEGER, recorded in
CLAUDE.md rule 17a.

The `.badge--p1`…`.badge--p6` CSS class is derived from the label client-side,
matching the first digit exactly as legacy's priorityClass() does, so no numeric
column is needed.

SQLite cannot ALTER a column type in place, so batch mode rebuilds the table:
it creates a copy, drops the original and renames. A VIEW that references the
table breaks that rename ("error in view v_allocation_kg: no such table:
main.sector"), so the views are dropped first and recreated afterwards,
identical to their definitions in migration 0002.

After running this, re-run `python seed_reference_data.py` to load the verbatim
labels from the CSV, which is the authoritative source. This migration
deliberately does NOT synthesise 'Priority ' + n from the old integers — that
would be inventing wording rather than reading it from the sheet.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-20

"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

_V_ALLOCATION_KG = """
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

_V_FLOW_KG = """
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

_V_CLOSING_BALANCE = """
CREATE VIEW v_closing_balance_by_date AS
SELECT
    allocation_date,
    party_id,
    SUM(balance_g)           AS balance_g,
    SUM(balance_g) / 1000.0  AS balance_kg
FROM metal_master
GROUP BY allocation_date, party_id
"""


def _drop_views() -> None:
    op.execute("DROP VIEW IF EXISTS v_closing_balance_by_date")
    op.execute("DROP VIEW IF EXISTS v_flow_kg")
    op.execute("DROP VIEW IF EXISTS v_allocation_kg")


def _create_views() -> None:
    op.execute(_V_ALLOCATION_KG)
    op.execute(_V_FLOW_KG)
    op.execute(_V_CLOSING_BALANCE)


def upgrade() -> None:
    # A previously failed run of this migration can leave alembic's working
    # copy behind; clearing it makes the migration safe to re-run.
    op.execute("DROP TABLE IF EXISTS _alembic_tmp_sector")
    op.execute("DROP TABLE IF EXISTS _alembic_tmp_metal_master")

    _drop_views()

    with op.batch_alter_table("sector") as batch:
        batch.alter_column(
            "priority", existing_type=sa.Integer(), type_=sa.Text(), existing_nullable=False
        )

    with op.batch_alter_table("metal_master") as batch:
        batch.alter_column(
            "priority_snapshot",
            existing_type=sa.Integer(),
            type_=sa.Text(),
            existing_nullable=False,
        )

    _create_views()


def downgrade() -> None:
    # Reverting to INTEGER will not round-trip a non-numeric label such as
    # 'Priority 1' — which is precisely why TEXT was chosen. Re-seed from the
    # CSV afterwards if a downgrade is ever genuinely needed.
    _drop_views()

    with op.batch_alter_table("metal_master") as batch:
        batch.alter_column(
            "priority_snapshot",
            existing_type=sa.Text(),
            type_=sa.Integer(),
            existing_nullable=False,
        )

    with op.batch_alter_table("sector") as batch:
        batch.alter_column(
            "priority", existing_type=sa.Text(), type_=sa.Integer(), existing_nullable=False
        )

    _create_views()
