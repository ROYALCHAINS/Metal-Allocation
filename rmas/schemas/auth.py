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
