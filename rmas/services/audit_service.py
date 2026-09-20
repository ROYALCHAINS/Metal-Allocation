"""
services/audit_service.py
Royal Metal Allocation System — Python port of AuditService.gs's writing half.

Every write is audited — successes, blocked attempts and failures alike
(CLAUDE.md section 6, rule 14). The log is append-only (rule 13).

IDENTITY RESOLUTION IS NOT HERE. Legacy's AuditService.gs also owned
isAdministrator_()/getActiveUserEmail_(), which made the audit file load-bearing
for authorization. That belongs in services/scope_service.py and lives there.

AUDITING MUST NEVER BLOCK OR REVERSE A COMPLETED BUSINESS OPERATION — legacy
swallows audit-write failures and logs them rather than failing the save. That
behaviour is preserved in write_entry_safely(); use it after a write has already
committed, and the plain write_entry() when the audit is part of the
transaction being decided.
"""

import json
import logging
import random
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from models.audit import MetalAllocationAuditLog
from repository import audit_repo
from services.date_service import APP_TIMEZONE
from services.weight_service import grams_to_kg

logger = logging.getLogger(__name__)

# Legacy's AUDIT_ACTIONS plus the three StagingService.gs writes to the same log.
ACTION_SAVE = "SAVE"
ACTION_REVISE = "REVISE"
ACTION_BLOCKED_DUPLICATE = "BLOCKED_DUPLICATE"
ACTION_FAILED_SAVE = "FAILED_SAVE"
ACTION_FAILED_REVISION = "FAILED_REVISION"
ACTION_UNAUTHORIZED_REVISION = "UNAUTHORIZED_REVISION"

# The three StagingService.gs writes to the same log, resolved lazily there by
# stagingAuditAction_(). Already permitted by the action_type CHECK.
ACTION_SUBMIT_REQUIREMENT = "SUBMIT_REQUIREMENT"
ACTION_BLOCKED_RESUBMISSION = "BLOCKED_RESUBMISSION"
ACTION_FAILED_SUBMISSION = "FAILED_SUBMISSION"

STATUS_SUCCESS = "SUCCESS"
STATUS_BLOCKED = "BLOCKED"
STATUS_FAILED = "FAILED"


def generate_audit_id() -> str:
    """Ports generateAuditId_(): 'AUD-yyyyMMdd-HHmmss-NNNN'."""
    stamp = datetime.now(ZoneInfo(APP_TIMEZONE)).strftime("%Y%m%d-%H%M%S")
    return f"AUD-{stamp}-{random.randint(1000, 9999)}"


def _kg_text(grams: int) -> str:
    """Snapshots record kilograms as strings — exact, human-readable, and no
    float ever enters the JSON."""
    return str(grams_to_kg(grams))


def snapshot_allocations(rows) -> str:
    """Compact JSON snapshot. Abbreviated keys are legacy's, kept so snapshots
    stay comparable with the Apps Script build's audit log."""
    if not rows:
        return ""
    return json.dumps(
        [
            {
                "p": row.priority,
                "s": row.sector_name,
                "pu": row.purity,
                "pr": _kg_text(row.previous_requirement_g),
                "tr": _kg_text(row.today_required_g),
                "al": _kg_text(row.alloted_g),
                "bl": _kg_text(row.balance_g),
            }
            for row in rows
        ]
    )


def snapshot_flow(rows) -> str:
    if not rows:
        return ""
    return json.dumps(
        [{"s": row.sector_name, "ac": _kg_text(row.today_acquired_g)} for row in rows]
    )


@dataclass
class AuditEntry:
    allocation_date: str
    action_type: str
    action_status: str
    user_email: str
    revision_number: int = 0
    reason: str | None = None
    previous_allocation_data: str | None = None
    updated_allocation_data: str | None = None
    previous_metal_flow_data: str | None = None
    updated_metal_flow_data: str | None = None
    request_id: str | None = None


def write_entry(db: Session, entry: AuditEntry) -> str:
    """Append one audit row and return its audit_id."""
    row = MetalAllocationAuditLog(
        audit_id=generate_audit_id(),
        allocation_date=entry.allocation_date,
        action_type=entry.action_type,
        action_status=entry.action_status,
        revision_number=entry.revision_number,
        user_email=entry.user_email,
        revision_reason=entry.reason,
        previous_allocation_data=entry.previous_allocation_data,
        updated_allocation_data=entry.updated_allocation_data,
        previous_metal_flow_data=entry.previous_metal_flow_data,
        updated_metal_flow_data=entry.updated_metal_flow_data,
        request_id=entry.request_id,
    )
    audit_repo.insert_entry(db, row)
    return row.audit_id


def write_entry_safely(db: Session, entry: AuditEntry) -> str:
    """As write_entry(), but never raises.

    Ports legacy's comment: "Auditing must never block or reverse a completed
    business operation." Use this only where the business write has already
    succeeded — a failure here is logged loudly and swallowed. Where the audit
    is part of the decision (a blocked or failed attempt), use write_entry().
    """
    try:
        return write_entry(db, entry)
    except Exception:  # noqa: BLE001 — deliberately never propagates
        logger.exception(
            "AUDIT WRITE FAILED date=%s action=%s", entry.allocation_date, entry.action_type
        )
        return ""


def get_latest_revision_number(db: Session, allocation_date: str) -> int:
    return audit_repo.get_latest_revision_number(db, allocation_date)
