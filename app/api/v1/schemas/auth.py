# app/api/v1/schemas/auth.py
"""Request and response schemas for user authentication."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    whatsapp_number: str | None = Field(
        default=None,
        description="Optional WhatsApp number (e.g. 919876543210) to link at registration",
    )


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Access token lifetime in seconds")


class RefreshRequest(BaseModel):
    refresh_token: str


class UserProfile(BaseModel):
    id: str
    email: str | None
    name: str | None
    whatsapp_number: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class LinkWhatsAppRequest(BaseModel):
    whatsapp_number: str = Field(
        min_length=10,
        max_length=20,
        description="WhatsApp number including country code (e.g. 919876543210)",
    )
