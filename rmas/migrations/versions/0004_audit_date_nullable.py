"""allow an audit entry with no allocation date

Resolved 2026-09-20. The Audit Log page spec (PROMPT_audit_log.md, rule 4) says
an entry with NO allocation date must never be excluded by the date window: it
is a hard failure that happened before the date could be resolved, which is
exactly the kind of event the log exists to record. `audit_repo` already
implements that filter, but the supplied schema.sql made `allocation_date`
NOT NULL with a date-format CHECK, so no such row could be written in the first
place and the rule was unreachable.

This makes the column nullable and relaxes the CHECK to `allocation_date IS
NULL OR <format test>`, so a NULL is permitted while a malformed date is still
rejected. A departure from schema.sql, recorded in CLAUDE.md rule 17a.

SQLite cannot drop NOT NULL or alter a CHECK in place, so the table is rebuilt
by hand rather than with batch_alter_table. Doing it manually is deliberate:
batch mode reflects the existing table, and a reflected CHECK constraint is
exactly the thing being changed here. The append-only triggers are dropped and
recreated because SQLite drops a table's triggers along with the table.

No VIEW references this table, so unlike migration 0003 there are no views to
juggle.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-20

"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

_COLUMNS = """
    audit_row_id, audit_id, allocation_date, action_type, action_status,
    revision_number, user_email, action_timestamp, revision_reason,
    previous_allocation_data, updated_allocation_data,
    previous_metal_flow_data, updated_metal_flow_data, request_id
"""

_INDEXES = (
    ("idx_audit_date", "allocation_date"),
    ("idx_audit_timestamp", "action_timestamp"),
    ("idx_audit_user", "user_email"),
    ("idx_audit_action", "action_type"),
    ("idx_audit_request", "request_id"),
)

_ACTION_TYPES = (
    "'SAVE', 'REVISE', 'BLOCKED_DUPLICATE', 'FAILED_SAVE', 'FAILED_REVISION', "
    "'UNAUTHORIZED_REVISION', 'SUBMIT_REQUIREMENT', 'BLOCKED_RESUBMISSION', "
    "'FAILED_SUBMISSION'"
)


def _table(date_clause: str, *, nullable: bool) -> str:
    null_sql = "" if nullable else " NOT NULL"
    return f"""
        CREATE TABLE _rmas_audit_rebuild (
            audit_row_id INTEGER NOT NULL,
            audit_id TEXT NOT NULL,
            allocation_date TEXT{null_sql},
            action_type TEXT NOT NULL,
            action_status TEXT NOT NULL,
            revision_number INTEGER DEFAULT 0 NOT NULL,
            user_email TEXT NOT NULL,
            action_timestamp TEXT DEFAULT (datetime('now')) NOT NULL,
            revision_reason TEXT,
            previous_allocation_data TEXT,
            updated_allocation_data TEXT,
            previous_metal_flow_data TEXT,
            updated_metal_flow_data TEXT,
            request_id TEXT,
            PRIMARY KEY (audit_row_id),
            CONSTRAINT ck_audit_date_format CHECK ({date_clause}),
            CONSTRAINT ck_audit_action_type CHECK (action_type IN ({_ACTION_TYPES})),
            CONSTRAINT ck_audit_action_status
                CHECK (action_status IN ('SUCCESS', 'BLOCKED', 'FAILED')),
            UNIQUE (audit_id)
        )
    """


def _drop_triggers() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_audit_no_update")
    op.execute("DROP TRIGGER IF EXISTS trg_audit_no_delete")


def _create_triggers() -> None:
    """Append-only enforced by the database, not merely by convention (rule 13)."""
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


def _rebuild(date_clause: str, *, nullable: bool, select_date: str) -> None:
    # A previously failed run can leave the working copy behind; clearing it
    # first makes the migration safe to re-run.
    op.execute("DROP TABLE IF EXISTS _rmas_audit_rebuild")

    # Dropped before the swap: SQLite drops a table's triggers with the table,
    # so leaving them would silently lose the append-only guarantee.
    _drop_triggers()

    op.execute(_table(date_clause, nullable=nullable))
    op.execute(
        f"""
        INSERT INTO _rmas_audit_rebuild ({_COLUMNS})
        SELECT
            audit_row_id, audit_id, {select_date}, action_type, action_status,
            revision_number, user_email, action_timestamp, revision_reason,
            previous_allocation_data, updated_allocation_data,
            previous_metal_flow_data, updated_metal_flow_data, request_id
        FROM metal_allocation_audit_log
        """
    )
    op.execute("DROP TABLE metal_allocation_audit_log")
    op.execute("ALTER TABLE _rmas_audit_rebuild RENAME TO metal_allocation_audit_log")

    for name, column in _INDEXES:
        op.execute(f"CREATE INDEX {name} ON metal_allocation_audit_log ({column})")
    _create_triggers()


def upgrade() -> None:
    _rebuild(
        "allocation_date IS NULL OR allocation_date IS strftime('%Y-%m-%d', allocation_date)",
        nullable=True,
        select_date="allocation_date",
    )


def downgrade() -> None:
    """Undated entries cannot survive a downgrade — the column becomes NOT NULL
    again. They are written as the empty string rather than dropped, so no audit
    row is ever lost; the log is append-only in both directions.

    Note the empty string does not satisfy the restored CHECK, so a downgrade
    with undated rows present will fail rather than corrupt the table. That is
    the intended outcome: decide what those rows should say before going back.
    """
    _rebuild(
        "allocation_date IS strftime('%Y-%m-%d', allocation_date)",
        nullable=False,
        select_date="COALESCE(allocation_date, '')",
    )
