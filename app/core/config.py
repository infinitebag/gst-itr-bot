import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    ENV = os.getenv("ENV", "dev")
    PORT = int(os.getenv("PORT", 8000))

    WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN")
    WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")
    WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")

    DATABASE_URL = os.getenv("DATABASE_URL")

    SARVAM_API_KEY = os.getenv("SARVAM_API_KEY")
    SARVAM_STT_URL = os.getenv("SARVAM_STT_URL")

    BHASHINI_API_KEY = os.getenv("BHASHINI_API_KEY")
    BHASHINI_TRANSLATION_URL = os.getenv("BHASHINI_TRANSLATION_URL")

    GST_SANDBOX_BASE_URL = os.getenv("GST_SANDBOX_BASE_URL")
    GST_SANDBOX_CLIENT_ID = os.getenv("GST_SANDBOX_CLIENT_ID")
    GST_SANDBOX_CLIENT_SECRET = os.getenv("GST_SANDBOX_CLIENT_SECRET")

    ITR_SANDBOX_BASE_URL = os.getenv("ITR_SANDBOX_BASE_URL")
    ITR_SANDBOX_API_KEY = os.getenv("ITR_SANDBOX_API_KEY")

settings = Settings()