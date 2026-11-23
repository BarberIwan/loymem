"""Data model for phase 1a.

Every table except ``businesses`` carries ``business_id`` and is protected by row
level security (see the first migration). ``ledger_events`` and ``audit_log`` are
append-only; the database refuses UPDATE and DELETE on them.
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _tenant() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=False, index=True
    )


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


def _enum(cls: type[enum.Enum], name: str) -> Enum:
    return Enum(cls, name=name, values_callable=lambda e: [m.value for m in e])


class Role(enum.StrEnum):
    OWNER = "owner"
    MANAGER = "manager"
    STAFF = "staff"


class CustomerSource(enum.StrEnum):
    SIGNUP = "signup"
    IMPORT = "import"


class ConsentPurpose(enum.StrEnum):
    MARKETING = "marketing"
    SLOT_ALERTS = "slot_alerts"


class ConsentStatus(enum.StrEnum):
    GRANTED = "granted"
    WITHDRAWN = "withdrawn"


class LedgerKind(enum.StrEnum):
    STAMP = "stamp"
    REWARD_EARNED = "reward_earned"
    REWARD_REDEEMED = "reward_redeemed"
    REVERSAL = "reversal"


class RewardStatus(enum.StrEnum):
    AVAILABLE = "available"
    REDEEMED = "redeemed"
    VOIDED = "voided"


class Business(Base):
    __tablename__ = "businesses"

    id: Mapped[uuid.UUID] = _pk()
    slug: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    brand_colour: Mapped[str] = mapped_column(String(7), nullable=False, default="#1F4A38")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Europe/Amsterdam")
    booking_url: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = _created()

    __table_args__ = (
        CheckConstraint("brand_colour ~ '^#[0-9A-Fa-f]{6}$'", name="brand_colour_hex"),
        CheckConstraint("slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'", name="slug_format"),
    )


class StaffMember(Base):
    __tablename__ = "staff_members"

    id: Mapped[uuid.UUID] = _pk()
    business_id: Mapped[uuid.UUID] = _tenant()
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20))
    role: Mapped[Role] = mapped_column(_enum(Role, "staff_role"), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(200), nullable=False)
    active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = _created()

    __table_args__ = (UniqueConstraint("email", name="uq_staff_email"),)


class Service(Base):
    """A service with its own return period, e.g. a cut every 4 weeks."""

    __tablename__ = "services"

    id: Mapped[uuid.UUID] = _pk()
    business_id: Mapped[uuid.UUID] = _tenant()
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    return_period_days: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = _created()

    __table_args__ = (
        CheckConstraint("return_period_days between 1 and 730", name="return_period_range"),
        UniqueConstraint("business_id", "name", name="uq_service_name"),
    )


class Program(Base):
    __tablename__ = "programs"

    id: Mapped[uuid.UUID] = _pk()
    business_id: Mapped[uuid.UUID] = _tenant()
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    stamps_required: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    reward_description: Mapped[str] = mapped_column(String(120), nullable=False)
    # 0 means one stamp per calendar day in the business time zone.
    stamp_period_hours: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = _created()

    __table_args__ = (
        CheckConstraint("stamps_required between 2 and 30", name="stamps_required_range"),
        CheckConstraint("stamp_period_hours between 0 and 720", name="stamp_period_range"),
    )


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[uuid.UUID] = _pk()
    business_id: Mapped[uuid.UUID] = _tenant()
    first_name: Mapped[str | None] = mapped_column(String(60))
    email: Mapped[str | None] = mapped_column(String(254))
    phone: Mapped[str | None] = mapped_column(String(20))
    birthday_day: Mapped[int | None] = mapped_column(SmallInteger)
    birthday_month: Mapped[int | None] = mapped_column(SmallInteger)
    source: Mapped[CustomerSource] = mapped_column(
        _enum(CustomerSource, "customer_source"), nullable=False
    )
    card_secret_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    scan_token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    anonymised_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()

    __table_args__ = (
        CheckConstraint("birthday_day is null or birthday_day between 1 and 31", name="bday"),
        CheckConstraint("birthday_month is null or birthday_month between 1 and 12", name="bmonth"),
        Index(
            "uq_customer_email",
            "business_id",
            "email",
            unique=True,
            postgresql_where="email is not null",
        ),
        Index(
            "uq_customer_phone",
            "business_id",
            "phone",
            unique=True,
            postgresql_where="phone is not null",
        ),
    )


class ConsentRecord(Base):
    __tablename__ = "consent_records"

    id: Mapped[uuid.UUID] = _pk()
    business_id: Mapped[uuid.UUID] = _tenant()
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), nullable=False)
    purpose: Mapped[ConsentPurpose] = mapped_column(
        _enum(ConsentPurpose, "consent_purpose"), nullable=False
    )
    status: Mapped[ConsentStatus] = mapped_column(
        _enum(ConsentStatus, "consent_status"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = _created()

    __table_args__ = (Index("ix_consent_customer", "customer_id", "purpose", "created_at"),)


class CustomerProgram(Base):
    __tablename__ = "customer_programs"

    id: Mapped[uuid.UUID] = _pk()
    business_id: Mapped[uuid.UUID] = _tenant()
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), nullable=False)
    program_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("programs.id"), nullable=False)
    # Derived from ledger_events; recomputable with services.ledger.recompute_balance.
    balance: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = _created()

    customer: Mapped[Customer] = relationship()
    program: Mapped[Program] = relationship()

    __table_args__ = (
        UniqueConstraint("customer_id", "program_id", name="uq_customer_program"),
        CheckConstraint("balance >= 0", name="balance_not_negative"),
    )


class LedgerEvent(Base):
    __tablename__ = "ledger_events"

    id: Mapped[uuid.UUID] = _pk()
    business_id: Mapped[uuid.UUID] = _tenant()
    customer_program_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customer_programs.id"), nullable=False, index=True
    )
    kind: Mapped[LedgerKind] = mapped_column(_enum(LedgerKind, "ledger_kind"), nullable=False)
    delta: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    reverses_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ledger_events.id"), unique=True
    )
    reward_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    service_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("services.id"))
    staff_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("staff_members.id"))
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()

    __table_args__ = (
        CheckConstraint(
            "kind <> 'reversal' or (reverses_id is not null and reason is not null)",
            name="reversal_has_reason",
        ),
        Index("ix_ledger_staff_time", "business_id", "staff_id", "created_at"),
    )


class Reward(Base):
    __tablename__ = "rewards"

    id: Mapped[uuid.UUID] = _pk()
    business_id: Mapped[uuid.UUID] = _tenant()
    customer_program_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customer_programs.id"), nullable=False, index=True
    )
    description: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[RewardStatus] = mapped_column(
        _enum(RewardStatus, "reward_status"), nullable=False, default=RewardStatus.AVAILABLE
    )
    earned_at: Mapped[datetime] = _created()
    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    redeemed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("staff_members.id"))


class RewardCode(Base):
    __tablename__ = "reward_codes"

    id: Mapped[uuid.UUID] = _pk()
    business_id: Mapped[uuid.UUID] = _tenant()
    reward_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rewards.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(6), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()

    __table_args__ = (Index("ix_reward_code_lookup", "business_id", "code", "expires_at"),)


class CardReissue(Base):
    __tablename__ = "card_reissues"

    id: Mapped[uuid.UUID] = _pk()
    business_id: Mapped[uuid.UUID] = _tenant()
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()


class OutboxMessage(Base):
    __tablename__ = "outbox"

    id: Mapped[uuid.UUID] = _pk()
    business_id: Mapped[uuid.UUID] = _tenant()
    channel: Mapped[str] = mapped_column(String(10), nullable=False)
    recipient: Mapped[str] = mapped_column(String(254), nullable=False)
    template: Mapped[str] = mapped_column(String(60), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()


class AuditEntry(Base):
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = _pk()
    business_id: Mapped[uuid.UUID] = _tenant()
    actor_staff_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("staff_members.id"))
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(40), nullable=False)
    subject_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = _created()

    __table_args__ = (Index("ix_audit_business_time", "business_id", "created_at"),)


TENANT_TABLES = [t.name for t in Base.metadata.sorted_tables if t.name != "businesses"]
APPEND_ONLY_TABLES = ["ledger_events", "audit_log"]
