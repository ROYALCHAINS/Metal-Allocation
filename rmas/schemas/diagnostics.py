"""
schemas/diagnostics.py — reduced-scope ports of DiagnosticsService.gs
(sheet-layout inspection, meaningless once the schema is explicit SQL) and
VersionCheck.gs (build-marker diagnostic, meaningless once code lives in
git). What survives: confirming what the running app + database actually
contain, and previewing another user's resolved scope (previewScopeFor).
"""

from pydantic import BaseModel


class VersionInfoOut(BaseModel):
    app_name: str
    app_version: str
    database_connected: bool
    app_timezone: str


class SchemaInspectionOut(BaseModel):
    """SQL-schema equivalent of describeDetectedSchema()/inspectAllLayouts()."""

    allocation_sector_count: int
    expected_allocation_rows: int
    flow_sector_count: int
    expected_flow_rows: int
    party_count: int
    distinct_saved_dates: int
    counts_match_expectation: bool


class ScopePreviewOut(BaseModel):
    """Legacy previewScopeFor()."""

    email: str
    display_name: str
    role: str
    is_admin: bool
    parties: list[str]
    allocation_sectors_visible: int
    allocation_sector_names: list[str]
    flow_sectors_visible: int
    flow_sector_names: list[str]
    can_edit_alloted: bool
    can_save_date: bool
