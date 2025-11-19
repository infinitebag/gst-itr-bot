from datetime import date
from app.domain.models.gst import Gstr3bSummary
from app.infrastructure.db.repositories import InvoiceRepository

async def prepare_gstr3b(user_id: str, start: date, end: date, repo: InvoiceRepository):
    invoices = await repo.get_invoices_for_period(user_id, start, end)
    total_taxable = sum(i.taxable_value for i in invoices)
    total_tax = sum(i.tax_amount for i in invoices)
    return Gstr3bSummary(
        user_id=user_id,
        period_start=start,
        period_end=end,
        total_taxable=total_taxable,
        total_tax=total_tax,
        total_invoices=len(invoices)
    )