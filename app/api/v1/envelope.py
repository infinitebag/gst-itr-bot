# app/api/v1/envelope.py
"""
Standardized API response envelope used by all v1 endpoints.

Every response wraps data in:
    {
        "status": "ok" | "error",
        "data": <payload>,
        "message": <optional string>,
        "errors": <optional list of detail dicts>
    }
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """Standard envelope for all v1 API responses."""

    status: str = "ok"
    data: T | None = None
    message: str | None = None
    errors: list[dict[str, Any]] | None = None


class PaginatedData(BaseModel, Generic[T]):
    """Wrapper for paginated list responses."""

    items: list[T]
    total: int
    limit: int
    offset: int
    has_more: bool


class PaginationParams(BaseModel):
    """Query parameters for paginated endpoints (use as Depends)."""

    limit: int = Field(default=20, ge=1, le=100, description="Items per page")
    offset: int = Field(default=0, ge=0, description="Number of items to skip")


# ---------------------------------------------------------------------------
# Helpers for building responses
# ---------------------------------------------------------------------------

def ok(data: Any = None, message: str | None = None) -> dict:
    """Build a success response dict."""
    return ApiResponse(status="ok", data=data, message=message).model_dump()


def error(message: str, errors: list[dict[str, Any]] | None = None, status: str = "error") -> dict:
    """Build an error response dict."""
    return ApiResponse(status=status, message=message, errors=errors).model_dump()


def paginated(items: list, total: int, limit: int, offset: int) -> dict:
    """Build a paginated success response dict."""
    page = PaginatedData(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
        has_more=(offset + limit) < total,
    )
    return ApiResponse(status="ok", data=page).model_dump()
