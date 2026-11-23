"""Signing up, the card, stamping and redeeming.

The QR on the card only identifies the customer. Stamps and redemptions come
only from a signed-in staff session (``StaffContext``); the card itself never
grants anything.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    Business,
    CardReissue,
    ConsentPurpose,
    ConsentRecord,
    ConsentStatus,
    Customer,
    CustomerProgram,
    CustomerSource,
    LedgerKind,
    OutboxMessage,
    Program,
    Reward,
    RewardCode,
    RewardStatus,
    Role,
    Service,
    StaffMember,
    utcnow,
)
from app.security import digest, new_reward_code, new_secret, normalise_email, normalise_phone
from app.services import Conflict, DomainError, Forbidden, NotFound, audit, ledger


@dataclass(frozen=True)
class StaffContext:
    staff: StaffMember
    business: Business

    @property
    def is_manager(self) -> bool:
        return self.staff.role in (Role.OWNER, Role.MANAGER)


@dataclass(frozen=True)
class IssuedCard:
    customer: Customer
    card_secret: str
    scan_token: str


def active_program(db: Session, business_id: uuid.UUID) -> Program:
    program = db.scalar(
        select(Program)
        .where(Program.business_id == business_id, Program.active.is_(True))
        .order_by(Program.created_at)
        .limit(1)
    )
    if program is None:
        raise NotFound("no_active_program")
    return program


def _program_link(db: Session, customer: Customer, program: Program) -> CustomerProgram:
    cp = db.scalar(
        select(CustomerProgram).where(
            CustomerProgram.customer_id == customer.id, CustomerProgram.program_id == program.id
        )
    )
    if cp is None:
        cp = CustomerProgram(
            business_id=customer.business_id, customer_id=customer.id, program_id=program.id
        )
        db.add(cp)
        db.flush()
    return cp


CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def scan_token_for(customer: Customer) -> str:
    """Stable per card link: derived from it, so a new link also gives a new QR.

    Ten Crockford characters (50 bits), short enough to type at the counter. It
    only identifies; a stamp still needs a signed-in staff member of this business.
    """
    n = int(digest(f"scan:{customer.card_secret_hash}")[:13], 16)
    return "".join(CROCKFORD[(n >> (5 * i)) & 31] for i in range(10))


def normalise_scan(value: str) -> str:
    v = value.strip().rsplit("/", 1)[-1].upper()
    v = v.replace("O", "0").replace("I", "1").replace("L", "1")
    return "".join(c for c in v if c in CROCKFORD)


def _new_secrets(customer: Customer) -> tuple[str, str]:
    card = new_secret()
    customer.card_secret_hash = digest(card)
    scan = scan_token_for(customer)
    customer.scan_token_hash = digest(scan)
    return card, scan


def create_customer(
    db: Session,
    business: Business,
    *,
    first_name: str | None,
    email: str | None,
    phone: str | None,
    source: CustomerSource,
    birthday: tuple[int, int] | None = None,
    marketing_consent: bool = False,
) -> IssuedCard:
    email, phone = normalise_email(email), normalise_phone(phone)
    if not email and not phone:
        raise DomainError("contact_required")
    customer = Customer(
        id=uuid.uuid4(),
        business_id=business.id,
        first_name=(first_name or "").strip()[:60] or None,
        email=email,
        phone=phone,
        source=source,
        birthday_day=birthday[0] if birthday else None,
        birthday_month=birthday[1] if birthday else None,
    )
    card, scan = _new_secrets(customer)
    try:
        with db.begin_nested():
            db.add(customer)
            db.flush()
    except IntegrityError as exc:
        raise Conflict("customer_exists") from exc
    # An import never records consent. Only the customer can give it, on signup.
    if marketing_consent and source == CustomerSource.SIGNUP:
        db.add(
            ConsentRecord(
                business_id=business.id,
                customer_id=customer.id,
                purpose=ConsentPurpose.MARKETING,
                status=ConsentStatus.GRANTED,
                source="signup_form",
            )
        )
    _program_link(db, customer, active_program(db, business.id))
    return IssuedCard(customer, card, scan)


def customer_by_card(db: Session, business: Business, secret: str) -> Customer:
    customer = db.scalar(
        select(Customer).where(
            Customer.business_id == business.id,
            Customer.card_secret_hash == digest(secret),
            Customer.anonymised_at.is_(None),
        )
    )
    if customer is None:
        raise NotFound("card_not_found")
    return customer


def card_view(db: Session, business: Business, customer: Customer) -> dict[str, object]:
    program = active_program(db, business.id)
    cp = _program_link(db, customer, program)
    rewards = db.scalars(
        select(Reward)
        .where(Reward.customer_program_id == cp.id, Reward.status == RewardStatus.AVAILABLE)
        .order_by(Reward.earned_at)
    ).all()
    return {
        "first_name": customer.first_name,
        "program": {
            "name": program.name,
            "stamps_required": program.stamps_required,
            "reward": program.reward_description,
        },
        "stamps": cp.balance,
        "rewards": [{"id": str(r.id), "description": r.description} for r in rewards],
    }


# --- Staff side -------------------------------------------------------------


def _is_own_profile(ctx: StaffContext, customer: Customer) -> bool:
    s = ctx.staff
    return bool(
        (customer.email and customer.email == normalise_email(s.email))
        or (customer.phone and s.phone and customer.phone == normalise_phone(s.phone))
    )


def customer_by_scan(db: Session, ctx: StaffContext, scan_token: str) -> Customer:
    customer = db.scalar(
        select(Customer).where(
            Customer.business_id == ctx.business.id,
            Customer.scan_token_hash == digest(normalise_scan(scan_token)),
            Customer.anonymised_at.is_(None),
        )
    )
    if customer is None:
        raise NotFound("scan_not_recognised")
    if _is_own_profile(ctx, customer):
        raise Forbidden("own_profile")
    return customer


def scan_summary(db: Session, ctx: StaffContext, customer: Customer) -> dict[str, object]:
    """What a staff member sees after a scan: first name and progress, no contact data."""
    view = card_view(db, ctx.business, customer)
    view["customer_id"] = str(customer.id)
    return view


def stamp(
    db: Session, ctx: StaffContext, customer_id: uuid.UUID, service_id: uuid.UUID | None
) -> dict[str, object]:
    customer = db.scalar(
        select(Customer).where(
            Customer.id == customer_id,
            Customer.business_id == ctx.business.id,
            Customer.anonymised_at.is_(None),
        )
    )
    if customer is None:
        raise NotFound("customer_not_found")
    if _is_own_profile(ctx, customer):
        raise Forbidden("own_profile")
    if (
        service_id is not None
        and db.scalar(
            select(Service.id).where(
                Service.id == service_id, Service.business_id == ctx.business.id
            )
        )
        is None
    ):
        raise NotFound("service_not_found")
    program = active_program(db, ctx.business.id)
    cp = _program_link(db, customer, program)
    # Serialise everything that touches this card for the rest of the transaction.
    db.refresh(cp, with_for_update=True)
    key = f"stamp:{cp.id}:{ledger.period_bucket(program, ctx.business, utcnow())}"
    event = ledger.append(
        db, cp, LedgerKind.STAMP, 1, key, staff_id=ctx.staff.id, service_id=service_id
    )
    if event is None:
        return {"stamped": False, "reason": "already_stamped_this_period", "stamps": cp.balance}
    rewards = ledger.convert_to_rewards(db, cp, program, event)
    return {
        "stamped": True,
        "event_id": str(event),
        "stamps": cp.balance,
        "rewards_earned": len(rewards),
    }


def issue_reward_code(
    db: Session, business: Business, customer: Customer, reward_id: uuid.UUID
) -> tuple[str, int]:
    reward = db.scalar(
        select(Reward)
        .join(CustomerProgram, CustomerProgram.id == Reward.customer_program_id)
        .where(
            Reward.id == reward_id,
            Reward.business_id == business.id,
            CustomerProgram.customer_id == customer.id,
            Reward.status == RewardStatus.AVAILABLE,
        )
    )
    if reward is None:
        raise NotFound("reward_not_available")
    seconds = get_settings().reward_code_seconds
    now = utcnow()
    # Older codes for this reward stop working as soon as a new one is shown.
    db.execute(
        update(RewardCode)
        .where(RewardCode.reward_id == reward.id, RewardCode.used_at.is_(None))
        .values(expires_at=now)
    )
    code = new_reward_code()
    db.add(
        RewardCode(
            business_id=business.id,
            reward_id=reward.id,
            code=code,
            expires_at=now + timedelta(seconds=seconds),
        )
    )
    db.flush()
    return code, seconds


def redeem(db: Session, ctx: StaffContext, code: str) -> dict[str, object]:
    now = utcnow()
    rc = db.scalar(
        select(RewardCode)
        .where(
            RewardCode.business_id == ctx.business.id,
            RewardCode.code == code.strip(),
            RewardCode.used_at.is_(None),
            RewardCode.expires_at > now,
        )
        .with_for_update(skip_locked=False)
    )
    if rc is None:
        raise NotFound("code_invalid_or_expired")
    reward = db.get(Reward, rc.reward_id)
    assert reward is not None
    cp = db.get(CustomerProgram, reward.customer_program_id)
    assert cp is not None
    customer = db.get(Customer, cp.customer_id)
    assert customer is not None
    if _is_own_profile(ctx, customer):
        raise Forbidden("own_profile")
    won = db.execute(
        update(Reward)
        .where(Reward.id == reward.id, Reward.status == RewardStatus.AVAILABLE)
        .values(status=RewardStatus.REDEEMED, redeemed_at=now, redeemed_by=ctx.staff.id)
        .returning(Reward.id)
    ).scalar_one_or_none()
    if won is None:
        raise Conflict("reward_already_redeemed")
    rc.used_at = now
    ledger.append(
        db,
        cp,
        LedgerKind.REWARD_REDEEMED,
        0,
        f"redeem:{reward.id}",
        staff_id=ctx.staff.id,
        reward_id=reward.id,
    )
    audit.record(db, ctx.business.id, "reward.redeemed", "reward", reward.id, ctx.staff.id)
    return {"redeemed": True, "description": reward.description, "first_name": customer.first_name}


# --- Lost card --------------------------------------------------------------


def request_reissue(db: Session, business: Business, contact: str) -> None:
    """Always answers the same, so nobody learns who is a customer here."""
    email, phone = normalise_email(contact), normalise_phone(contact)
    cond = Customer.email == email if "@" in contact else Customer.phone == phone
    customer = db.scalar(
        select(Customer).where(
            Customer.business_id == business.id, cond, Customer.anonymised_at.is_(None)
        )
    )
    if customer is None:
        return
    token = new_secret()
    db.add(
        CardReissue(
            business_id=business.id,
            customer_id=customer.id,
            token_hash=digest(token),
            expires_at=utcnow() + timedelta(minutes=get_settings().reissue_link_minutes),
        )
    )
    channel, recipient = ("email", customer.email) if customer.email else ("sms", customer.phone)
    assert recipient is not None
    db.add(
        OutboxMessage(
            business_id=business.id,
            channel=channel,
            recipient=recipient,
            template="card_reissue",
            payload={"url": f"{get_settings().public_base_url}/k/{business.slug}/nieuw/{token}"},
        )
    )


def complete_reissue(db: Session, business: Business, token: str) -> str:
    row = db.scalar(
        select(CardReissue)
        .where(
            CardReissue.business_id == business.id,
            CardReissue.token_hash == digest(token),
            CardReissue.used_at.is_(None),
            CardReissue.expires_at > utcnow(),
        )
        .with_for_update()
    )
    if row is None:
        raise NotFound("link_invalid_or_expired")
    row.used_at = utcnow()
    customer = db.get(Customer, row.customer_id)
    assert customer is not None
    card, _ = _new_secrets(customer)
    audit.record(db, business.id, "card.reissued", "customer", customer.id)
    return card
