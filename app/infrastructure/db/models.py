# app/infrastructure/db/models.py

import uuid

from app.db.base import Base
from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.infrastructure.db.base import Base


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    whatsapp_number = Column(String(20), unique=True, index=True, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )

    sessions = relationship("Session", back_populates="user")
    invoices = relationship("Invoice", back_populates="user")


class Session(Base):
    __tablename__ = "sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    language = Column(String(5), default="en", nullable=False)
    step = Column(String(50), default="LANG_SELECT", nullable=False)
    active = Column(Boolean, default=True, nullable=False)

    # 🟩 Created automatically when session is created
    created_at = Column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )

    # 🟩 Auto-updated timestamp maintained by DB on each update
    last_updated = Column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=func.now(),
        nullable=False,
    )

    # 🟩 Optional manual field — we will update this ourselves in repository
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


from sqlalchemy import Boolean, ForeignKey
from sqlalchemy.orm import relationship


class CAUser(Base):
    __tablename__ = "ca_users"

    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)  # store hash later
    name = Column(String(255), nullable=False)

    active = Column(Boolean, default=True)

    clients = relationship("BusinessClient", back_populates="ca")


class BusinessClient(Base):
    __tablename__ = "business_clients"

    id = Column(Integer, primary_key=True)
    ca_id = Column(Integer, ForeignKey("ca_users.id"))
    name = Column(String(255), nullable=False)
    gstin = Column(String(20))
    whatsapp_number = Column(String(32), unique=True)

    ca = relationship("CAUser", back_populates="clients")
