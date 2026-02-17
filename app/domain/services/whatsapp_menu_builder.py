# app/domain/services/whatsapp_menu_builder.py
"""
Dynamic WhatsApp menu builder for segment-based feature gating.

Builds GST menus dynamically based on the client's segment,
storing the feature→number mapping in the session for dispatch.

Segment menus:
  Small:      Upload Bills, File This Month, Tax to Pay, Filed Status
  Medium:     Upload Bills, File GST, Check Purchase Credits, Tax to Pay, Filed Status
  Enterprise: Select GST Number, Upload Bills, File GST, Check Purchase Credits,
              Tax to Pay, Filed Status

For medium/enterprise segments with >3 features, returns an
interactive list payload (for ``send_whatsapp_list``).  For
small segments, returns plain text with numbered options.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Union

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.domain.i18n import MESSAGES, SUPPORTED_LANGS

logger = logging.getLogger("whatsapp_menu_builder")

# Type alias: the menu builder returns either a plain text string
# or a dict describing an interactive list payload.
MenuResult = Union[str, dict]

# ──────────────────────────────────────────────────────────
# Segment-specific menu definitions
# Each tuple: (feature_code, i18n_key)
# ──────────────────────────────────────────────────────────

_SMALL_MENU = [
    ("upload_bills", "GST_MENU_UPLOAD_BILLS"),
    ("file_this_month", "GST_MENU_FILE_THIS_MONTH"),
    ("tax_to_pay", "GST_MENU_TAX_TO_PAY"),
    ("filed_status", "GST_MENU_FILED_STATUS"),
]

_MEDIUM_MENU = [
    ("upload_bills", "GST_MENU_UPLOAD_BILLS"),
    ("file_gst", "GST_MENU_FILE_GST"),
    ("credit_check", "GST_MENU_CREDIT_CHECK"),
    ("tax_to_pay", "GST_MENU_TAX_TO_PAY"),
    ("filed_status", "GST_MENU_FILED_STATUS"),
]

_ENTERPRISE_MENU = [
    ("select_gstin", "GST_MENU_SELECT_GSTIN"),
    ("upload_bills", "GST_MENU_UPLOAD_BILLS"),
    ("file_gst", "GST_MENU_FILE_GST"),
    ("credit_check", "GST_MENU_CREDIT_CHECK"),
    ("tax_to_pay", "GST_MENU_TAX_TO_PAY"),
    ("filed_status", "GST_MENU_FILED_STATUS"),
]

_SEGMENT_MENUS = {
    "small": _SMALL_MENU,
    "medium": _MEDIUM_MENU,
    "enterprise": _ENTERPRISE_MENU,
}


async def build_gst_menu(
    wa_id: str,
    session: Dict[str, Any],
    db: AsyncSession,
) -> MenuResult:
    """Build a segment-aware GST menu.

    Returns
    -------
    str
        Plain text numbered menu (small segment or fallback).
    dict
        Interactive list payload for ``send_whatsapp_list()``
        when the segment is medium/enterprise and there are >3 features.
        Keys: ``type="list"``, ``body``, ``sections``, ``button_text``,
        ``header``, ``footer``.

    Side effects
    ------------
    Stores ``session["data"]["gst_menu_map"]`` — maps feature codes
    (used as list row IDs or numeric strings) to feature codes for dispatch.
    Also stores ``session["data"]["client_segment"]`` for downstream use.
    """
    lang = session.get("lang", "en")
    data = session.setdefault("data", {})

    # Determine segment from session (set during onboarding) or DB
    client_segment = data.get("client_segment", "small")

    # If segment gating is enabled and we have a GSTIN, try to get from DB
    gstin = data.get("gstin")
    if settings.SEGMENT_GATING_ENABLED and gstin and not data.get("gst_onboarded"):
        try:
            from app.infrastructure.db.models import BusinessClient
            stmt = select(BusinessClient).where(BusinessClient.gstin == gstin)
            result = await db.execute(stmt)
            client = result.scalar_one_or_none()
            if client:
                client_segment = getattr(client, "segment", "small") or "small"
        except Exception:
            logger.exception("Failed to load segment for gstin=%s", gstin)

    data["client_segment"] = client_segment

    # Get menu items for this segment
    menu_items = _SEGMENT_MENUS.get(client_segment, _SMALL_MENU)

    # Build menu map
    menu_map: dict[str, str] = {}

    header = _get_i18n_label("GST_MENU_HEADER", lang) or "GST Services"
    count = len(menu_items)

    # ---- Interactive list for medium / enterprise ----
    if client_segment in ("medium", "enterprise") and count > 3:
        rows = []
        for code, i18n_key in menu_items:
            menu_map[code] = code
            label = _get_i18n_label(i18n_key, lang) or code.replace("_", " ").title()
            rows.append({
                "id": code,
                "title": label[:24],
                "description": "",
            })

        data["gst_menu_map"] = menu_map

        footer_text = _get_i18n_label("GST_MENU_FOOTER", lang)
        if footer_text:
            footer_text = footer_text.strip()
        else:
            footer_text = "MENU = Main Menu | BACK = Go Back"

        return {
            "type": "list",
            "header": header,
            "body": f"{header}\n\n{_get_i18n_label('GST_MENU_LIST_BODY', lang) or 'Select a service from the list below.'}",
            "sections": [{"title": header, "rows": rows}],
            "button_text": _get_i18n_label("GST_MENU_LIST_BUTTON", lang) or "Choose Service",
            "footer": footer_text,
        }

    # ---- Plain text numbered menu for small segment ----
    menu_lines = []
    for idx, (code, i18n_key) in enumerate(menu_items, start=1):
        num = str(idx)
        menu_map[num] = code
        label = _get_i18n_label(i18n_key, lang) or code.replace("_", " ").title()
        menu_lines.append(f"{num}) {label}")

    data["gst_menu_map"] = menu_map

    footer = _get_i18n_label("GST_MENU_FOOTER", lang) or (
        f"\nReply 1-{count}\nMENU = Main Menu\nBACK = Go Back"
    )

    menu_text = f"{header}\n\n" + "\n".join(menu_lines) + footer
    return menu_text


async def resolve_gst_menu_choice(choice: str, session: Dict[str, Any]) -> str | None:
    """Map a user's numeric or feature-code choice to a feature code.

    Uses the ``gst_menu_map`` stored in session by ``build_gst_menu()``.

    For **text menus** (small segment), the choice is "1", "2", etc.
    For **interactive lists** (medium/enterprise), the choice is the
    feature code itself (e.g. ``"upload_bills"``).

    Returns feature code string or None if invalid choice.
    """
    menu_map = session.get("data", {}).get("gst_menu_map")
    if not menu_map:
        return None

    stripped = choice.strip()

    # Direct lookup (handles both "1" → "upload_bills" and "upload_bills" → "upload_bills")
    return menu_map.get(stripped)


def _get_i18n_label(key: str, lang: str) -> str | None:
    """Get an i18n label. Returns None if not found."""
    msgs = MESSAGES.get(key)
    if not msgs:
        return None
    return msgs.get(lang) or msgs.get("en")
