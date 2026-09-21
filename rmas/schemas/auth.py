"""schemas/auth.py — auth-related request/response models.

Never return the administrator list or another account's scope to the
client (CLAUDE.md section 6, rule 10) — CurrentUserResponse exposes only
the caller's own identity.
"""

from typing import Literal

from pydantic import BaseModel


class LoginRequest(BaseModel):
    email: str
    password: str


class CurrentUserResponse(BaseModel):
    email: str
    display_name: str
    # Derived server-side from is_admin AND the deny list — never read straight
    # off the row, since a denied admin must report as an operator.
    role: Literal["admin", "operator"]


class AccessDiagnosticsResponse(BaseModel):
    """Why the server treats THIS caller the way it does.

    Ports the surviving half of diagnoseAdminAccess() (AuditReportService.gs:42).
    Four legacy fields are deliberately absent:

      * configuredAdmins / forcedNonAdmins — the administrator roster and the
        deny list. Rule 10 forbids the first outright, and the second is worse,
        since it names specifically revoked individuals.
      * activeUser / effectiveUser / scriptRunsAs — Apps Script session
        artefacts. No Google dependency remains (rule 11).

    Legacy could afford the roster because the function ran only from the Apps
    Script editor. An HTTP route has no such containment, so the payload is
    restricted to the caller's own row. There is no subject parameter for the
    same reason: diagnosing somebody else would be "another account's scope".
    """

    email: str
    display_name: str
    # Effective, with the deny list applied — not the raw is_admin column.
    is_administrator: bool
    # This account's own deny flag. Never the list it mirrors.
    admin_denied: bool
    is_active: bool
    # Party names in the caller's OWN scope.
    parties: list[str]
    flow_scope: str
    diagnosis: list[str]
