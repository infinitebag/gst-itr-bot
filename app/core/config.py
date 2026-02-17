# app/core/config.py
#
# Single authoritative Settings class for the entire project.
# All modules should import from here: ``from app.core.config import settings``

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env.local", ".env", ".env.docker"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- Core ----
    ENV: str = Field(default="dev")
    PORT: int = Field(default=8000)
    LOG_LEVEL: str = Field(default="INFO")
    DEBUG: bool = Field(default=False)

    # ---- WhatsApp Cloud API / AiSensy ----
    WHATSAPP_VERIFY_TOKEN: str = Field(default="")
    WHATSAPP_ACCESS_TOKEN: str = Field(default="")
    WHATSAPP_PHONE_NUMBER_ID: str = Field(default="")
    WHATSAPP_APP_SECRET: str = Field(default="")

    AISENSY_API_KEY: str = Field(default="")
    AISENSY_PROJECT_ID: str = Field(default="")

    # ---- Database ----
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/gst_itr_db"
    )

    # ---- Redis ----
    REDIS_URL: str = Field(default="redis://localhost:6379/0")

    # ---- Sarvam STT ----
    SARVAM_API_KEY: str = Field(default="")
    SARVAM_STT_URL: str = Field(default="")

    # ---- Bhashini (Govt Translation / ASR / TTS) ----
    BHASHINI_USER_ID: str = Field(default="")
    BHASHINI_ULCA_API_KEY: str = Field(default="")
    BHASHINI_TRANSLATION_PIPELINE_ID: str = Field(default="")
    BHASHINI_PIPELINE_BASE_URL: str = Field(
        default="https://meity-auth.ulcacontrib.org/ulca/apis"
    )
    # Backward-compat aliases (some services may reference these short names)
    BHASHINI_API_KEY: str = Field(default="")
    BHASHINI_TRANSLATION_URL: str = Field(default="")

    # ---- OpenAI ----
    OPENAI_API_KEY: str = Field(default="")
    OPENAI_MODEL: str = Field(default="gpt-4o")
    OPENAI_TIMEOUT: int = Field(default=30)

    # ---- MasterGST / WhiteBooks ----
    # GST API (auth via OTP flow)
    MASTERGST_BASE_URL: str = Field(default="https://apisandbox.whitebooks.in")
    MASTERGST_CLIENT_ID: str = Field(default="")
    MASTERGST_CLIENT_SECRET: str = Field(default="")
    MASTERGST_EMAIL: str = Field(default="")            # WhiteBooks registration email
    MASTERGST_GST_USERNAME: str = Field(default="")     # GST portal username (e.g. BVMKA)
    MASTERGST_STATE_CD: str = Field(default="")         # State code (e.g. "29" for Karnataka)
    MASTERGST_IP_ADDRESS: str = Field(default="127.0.0.1")  # IP address for API calls
    MASTERGST_OTP_DEFAULT: str = Field(default="575757")    # Sandbox OTP (always accepted)

    # e-Invoice API (auth via username/password)
    MASTERGST_EINVOICE_BASE_URL: str = Field(default="https://apisandbox.whitebooks.in")
    MASTERGST_EINVOICE_CLIENT_ID: str = Field(default="")    # Falls back to MASTERGST_CLIENT_ID if empty
    MASTERGST_EINVOICE_CLIENT_SECRET: str = Field(default="")  # Falls back to MASTERGST_CLIENT_SECRET if empty
    MASTERGST_EINVOICE_USERNAME: str = Field(default="")  # e-Invoice portal username
    MASTERGST_EINVOICE_PASSWORD: str = Field(default="")  # e-Invoice portal password

    # e-WayBill API (auth via username/password)
    MASTERGST_EWAYBILL_BASE_URL: str = Field(default="https://apisandbox.whitebooks.in")
    MASTERGST_EWAYBILL_CLIENT_ID: str = Field(default="")    # Falls back to MASTERGST_CLIENT_ID if empty
    MASTERGST_EWAYBILL_CLIENT_SECRET: str = Field(default="")  # Falls back to MASTERGST_CLIENT_SECRET if empty
    MASTERGST_EWAYBILL_USERNAME: str = Field(default="")  # e-WayBill portal username
    MASTERGST_EWAYBILL_PASSWORD: str = Field(default="")

    # ---- ITR Sandbox ----
    ITR_SANDBOX_BASE_URL: str = Field(default="")
    ITR_SANDBOX_API_KEY: str = Field(default="")

    # ---- OCR ----
    OCR_BACKEND: str = Field(default="tesseract")

    # ---- Admin / Debug ----
    ADMIN_API_KEY: str = Field(default="dev_admin_key")
    ADMIN_JWT_SECRET: str = Field(default="change-me-admin-jwt")
    ADMIN_JWT_ACCESS_EXPIRE_MINUTES: int = Field(default=480)  # 8 hours
    DEBUG_ADMIN_MSISDN: str = Field(default="")

    # ---- Session / Conversation ----
    SESSION_IDLE_MINUTES: int = Field(default=10)

    # ---- CA Dashboard JWT ----
    CA_JWT_SECRET: str = Field(default="change-me-in-production")
    CA_JWT_ALGORITHM: str = Field(default="HS256")
    CA_JWT_ACCESS_EXPIRE_MINUTES: int = Field(default=30)
    CA_JWT_REFRESH_EXPIRE_DAYS: int = Field(default=7)

    # ---- User API JWT (mobile / web clients) ----
    USER_JWT_SECRET: str = Field(default="change-me-user-jwt")
    USER_JWT_ACCESS_EXPIRE_MINUTES: int = Field(default=60)
    USER_JWT_REFRESH_EXPIRE_DAYS: int = Field(default=30)

    # ---- RAG / Embeddings ----
    EMBEDDING_MODEL: str = Field(default="text-embedding-3-small")
    EMBEDDING_DIMENSIONS: int = Field(default=1536)
    RAG_TOP_K: int = Field(default=5)
    RAG_SIMILARITY_THRESHOLD: float = Field(default=0.7)
    RAG_CHUNK_SIZE: int = Field(default=500)          # tokens per chunk
    RAG_CHUNK_OVERLAP: int = Field(default=50)         # token overlap between chunks

    # ---- ML Risk Scoring ----
    ML_RISK_ENABLED: bool = Field(default=True)
    ML_RISK_BLEND_WEIGHT: float = Field(default=0.3)           # 0=rule-only, 1=ML-only
    ML_RISK_MIN_SAMPLES: int = Field(default=50)               # cold-start threshold
    ML_RISK_RETRAIN_THRESHOLD: int = Field(default=20)         # new labels to trigger retrain
    ML_RISK_N_ESTIMATORS: int = Field(default=100)
    ML_RISK_MAX_DEPTH: int = Field(default=5)
    ML_RISK_SHAP_ENABLED: bool = Field(default=True)

    # ---- Segment Gating ----
    SEGMENT_GATING_ENABLED: bool = Field(default=True)
    DEFAULT_SEGMENT: str = Field(default="small")          # small / medium / enterprise
    SEGMENT_CACHE_TTL: int = Field(default=3600)            # Redis cache TTL in seconds

    # ---- Proactive Notifications ----
    NOTIFICATION_ENABLED: bool = Field(default=True)
    NOTIFICATION_CHECK_INTERVAL_SECONDS: int = Field(default=3600)  # 1 hour
    NOTIFICATION_REMINDER_DAYS: list[int] = Field(default=[7, 3, 1])  # days before deadline
    NOTIFICATION_DAILY_SCHEDULE_HOUR: int = Field(default=9)  # 9 AM IST

    # ---- OTP / Mobile Number Change ----
    OTP_EMAIL_ENABLED: bool = Field(default=False)
    OTP_SMTP_HOST: str = Field(default="")
    OTP_SMTP_PORT: int = Field(default=587)
    OTP_SMTP_USERNAME: str = Field(default="")
    OTP_SMTP_PASSWORD: str = Field(default="")
    OTP_SMTP_USE_TLS: bool = Field(default=True)
    OTP_FROM_EMAIL: str = Field(default="noreply@example.com")

    # ---- Demo mode ----
    INVESTOR_DEMO_MODE: bool = Field(default=False)


# Single global settings object used everywhere
settings = Settings()


# ---------------------------------------------------------------------------
# Startup safety: warn / reject dangerous defaults in non-dev environments
# ---------------------------------------------------------------------------
_UNSAFE_DEFAULTS = {
    "CA_JWT_SECRET": "change-me-in-production",
    "ADMIN_API_KEY": "dev_admin_key",
    "ADMIN_JWT_SECRET": "change-me-admin-jwt",
    "USER_JWT_SECRET": "change-me-user-jwt",
}


def validate_secrets() -> None:
    """
    Called once at application startup.

    In production (ENV != dev/development/test) this will **raise** if any
    secret still has its placeholder default value.  In dev mode it logs a
    warning instead.
    """
    import logging

    logger = logging.getLogger("config")
    is_dev = settings.ENV in ("dev", "development", "test")

    for field_name, bad_value in _UNSAFE_DEFAULTS.items():
        actual = getattr(settings, field_name, "")
        if actual == bad_value:
            msg = (
                f"{field_name} is still set to the unsafe default "
                f"'{bad_value}'.  Change it before deploying!"
            )
            if is_dev:
                logger.warning(msg)
            else:
                raise RuntimeError(msg)

    if not settings.WHATSAPP_APP_SECRET and not is_dev:
        raise RuntimeError(
            "WHATSAPP_APP_SECRET must be set in production to verify "
            "webhook signatures.  Set it in your .env file."
        )
