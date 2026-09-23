"""ORM models for the Companio SIH backend.

Tables intentionally mirror the Flutter drift schema (``lib/data/local``)
so sync payloads map 1:1. Every table uses string IDs so records created
offline on a device can be idempotently reconciled server-side.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

Role = str  # 'patient' | 'caregiver'
Difficulty = str  # 'gentle' | 'comfortable' | 'challenging'
SosStatus = str  # 'active' | 'acknowledged' | 'resolved' | 'cancelled'


def utcnow() -> datetime:
    """Naive UTC now - keeps SQLite round-trips simple."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_id(prefix: str) -> str:
    return f"{prefix}.{uuid.uuid4().hex[:16]}"


def generate_pairing_code() -> str:
    return secrets.token_hex(3).upper()  # 6 hex chars


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    profile: Mapped["PatientProfile | None"] = relationship(
        back_populates="account", uselist=False, lazy="joined"
    )


class PatientProfile(Base):
    __tablename__ = "patient_profiles"

    account_id: Mapped[str] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )
    display_name: Mapped[str] = mapped_column(String(128))
    region: Mapped[str | None] = mapped_column(String(128), nullable=True)
    language: Mapped[str] = mapped_column(String(8), default="hi")
    voice_language: Mapped[str] = mapped_column(String(16), default="hi-IN")
    pairing_code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    account: Mapped["Account"] = relationship(back_populates="profile")


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    device_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    # The patient whose data this device reads/writes. A patient's own device
    # points at itself; a caregiver device points at the patient it currently
    # manages for the demo.
    patient_id: Mapped[str | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class CaregiverLink(Base):
    __tablename__ = "caregiver_links"
    __table_args__ = (
        UniqueConstraint("caregiver_account_id", "patient_account_id", name="uq_link"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    caregiver_account_id: Mapped[str] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    patient_account_id: Mapped[str] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    relationship: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class InboxRecord(Base):
    """The server-side sync inbox; mirrors the Flutter ``CompanioRecord``."""

    __tablename__ = "inbox_records"

    idempotency_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(32), index=True)
    entity_id: Mapped[str] = mapped_column(String(128), index=True)
    operation: Mapped[str] = mapped_column(String(16))
    payload_json: Mapped[str] = mapped_column(Text)
    patient_id: Mapped[str] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    device_id: Mapped[str] = mapped_column(String(128), index=True)
    client_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SosAlert(Base):
    __tablename__ = "sos_alerts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    patient_account_id: Mapped[str] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    source_device_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    ack_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    acknowledged_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ActivityRecord(Base):
    __tablename__ = "activity_records"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    patient_account_id: Mapped[str] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    device_id: Mapped[str] = mapped_column(String(128))
    activity_id: Mapped[str] = mapped_column(String(64), index=True)
    category: Mapped[str] = mapped_column(String(32), index=True)
    difficulty: Mapped[str] = mapped_column(String(16))
    started_at: Mapped[datetime] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    correct: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)
    hints: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(8), default="real")  # real | demo
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)