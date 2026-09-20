"""schemas/common.py — shared response models used across routers."""

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    version: str
