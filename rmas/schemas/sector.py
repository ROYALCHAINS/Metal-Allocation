"""schemas/sector.py — sector reference data as returned to the client.

Only sectors the caller is allowed to see are ever included; the scoping
happens in the repository's WHERE clause, not here (CLAUDE.md section 6,
rule 8). Never expose another account's scope or the administrator list
(rule 10).
"""

from pydantic import BaseModel


class AllocationSectorResponse(BaseModel):
    sector_id: int
    sector_name: str
    # Verbatim from the sheet, e.g. 'Priority 1' — see models/sector.py.
    priority: str
    purity: str
    party_name: str
    display_order: int | None


class FlowSectorResponse(BaseModel):
    flow_sector_id: int
    sector_name: str
    party_name: str
    display_order: int | None


class SectorsResponse(BaseModel):
    allocation_sectors: list[AllocationSectorResponse]
    flow_sectors: list[FlowSectorResponse]
