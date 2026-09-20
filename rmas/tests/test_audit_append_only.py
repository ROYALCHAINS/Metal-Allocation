"""tests/test_audit_append_only.py — the audit log is append-only in the DATABASE.

CLAUDE.md section 6, rule 13. Convention isn't enough: these tests run the
migration against a temporary SQLite file and prove the triggers actually abort
an UPDATE and a DELETE, and that the action_type CHECK accepts every action
legacy emits — including the three staging actions the supplied schema.sql
omitted (see models/audit.py).
"""

import sqlite3
from pathlib import Path

import pytest

from models.audit import AUDIT_ACTION_TYPES

_INSERT = """
    INSERT INTO metal_allocation_audit_log
        (audit_id, allocation_date, action_type, action_status, user_email)
    VALUES (?, '2026-08-17', ?, ?, 'admin@royalchains.com')
"""


@pytest.fixture()
def audit_db(tmp_path: Path):
    """A SQLite file with the real schema applied by Alembic."""
    from alembic import command
    from alembic.config import Config

    db_path = tmp_path / "audit_test.db"
    alembic_ini = Path(__file__).resolve().parent.parent / "alembic.ini"

    config = Config(str(alembic_ini))
    config.set_main_option("script_location", str(alembic_ini.parent / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    command.upgrade(config, "head")

    conn = sqlite3.connect(db_path)
    yield conn
    conn.close()


def test_insert_is_allowed(audit_db) -> None:
    audit_db.execute(_INSERT, ("AUD-1", "SAVE", "SUCCESS"))
    audit_db.commit()
    assert audit_db.execute("SELECT COUNT(*) FROM metal_allocation_audit_log").fetchone()[0] == 1


def test_update_is_rejected_by_trigger(audit_db) -> None:
    audit_db.execute(_INSERT, ("AUD-2", "SAVE", "SUCCESS"))
    audit_db.commit()

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        audit_db.execute(
            "UPDATE metal_allocation_audit_log SET action_status = 'FAILED' WHERE audit_id = 'AUD-2'"
        )


def test_delete_is_rejected_by_trigger(audit_db) -> None:
    audit_db.execute(_INSERT, ("AUD-3", "SAVE", "SUCCESS"))
    audit_db.commit()

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        audit_db.execute("DELETE FROM metal_allocation_audit_log WHERE audit_id = 'AUD-3'")


@pytest.mark.parametrize("action_type", AUDIT_ACTION_TYPES)
def test_every_legacy_action_type_is_accepted(audit_db, action_type: str) -> None:
    """Includes SUBMIT_REQUIREMENT/BLOCKED_RESUBMISSION/FAILED_SUBMISSION, which
    schema.sql's CHECK omitted and which staging will emit once ported."""
    status = "SUCCESS" if action_type in ("SAVE", "REVISE", "SUBMIT_REQUIREMENT") else "FAILED"
    audit_db.execute(_INSERT, (f"AUD-{action_type}", action_type, status))
    audit_db.commit()


def test_unknown_action_type_is_rejected(audit_db) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        audit_db.execute(_INSERT, ("AUD-BAD", "NOT_A_REAL_ACTION", "SUCCESS"))
        audit_db.commit()


def test_malformed_date_is_rejected(audit_db) -> None:
    """allocation_date must be strict YYYY-MM-DD (schema.sql date design note)."""
    with pytest.raises(sqlite3.IntegrityError):
        audit_db.execute(
            """
            INSERT INTO metal_allocation_audit_log
                (audit_id, allocation_date, action_type, action_status, user_email)
            VALUES ('AUD-DATE', '17/08/2026', 'SAVE', 'SUCCESS', 'a@b.com')
            """
        )
        audit_db.commit()
