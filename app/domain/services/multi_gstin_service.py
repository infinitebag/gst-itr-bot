# app/domain/services/multi_gstin_service.py
"""
Multi-GSTIN management service.

Allows enterprise users to register multiple GSTINs, switch between them,
and get consolidated summaries across all their businesses.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("multi_gstin_service")


async def add_gstin(
    user_id: int,
    gstin: str,
    label: str,
    db: AsyncSession,
    *,
    is_primary: bool = False,
) -> dict[str, Any]:
    """Register a new GSTIN for a user.

    Returns
    -------
    dict
        ``{"success": True, "gstin": "...", "label": "..."}``
        or ``{"success": False, "error": "..."}``
    """
    from app.infrastructure.db.models import UserGSTIN

    # Check for duplicate
    stmt = select(UserGSTIN).where(
        UserGSTIN.user_id == user_id,
        UserGSTIN.gstin == gstin,
    )
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()
    if existing:
        return {"success": False, "error": f"GSTIN {gstin} is already registered"}

    # If this is the first GSTIN, make it primary
    count_stmt = select(UserGSTIN).where(UserGSTIN.user_id == user_id)
    count_result = await db.execute(count_stmt)
    is_first = not count_result.scalars().first()

    new_gstin = UserGSTIN(
        user_id=user_id,
        gstin=gstin,
        label=label,
        is_primary=is_first or is_primary,
        is_active=True,
    )
    db.add(new_gstin)
    await db.commit()
    await db.refresh(new_gstin)

    return {"success": True, "gstin": gstin, "label": label, "id": new_gstin.id}


async def remove_gstin(user_id: int, gstin: str, db: AsyncSession) -> bool:
    """Remove a GSTIN from a user's list. Returns True if removed."""
    from app.infrastructure.db.models import UserGSTIN

    stmt = delete(UserGSTIN).where(
        UserGSTIN.user_id == user_id,
        UserGSTIN.gstin == gstin,
    )
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount > 0


async def list_gstins(user_id: int, db: AsyncSession) -> list[dict[str, Any]]:
    """List all GSTINs for a user.

    Returns
    -------
    list[dict]
        Each dict: ``{"gstin": "...", "label": "...", "is_primary": bool, "is_active": bool}``
    """
    from app.infrastructure.db.models import UserGSTIN

    stmt = select(UserGSTIN).where(
        UserGSTIN.user_id == user_id,
        UserGSTIN.is_active.is_(True),
    ).order_by(UserGSTIN.is_primary.desc(), UserGSTIN.created_at)
    result = await db.execute(stmt)
    gstins = result.scalars().all()

    return [
        {
            "gstin": g.gstin,
            "label": g.label or "",
            "is_primary": g.is_primary,
            "is_active": g.is_active,
        }
        for g in gstins
    ]


async def set_primary(user_id: int, gstin: str, db: AsyncSession) -> bool:
    """Set a GSTIN as the primary one for a user.

    Returns True if successful, False if GSTIN not found.
    """
    from app.infrastructure.db.models import UserGSTIN

    # Clear existing primary
    await db.execute(
        update(UserGSTIN)
        .where(UserGSTIN.user_id == user_id)
        .values(is_primary=False)
    )

    # Set new primary
    result = await db.execute(
        update(UserGSTIN)
        .where(UserGSTIN.user_id == user_id, UserGSTIN.gstin == gstin)
        .values(is_primary=True)
    )
    await db.commit()
    return result.rowcount > 0


async def get_consolidated_summary(
    user_id: int,
    period: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """Aggregate filing status across all GSTINs for enterprise dashboard.

    Returns
    -------
    dict
        ``{"gstins": [...], "total_tax": float, "total_credit": float}``
    """
    from app.infrastructure.db.models import UserGSTIN, ReturnPeriod

    gstins = await list_gstins(user_id, db)

    summary_items = []
    total_tax = 0.0
    total_credit = 0.0

    for g in gstins:
        gstin = g["gstin"]
        # Try to find filing status for this period
        rp_stmt = select(ReturnPeriod).where(
            ReturnPeriod.gstin == gstin,
            ReturnPeriod.period == period,
        )
        rp_result = await db.execute(rp_stmt)
        rp = rp_result.scalar_one_or_none()

        if rp:
            status = rp.status or "pending"
            tax = float(rp.total_tax or 0)
            credit = float(rp.total_itc or 0)
        else:
            status = "not_started"
            tax = 0.0
            credit = 0.0

        # Status emoji
        if status in ("filed", "submitted"):
            emoji = "🟢"
        elif status in ("pending", "draft"):
            emoji = "🟡"
        else:
            emoji = "🔴"

        label = g.get("label") or gstin[:8] + "..."
        summary_items.append(f"{emoji} {gstin[:8]}...{gstin[-4:]} ({label}): {status.title()}")
        total_tax += tax
        total_credit += credit

    return {
        "gstins": gstins,
        "summary_text": "\n".join(summary_items) if summary_items else "No GSTINs registered",
        "total_tax": total_tax,
        "total_credit": total_credit,
        "count": len(gstins),
    }


def format_gstin_list(gstins: list[dict]) -> str:
    """Format a list of GSTINs for WhatsApp display."""
    if not gstins:
        return "No GSTINs registered yet."

    lines = []
    for i, g in enumerate(gstins, 1):
        primary = " ✅" if g.get("is_primary") else ""
        label = f" ({g['label']})" if g.get("label") else ""
        lines.append(f"{i}. {g['gstin']}{label}{primary}")
    return "\n".join(lines)
