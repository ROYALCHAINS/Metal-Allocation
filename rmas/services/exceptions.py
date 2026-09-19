"""
exceptions.py — domain exceptions raised by the services/ layer.

Legacy equivalent: ValidationService.gs's appError_() (a machine `code` plus
a safe `userMessage`) and handleServerError_() (never leaks a stack trace to
the browser). Here the same two-part shape (code + safe message) is kept,
but as real Python exceptions instead of an {ok,code,message,data} envelope,
per CLAUDE.md's layering rule: services raise these, routers translate them
to HTTP responses, and services never import HTTPException.
"""


class DomainError(Exception):
    """Base for every exception a service is allowed to raise."""

    code: str = "ERROR"
    default_status: int = 400

    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code


class ValidationError(DomainError):
    """Malformed or out-of-range input. Legacy: INVALID_*, *_TOO_LARGE, etc."""

    code = "VALIDATION_ERROR"
    default_status = 400


class AuthenticationError(DomainError):
    """Missing or invalid Google ID token. Distinct from ScopeError (403):
    this means WHO you are could not be established at all, not that the
    identity you have is disallowed."""

    code = "NOT_AUTHENTICATED"
    default_status = 401


class ScopeError(DomainError):
    """
    The caller has no party/sector scope for what they asked for, or is not
    authorized for the action at all. Legacy: NOT_AUTHORIZED, NO_PARTY_ASSIGNED,
    SECTOR_NOT_IN_SCOPE.
    """

    code = "SCOPE_ERROR"
    default_status = 403


class NotFoundError(DomainError):
    """Legacy: DATE_NOT_SAVED, AUDIT_ENTRY_NOT_FOUND."""

    code = "NOT_FOUND"
    default_status = 404


class ConflictError(DomainError):
    """
    A date is already saved / already submitted / cannot be revised. Legacy:
    DATE_ALREADY_SAVED, ALREADY_SUBMITTED, DATE_ALREADY_FINALISED.
    """

    code = "CONFLICT"
    default_status = 409


class DuplicateRequestError(DomainError):
    """
    A request_id was replayed inside the idempotency window. Legacy:
    DUPLICATE_REQUEST — the router should treat this as "already handled",
    not as a hard failure; see routers/allocations.py.
    """

    code = "DUPLICATE_REQUEST"
    default_status = 409


class LockTimeoutError(DomainError):
    """Legacy: LOCK_TIMEOUT (LockService.getScriptLock, 30s)."""

    code = "LOCK_TIMEOUT"
    default_status = 503
