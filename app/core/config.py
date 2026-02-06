# app/core/config.py

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Pydantic Settings v2 config
    model_config = SettingsConfigDict(
        env_file=(".env.local", ".env"),  # reads .env.local first
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- Core ----
    ENV: str = Field(default="dev")
    PORT: int = Field(default=8000)

    # ---- WhatsApp Cloud API / AiSensy ----
    WHATSAPP_VERIFY_TOKEN: str | None = None
    WHATSAPP_ACCESS_TOKEN: str | None = None
    WHATSAPP_PHONE_NUMBER_ID: str | None = None

    # AiSensy (India-first BSP)
    AISENSY_API_KEY: str = Field(default="")
    AISENSY_PROJECT_ID: str = Field(default="")

    # ---- Database ----
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/gst_itr_db"
    )

    # ---- Sarvam STT ----
    SARVAM_API_KEY: str | None = None
    SARVAM_STT_URL: str | None = None

    # ---- Bhashini ----
    BHASHINI_API_KEY: str | None = None
    BHASHINI_TRANSLATION_URL: str | None = None

    # ---- GST Sandbox (NIC / GSP) ----
    GST_SANDBOX_BASE_URL: str | None = None
    GST_SANDBOX_CLIENT_ID: str | None = None
    GST_SANDBOX_CLIENT_SECRET: str | None = None

    GST_SANDBOX_GSTIN: str | None = None

    # ---- ITR Sandbox (ClearTax etc.) ----
    ITR_SANDBOX_BASE_URL: str | None = None
    ITR_SANDBOX_API_KEY: str | None = None

    # ---- Admin / Debug ----
    ADMIN_API_KEY: str = Field(default="dev_admin_key")
    DEBUG_ADMIN_MSISDN: str = Field(default="")  # e.g. "91XXXXXXXXXX"

    # ---- Session / Conversation ----
    SESSION_IDLE_MINUTES: int = Field(default=10)

    # ---- MasterGST Sandbox ----
    MASTERGST_BASE_URL: str = Field(default="https://sandbox-apis.mastergst.com")
    MASTERGST_API_KEY: str = Field(default="")
    MASTERGST_CLIENT_ID: str = Field(default="")
    MASTERGST_CLIENT_SECRET: str = Field(default="")

    # ---- OCR & Queue ----
    OCR_BACKEND: str = Field(default="tesseract")  # or "google", "aws_textract"
    REDIS_URL: str = Field(default="redis://localhost:6379/0")


# Single global settings object used everywhere
settings = Settings()
