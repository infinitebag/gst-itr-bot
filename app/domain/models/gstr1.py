# app/domain/models/gstr1.py

from datetime import date

from pydantic import BaseModel, Field


class Gstr1InvoiceItem(BaseModel):
    num: int = Field(..., description="Line item number")
    rt: float = Field(..., description="Tax rate (e.g. 18.0)")
    txval: float = Field(..., description="Taxable value")
    iamt: float = Field(0.0, description="IGST amount")
    camt: float = Field(0.0, description="CGST amount")
    samt: float = Field(0.0, description="SGST amount")


class Gstr1B2BInv(BaseModel):
    inum: str  # invoice number
    idt: date  # invoice date
    val: float  # total invoice value
    pos: str  # place of supply (state code)
    itms: list[Gstr1InvoiceItem]


class Gstr1B2BEntry(BaseModel):
    ctin: str  # recipient GSTIN
    inv: list[Gstr1B2BInv]


class Gstr1B2CInv(BaseModel):
    inum: str
    idt: date
    pos: str
    txval: float
    rt: float
    iamt: float = 0.0
    camt: float = 0.0
    samt: float = 0.0


class Gstr1Payload(BaseModel):
    gstin: str
    fp: str  # filing period e.g. "112025" for Nov 2025
    b2b: list[Gstr1B2BEntry] | None = None
    b2c: list[Gstr1B2CInv] | None = None
