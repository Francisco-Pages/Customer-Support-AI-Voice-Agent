"""
SQLAlchemy ORM models for the HVAC Voice AI Agent.

Tables
------
  customers          — caller identity, contact info, TCPA consent
  customer_products  — products a customer has registered (for warranty lookups)
  calls              — every inbound/outbound call: SID, transcript, outcome
  appointments       — service visits scheduled during or after calls
  outbound_queue     — campaign entries waiting to be dialled
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship



# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# customers
# ---------------------------------------------------------------------------


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    phone: Mapped[str] = mapped_column(
        String(20), unique=True, index=True, nullable=False
    )
    name: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(200))
    address: Mapped[str | None] = mapped_column(Text)
    # "owner" | "technician" | None (unknown)
    caller_type: Mapped[str | None] = mapped_column(String(20))
    tcpa_consent: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    products: Mapped[list["CustomerProduct"]] = relationship(
        back_populates="customer", cascade="all, delete-orphan"
    )
    calls: Mapped[list["Call"]] = relationship(back_populates="customer")
    appointments: Mapped[list["Appointment"]] = relationship(
        back_populates="customer"
    )
    outbound_entries: Mapped[list["OutboundQueue"]] = relationship(
        back_populates="customer"
    )


# ---------------------------------------------------------------------------
# customer_products
# ---------------------------------------------------------------------------


class CustomerProduct(Base):
    __tablename__ = "customer_products"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product_model: Mapped[str] = mapped_column(String(100), nullable=False)
    # "residential" | "commercial" | "parts"
    product_line: Mapped[str] = mapped_column(String(50), nullable=False)
    serial_number: Mapped[str | None] = mapped_column(String(100))
    serial_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    purchase_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    warranty_end_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    customer: Mapped["Customer"] = relationship(back_populates="products")


# ---------------------------------------------------------------------------
# calls
# ---------------------------------------------------------------------------


class Call(Base):
    __tablename__ = "calls"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="SET NULL"),
        index=True,
    )
    # "inbound" | "outbound"
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    caller_phone: Mapped[str | None] = mapped_column(String(20))
    twilio_call_sid: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, index=True
    )
    livekit_room: Mapped[str | None] = mapped_column(String(200))
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_sec: Mapped[int | None] = mapped_column(Integer)
    transcript: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    # "resolved" | "escalated" | "voicemail" | "abandoned"
    resolution: Mapped[str | None] = mapped_column(String(50))
    safety_event: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    recording_sid: Mapped[str | None] = mapped_column(String(100))
    recording_url: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    customer: Mapped["Customer | None"] = relationship(back_populates="calls")
    appointment: Mapped["Appointment | None"] = relationship(
        back_populates="call", uselist=False
    )


# ---------------------------------------------------------------------------
# appointments
# ---------------------------------------------------------------------------


class Appointment(Base):
    __tablename__ = "appointments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    call_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calls.id", ondelete="SET NULL")
    )
    # "service" | "installation" | "maintenance" | "inspection"
    appointment_type: Mapped[str] = mapped_column(String(50), nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # "scheduled" | "confirmed" | "cancelled" | "completed"
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="scheduled"
    )
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    customer: Mapped["Customer"] = relationship(back_populates="appointments")
    call: Mapped["Call | None"] = relationship(back_populates="appointment")


# ---------------------------------------------------------------------------
# outbound_queue
# ---------------------------------------------------------------------------


class OutboundQueue(Base):
    __tablename__ = "outbound_queue"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # "reminder" | "followup" | "warranty_alert"
    campaign_type: Mapped[str] = mapped_column(String(50), nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # "pending" | "dialing" | "completed" | "failed" | "cancelled"
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", index=True
    )
    twilio_call_sid: Mapped[str | None] = mapped_column(String(50))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    customer: Mapped["Customer"] = relationship(back_populates="outbound_entries")


# ---------------------------------------------------------------------------
# parts
# ---------------------------------------------------------------------------


class Part(Base):
    __tablename__ = "parts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    part_type: Mapped[str] = mapped_column(String(100), nullable=False)
    part_name: Mapped[str] = mapped_column(String(200), nullable=False)
    part_number: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True
    )
    brand: Mapped[str] = mapped_column(String(100), nullable=False)

    compatible_models: Mapped[list["PartCompatibility"]] = relationship(
        back_populates="part", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# part_compatibility
# ---------------------------------------------------------------------------


class PartCompatibility(Base):
    __tablename__ = "part_compatibility"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    part_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("parts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product_model: Mapped[str] = mapped_column(String(150), nullable=False)

    part: Mapped["Part"] = relationship(back_populates="compatible_models")
