# app/infrastructure/db/models.py

import uuid

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

try:
    from pgvector.sqlalchemy import Vector
except ImportError:  # pragma: no cover – optional at import time
    Vector = None

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    whatsapp_number = Column(String(20), unique=True, index=True, nullable=False)

    # API auth columns (nullable — WhatsApp-only users won't have these)
    email = Column(String(255), unique=True, nullable=True, index=True)
    password_hash = Column(String(255), nullable=True)
    name = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    created_at = Column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )

    sessions = relationship("Session", back_populates="user")
    invoices = relationship("Invoice", back_populates="user")
    filing_records = relationship("FilingRecord", back_populates="user")


class Session(Base):
    __tablename__ = "sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    language = Column(String(5), default="en", nullable=False)
    step = Column(String(50), default="LANG_SELECT", nullable=False)
    active = Column(Boolean, default=True, nullable=False)

    created_at = Column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )

    updated_at = Column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=func.now(),
        nullable=False,
    )

    user = relationship("User", back_populates="sessions")

    def to_dict(self) -> dict:
        """
        Lightweight dict used only for Redis cache – do NOT include datetime fields
        to avoid async lazy-load (MissingGreenlet) issues.
        """
        return {
            "id": str(self.id),
            "user_id": str(self.user_id),
            "step": self.step,
            "language": self.language,
        }


class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    raw_text = Column(Text, nullable=True)
    supplier_gstin = Column(String(20))
    receiver_gstin = Column(String(20))

    # Core invoice info
    invoice_number = Column(String(50), nullable=False)
    invoice_date = Column(Date, nullable=True)

    # Recipient – if GSTIN present => B2B, else B2C
    recipient_gstin = Column(String(15), nullable=True)  # 15-char GSTIN or NULL for B2C
    place_of_supply = Column(String(2), nullable=True)  # state code like "36", "27"

    # Tax values
    taxable_value = Column(Numeric(12, 2), nullable=False)
    total_amount = Column(Numeric(12, 2), nullable=True)
    tax_amount = Column(Numeric(12, 2), nullable=False)
    cgst_amount = Column(Numeric(12, 2), nullable=True)
    sgst_amount = Column(Numeric(12, 2), nullable=True)
    igst_amount = Column(Numeric(12, 2), nullable=True)
    tax_rate = Column(Numeric(5, 2), nullable=True)  # e.g. 18.00

    supplier_gstin_valid = Column(Boolean)
    receiver_gstin_valid = Column(Boolean)

    # Monthly compliance fields
    direction = Column(String(10), default="outward", nullable=False, index=True)  # "outward" or "inward"
    itc_eligible = Column(Boolean, default=False, nullable=False)
    reverse_charge = Column(Boolean, default=False, nullable=False)
    blocked_itc_reason = Column(String(100), nullable=True)
    gstr2b_match_status = Column(String(20), nullable=True)  # matched / missing_in_2b / mismatch / excess_in_2b
    gstr2b_match_id = Column(
        UUID(as_uuid=True),
        ForeignKey("itc_matches.id", ondelete="SET NULL", use_alter=True),
        nullable=True,
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )

    user = relationship("User", back_populates="invoices")


class WhatsAppDeadLetter(Base):
    __tablename__ = "whatsapp_dead_letters"

    id = Column(Integer, primary_key=True)
    to_number = Column(String(32), nullable=False)
    text = Column(Text, nullable=False)

    failure_reason = Column(
        String(64), nullable=False
    )  # e.g. 'max_retries_exceeded', 'per_user_rate_limit'
    last_error = Column(
        Text, nullable=True
    )  # JSON or message from WhatsApp / exception

    retry_count = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())


class WhatsAppMessageLog(Base):
    __tablename__ = "whatsapp_message_logs"

    id = Column(Integer, primary_key=True)
    to_number = Column(String(32), nullable=False)
    text = Column(Text, nullable=False)

    status = Column(
        String(32), nullable=False
    )  # 'sent', 'dropped_rate_limit', 'failed'
    error = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())


class CAUser(Base):
    __tablename__ = "ca_users"

    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    name = Column(String(255), nullable=False)
    phone = Column(String(20), nullable=True)
    membership_number = Column(String(20), nullable=True)  # ICAI membership no.

    active = Column(Boolean, default=True)
    approved = Column(Boolean, default=False, nullable=False)
    approved_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    last_login = Column(DateTime(timezone=True), nullable=True)

    clients = relationship("BusinessClient", back_populates="ca")


class BusinessClient(Base):
    __tablename__ = "business_clients"

    id = Column(Integer, primary_key=True)
    ca_id = Column(Integer, ForeignKey("ca_users.id", ondelete="CASCADE"), index=True)
    name = Column(String(255), nullable=False)
    gstin = Column(String(20))
    whatsapp_number = Column(String(32), unique=True)

    # Extended fields
    pan = Column(String(10), nullable=True)
    email = Column(String(255), nullable=True)
    business_type = Column(String(50), nullable=True)  # sole_prop, partnership, pvt_ltd, llp
    address = Column(Text, nullable=True)
    state_code = Column(String(2), nullable=True)  # e.g. "36" for Telangana
    status = Column(String(20), default="active", nullable=False)  # active / inactive
    notes = Column(Text, nullable=True)

    # Phase 2: Taxpayer type & composition rate
    taxpayer_type = Column(String(20), default="regular", nullable=False)  # regular / composition / qrmp
    composition_rate = Column(Numeric(5, 2), nullable=True)  # e.g. 1.00 traders, 5.00 restaurants

    # Phase 4: Segment gating
    segment = Column(String(20), default="small", nullable=False)  # small / medium / enterprise
    annual_turnover = Column(Numeric(15, 2), nullable=True)        # in INR
    monthly_invoice_volume = Column(Integer, nullable=True)
    gstin_count = Column(Integer, default=1, nullable=False)
    is_exporter = Column(Boolean, default=False, nullable=False)
    segment_override = Column(Boolean, default=False, nullable=False)  # True if CA manually set segment

    created_at = Column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=func.now(),
        nullable=False,
    )

    ca = relationship("CAUser", back_populates="clients")


class FilingRecord(Base):
    """Track GST and ITR filing submissions."""

    __tablename__ = "filing_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    filing_type = Column(String(20), nullable=False)  # "GST" or "ITR"
    form_type = Column(String(20), nullable=False)  # "GSTR-3B", "GSTR-1", "ITR-1", "ITR-4"

    gstin = Column(String(20), nullable=True)
    pan = Column(String(10), nullable=True)
    period = Column(String(10), nullable=False)  # "2025-01" (GST) or "2025-26" (ITR AY)

    status = Column(
        String(30), nullable=False, default="draft"
    )  # "draft", "pending_ca_review", "ca_approved", "changes_requested",
    #   "submitted", "acknowledged", "error"

    reference_number = Column(String(100), nullable=True)  # Ack number from API
    payload_json = Column(Text, nullable=True)  # Full JSON payload stored
    response_json = Column(Text, nullable=True)  # API response stored

    # CA review fields
    ca_id = Column(
        Integer,
        ForeignKey("ca_users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    ca_notes = Column(Text, nullable=True)
    ca_reviewed_at = Column(DateTime(timezone=True), nullable=True)

    filed_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=func.now(),
        nullable=False,
    )

    user = relationship("User", back_populates="filing_records")
    ca = relationship("CAUser")


class ITRDraft(Base):
    """ITR draft computation pending CA review / user confirmation."""

    __tablename__ = "itr_drafts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ca_id = Column(
        Integer,
        ForeignKey("ca_users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    form_type = Column(String(20), nullable=False)       # "ITR-1" or "ITR-4"
    assessment_year = Column(String(10), nullable=False)  # "2025-26"
    pan = Column(String(10), nullable=True)

    # Workflow status
    status = Column(
        String(30), nullable=False, default="draft"
    )  # draft, pending_ca_review, ca_approved, changes_requested, user_confirmed, filed

    # Serialized computation data
    input_json = Column(Text, nullable=True)         # ITR1Input / ITR4Input
    result_json = Column(Text, nullable=True)        # ITRResult
    merged_data_json = Column(Text, nullable=True)   # MergedITRData
    mismatch_json = Column(Text, nullable=True)      # MismatchReport
    checklist_json = Column(Text, nullable=True)     # DocumentChecklist

    # CA review
    ca_notes = Column(Text, nullable=True)
    ca_reviewed_at = Column(DateTime(timezone=True), nullable=True)

    # GST linking
    linked_gst_filing_ids = Column(Text, nullable=True)  # JSON array of UUIDs

    # Final filing reference
    filing_record_id = Column(
        UUID(as_uuid=True),
        ForeignKey("filing_records.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=func.now(),
        nullable=False,
    )

    user = relationship("User")
    ca = relationship("CAUser")
    filing_record = relationship("FilingRecord")


class TaxRateConfig(Base):
    """Versioned tax rate configurations with audit trail."""

    __tablename__ = "tax_rate_configs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    rate_type = Column(String(10), nullable=False, index=True)  # "itr" or "gst"
    assessment_year = Column(String(10), nullable=True, index=True)  # "2025-26" for ITR; NULL for GST

    config_json = Column(Text, nullable=False)  # Serialized ITRSlabConfig or GSTRateConfig

    source = Column(String(20), nullable=False, default="hardcoded")  # "openai", "manual", "hardcoded"
    version = Column(Integer, nullable=False, default=1)  # Incremented per (rate_type, assessment_year)

    is_active = Column(Boolean, nullable=False, default=True)  # Only one active per (rate_type, ay)

    created_by = Column(String(100), nullable=True)  # "admin", "system", "openai_refresh"
    notes = Column(Text, nullable=True)  # Human-readable description

    created_at = Column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )


class ReturnPeriod(Base):
    """Monthly GST return period tracking with computation aggregates."""

    __tablename__ = "return_periods"
    __table_args__ = (
        UniqueConstraint("gstin", "period", name="uq_return_periods_gstin_period"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    gstin = Column(String(20), nullable=False)
    fy = Column(String(10), nullable=False)          # "2024-25"
    period = Column(String(10), nullable=False)       # "2025-01" (YYYY-MM)
    filing_mode = Column(String(20), default="monthly", nullable=False)

    # Status lifecycle:
    # draft → data_ready → recon_in_progress → reconciled → ca_review
    # → approved → payment_pending → paid → filed → closed
    status = Column(String(30), default="draft", nullable=False)

    # Invoice counts
    outward_count = Column(Integer, default=0, nullable=False)
    inward_count = Column(Integer, default=0, nullable=False)

    # Output tax aggregates (from outward supplies)
    output_tax_igst = Column(Numeric(14, 2), default=0, nullable=False)
    output_tax_cgst = Column(Numeric(14, 2), default=0, nullable=False)
    output_tax_sgst = Column(Numeric(14, 2), default=0, nullable=False)

    # Eligible ITC aggregates (from matched 2B + eligible inward)
    itc_igst = Column(Numeric(14, 2), default=0, nullable=False)
    itc_cgst = Column(Numeric(14, 2), default=0, nullable=False)
    itc_sgst = Column(Numeric(14, 2), default=0, nullable=False)

    # Net payable = output - ITC + RCM
    net_payable_igst = Column(Numeric(14, 2), default=0, nullable=False)
    net_payable_cgst = Column(Numeric(14, 2), default=0, nullable=False)
    net_payable_sgst = Column(Numeric(14, 2), default=0, nullable=False)

    # Reverse charge mechanism liability
    rcm_igst = Column(Numeric(14, 2), default=0, nullable=False)
    rcm_cgst = Column(Numeric(14, 2), default=0, nullable=False)
    rcm_sgst = Column(Numeric(14, 2), default=0, nullable=False)

    # Phase 2: Additional tax heads & penalties
    late_fee = Column(Numeric(14, 2), default=0, nullable=False)
    interest = Column(Numeric(14, 2), default=0, nullable=False)
    cess_output = Column(Numeric(14, 2), default=0, nullable=False)
    cess_itc = Column(Numeric(14, 2), default=0, nullable=False)

    # Risk flags & metadata
    risk_flags = Column(Text, nullable=True)  # JSON array of risk flag strings
    risk_assessment_id = Column(
        UUID(as_uuid=True),
        ForeignKey("risk_assessments.id", ondelete="SET NULL", use_alter=True),
        nullable=True,
    )
    ca_id = Column(
        Integer,
        ForeignKey("ca_users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    gstr1_filing_id = Column(
        UUID(as_uuid=True),
        ForeignKey("filing_records.id", ondelete="SET NULL"),
        nullable=True,
    )
    gstr3b_filing_id = Column(
        UUID(as_uuid=True),
        ForeignKey("filing_records.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Due dates (11th for GSTR-1, 20th for GSTR-3B of next month)
    due_date_gstr1 = Column(Date, nullable=True)
    due_date_gstr3b = Column(Date, nullable=True)

    computed_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    user = relationship("User")
    ca = relationship("CAUser")
    gstr1_filing = relationship("FilingRecord", foreign_keys=[gstr1_filing_id])
    gstr3b_filing = relationship("FilingRecord", foreign_keys=[gstr3b_filing_id])
    risk_assessment = relationship(
        "RiskAssessment",
        foreign_keys=[risk_assessment_id],
        uselist=False,
    )
    payments = relationship("PaymentRecord", back_populates="period")


class ITCMatch(Base):
    """GSTR-2B entry matched against purchase invoices for ITC reconciliation."""

    __tablename__ = "itc_matches"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    period_id = Column(
        UUID(as_uuid=True),
        ForeignKey("return_periods.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    purchase_invoice_id = Column(
        UUID(as_uuid=True),
        ForeignKey("invoices.id", ondelete="SET NULL"),
        nullable=True,
    )

    # GSTR-2B source data
    gstr2b_supplier_gstin = Column(String(20), nullable=False)
    gstr2b_invoice_number = Column(String(50), nullable=False)
    gstr2b_invoice_date = Column(Date, nullable=True)
    gstr2b_taxable_value = Column(Numeric(12, 2), nullable=False)
    gstr2b_igst = Column(Numeric(12, 2), default=0, nullable=False)
    gstr2b_cgst = Column(Numeric(12, 2), default=0, nullable=False)
    gstr2b_sgst = Column(Numeric(12, 2), default=0, nullable=False)

    # Reconciliation result
    match_status = Column(String(20), nullable=False)  # matched / missing_in_books / missing_in_2b / value_mismatch / unmatched
    mismatch_details = Column(Text, nullable=True)  # JSON: {"field": "taxable_value", "books": 5000, "2b": 4800}

    created_at = Column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )

    # Relationships
    period = relationship("ReturnPeriod")
    purchase_invoice = relationship("Invoice", foreign_keys=[purchase_invoice_id])


class RiskAssessment(Base):
    """100-point risk scoring result for a return period (Categories A-E)."""

    __tablename__ = "risk_assessments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    period_id = Column(
        UUID(as_uuid=True),
        ForeignKey("return_periods.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    # Overall score & level
    risk_score = Column(Integer, default=0, nullable=False)  # 0-100
    risk_level = Column(String(20), default="LOW", nullable=False)  # LOW/MEDIUM/HIGH/CRITICAL

    # Detailed flags & recommendations (JSON)
    risk_flags = Column(Text, nullable=True)  # [{code, severity, points, evidence}]
    recommended_actions = Column(Text, nullable=True)  # [{action, why}]

    # Per-category scores
    category_a_score = Column(Integer, default=0, nullable=False)  # Data Quality (max 20)
    category_b_score = Column(Integer, default=0, nullable=False)  # ITC & 2B Recon (max 35)
    category_c_score = Column(Integer, default=0, nullable=False)  # Liability/Payment/Filing (max 20)
    category_d_score = Column(Integer, default=0, nullable=False)  # Behavioral/Anomaly (max 15)
    category_e_score = Column(Integer, default=0, nullable=False)  # Policy/Structural (max 10)

    # CA calibration fields
    ca_override_score = Column(Integer, nullable=True)
    ca_override_notes = Column(Text, nullable=True)
    ca_final_outcome = Column(String(30), nullable=True)  # approved/approved_with_changes/major_changes
    post_filing_outcome = Column(String(30), nullable=True)  # clean/notice/query/late_fee

    # ML risk scoring (Phase 3B)
    ml_risk_score = Column(Integer, nullable=True)          # ML-only score (0-100)
    ml_prediction_json = Column(Text, nullable=True)        # full MLPrediction as JSON
    blend_weight = Column(Float, nullable=True)             # actual weight used (0.0 if rule-only)

    computed_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    period = relationship(
        "ReturnPeriod",
        foreign_keys=[period_id],
        overlaps="risk_assessment",
    )


class PaymentRecord(Base):
    """Challan / payment record for a return period (supports split payments)."""

    __tablename__ = "payment_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    period_id = Column(
        UUID(as_uuid=True),
        ForeignKey("return_periods.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    challan_number = Column(String(50), nullable=True)
    challan_date = Column(Date, nullable=True)

    igst = Column(Numeric(14, 2), default=0, nullable=False)
    cgst = Column(Numeric(14, 2), default=0, nullable=False)
    sgst = Column(Numeric(14, 2), default=0, nullable=False)
    cess = Column(Numeric(14, 2), default=0, nullable=False)
    total = Column(Numeric(14, 2), default=0, nullable=False)

    payment_mode = Column(String(20), nullable=True)  # cash / neft / rtgs / online
    bank_reference = Column(String(100), nullable=True)
    status = Column(String(20), default="pending", nullable=False)  # pending / confirmed / failed
    notes = Column(Text, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    period = relationship("ReturnPeriod", back_populates="payments")


class AnnualReturn(Base):
    """GSTR-9 annual return aggregation across 12 monthly periods."""

    __tablename__ = "annual_returns"
    __table_args__ = (
        UniqueConstraint("gstin", "fy", name="uq_annual_returns_gstin_fy"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    gstin = Column(String(20), nullable=False)
    fy = Column(String(10), nullable=False)  # "2024-25"

    # Status lifecycle:
    # draft → aggregated → ca_review → approved → filed → closed
    status = Column(String(30), default="draft", nullable=False)

    # Aggregated totals (from 12 monthly periods)
    total_outward_taxable = Column(Numeric(14, 2), default=0, nullable=False)
    total_inward_taxable = Column(Numeric(14, 2), default=0, nullable=False)
    total_itc_claimed = Column(Numeric(14, 2), default=0, nullable=False)
    total_itc_reversed = Column(Numeric(14, 2), default=0, nullable=False)
    total_tax_paid = Column(Numeric(14, 2), default=0, nullable=False)

    # Discrepancy analysis (JSON)
    monthly_vs_annual_diff = Column(Text, nullable=True)  # per-month comparison
    books_vs_gst_diff = Column(Text, nullable=True)  # reconciliation with books

    # Risk score for annual return
    risk_score = Column(Integer, nullable=True)

    # CA assignment & filing
    ca_id = Column(
        Integer,
        ForeignKey("ca_users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    filing_record_id = Column(
        UUID(as_uuid=True),
        ForeignKey("filing_records.id", ondelete="SET NULL"),
        nullable=True,
    )

    computed_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    user = relationship("User")
    ca = relationship("CAUser")
    filing_record = relationship("FilingRecord")


class KnowledgeDocument(Base):
    """Knowledge base document for RAG — stores circulars, rules, CA precedents."""

    __tablename__ = "knowledge_documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(500), nullable=False)
    content = Column(Text, nullable=False)  # full original text

    # Category: gst / itr / general / ca_precedent / circular
    category = Column(String(50), nullable=False, index=True)
    source = Column(String(500), nullable=True)  # URL, circular number, or "ca_review:{id}"
    effective_date = Column(Date, nullable=True)

    metadata_json = Column(Text, nullable=True)  # JSON for extra fields (section numbers, act, etc.)
    chunk_count = Column(Integer, default=0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False, index=True)

    created_at = Column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    chunks = relationship(
        "KnowledgeChunk",
        back_populates="document",
        cascade="all, delete-orphan",
    )


class KnowledgeChunk(Base):
    """Chunk of a knowledge document with pgvector embedding for RAG search."""

    __tablename__ = "knowledge_chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    chunk_index = Column(Integer, nullable=False)  # 0-based order within document
    content = Column(Text, nullable=False)  # chunk text (≤ RAG_CHUNK_SIZE tokens)
    token_count = Column(Integer, nullable=False)

    # pgvector column — 1536 dimensions for text-embedding-3-small
    embedding = Column(Vector(1536)) if Vector else Column(Text)

    section_header = Column(String(300), nullable=True)  # extracted section/heading for context
    metadata_json = Column(Text, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )

    # Relationships
    document = relationship("KnowledgeDocument", back_populates="chunks")


class MLModelArtifact(Base):
    """Serialized ML model artifacts stored in PostgreSQL for risk scoring."""

    __tablename__ = "ml_model_artifacts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    model_name = Column(String(100), nullable=False, index=True)  # "risk_scoring_v1"
    version = Column(Integer, nullable=False)
    is_active = Column(Boolean, default=False, nullable=False)

    # Serialized model (joblib)
    model_binary = Column(LargeBinary, nullable=False)
    model_size_bytes = Column(Integer, nullable=True)

    # Training metadata
    training_samples = Column(Integer, nullable=False)
    accuracy = Column(Float, nullable=True)
    f1_macro = Column(Float, nullable=True)
    metrics_json = Column(Text, nullable=True)          # full classification report JSON
    feature_names_json = Column(Text, nullable=True)    # ordered feature list

    trained_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )


class Feature(Base):
    """Feature registry for segment-based gating (Phase 4)."""

    __tablename__ = "features"

    id = Column(Integer, primary_key=True)
    code = Column(String(50), unique=True, index=True, nullable=False)  # "enter_gstin", "e_invoice", etc.
    name = Column(String(100), nullable=False)           # human-friendly name
    description = Column(Text, nullable=True)
    category = Column(String(50), default="gst", nullable=False)  # "gst" / "itr" / "settings"
    display_order = Column(Integer, default=0, nullable=False)     # controls menu ordering
    whatsapp_state = Column(String(50), nullable=True)    # maps to WhatsApp state constant
    i18n_key = Column(String(100), nullable=True)         # i18n message key for menu label
    is_active = Column(Boolean, default=True, nullable=False)

    created_at = Column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )


class SegmentFeature(Base):
    """Maps features to segments (small/medium/enterprise)."""

    __tablename__ = "segment_features"
    __table_args__ = (
        UniqueConstraint("segment", "feature_id", name="uq_segment_feature"),
    )

    id = Column(Integer, primary_key=True)
    segment = Column(String(20), index=True, nullable=False)  # "small" / "medium" / "enterprise"
    feature_id = Column(
        Integer,
        ForeignKey("features.id", ondelete="CASCADE"),
        nullable=False,
    )
    enabled = Column(Boolean, default=True, nullable=False)

    feature = relationship("Feature")


class ClientAddon(Base):
    """Per-client feature overrides beyond their segment defaults."""

    __tablename__ = "client_addons"
    __table_args__ = (
        UniqueConstraint("client_id", "feature_id", name="uq_client_addon"),
    )

    id = Column(Integer, primary_key=True)
    client_id = Column(
        Integer,
        ForeignKey("business_clients.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    feature_id = Column(
        Integer,
        ForeignKey("features.id", ondelete="CASCADE"),
        nullable=False,
    )
    enabled = Column(Boolean, default=True, nullable=False)
    granted_by = Column(String(50), nullable=True)  # "admin" / "ca" / "auto_upgrade"
    granted_at = Column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )

    feature = relationship("Feature")


# ========================
# Phase 8: Multi-GSTIN
# ========================
class UserGSTIN(Base):
    """User's registered GSTINs for multi-GSTIN management (enterprise)."""

    __tablename__ = "user_gstins"
    __table_args__ = (
        UniqueConstraint("user_id", "gstin", name="uq_user_gstin"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    gstin = Column(String(15), nullable=False)
    label = Column(String(100), nullable=True)  # "Main Office", "Branch 2"
    is_primary = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )


# ========================
# Phase 9A: Refund Claims
# ========================
class RefundClaim(Base):
    """GST refund claim tracking."""

    __tablename__ = "refund_claims"

    id = Column(Integer, primary_key=True)
    gstin = Column(String(15), index=True, nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    claim_type = Column(String(50), nullable=False)  # excess_balance / export / inverted_duty
    amount = Column(Numeric(15, 2), nullable=True)
    period = Column(String(10), nullable=True)
    status = Column(String(30), default="draft", nullable=False)
    arn = Column(String(50), nullable=True)  # Application Reference Number
    created_at = Column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        onupdate=text("CURRENT_TIMESTAMP"),
        nullable=True,
    )


# ========================
# Phase 9B: GST Notices
# ========================
class GSTNotice(Base):
    """GST notice tracking and response management."""

    __tablename__ = "gst_notices"

    id = Column(Integer, primary_key=True)
    gstin = Column(String(15), index=True, nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    notice_type = Column(String(50), nullable=False)  # ASMT-10, DRC-01, REG-17, etc.
    description = Column(Text, nullable=True)
    due_date = Column(Date, nullable=True)
    status = Column(String(30), default="received", nullable=False)
    response_text = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )


# ========================
# Phase 10: Notifications
# ========================
class NotificationSchedule(Base):
    """Scheduled proactive notifications via WhatsApp templates."""

    __tablename__ = "notification_schedules"

    id = Column(Integer, primary_key=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), index=True, nullable=True)
    gstin = Column(String(15), nullable=True)
    notification_type = Column(String(50), nullable=False)
    scheduled_for = Column(DateTime(timezone=True), nullable=False)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(20), default="pending", nullable=False)
    template_name = Column(String(100), nullable=False)
    template_params = Column(JSON, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
