"""Shared test fixtures for the GST/ITR Bot test suite."""

import asyncio
from decimal import Decimal

import pytest


@pytest.fixture(scope="session")
def event_loop():
    """Use a single event loop for the entire test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def sample_invoice_text() -> str:
    """Sample OCR text from a typical Indian GST invoice."""
    return """
    TAX INVOICE
    Invoice No: INV-2025-001
    Date: 15-01-2025

    Supplier GSTIN: 36AABCU9603R1ZM
    Seller: ABC Traders Pvt Ltd
    Address: Hyderabad, Telangana

    Buyer (Bill To):
    Buyer GSTIN: 27AADCB2230M1ZP
    XYZ Enterprises
    Mumbai, Maharashtra

    HSN Code: 84715000
    Description: Laptop Computer

    Place of Supply: 27-Maharashtra

    Taxable Value: Rs 85,000.00
    IGST @ 18%: Rs 15,300.00
    Total Amount: Rs 1,00,300.00
    """


@pytest.fixture
def sample_itr1_input() -> dict:
    """Sample ITR-1 input for a salaried individual."""
    return {
        "salary_income": Decimal("1200000"),
        "house_property_income": Decimal("0"),
        "other_income": Decimal("50000"),
        "section_80c": Decimal("150000"),
        "section_80d": Decimal("25000"),
        "section_80tta": Decimal("10000"),
        "tds_total": Decimal("80000"),
    }
