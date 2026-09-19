"""
common.py — shared response shapes. No {ok, code, message, data} envelope
here (that legacy pattern is replaced by real HTTP status codes plus
routers/exception_handlers.py translating services/exceptions.py); these
are just genuinely reusable fragments.
"""

from decimal import Decimal

from pydantic import BaseModel


class PartyOut(BaseModel):
    party_key: str
    party_name: str

    model_config = {"from_attributes": True}


class PageInfo(BaseModel):
    current_page: int
    total_pages: int
    page_size: int
    offset: int
    total_records: int
    first_record: int
    last_record: int
    has_previous: bool
    has_next: bool


class ErrorResponse(BaseModel):
    code: str
    message: str
