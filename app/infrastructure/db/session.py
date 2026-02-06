# app/domain/models/session.py
from enum import Enum
from pydantic import BaseModel
from typing import Optional

class Step(str, Enum):
    LANGUAGE = "language"
    MAIN_MENU = "main_menu"
    GSTIN = "gstin"
    INVOICE_UPLOAD = "invoice_upload"
    INVOICE_PARSED = "invoice_parsed"

class Session(BaseModel):
    wa_id: str
    language: str = "en"
    step: Step = Step.LANGUAGE
    gstin: Optional[str] = None