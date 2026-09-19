"""
models package — SQLAlchemy ORM table definitions only.

No business logic here (see CLAUDE.md's layering table). Every model is
imported here so Alembic's autogenerate can discover them via Base.metadata.
"""

from rmas.database import Base
from rmas.models.party import Party
from rmas.models.sector import AllocationSector, FlowSector
from rmas.models.allocation import AllocationRecord
from rmas.models.flow import FlowRecord
from rmas.models.staging import StagingRequirement
from rmas.models.audit import AuditLogEntry
from rmas.models.user import User, UserFlowScope, UserPartyScope
from rmas.models.idempotency import IdempotencyKey

__all__ = [
    "Base",
    "Party",
    "AllocationSector",
    "FlowSector",
    "AllocationRecord",
    "FlowRecord",
    "StagingRequirement",
    "AuditLogEntry",
    "User",
    "UserPartyScope",
    "UserFlowScope",
    "IdempotencyKey",
]
