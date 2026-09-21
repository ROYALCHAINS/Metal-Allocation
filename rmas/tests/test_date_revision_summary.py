"""tests/test_date_revision_summary.py — one allocation date's commit history.

Ports getDateRevisionSummary() (AuditReportService.gs:517). The rules that are
easy to get wrong and are pinned here:

  * "Originally saved by" is the FIRST save of the date, never the latest.
  * Only SUCCESS entries count — a failed or blocked revision never happened.
  * The reason comes back WHOLE, not previewed like the audit list's.

NOTE ON COVERAGE. The port has no revise path yet, so no REVISE row can be
written by the application and every live audit row carries revision_number 0.
The revision half is therefore driven by hand-inserted rows here, the same
technique test_audit_access.py already uses. The originally-saved half is the
only half backed by real data today.
"""

import re

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from models.audit import MetalAllocationAuditLog
from services.audit_report_service import get_date_revision_summary

DATE = "2026-09-01"
TIMESTAMP_DISPLAY = re.compile(r"^\d{2}-[A-Z][a-z]{2}-\d{4} \d{2}:\d{2}:\d{2}$")


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _entry(
    db,
    *,
    audit_id,
    action_type,
    status="SUCCESS",
    user="admin@royalchains.com",
    timestamp="2026-09-01 10:00:00",
    revision_number=0,
    reason=None,
    allocation_date=DATE,
):
    db.add(
        MetalAllocationAuditLog(
            audit_id=audit_id,
            allocation_date=allocation_date,
            action_type=action_type,
            action_status=status,
            revision_number=revision_number,
            user_email=user,
            action_timestamp=timestamp,
            revision_reason=reason,
        )
    )
    db.flush()


def test_a_date_with_no_audit_history_reports_nothing(db_session) -> None:
    summary = get_date_revision_summary(db_session, DATE)

    assert summary.revision_count == 0
    assert summary.latest_revision_number == 0
    assert summary.last_revised_by is None
    assert summary.originally_saved_by is None
    assert summary.message == "This date has not been revised."


def test_the_original_save_is_the_first_one_not_the_latest(db_session) -> None:
    """Legacy sorts saves ASCENDING and takes [0] (AuditReportService.gs:531)."""
    _entry(db_session, audit_id="AUD-1", action_type="SAVE", user="first@x.com",
           timestamp="2026-09-01 09:00:00")
    _entry(db_session, audit_id="AUD-2", action_type="SAVE", user="later@x.com",
           timestamp="2026-09-01 17:00:00")

    summary = get_date_revision_summary(db_session, DATE)
    assert summary.originally_saved_by == "first@x.com"


def test_the_last_revision_is_the_newest_one(db_session) -> None:
    _entry(db_session, audit_id="AUD-1", action_type="SAVE", timestamp="2026-09-01 09:00:00")
    _entry(db_session, audit_id="AUD-2", action_type="REVISE", revision_number=1,
           user="one@x.com", timestamp="2026-09-01 11:00:00", reason="First correction.")
    _entry(db_session, audit_id="AUD-3", action_type="REVISE", revision_number=2,
           user="two@x.com", timestamp="2026-09-01 15:00:00", reason="Second correction.")

    summary = get_date_revision_summary(db_session, DATE)
    assert summary.revision_count == 2
    assert summary.latest_revision_number == 2
    assert summary.last_revised_by == "two@x.com"
    assert summary.last_revision_reason == "Second correction."
    assert summary.message == "This date has been revised 2 time(s)."


def test_failed_and_blocked_entries_never_count(db_session) -> None:
    """A revision that failed never happened — legacy filters on SUCCESS first."""
    _entry(db_session, audit_id="AUD-1", action_type="SAVE", timestamp="2026-09-01 09:00:00")
    _entry(db_session, audit_id="AUD-2", action_type="REVISE", status="FAILED",
           revision_number=1, timestamp="2026-09-01 10:00:00")
    _entry(db_session, audit_id="AUD-3", action_type="BLOCKED_RESUBMISSION",
           status="BLOCKED", timestamp="2026-09-01 11:00:00")

    summary = get_date_revision_summary(db_session, DATE)
    assert summary.revision_count == 0
    assert summary.latest_revision_number == 0
    assert summary.message == "This date has not been revised."


def test_a_submission_is_neither_a_save_nor_a_revision(db_session) -> None:
    _entry(db_session, audit_id="AUD-1", action_type="SUBMIT_REQUIREMENT",
           user="op@x.com", timestamp="2026-09-01 08:00:00")

    summary = get_date_revision_summary(db_session, DATE)
    assert summary.revision_count == 0
    assert summary.originally_saved_by is None


def test_another_date_does_not_bleed_in(db_session) -> None:
    _entry(db_session, audit_id="AUD-1", action_type="SAVE", user="ours@x.com")
    _entry(db_session, audit_id="AUD-2", action_type="REVISE", revision_number=1,
           allocation_date="2026-09-02", user="theirs@x.com")

    summary = get_date_revision_summary(db_session, DATE)
    assert summary.revision_count == 0
    assert summary.originally_saved_by == "ours@x.com"


def test_the_full_reason_is_returned_not_a_preview(db_session) -> None:
    """The audit LIST previews at 140 chars; this payload does not."""
    reason = "A" * 400
    _entry(db_session, audit_id="AUD-1", action_type="REVISE", revision_number=1,
           reason=reason)

    summary = get_date_revision_summary(db_session, DATE)
    assert summary.last_revision_reason == reason
    assert "…" not in (summary.last_revision_reason or "")


def test_entries_in_the_same_second_order_by_insertion(db_session) -> None:
    """datetime('now') has one-second granularity, so audit_row_id breaks ties.

    Without it, "the first save of this date" is not a stable answer.
    """
    _entry(db_session, audit_id="AUD-1", action_type="SAVE", user="first@x.com",
           timestamp="2026-09-01 10:00:00")
    _entry(db_session, audit_id="AUD-2", action_type="SAVE", user="second@x.com",
           timestamp="2026-09-01 10:00:00")

    summary = get_date_revision_summary(db_session, DATE)
    assert summary.originally_saved_by == "first@x.com"


def test_the_service_returns_raw_timestamps_for_the_router_to_format(db_session) -> None:
    """Formatting belongs at the HTTP boundary, as it does for submissions."""
    _entry(db_session, audit_id="AUD-1", action_type="SAVE",
           timestamp="2026-09-01 10:00:00")

    summary = get_date_revision_summary(db_session, DATE)
    assert summary.originally_saved_at == "2026-09-01 10:00:00"
    assert not TIMESTAMP_DISPLAY.match(summary.originally_saved_at)
