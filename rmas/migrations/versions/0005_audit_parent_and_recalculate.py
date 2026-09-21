"""Audit log: parent_audit_id, and RECALCULATE as an action type.

The forward cascade (PROMPT_edit_saved_date.md) writes one audit entry per later
date it recomputes, each linked to the REVISE entry that caused it. That needs
two things this table does not have: a new action value, and a column to hold
the link.

WHY A HAND-ROLLED REBUILD RATHER THAN add_column + batch_alter_table.

Adding `parent_audit_id` on its own would be a plain ALTER TABLE ADD COLUMN,
which is safe here — that is DDL, and the append-only triggers are BEFORE UPDATE
and BEFORE DELETE on rows, so they do not fire. But widening
`ck_audit_action_type` to admit 'RECALCULATE' cannot be done in place: SQLite
has no ALTER CONSTRAINT. So the table is rebuilt once, doing both jobs.

The rebuild is written out by hand, exactly as migration 0004 does, and for the
same reason: `migrations/env.py` sets render_as_batch for SQLite, so autogenerate
will happily suggest op.batch_alter_table — and batch mode rebuilds the table
WITHOUT recreating the triggers, silently discarding the append-only guarantee
(rule 13). The triggers are therefore dropped and recreated explicitly below.

No VIEW references this table, so unlike migration 0003 there are no views to
juggle.

`parent_audit_id` is deliberately NOT a foreign key — see the note in
models/audit.py.
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

# The fourteen columns that existed before this migration. parent_audit_id is
# absent on purpose: every historical row gets NULL for it.
_COLUMNS_BEFORE = """
    audit_row_id, audit_id, allocation_date, action_type, action_status,
    revision_number, user_email, action_timestamp, revision_reason,
    previous_allocation_data, updated_allocation_data,
    previous_metal_flow_data, updated_metal_flow_data, request_id
"""

_INDEXES_BEFORE = (
    ("idx_audit_date", "allocation_date"),
    ("idx_audit_timestamp", "action_timestamp"),
    ("idx_audit_user", "user_email"),
    ("idx_audit_action", "action_type"),
    ("idx_audit_request", "request_id"),
)

_INDEXES_AFTER = _INDEXES_BEFORE + (("idx_audit_parent", "parent_audit_id"),)

_ACTIONS_BEFORE = (
    "'SAVE', 'REVISE', 'BLOCKED_DUPLICATE', 'FAILED_SAVE', 'FAILED_REVISION', "
    "'UNAUTHORIZED_REVISION', 'SUBMIT_REQUIREMENT', 'BLOCKED_RESUBMISSION', "
    "'FAILED_SUBMISSION'"
)

_ACTIONS_AFTER = f"{_ACTIONS_BEFORE}, 'RECALCULATE'"

_DATE_CLAUSE = (
    "allocation_date IS NULL OR "
    "allocation_date IS strftime('%Y-%m-%d', allocation_date)"
)


def _table(*, actions: str, with_parent: bool) -> str:
    parent_sql = "\n            parent_audit_id TEXT," if with_parent else ""
    return f"""
        CREATE TABLE _rmas_audit_rebuild (
            audit_row_id INTEGER NOT NULL,
            audit_id TEXT NOT NULL,
            allocation_date TEXT,
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
            request_id TEXT,{parent_sql}
            PRIMARY KEY (audit_row_id),
            CONSTRAINT ck_audit_date_format CHECK ({_DATE_CLAUSE}),
            CONSTRAINT ck_audit_action_type CHECK (action_type IN ({actions})),
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


def _rebuild(*, actions: str, with_parent: bool, indexes) -> None:
    # A previously failed run can leave the working copy behind; clearing it
    # first makes the migration safe to re-run.
    op.execute("DROP TABLE IF EXISTS _rmas_audit_rebuild")

    # Dropped before the swap: SQLite drops a table's triggers with the table,
    # so leaving them would silently lose the append-only guarantee.
    _drop_triggers()

    op.execute(_table(actions=actions, with_parent=with_parent))
    # Only the pre-existing fourteen columns are copied, in both directions —
    # going up, parent_audit_id defaults to NULL; coming down, it is dropped.
    op.execute(
        f"""
        INSERT INTO _rmas_audit_rebuild ({_COLUMNS_BEFORE})
        SELECT {_COLUMNS_BEFORE}
        FROM metal_allocation_audit_log
        """
    )
    op.execute("DROP TABLE metal_allocation_audit_log")
    op.execute("ALTER TABLE _rmas_audit_rebuild RENAME TO metal_allocation_audit_log")

    for name, column in indexes:
        op.execute(f"CREATE INDEX {name} ON metal_allocation_audit_log ({column})")
    _create_triggers()


def upgrade() -> None:
    _rebuild(actions=_ACTIONS_AFTER, with_parent=True, indexes=_INDEXES_AFTER)


def downgrade() -> None:
    """Refuses while any RECALCULATE row exists.

    Those rows cannot be honestly carried backwards. Rewriting them to REVISE
    would retroactively inflate the Revisions KPI, which counts administrator
    edits; deleting them is forbidden outright, in both directions — the log is
    append-only. So the migration stops and asks for a decision instead.
    """
    remaining = (
        op.get_bind()
        .exec_driver_sql(
            "SELECT COUNT(*) FROM metal_allocation_audit_log "
            "WHERE action_type = 'RECALCULATE'"
        )
        .scalar()
    )
    if remaining:
        raise RuntimeError(
            f"{remaining} RECALCULATE audit entries exist. Decide what they should "
            "say before downgrading: they cannot become REVISE (that would inflate "
            "the Revisions KPI) and they cannot be deleted (the log is append-only)."
        )

    _rebuild(actions=_ACTIONS_BEFORE, with_parent=False, indexes=_INDEXES_BEFORE)
