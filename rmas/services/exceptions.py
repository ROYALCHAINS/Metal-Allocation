"""
services/exceptions.py
Royal Metal Allocation System — Python port

Domain exceptions raised by services and translated to HTTP by routers.
Services never import HTTPException (CLAUDE.md section 3).

`code` carries the legacy error codes verbatim (`INVALID_NUMBER`,
`NEGATIVE_VALUE`, `DATE_ALREADY_SAVED`, …) so responses stay comparable with
the Apps Script build during the port.
"""


class RmasError(Exception):
    """Base for every domain error. Ports legacy's appError_()."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ValidationError(RmasError):
    """Bad or inconsistent input. Maps to HTTP 400."""


class ScopeError(RmasError):
    """The caller may not see or touch this party/sector. Maps to HTTP 403."""


class NotAuthorizedError(RmasError):
    """The caller lacks the role for this action. Maps to HTTP 403."""


class DuplicateRequestError(RmasError):
    """A repeat of an already-processed request_id. Maps to HTTP 409."""


class DateAlreadySavedError(RmasError):
    """The date is already committed; revise it instead. Maps to HTTP 409."""


class LockTimeoutError(RmasError):
    """Another write holds the per-date lock. Maps to HTTP 409."""
