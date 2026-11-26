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
    BONUS = "bonus"


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
    # A review request after a visit. Off while the link is empty; the number of
    # days keeps a regular from being asked every time (0 = every visit).
    review_url: Mapped[str | None] = mapped_column(String(500))
    review_request_days: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default="0"
    )
    # Retention inbox: how many opportunities a day, how long "ignore" lasts.
    inbox_daily_limit: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=10, server_default="10"
    )
    inbox_ignore_days: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=30, server_default="30"
    )
    created_at: Mapped[datetime] = _created()

    __table_args__ = (
        CheckConstraint("inbox_daily_limit between 1 and 50", name="inbox_daily_limit_range"),
        CheckConstraint("inbox_ignore_days between 1 and 365", name="inbox_ignore_days_range"),
        CheckConstraint("review_request_days between 0 and 3650", name="review_request_days_range"),
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
    # Set for messages that need an unsubscribe link (marketing, slot alerts).
    customer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("customers.id"))
    attempts: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default="0"
    )
    last_error: Mapped[str | None] = mapped_column(String(300))
    # Not before this moment. A review request waits until the visit is over.
    send_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()

    __table_args__ = (Index("ix_outbox_pending", "business_id", "sent_at", "attempts"),)


class InboxDecision(enum.StrEnum):
    SENT = "sent"
    DONE = "done"
    IGNORED = "ignored"


class InboxEntry(Base):
    """What the owner did with an opportunity. Hides it until ``hidden_until``."""

    __tablename__ = "inbox_entries"

    id: Mapped[uuid.UUID] = _pk()
    business_id: Mapped[uuid.UUID] = _tenant()
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    decision: Mapped[InboxDecision] = mapped_column(
        _enum(InboxDecision, "inbox_decision"), nullable=False
    )
    hidden_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    staff_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("staff_members.id"))
    message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()

    __table_args__ = (
        Index("ix_inbox_lookup", "business_id", "customer_id", "kind", "hidden_until"),
    )


class WaitlistEntry(Base):
    """A customer who wants to hear about free slots, with their preferences."""

    __tablename__ = "waitlist_entries"

    id: Mapped[uuid.UUID] = _pk()
    business_id: Mapped[uuid.UUID] = _tenant()
    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customers.id"), nullable=False, unique=True
    )
    # Null means any service.
    service_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("services.id"))
    # Bit 0 is Monday ... bit 6 is Sunday.
    days_mask: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=127)
    # Bit 0 morning (before 12), bit 1 afternoon (12-17), bit 2 evening (from 17).
    dayparts_mask: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=7)
    min_notice_minutes: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=60)
    active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = _created()

    __table_args__ = (
        CheckConstraint("days_mask between 1 and 127", name="days_mask_range"),
        CheckConstraint("dayparts_mask between 1 and 7", name="dayparts_mask_range"),
        CheckConstraint("min_notice_minutes between 0 and 1440", name="notice_range"),
    )


class SlotBenefit(enum.StrEnum):
    STAMPS = "stamps"
    UPGRADE = "upgrade"
    DISCOUNT = "discount"


class SlotStatus(enum.StrEnum):
    OPEN = "open"
    FILLED = "filled"
    EXPIRED = "expired"
    CLOSED = "closed"


class SlotOffer(Base):
    __tablename__ = "slot_offers"

    id: Mapped[uuid.UUID] = _pk()
    business_id: Mapped[uuid.UUID] = _tenant()
    service_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("services.id"))
    staff_name: Mapped[str | None] = mapped_column(String(80))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    book_by: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    benefit: Mapped[SlotBenefit] = mapped_column(_enum(SlotBenefit, "slot_benefit"), nullable=False)
    # Stamps: number of extra stamps. Discount: percentage. Upgrade: unused.
    benefit_value: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    benefit_text: Mapped[str | None] = mapped_column(String(120))
    capacity: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    claims_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    group_size: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=3)
    wait_minutes: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=10)
    status: Mapped[SlotStatus] = mapped_column(
        _enum(SlotStatus, "slot_status"), nullable=False, default=SlotStatus.OPEN
    )
    sending_started: Mapped[bool] = mapped_column(default=False, nullable=False)
    next_send_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("staff_members.id"))
    created_at: Mapped[datetime] = _created()

    __table_args__ = (
        CheckConstraint("capacity between 1 and 20", name="capacity_range"),
        CheckConstraint("claims_count between 0 and capacity", name="claims_within_capacity"),
        CheckConstraint("group_size between 1 and 50", name="group_size_range"),
        CheckConstraint("wait_minutes between 1 and 240", name="wait_range"),
        CheckConstraint("book_by <= starts_at", name="book_before_start"),
        CheckConstraint(
            "benefit <> 'discount' or benefit_value between 1 and 50", name="discount_range"
        ),
        CheckConstraint(
            "benefit <> 'stamps' or benefit_value between 1 and 10", name="bonus_stamps_range"
        ),
        Index("ix_slot_offer_send", "status", "next_send_at"),
    )


class SlotRecipient(Base):
    __tablename__ = "slot_recipients"

    id: Mapped[uuid.UUID] = _pk()
    business_id: Mapped[uuid.UUID] = _tenant()
    offer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("slot_offers.id"), nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), nullable=False)
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    reason: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="queued")
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("offer_id", "customer_id", name="uq_slot_recipient"),
        Index("ix_slot_recipient_queue", "offer_id", "status", "position"),
    )


class SlotClaim(Base):
    __tablename__ = "slot_claims"

    id: Mapped[uuid.UUID] = _pk()
    business_id: Mapped[uuid.UUID] = _tenant()
    offer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("slot_offers.id"), nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), nullable=False)
    claimed_at: Mapped[datetime] = _created()
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    applied_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("staff_members.id"))

    __table_args__ = (UniqueConstraint("offer_id", "customer_id", name="uq_slot_claim"),)


class WebhookConfig(Base):
    """A business's generic webhook for completed appointments.

    The secret is stored encrypted: verifying an HMAC needs the secret itself.
    ``mapping`` says where in the incoming JSON each field lives.
    """

    __tablename__ = "webhook_configs"

    id: Mapped[uuid.UUID] = _pk()
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=False, unique=True
    )
    secret_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    mapping: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = _created()


class WebhookDelivery(Base):
    """One received call and what came of it. Never holds personal data."""

    __tablename__ = "webhook_deliveries"

    id: Mapped[uuid.UUID] = _pk()
    business_id: Mapped[uuid.UUID] = _tenant()
    appointment_id: Mapped[str | None] = mapped_column(String(120))
    outcome: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = _created()

    __table_args__ = (Index("ix_webhook_delivery_time", "business_id", "created_at"),)


class PlanKind(enum.StrEnum):
    MEMBERSHIP = "membership"
    BUNDLE = "bundle"
    CREDIT = "credit"  # prepaid balance in euros, possibly worth more than its price


class Plan(Base):
    """A membership (monthly, renews) or a visit bundle (prepaid, expires).

    Every condition the customer must see before buying lives here, and any change
    to them bumps ``terms_version``; a purchase records the version it accepted.
    """

    __tablename__ = "plans"

    id: Mapped[uuid.UUID] = _pk()
    business_id: Mapped[uuid.UUID] = _tenant()
    kind: Mapped[PlanKind] = mapped_column(_enum(PlanKind, "plan_kind"), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    credits: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    # Credit plans only: what the customer can spend (price_cents is what they pay).
    value_cents: Mapped[int | None] = mapped_column(Integer)
    validity_days: Mapped[int | None] = mapped_column(SmallInteger)
    cancel_notice_days: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    cooling_off_days: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=14)
    # The chosen options (services/policies.py); the texts below are what they said then.
    unused_rule: Mapped[str | None] = mapped_column(String(30))
    no_show_rule: Mapped[str | None] = mapped_column(String(30))
    unused_policy: Mapped[str] = mapped_column(Text, nullable=False)
    no_show_policy: Mapped[str] = mapped_column(Text, nullable=False)
    pause_policy: Mapped[str] = mapped_column(Text, nullable=False)
    refund_policy: Mapped[str] = mapped_column(Text, nullable=False, default="")
    terms_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = _created()

    __table_args__ = (
        CheckConstraint("price_cents between 100 and 100000", name="price_range"),
        CheckConstraint(
            "(kind::text = 'credit' and credits = 0) or "
            "(kind::text <> 'credit' and credits between 1 and 100)",
            name="credits_range",
        ),
        CheckConstraint(
            "(kind::text = 'credit') = (value_cents is not null) and "
            "(value_cents is null or value_cents between price_cents and price_cents * 2)",
            name="credit_value",
        ),
        CheckConstraint(
            "kind::text <> 'credit' or validity_days between 365 and 1095", name="credit_validity"
        ),
        CheckConstraint(
            "unused_rule is null or unused_rule in ('expire_period', 'roll_one_period')",
            name="unused_rule_known",
        ),
        CheckConstraint(
            "no_show_rule is null or no_show_rule in "
            "('free', 'no_show_counts', 'late_24h', 'late_24h_first_free')",
            name="no_show_rule_known",
        ),
        CheckConstraint(
            "unused_rule is null or kind::text = 'membership'", name="roll_only_membership"
        ),
        # Renewing memberships may be cancelled monthly: notice of at most a month.
        CheckConstraint("cancel_notice_days between 0 and 31", name="notice_at_most_month"),
        CheckConstraint(
            "kind <> 'bundle' or validity_days between 30 and 1095", name="bundle_validity"
        ),
    )


class SubscriptionStatus(enum.StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    CANCELLED = "cancelled"
    ENDED = "ended"
    FAILED = "failed"


class Subscription(Base):
    """A customer's membership or bundle. Status only changes through payment events
    or the customer's own cancellation; staff cannot change it."""

    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = _pk()
    business_id: Mapped[uuid.UUID] = _tenant()
    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customers.id"), nullable=False, index=True
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("plans.id"), nullable=False)
    status: Mapped[SubscriptionStatus] = mapped_column(
        _enum(SubscriptionStatus, "subscription_status"), nullable=False
    )
    terms_version: Mapped[int] = mapped_column(Integer, nullable=False)
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    renews: Mapped[bool] = mapped_column(default=False, nullable=False)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_customer_id: Mapped[str | None] = mapped_column(String(60))
    provider_mandate_id: Mapped[str | None] = mapped_column(String(60))
    created_at: Mapped[datetime] = _created()


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = _pk()
    business_id: Mapped[uuid.UUID] = _tenant()
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("subscriptions.id"), nullable=False
    )
    provider_payment_id: Mapped[str] = mapped_column(String(60), nullable=False, unique=True)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    sequence: Mapped[str] = mapped_column(String(12), nullable=False)
    # Set once when the payment's credits were granted; makes processing idempotent.
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()


class Refund(Base):
    """Money given back for one purchase, at most once. Append-only."""

    __tablename__ = "refunds"

    id: Mapped[uuid.UUID] = _pk()
    business_id: Mapped[uuid.UUID] = _tenant()
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("subscriptions.id"), nullable=False, unique=True
    )
    payment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("payments.id"), nullable=False)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    provider_refund_id: Mapped[str | None] = mapped_column(String(60))
    reason: Mapped[str] = mapped_column(String(40), nullable=False)
    staff_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("staff_members.id"), nullable=False)
    created_at: Mapped[datetime] = _created()

    __table_args__ = (CheckConstraint("amount_cents > 0", name="refund_positive"),)


class CreditKind(enum.StrEnum):
    GRANT = "grant"
    RESERVE = "reserve"
    CONSUME = "consume"
    RELEASE = "release"
    EXPIRE = "expire"
    REFUND = "refund"


class CreditEvent(Base):
    """Credit ledger, append-only like ``ledger_events``.

    ``delta`` changes the available balance: grant +n, reserve -1, release +1,
    consume 0 (the credit already left at reservation), expire -n. ``settles_id``
    points a consume or release at its reservation, and is unique: a reservation
    is settled exactly once.
    """

    __tablename__ = "credit_events"

    id: Mapped[uuid.UUID] = _pk()
    business_id: Mapped[uuid.UUID] = _tenant()
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("subscriptions.id"), nullable=False, index=True
    )
    kind: Mapped[CreditKind] = mapped_column(_enum(CreditKind, "credit_kind"), nullable=False)
    delta: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    settles_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("credit_events.id"), unique=True
    )
    staff_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("staff_members.id"))
    created_at: Mapped[datetime] = _created()


class BalanceKind(enum.StrEnum):
    TOPUP = "topup"
    SPEND = "spend"
    REVERSAL = "reversal"
    EXPIRE = "expire"
    REFUND = "refund"


class BalanceEvent(Base):
    """Euro balance ledger for credit plans, append-only like ``credit_events``.

    ``amount_cents`` is signed: top-up and reversal add, spend and expiry take
    away. A reversal points at the spend it undoes and can do so only once.
    """

    __tablename__ = "balance_events"

    id: Mapped[uuid.UUID] = _pk()
    business_id: Mapped[uuid.UUID] = _tenant()
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("subscriptions.id"), nullable=False, index=True
    )
    kind: Mapped[BalanceKind] = mapped_column(_enum(BalanceKind, "balance_kind"), nullable=False)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    reverses_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("balance_events.id"), unique=True
    )
    staff_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("staff_members.id"))
    note: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = _created()

    __table_args__ = (
        CheckConstraint(
            "(kind::text in ('topup', 'reversal') and amount_cents > 0) or "
            "(kind::text in ('spend', 'expire', 'refund') and amount_cents < 0)",
            name="balance_sign",
        ),
        CheckConstraint(
            "(kind = 'reversal') = (reverses_id is not null)", name="reversal_points_back"
        ),
        CheckConstraint("kind <> 'reversal' or note is not null", name="reversal_has_reason"),
    )


class ProviderConnection(Base):
    """A business's own payment account (Mollie Connect). Tokens stored encrypted."""

    __tablename__ = "provider_connections"

    id: Mapped[uuid.UUID] = _pk()
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=False, unique=True
    )
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    access_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    profile_id: Mapped[str | None] = mapped_column(String(60))
    created_at: Mapped[datetime] = _created()


class WalletPass(Base):
    """What a customer's wallet pass last showed, to know when to push an update."""

    __tablename__ = "wallet_passes"

    id: Mapped[uuid.UUID] = _pk()
    business_id: Mapped[uuid.UUID] = _tenant()
    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customers.id"), nullable=False, unique=True
    )
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    google_issued: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = _created()


class WalletRegistration(Base):
    """A device that holds a customer's Apple pass, with its push token."""

    __tablename__ = "wallet_registrations"

    id: Mapped[uuid.UUID] = _pk()
    business_id: Mapped[uuid.UUID] = _tenant()
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), nullable=False)
    device_id: Mapped[str] = mapped_column(String(64), nullable=False)
    push_token: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = _created()

    __table_args__ = (
        UniqueConstraint("device_id", "customer_id", name="uq_wallet_device_pass"),
        Index("ix_wallet_registrations_customer", "customer_id"),
    )


class MailInbox(Base):
    """A business's own address for forwarded booking mails."""

    __tablename__ = "mail_inboxes"

    id: Mapped[uuid.UUID] = _pk()
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id"), nullable=False, unique=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    generation: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    active: Mapped[bool] = mapped_column(default=True, nullable=False)
    count_visits: Mapped[bool] = mapped_column(default=False, nullable=False)
    gmail_code: Mapped[str | None] = mapped_column(String(12))
    last_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()


class Appointment(Base):
    """An appointment as a booking system reported it. Personal data only for customers."""

    __tablename__ = "appointments"

    id: Mapped[uuid.UUID] = _pk()
    business_id: Mapped[uuid.UUID] = _tenant()
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(40))
    customer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("customers.id"))
    name_hash: Mapped[str | None] = mapped_column(String(64))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="booked")
    service: Mapped[str | None] = mapped_column(String(120))
    staff: Mapped[str | None] = mapped_column(String(60))
    visit_recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()

    __table_args__ = (
        CheckConstraint("status in ('booked', 'cancelled')", name="appointment_status"),
        UniqueConstraint("business_id", "source", "external_id", name="uq_appointment_ext"),
        Index("ix_appointments_business_start", "business_id", "starts_at"),
        Index("ix_appointments_customer", "customer_id"),
    )


class MailReceipt(Base):
    """One forwarded mail: what kind and what came of it. Nothing of its content."""

    __tablename__ = "mail_receipts"

    id: Mapped[uuid.UUID] = _pk()
    business_id: Mapped[uuid.UUID] = _tenant()
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = _created()

    __table_args__ = (Index("ix_mail_receipts_business", "business_id", "created_at"),)


class Campaign(Base):
    """A message to a group of customers, with a control group that gets nothing.

    The control group is what makes an effect claim possible at all; the report
    compares the two groups and says "not demonstrable" unless the difference holds.
    """

    __tablename__ = "campaigns"

    id: Mapped[uuid.UUID] = _pk()
    business_id: Mapped[uuid.UUID] = _tenant()
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    audience: Mapped[str] = mapped_column(String(30), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    holdout_percent: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=10)
    window_days: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=30)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("staff_members.id"))
    created_at: Mapped[datetime] = _created()

    __table_args__ = (
        CheckConstraint("holdout_percent between 5 and 50", name="holdout_range"),
        CheckConstraint("window_days between 7 and 90", name="window_range"),
    )


class CampaignMember(Base):
    __tablename__ = "campaign_members"

    id: Mapped[uuid.UUID] = _pk()
    business_id: Mapped[uuid.UUID] = _tenant()
    campaign_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("campaigns.id"), nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), nullable=False)
    holdout: Mapped[bool] = mapped_column(nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("campaign_id", "customer_id", name="uq_campaign_member"),
        # A control-group member can never have been sent anything.
        CheckConstraint("not (holdout and sent_at is not null)", name="holdout_never_sent"),
    )


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
APPEND_ONLY_TABLES = [
    "ledger_events",
    "audit_log",
    "credit_events",
    "balance_events",
    "refunds",
]
