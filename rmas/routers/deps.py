"""
deps.py — shared FastAPI dependencies: current user, resolved scope, admin gate.

Auth is Google OAuth / Workspace SSO. The frontend sends a Google ID token
as a Bearer token; this verifies its signature/audience/issuer via
google-auth, then resolves (or provisions) the matching User row.
CLAUDE.md 6.8: nothing here trusts a role or scope claim from the client —
only the verified email is taken from the token, and role/scope always come
from the database via services/scope_service.py.
"""

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from rmas.config import get_settings
from rmas.database import get_db
from rmas.models.user import User
from rmas.repository import user_repo
from rmas.services.exceptions import AuthenticationError, ScopeError
from rmas.services.scope_service import UserScope, resolve_scope


def _verify_google_id_token(token: str) -> str:
    """Returns the verified, lowercased email claim."""
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token as google_id_token

    settings = get_settings()
    try:
        claims = google_id_token.verify_oauth2_token(
            token, google_requests.Request(), settings.google_oauth_client_id
        )
    except Exception as exc:  # noqa: BLE001 — any verification failure is "not authenticated"
        raise AuthenticationError("Your sign-in could not be verified. Sign in again.", code="INVALID_TOKEN") from exc

    email = str(claims.get("email", "")).strip().lower()
    if not email or not claims.get("email_verified", False):
        raise AuthenticationError("Your Google account email is not verified.", code="EMAIL_NOT_VERIFIED")

    hosted_domain = settings.google_workspace_hosted_domain
    if hosted_domain and str(claims.get("hd", "")).lower() != hosted_domain.lower():
        raise ScopeError("Sign in with your organisation's Google Workspace account.", code="WRONG_DOMAIN")

    return email


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthenticationError("Sign in to continue.", code="NOT_AUTHENTICATED")

    email = _verify_google_id_token(authorization.split(" ", 1)[1].strip())

    user = user_repo.get_user_by_email(db, email)
    if user is None:
        user = user_repo.create_user(db, email=email)
        db.commit()
    return user


def get_current_scope(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> UserScope:
    return resolve_scope(db, user)


def require_admin(scope: UserScope = Depends(get_current_scope)) -> UserScope:
    if not scope.is_admin:
        raise ScopeError("This action requires administrator access.", code="NOT_AUTHORIZED")
    return scope
