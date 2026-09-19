"""schemas/auth.py — identity/access shapes. Legacy: getCurrentUserAccess()."""

from pydantic import BaseModel


class CurrentUserOut(BaseModel):
    email: str
    display_name: str
    is_admin: bool
    role: str
