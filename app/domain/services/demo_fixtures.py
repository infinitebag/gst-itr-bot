from __future__ import annotations
from typing import Dict, Any
import random
from datetime import date

def demo_invoice_parse_result() -> Dict[str, Any]:
    inv_no = f"INV-{random.randint(1000,9999)}"
    return {
        "supplier_gstin": "36ABCDE1234F1Z5",
        "receiver_gstin": "29ABCDE1234F1Z5",
        "invoice_number": inv_no,
        "invoice_date": date.today().isoformat(),
        "taxable_value": 12000.00,
        "tax_amount": 2160.00,
        "cgst_amount": 1080.00,
        "sgst_amount": 1080.00,
        "igst_amount": 0.00,
        "total_amount": 14160.00,
        "place_of_supply": "Telangana",
        "confidence": 0.91,
    }