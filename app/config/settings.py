from pydantic import Field, AliasChoices
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Read env from container + optionally from files
    model_config = SettingsConfigDict(
        env_file=(".env", ".env.docker"),
        extra="ignore",
        case_sensitive=False,
    )

    # App
    ENVIRONMENT: str = Field(default="docker", validation_alias=AliasChoices("ENVIRONMENT", "environment"))
    APP_NAME: str = Field(default="gst_itr_bot", validation_alias=AliasChoices("APP_NAME", "app_name"))
    LOG_LEVEL: str = Field(default="INFO", validation_alias=AliasChoices("LOG_LEVEL", "log_level"))
    DEBUG: bool = Field(default=False, validation_alias=AliasChoices("DEBUG", "debug"))

    # Infrastructure
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:postgres@db:5432/gst_itr_db",
        validation_alias=AliasChoices("DATABASE_URL", "database_url"),
    )
    REDIS_URL: str = Field(
        default="redis://redis:6379/0",
        validation_alias=AliasChoices("REDIS_URL", "redis_url"),
    )

    # WhatsApp Meta
    WHATSAPP_VERIFY_TOKEN: str = Field(default="", validation_alias=AliasChoices("WHATSAPP_VERIFY_TOKEN", "whatsapp_verify_token"))
    WHATSAPP_ACCESS_TOKEN: str = Field(default="", validation_alias=AliasChoices("WHATSAPP_ACCESS_TOKEN", "whatsapp_access_token"))
    WHATSAPP_PHONE_NUMBER_ID: str = Field(default="", validation_alias=AliasChoices("WHATSAPP_PHONE_NUMBER_ID", "whatsapp_phone_number_id"))

    # MasterGST
    MASTERGST_BASE_URL: str = Field(default="https://sandbox.mastergst.com", validation_alias=AliasChoices("MASTERGST_BASE_URL", "mastergst_base_url"))
    MASTERGST_API_KEY: str = Field(default="", validation_alias=AliasChoices("MASTERGST_API_KEY", "mastergst_api_key"))

    # ClearTax (sandbox)
    CLEARTAX_GST_BASE_URL: str = Field(default="https://sandbox.cleartax.in", validation_alias=AliasChoices("CLEARTAX_GST_BASE_URL", "cleartax_gst_base_url"))
    CLEARTAX_GST_API_KEY: str = Field(default="", validation_alias=AliasChoices("CLEARTAX_GST_API_KEY", "cleartax_gst_api_key"))

    # Investor demo mode (accept both names)
    INVESTOR_DEMO_MODE: bool = Field(
        default=False,
        validation_alias=AliasChoices("DEMO_MODE", "INVESTOR_DEMO_MODE"),
    )


settings = Settings()