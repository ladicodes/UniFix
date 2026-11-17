"""Base Pydantic models.

Field names are the wire names (snake_case). Unknown fields are rejected so that a
misspelled or camelCase field fails loudly with 422 instead of being ignored.
Whitespace stripping is opt-in per field type (passwords must never be altered).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class APIModel(BaseModel):
    """Request bodies."""

    model_config = ConfigDict(extra="forbid")


class ResponseModel(BaseModel):
    """Response bodies."""

    model_config = ConfigDict(from_attributes=True)
