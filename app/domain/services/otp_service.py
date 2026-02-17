# app/domain/services/otp_service.py
"""
OTP service for mobile number change verification.

Supports pluggable email backend:
- When OTP_EMAIL_ENABLED=True and SMTP settings configured → sends via SMTP
- When OTP_EMAIL_ENABLED=False → dev stub (logs OTP, returns True)

Set the following env vars for production:
    OTP_EMAIL_ENABLED=true
    OTP_SMTP_HOST=smtp.gmail.com  (or your provider)
    OTP_SMTP_PORT=587
    OTP_SMTP_USERNAME=your-email@example.com
    OTP_SMTP_PASSWORD=your-app-password
    OTP_SMTP_USE_TLS=true
    OTP_FROM_EMAIL=noreply@yourdomain.com
"""

from __future__ import annotations

import hashlib
import logging
import random
import string
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from app.core.config import settings

logger = logging.getLogger("otp_service")

# OTP configuration
OTP_LENGTH = 6
OTP_EXPIRY_SECONDS = 300  # 5 minutes
MAX_ATTEMPTS = 3
LOCKOUT_SECONDS = 3600  # 1 hour

# In-memory store for dev (production should use Redis)
_otp_store: dict[str, dict] = {}
_lockout_store: dict[str, float] = {}


def generate_otp(wa_id: str, purpose: str = "change_number") -> str:
    """Generate a 6-digit OTP and store its hash.

    Returns the plaintext OTP (for dev logging / email sending).
    """
    otp = "".join(random.choices(string.digits, k=OTP_LENGTH))
    key = f"{wa_id}:{purpose}"

    _otp_store[key] = {
        "hash": _hash_otp(otp),
        "created_at": time.time(),
        "attempts": 0,
    }

    logger.info("OTP generated for %s (purpose=%s)", wa_id, purpose)
    return otp


def verify_otp(wa_id: str, purpose: str, code: str) -> bool:
    """Verify an OTP code against the stored hash.

    Returns True if valid, False otherwise. Increments attempt counter.
    """
    key = f"{wa_id}:{purpose}"
    entry = _otp_store.get(key)

    if not entry:
        return False

    # Check expiry
    if (time.time() - entry["created_at"]) > OTP_EXPIRY_SECONDS:
        _otp_store.pop(key, None)
        return False

    # Check attempts
    entry["attempts"] += 1
    if entry["attempts"] > MAX_ATTEMPTS:
        _otp_store.pop(key, None)
        _lockout_store[wa_id] = time.time()
        logger.warning("OTP max attempts exceeded for %s, locked out", wa_id)
        return False

    if _hash_otp(code.strip()) == entry["hash"]:
        _otp_store.pop(key, None)  # Consume OTP
        return True

    return False


async def send_otp_email(email: str, otp: str, lang: str = "en") -> bool:
    """Send OTP via email.

    When OTP_EMAIL_ENABLED=True: sends via configured SMTP.
    When OTP_EMAIL_ENABLED=False: dev stub (logs OTP, returns True).

    Returns True on success, False on failure.
    """
    otp_email_enabled = getattr(settings, "OTP_EMAIL_ENABLED", False)

    if not otp_email_enabled:
        # Dev/test: just log it
        logger.info(
            "STUB: Would send OTP %s to email %s (lang=%s)",
            otp, email, lang,
        )
        return True

    # Production: send via SMTP
    smtp_host = getattr(settings, "OTP_SMTP_HOST", "")
    smtp_port = getattr(settings, "OTP_SMTP_PORT", 587)
    smtp_username = getattr(settings, "OTP_SMTP_USERNAME", "")
    smtp_password = getattr(settings, "OTP_SMTP_PASSWORD", "")
    smtp_use_tls = getattr(settings, "OTP_SMTP_USE_TLS", True)
    from_email = getattr(settings, "OTP_FROM_EMAIL", "noreply@example.com")

    if not smtp_host or not smtp_username:
        logger.error(
            "OTP_EMAIL_ENABLED=True but SMTP not configured. "
            "Set OTP_SMTP_HOST and OTP_SMTP_USERNAME."
        )
        return False

    # Build email
    subject = _get_subject(lang)
    body = _get_body(otp, lang)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_email
    msg["To"] = email
    msg.attach(MIMEText(body, "plain", "utf-8"))

    # Send via SMTP (in a thread to avoid blocking the event loop)
    import asyncio
    import smtplib

    def _send_smtp() -> bool:
        try:
            if smtp_use_tls:
                server = smtplib.SMTP(smtp_host, smtp_port, timeout=30)
                server.ehlo()
                server.starttls()
            else:
                server = smtplib.SMTP(smtp_host, smtp_port, timeout=30)
                server.ehlo()

            server.login(smtp_username, smtp_password)
            server.sendmail(from_email, [email], msg.as_string())
            server.quit()
            logger.info("OTP email sent to %s via %s", email, smtp_host)
            return True
        except Exception:
            logger.exception("Failed to send OTP email to %s", email)
            return False

    return await asyncio.get_event_loop().run_in_executor(None, _send_smtp)


def is_locked(wa_id: str) -> bool:
    """Check if a user is locked out due to too many failed OTP attempts."""
    lockout_time = _lockout_store.get(wa_id)
    if not lockout_time:
        return False

    if (time.time() - lockout_time) > LOCKOUT_SECONDS:
        _lockout_store.pop(wa_id, None)
        return False

    return True


def _hash_otp(otp: str) -> str:
    """Hash an OTP for secure storage."""
    return hashlib.sha256(otp.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Email templates (multilingual)
# ---------------------------------------------------------------------------

def _get_subject(lang: str) -> str:
    """Return email subject by language."""
    subjects = {
        "en": "Your OTP for Mobile Number Change",
        "hi": "मोबाइल नंबर बदलने के लिए आपका OTP",
        "gu": "મોબાઈલ નંબર બદલવા માટે તમારો OTP",
        "ta": "மொபைல் எண் மாற்றத்திற்கான உங்கள் OTP",
        "te": "మొబైల్ నంబర్ మార్పు కోసం మీ OTP",
        "kn": "ಮೊಬೈಲ್ ಸಂಖ್ಯೆ ಬದಲಾವಣೆಗಾಗಿ ನಿಮ್ಮ OTP",
    }
    return subjects.get(lang, subjects["en"])


def _get_body(otp: str, lang: str) -> str:
    """Return email body by language."""
    bodies = {
        "en": (
            f"Your One-Time Password (OTP) for mobile number change is: {otp}\n\n"
            "This OTP is valid for 5 minutes.\n"
            "Do not share this code with anyone.\n\n"
            "If you did not request this change, please ignore this email."
        ),
        "hi": (
            f"मोबाइल नंबर बदलने के लिए आपका OTP है: {otp}\n\n"
            "यह OTP 5 मिनट के लिए मान्य है।\n"
            "इस कोड को किसी के साथ साझा न करें।\n\n"
            "अगर आपने यह अनुरोध नहीं किया है, तो इस ईमेल को अनदेखा करें।"
        ),
        "gu": (
            f"મોબાઈલ નંબર બદલવા માટે તમારો OTP છે: {otp}\n\n"
            "આ OTP 5 મિનિટ માટે માન્ય છે।\n"
            "આ કોડ કોઈની સાથે શેર ન કરો।\n\n"
            "જો તમે આ વિનંતી કરી નથી, તો આ ઈમેલને અવગણો."
        ),
        "ta": (
            f"மொபைல் எண் மாற்றத்திற்கான உங்கள் OTP: {otp}\n\n"
            "இந்த OTP 5 நிமிடங்களுக்கு செல்லுபடியாகும்.\n"
            "இந்த குறியீட்டை யாரிடமும் பகிர வேண்டாம்.\n\n"
            "இந்த மாற்றத்தை நீங்கள் கோரவில்லை என்றால், இந்த மின்னஞ்சலை புறக்கணிக்கவும்."
        ),
        "te": (
            f"మొబైల్ నంబర్ మార్పు కోసం మీ OTP: {otp}\n\n"
            "ఈ OTP 5 నిమిషాలు చెల్లుబాటు అవుతుంది.\n"
            "ఈ కోడ్‌ను ఎవరికీ షేర్ చేయకండి.\n\n"
            "మీరు ఈ మార్పును అభ్యర్థించకపోతే, ఈ ఇమెయిల్‌ను విస్మరించండి."
        ),
        "kn": (
            f"ಮೊಬೈಲ್ ಸಂಖ್ಯೆ ಬದಲಾವಣೆಗಾಗಿ ನಿಮ್ಮ OTP: {otp}\n\n"
            "ಈ OTP 5 ನಿಮಿಷಗಳವರೆಗೆ ಮಾನ್ಯವಾಗಿದೆ.\n"
            "ಈ ಕೋಡ್ ಅನ್ನು ಯಾರೊಂದಿಗೂ ಹಂಚಿಕೊಳ್ಳಬೇಡಿ.\n\n"
            "ನೀವು ಈ ಬದಲಾವಣೆಯನ್ನು ಕೋರಿಲ್ಲದಿದ್ದರೆ, ಈ ಇಮೇಲ್ ಅನ್ನು ನಿರ್ಲಕ್ಷಿಸಿ."
        ),
    }
    return bodies.get(lang, bodies["en"])
