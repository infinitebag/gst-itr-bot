# app/infrastructure/external/openai_client.py

import base64
import json
import logging
from dataclasses import dataclass

from openai import AsyncOpenAI

from app.config.settings import settings

logger = logging.getLogger("openai_client")

# ---------------------------------------------------------------------------
# Singleton client (lazy init)
# ---------------------------------------------------------------------------
_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY,
            timeout=settings.OPENAI_TIMEOUT,
        )
    return _client


# ---------------------------------------------------------------------------
# Intent detection
# ---------------------------------------------------------------------------
@dataclass
class IntentResult:
    intent: str  # one of the enum values
    confidence: float  # 0.0 - 1.0
    extracted_entity: str | None = None


INTENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "classify_user_intent",
            "description": "Classify the user's WhatsApp message into a bot intent",
            "parameters": {
                "type": "object",
                "properties": {
                    "intent": {
                        "type": "string",
                        "enum": [
                            "gst_services",
                            "itr_services",
                            "upload_invoice",
                            "change_language",
                            "tax_qa",
                            "tax_insights",
                            "enter_gstin",
                            "main_menu",
                            "go_back",
                            "unknown",
                        ],
                        "description": "The detected intent of the user's message",
                    },
                    "confidence": {
                        "type": "number",
                        "description": "Confidence score between 0.0 and 1.0",
                    },
                    "extracted_entity": {
                        "type": "string",
                        "description": "Any entity extracted, e.g. a GSTIN or PAN number",
                    },
                },
                "required": ["intent", "confidence"],
            },
        },
    }
]

INTENT_SYSTEM_PROMPT = """\
You are an intent classifier for an Indian GST and ITR tax filing WhatsApp bot.

The bot supports these intents:
- gst_services: User wants to access GST services, file GSTR-3B, GSTR-1, view GST returns
- itr_services: User wants to file income tax returns, ITR-1/2/3/4
- upload_invoice: User wants to upload/scan an invoice for OCR processing
- change_language: User wants to change the bot's language
- tax_qa: User is asking a question about tax rules, rates, deadlines, procedures
- tax_insights: User wants to see tax analytics, insights, summary, anomaly reports, or filing deadlines
- enter_gstin: User is providing or wants to enter a GSTIN number (15-char alphanumeric)
- main_menu: User wants to go back to the main menu
- go_back: User wants to go to the previous screen
- unknown: Cannot determine intent

The user may type in English, Hindi, Telugu, Tamil, or Gujarati.

Classify the message and provide a confidence score.
If the message is a single number (0-9), classify as unknown so number-based routing handles it.\
"""


async def detect_intent(text: str, lang: str) -> IntentResult:
    """Classify user message into a bot intent using OpenAI function calling."""
    if not settings.OPENAI_API_KEY:
        return IntentResult(intent="unknown", confidence=0.0)

    try:
        client = _get_client()
        response = await client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": INTENT_SYSTEM_PROMPT},
                {"role": "user", "content": f"[lang={lang}] {text}"},
            ],
            tools=INTENT_TOOLS,
            tool_choice={"type": "function", "function": {"name": "classify_user_intent"}},
            temperature=0,
        )

        tool_call = response.choices[0].message.tool_calls[0]
        args = json.loads(tool_call.function.arguments)

        return IntentResult(
            intent=args.get("intent", "unknown"),
            confidence=float(args.get("confidence", 0.0)),
            extracted_entity=args.get("extracted_entity"),
        )
    except Exception:
        logger.exception("Intent detection failed")
        return IntentResult(intent="unknown", confidence=0.0)


# ---------------------------------------------------------------------------
# LLM invoice parsing — Vision (primary) + Text (fallback)
# ---------------------------------------------------------------------------
INVOICE_VISION_PROMPT = """\
You are an expert Indian GST tax invoice parser. Carefully read this invoice image and extract ALL fields.

Return a JSON object with EXACTLY these fields (use null if not found):
{
  "supplier_name": "Name of the supplier/seller company",
  "supplier_gstin": "15-char GSTIN of the supplier/seller (format: 2-digit state + 5-letter PAN + 4-digit + 1-letter + 1Z + 1-char)",
  "receiver_name": "Name of the buyer/receiver company",
  "receiver_gstin": "15-char GSTIN of the buyer/receiver/consignee",
  "invoice_number": "Invoice number (e.g. INV-001, 6, KTD/2025/123)",
  "invoice_date": "Invoice date in YYYY-MM-DD format",
  "hsn_code": "HSN/SAC code (4-8 digit number)",
  "item_description": "Description of goods/services",
  "taxable_value": numeric taxable value (before tax),
  "tax_rate": numeric total GST rate as percentage (e.g. 0.25, 5, 12, 18, 28),
  "cgst_amount": numeric CGST amount (null if inter-state),
  "sgst_amount": numeric SGST amount (null if inter-state),
  "igst_amount": numeric IGST amount (null if intra-state),
  "tax_amount": numeric total tax (sum of CGST+SGST or IGST),
  "total_amount": numeric final invoice total (taxable + tax, after rounding),
  "place_of_supply": "State name or 2-digit state code of supply"
}

CRITICAL RULES:
- GSTINs are EXACTLY 15 characters alphanumeric, e.g. 24AAHPA8018P1ZL
- The FIRST GSTIN near seller/supplier section = supplier_gstin
- The GSTIN near buyer/consignee/bill-to section = receiver_gstin
- If the same GSTIN appears for both consignee and buyer, it's the receiver
- For dates like "20-May-25", convert to "2025-05-20"
- total_amount is the FINAL payable amount (₹ symbol line, "Amount Chargeable", or grand total)
- taxable_value is the pre-tax amount (before GST is added)
- tax_amount = cgst + sgst (intra-state) OR igst (inter-state)
- Look at the tax summary table at the bottom of the invoice for accurate tax breakdowns
- Rounding adjustments: the total should reflect the rounded final amount
- Return ONLY valid JSON, no explanation\
"""

INVOICE_TEXT_PROMPT = """\
You are an expert Indian GST tax invoice parser. Extract structured fields from this OCR text.

Return a JSON object with EXACTLY these fields (use null if not found):
{
  "supplier_name": "Name of the supplier/seller",
  "supplier_gstin": "15-char GSTIN of the supplier/seller",
  "receiver_name": "Name of the buyer/receiver",
  "receiver_gstin": "15-char GSTIN of the buyer/receiver",
  "invoice_number": "Invoice number string",
  "invoice_date": "Date in YYYY-MM-DD format",
  "hsn_code": "HSN/SAC code",
  "item_description": "Description of goods/services",
  "taxable_value": numeric taxable value (before tax),
  "tax_rate": numeric total GST rate percentage,
  "cgst_amount": numeric CGST amount,
  "sgst_amount": numeric SGST amount,
  "igst_amount": numeric IGST amount,
  "tax_amount": numeric total tax amount,
  "total_amount": numeric final invoice total,
  "place_of_supply": "State name or code"
}

Rules:
- GSTINs are 15-char alphanumeric (e.g. 27AABCU9603R1ZM)
- First GSTIN is usually supplier, second is receiver/buyer
- Tax: CGST + SGST for intra-state, IGST for inter-state
- Dates: convert any format (DD-Mon-YY, DD/MM/YYYY etc.) to YYYY-MM-DD
- total_amount = taxable_value + tax_amount
- Return ONLY the JSON object, no explanation\
"""


async def parse_invoice_vision(image_bytes: bytes, mime_type: str = "image/jpeg") -> dict:
    """
    PRIMARY parser: Send raw invoice image to GPT-4o Vision for extraction.
    This is far more accurate than Tesseract OCR + regex.
    """
    if not settings.OPENAI_API_KEY:
        return {}

    try:
        client = _get_client()

        # Encode image to base64 for the API
        b64_image = base64.b64encode(image_bytes).decode("utf-8")
        # Normalize mime type
        if mime_type not in ("image/jpeg", "image/png", "image/webp", "image/gif"):
            mime_type = "image/jpeg"

        response = await client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": INVOICE_VISION_PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{b64_image}",
                                "detail": "high",
                            },
                        },
                    ],
                }
            ],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=1500,
        )

        content = response.choices[0].message.content
        result = json.loads(content) if content else {}
        logger.info("Vision invoice parse result: %s", result)
        return result
    except Exception:
        logger.exception("Vision invoice parsing failed")
        return {}


async def parse_invoice_llm(ocr_text: str) -> dict:
    """FALLBACK parser: Use GPT-4o to extract from OCR text when Vision unavailable."""
    if not settings.OPENAI_API_KEY:
        return {}

    try:
        client = _get_client()
        response = await client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": INVOICE_TEXT_PROMPT},
                {"role": "user", "content": ocr_text[:6000]},
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )

        content = response.choices[0].message.content
        return json.loads(content) if content else {}
    except Exception:
        logger.exception("LLM invoice parsing failed")
        return {}


# ---------------------------------------------------------------------------
# Tax Q&A
# ---------------------------------------------------------------------------
TAX_QA_SYSTEM_PROMPT = """\
You are a helpful Indian tax assistant specializing in GST (Goods and Services Tax) \
and ITR (Income Tax Return) filing.

Key knowledge areas:
- GST: GSTR-1, GSTR-3B, GSTR-9, Input Tax Credit (ITC), HSN codes, \
GST rates (5%, 12%, 18%, 28%), e-way bills, reverse charge mechanism, composition scheme
- ITR: ITR-1 (Sahaj), ITR-2, ITR-3, ITR-4 (Sugam), Form 26AS, AIS, TDS, \
deductions under 80C/80D/80E, advance tax, capital gains
- Filing deadlines, penalties, and compliance requirements

Rules:
1. Answer in the SAME language the user asks in
2. Cite relevant section numbers (e.g. "Section 16 of CGST Act")
3. Keep answers concise (under 300 words) since this is WhatsApp
4. If unsure, say so clearly - do not make up information
5. For complex cases, recommend consulting a Chartered Accountant (CA)
6. Never provide advice on tax evasion
7. Include current financial year context where relevant\
"""


async def tax_qa(
    question: str,
    lang: str,
    history: list[dict] | None = None,
) -> str:
    """Answer a tax-related question using GPT-4o."""
    if not settings.OPENAI_API_KEY:
        return ""

    try:
        messages = [{"role": "system", "content": TAX_QA_SYSTEM_PROMPT}]

        # Add conversation history (last 10 turns max)
        if history:
            messages.extend(history[-10:])

        messages.append({"role": "user", "content": f"[lang={lang}] {question}"})

        client = _get_client()
        response = await client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=messages,
            temperature=0.3,
            max_tokens=800,
        )

        return response.choices[0].message.content or ""
    except Exception:
        logger.exception("Tax Q&A failed")
        return ""


# ---------------------------------------------------------------------------
# HSN Code Lookup
# ---------------------------------------------------------------------------
HSN_LOOKUP_SYSTEM_PROMPT = """\
You are an Indian GST HSN code expert. Given a product or service description, return the most \
appropriate HSN/SAC code with the applicable GST rate.

Return a JSON object:
{
  "hsn_code": "the 4-8 digit HSN or SAC code",
  "description": "official description of this HSN/SAC code",
  "gst_rate": numeric GST rate (e.g. 5, 12, 18, 28),
  "category": "Goods" or "Services",
  "chapter": "HSN Chapter heading (e.g. Chapter 61 - Articles of apparel)",
  "notes": "any important notes (exemptions, conditions, etc.)"
}

Rules:
1. HSN codes are for Goods (Chapters 1-98), SAC codes are for Services (99xx)
2. Include the most specific code possible (6 or 8 digit preferred)
3. If multiple rates apply, mention conditions in notes
4. If unsure, provide the closest match and note the uncertainty
5. Return ONLY the JSON object, no explanation\
"""


async def lookup_hsn(product_description: str, lang: str = "en") -> dict:
    """Look up HSN/SAC code for a product/service description using GPT-4o."""
    if not settings.OPENAI_API_KEY:
        return {}

    try:
        client = _get_client()
        response = await client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": HSN_LOOKUP_SYSTEM_PROMPT},
                {"role": "user", "content": f"[lang={lang}] {product_description}"},
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )

        content = response.choices[0].message.content
        return json.loads(content) if content else {}
    except Exception:
        logger.exception("HSN lookup failed")
        return {}


# ---------------------------------------------------------------------------
# ITR Document Parsing — Form 16, Form 26AS, AIS
# ---------------------------------------------------------------------------

FORM16_VISION_PROMPT = """\
You are an expert Indian income tax document parser. Carefully read this Form 16 \
(TDS Certificate) image and extract ALL fields.

Return a JSON object with EXACTLY these fields (use null if not found):
{
  "employer_name": "Name of the employer/deductor company",
  "employer_tan": "10-char TAN of the employer (e.g. BLRA12345E)",
  "employee_pan": "10-char PAN of the employee (e.g. ABCDE1234F)",
  "assessment_year": "Assessment Year (e.g. 2025-26)",
  "gross_salary": numeric gross salary amount (before any deductions),
  "standard_deduction": numeric standard deduction u/s 16(ia) (usually 50000 or 75000),
  "house_property_income": numeric income/loss from house property (can be negative),
  "section_80c": numeric total 80C deductions (PPF, ELSS, LIC, etc.),
  "section_80d": numeric 80D deductions (health insurance premium),
  "section_80e": numeric 80E deductions (education loan interest),
  "section_80g": numeric 80G deductions (donations),
  "section_80ccd_1b": numeric 80CCD(1B) deductions (NPS additional contribution),
  "section_80tta": numeric 80TTA deductions (savings interest up to 10K),
  "other_deductions": numeric any other Chapter VI-A deductions not listed above,
  "total_tax_deducted": numeric total TDS deducted by employer (from Part B)
}

CRITICAL RULES:
- PAN is EXACTLY 10 characters: 5 letters + 4 digits + 1 letter (e.g. ABCDE1234F)
- TAN is EXACTLY 10 characters: 4 letters + 5 digits + 1 letter
- gross_salary is the TOTAL salary BEFORE standard deduction
- total_tax_deducted is the NET tax deducted (from Part B of Form 16)
- Look at Part B / Annexure B for detailed deduction breakdowns
- For deductions, sum all items within each section
- Assessment Year format: YYYY-YY (e.g. 2025-26)
- Return ONLY valid JSON, no explanation\
"""

FORM26AS_VISION_PROMPT = """\
You are an expert Indian income tax document parser. Carefully read this Form 26AS \
(Tax Credit Statement) image and extract ALL fields.

Return a JSON object with EXACTLY these fields (use null if not found):
{
  "pan": "10-char PAN of the taxpayer",
  "assessment_year": "Assessment Year (e.g. 2025-26)",
  "tds_entries": [
    {
      "deductor_name": "Name of the deductor/employer",
      "deductor_tan": "TAN of the deductor",
      "section": "Tax section (e.g. 192, 194A, 194H)",
      "amount_paid": numeric amount paid/credited,
      "tds_deducted": numeric TDS deducted,
      "tds_deposited": numeric TDS deposited
    }
  ],
  "total_tds": numeric total of all TDS deducted across all entries,
  "total_tcs": numeric total TCS (Tax Collected at Source) if any,
  "advance_tax_paid": numeric advance tax paid (Part C),
  "self_assessment_tax": numeric self-assessment tax paid (Part C),
  "stcg_equity": numeric short-term capital gains from equity/listed securities (section 111A) or null,
  "ltcg_equity": numeric long-term capital gains from equity/listed securities (section 112A) or null,
  "capital_gains_total": numeric total capital gains across all categories or null
}

CRITICAL RULES:
- Part A: TDS on salary (Section 192)
- Part A1/A2: TDS on other income (194A for interest, 194H for commission, etc.)
- Part A2 often has TDS on sale of securities — check for capital gains
- Part B: TCS (Tax Collected at Source)
- Part C: Advance tax and self-assessment tax payments
- total_tds should be the SUM of all tds_deducted values from Part A + A1 + A2
- Include ALL deductors, not just employer
- For capital gains: Look for entries under sections 111A (STCG equity) and 112A (LTCG equity)
- PAN is 10 characters: 5 letters + 4 digits + 1 letter
- Return ONLY valid JSON, no explanation\
"""

AIS_VISION_PROMPT = """\
You are an expert Indian income tax document parser. Carefully read this AIS \
(Annual Information Statement) image and extract ALL fields.

Return a JSON object with EXACTLY these fields (use null if not found):
{
  "pan": "10-char PAN of the taxpayer",
  "salary_income": numeric total salary received (from all employers),
  "interest_income": numeric total interest income (savings, FD, etc.),
  "dividend_income": numeric total dividend income,
  "rental_income": numeric rental/property income,
  "business_turnover": numeric business/professional turnover (if applicable),
  "tds_total": numeric total TDS deducted across all sources,
  "stcg_equity": numeric short-term capital gains from equity/listed securities or null,
  "ltcg_equity": numeric long-term capital gains from equity/listed securities or null,
  "capital_gains_total": numeric total capital gains from all sources or null,
  "sft_transactions": [
    {
      "type": "Type of transaction (e.g. Cash Deposit, Property Purchase, Sale of Securities)",
      "amount": numeric transaction amount,
      "reported_by": "Entity that reported the transaction"
    }
  ]
}

CRITICAL RULES:
- AIS has multiple sections: TDS/TCS, SFT (Specified Financial Transactions), other info
- salary_income = total from "Salary" section
- interest_income = sum of all interest entries (savings, FD, recurring deposits)
- dividend_income = sum of all dividend entries
- business_turnover = turnover reported under GST or business section
- tds_total = sum of all TDS amounts from TDS section
- For capital gains: Look for "Sale of Securities" or "Capital Gains" sections
- stcg_equity = short-term gains from listed equity (held < 1 year, STT paid)
- ltcg_equity = long-term gains from listed equity (held > 1 year, STT paid)
- SFT transactions are high-value transactions reported by banks/registrars
- PAN is 10 characters: 5 letters + 4 digits + 1 letter
- Return ONLY valid JSON, no explanation\
"""


async def _parse_tax_document_vision(
    image_bytes: bytes,
    mime_type: str,
    prompt: str,
    doc_type: str,
) -> dict:
    """Generic Vision parser for tax documents (Form 16, 26AS, AIS)."""
    if not settings.OPENAI_API_KEY:
        return {}

    try:
        client = _get_client()
        b64_image = base64.b64encode(image_bytes).decode("utf-8")
        if mime_type not in ("image/jpeg", "image/png", "image/webp", "image/gif"):
            mime_type = "image/jpeg"

        response = await client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{b64_image}",
                                "detail": "high",
                            },
                        },
                    ],
                }
            ],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=2000,
        )

        content = response.choices[0].message.content
        result = json.loads(content) if content else {}
        logger.info("Vision %s parse result: %s", doc_type, result)
        return result
    except Exception:
        logger.exception("Vision %s parsing failed", doc_type)
        return {}


async def _parse_tax_document_text(
    ocr_text: str,
    prompt: str,
    doc_type: str,
) -> dict:
    """Generic OCR text parser for tax documents (Form 16, 26AS, AIS)."""
    if not settings.OPENAI_API_KEY:
        return {}

    try:
        client = _get_client()
        response = await client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": ocr_text[:8000]},
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )

        content = response.choices[0].message.content
        return json.loads(content) if content else {}
    except Exception:
        logger.exception("LLM %s text parsing failed", doc_type)
        return {}


# --- Form 16 ---

async def parse_form16_vision(image_bytes: bytes, mime_type: str = "image/jpeg") -> dict:
    """Parse Form 16 image using GPT-4o Vision."""
    return await _parse_tax_document_vision(image_bytes, mime_type, FORM16_VISION_PROMPT, "Form16")


async def parse_form16_text(ocr_text: str) -> dict:
    """Parse Form 16 OCR text using GPT-4o."""
    return await _parse_tax_document_text(ocr_text, FORM16_VISION_PROMPT, "Form16")


# --- Form 26AS ---

async def parse_form26as_vision(image_bytes: bytes, mime_type: str = "image/jpeg") -> dict:
    """Parse Form 26AS image using GPT-4o Vision."""
    return await _parse_tax_document_vision(image_bytes, mime_type, FORM26AS_VISION_PROMPT, "Form26AS")


async def parse_form26as_text(ocr_text: str) -> dict:
    """Parse Form 26AS OCR text using GPT-4o."""
    return await _parse_tax_document_text(ocr_text, FORM26AS_VISION_PROMPT, "Form26AS")


# --- AIS ---

async def parse_ais_vision(image_bytes: bytes, mime_type: str = "image/jpeg") -> dict:
    """Parse AIS image using GPT-4o Vision."""
    return await _parse_tax_document_vision(image_bytes, mime_type, AIS_VISION_PROMPT, "AIS")


async def parse_ais_text(ocr_text: str) -> dict:
    """Parse AIS OCR text using GPT-4o."""
    return await _parse_tax_document_text(ocr_text, AIS_VISION_PROMPT, "AIS")
