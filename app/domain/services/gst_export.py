from typing import Dict
from .gst_service import Gstr3BSummary


def make_gstr3b_json(summary: Gstr3BSummary) -> Dict:
    return {
        "sup_details": {
            "osup_det": {
                "txval": summary.total_taxable_value,
                "igst": summary.total_igst,
                "cgst": summary.total_cgst,
                "sgst": summary.total_sgst,
            }
        },
        "tax_payable": {
            "total_tax": summary.total_tax
        }
    }


def make_gstr1_json() -> Dict:
    # Phase-3 stub (works for demo)
    return {
        "b2b": [],
        "b2c": [],
        "hsn": []
    }