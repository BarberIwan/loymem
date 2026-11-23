"""Free slots: waitlist, staged offers, claims (phase 1c, manual route).

The owner releases a slot by hand; no calendar connection is needed.

- Claim in Loymem, book in the calendar. The benefit belongs to the customer who
  claimed, and is applied once at the scan after the visit, only when the visit
  falls inside the offered slot.
- Staged sending: a small group first (default 3), the next group only after a
  wait, and nothing more once the slot is filled, closed or past its deadline.
- Joining the waitlist is consent for slot alerts only, never for other
  marketing; and a free slot is never a reason to message someone without it.
- Free-slot offers have no control group: every matching customer can get one.
- Discount is capped: at most one last-minute discount per customer per 60 days.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    Business,
    ConsentPurpose,
    ConsentRecord,
    ConsentStatus,
    Customer,
    CustomerProgram,
    LedgerKind,
    OutboxMessage,
    Service,
    SlotBenefit,
    SlotClaim,
    SlotOffer,
    SlotRecipient,
    SlotStatus,
    WaitlistEntry,
    utcnow,
)
from app.security import digest, new_secret
from app.services import Conflict, DomainError, NotFound, audit, ledger
from app.services.cards import StaffContext, active_program
from app.services.rhythm import visit_statuses

DISCOUNT_COOLDOWN = timedelta(days=60)
# A claimed benefit applies to a visit from one hour before the slot until four after.
APPLY_BEFORE = timedelta(hours=1)
APPLY_AFTER = timedelta(hours=4)


def daypart(local: datetime) -> int:
    return 0 if local.hour < 12 else 1 if local.hour < 17 else 2


# --- Waitlist ---------------------------------------------------------------


def has_slot_consent(db: Session, customer_id: uuid.UUID) -> bool:
    latest = db.scalar(
        select(ConsentRecord.status)
        .where(
            ConsentRecord.customer_id == customer_id,
            ConsentRecord.purpose == ConsentPurpose.SLOT_ALERTS,
        )
        .order_by(ConsentRecord.created_at.desc())
        .limit(1)
    )
    return latest == ConsentStatus.GRANTED


def join_waitlist(
    db: Session,
    business: Business,
    customer: Customer,
    *,
    service_id: uuid.UUID | None,
    days_mask: int,
    dayparts_mask: int,
    min_notice_minutes: int,
) -> None:
    if not customer.email:
        raise DomainError("email_needed_for_alerts")
    if (
        service_id is not None
        and db.scalar(
            select(Service.id).where(Service.id == service_id, Service.business_id == business.id)
        )
        is None
    ):
        raise NotFound("service_not_found")
    entry = db.scalar(select(WaitlistEntry).where(WaitlistEntry.customer_id == customer.id))
    if entry is None:
        entry = WaitlistEntry(business_id=business.id, customer_id=customer.id)
        db.add(entry)
    entry.service_id = service_id
    entry.days_mask = days_mask
    entry.dayparts_mask = dayparts_mask
    entry.min_notice_minutes = min_notice_minutes
    entry.active = True
    db.add(
        ConsentRecord(
            business_id=business.id,
            customer_id=customer.id,
            purpose=ConsentPurpose.SLOT_ALERTS,
            status=ConsentStatus.GRANTED,
            source="waitlist",
        )
    )


def leave_waitlist(db: Session, business: Business, customer: Customer) -> None:
    entry = db.scalar(select(WaitlistEntry).where(WaitlistEntry.customer_id == customer.id))
    if entry is not None:
        entry.active = False
    db.add(
        ConsentRecord(
            business_id=business.id,
            customer_id=customer.id,
            purpose=ConsentPurpose.SLOT_ALERTS,
            status=ConsentStatus.WITHDRAWN,
            source="waitlist",
        )
    )


def waitlist_view(db: Session, customer: Customer) -> dict[str, object] | None:
    e = db.scalar(
        select(WaitlistEntry).where(
            WaitlistEntry.customer_id == customer.id, WaitlistEntry.active.is_(True)
        )
    )
    if e is None:
        return None
    return {
        "service_id": str(e.service_id) if e.service_id else None,
        "days_mask": e.days_mask,
        "dayparts_mask": e.dayparts_mask,
        "min_notice_minutes": e.min_notice_minutes,
    }


# --- Offers -----------------------------------------------------------------


@dataclass
class OfferInput:
    service_id: uuid.UUID | None
    staff_name: str | None
    starts_at: datetime
    book_by: datetime
    benefit: SlotBenefit
    benefit_value: int
    benefit_text: str | None
    capacity: int
    group_size: int
    wait_minutes: int


def _local(business: Business, naive: datetime) -> datetime:
    """The owner types times in the shop's own time zone."""
    tz = ZoneInfo(business.timezone)
    return naive.replace(tzinfo=tz) if naive.tzinfo is None else naive.astimezone(tz)


def candidates(
    db: Session, business: Business, offer: SlotOffer, now: datetime
) -> list[tuple[uuid.UUID, str]]:
    """Matching waitlist customers, due-for-a-visit first. Returns (customer, reason)."""
    local = offer.starts_at.astimezone(ZoneInfo(business.timezone))
    weekday_bit, part_bit = 1 << local.weekday(), 1 << daypart(local)
    minutes_ahead = (offer.starts_at - now).total_seconds() / 60
    rows = db.execute(
        select(WaitlistEntry, Customer)
        .join(Customer, Customer.id == WaitlistEntry.customer_id)
        .where(
            WaitlistEntry.business_id == business.id,
            WaitlistEntry.active.is_(True),
            Customer.anonymised_at.is_(None),
            Customer.email.is_not(None),
        )
        .order_by(WaitlistEntry.created_at)
    ).all()
    discounted: set[uuid.UUID] = set()
    if offer.benefit == SlotBenefit.DISCOUNT:
        discounted = set(
            db.scalars(
                select(SlotClaim.customer_id)
                .join(SlotOffer, SlotOffer.id == SlotClaim.offer_id)
                .where(
                    SlotClaim.business_id == business.id,
                    SlotOffer.benefit == SlotBenefit.DISCOUNT,
                    SlotClaim.claimed_at >= now - DISCOUNT_COOLDOWN,
                )
            )
        )
    due = {
        s.customer_id: s.days_since / (s.return_period_days or 1)
        for s in visit_statuses(db, business.id, now)
        if s.due
    }
    picked: list[tuple[uuid.UUID, str, float]] = []
    for entry, customer in rows:
        if entry.service_id and offer.service_id and entry.service_id != offer.service_id:
            continue
        if not entry.days_mask & weekday_bit or not entry.dayparts_mask & part_bit:
            continue
        if minutes_ahead < entry.min_notice_minutes:
            continue
        if customer.id in discounted or not has_slot_consent(db, customer.id):
            continue
        if customer.id in due:
            picked.append((customer.id, "due_for_visit", -due[customer.id]))
        else:
            picked.append((customer.id, "waitlist", 0.0))
    picked.sort(key=lambda p: p[2])  # stable: waitlist order within each reason
    return [(c, r) for c, r, _ in picked]


def create_offer(db: Session, ctx: StaffContext, data: OfferInput) -> SlotOffer:
    b = ctx.business
    now = utcnow()
    starts_at, book_by = _local(b, data.starts_at), _local(b, data.book_by)
    if book_by > starts_at:
        raise DomainError("book_by_after_start")
    if book_by <= now:
        raise DomainError("book_by_in_past")
    if data.benefit == SlotBenefit.UPGRADE and not (data.benefit_text or "").strip():
        raise DomainError("upgrade_needs_text")
    if (
        data.service_id is not None
        and db.scalar(
            select(Service.id).where(Service.id == data.service_id, Service.business_id == b.id)
        )
        is None
    ):
        raise NotFound("service_not_found")
    offer = SlotOffer(
        id=uuid.uuid4(),
        business_id=b.id,
        service_id=data.service_id,
        staff_name=(data.staff_name or "").strip() or None,
        starts_at=starts_at,
        book_by=book_by,
        benefit=data.benefit,
        benefit_value=data.benefit_value,
        benefit_text=(data.benefit_text or "").strip() or None,
        capacity=data.capacity,
        group_size=data.group_size,
        wait_minutes=data.wait_minutes,
        created_by=ctx.staff.id,
    )
    db.add(offer)
    db.flush()
    for position, (customer_id, reason) in enumerate(candidates(db, b, offer, now)):
        db.add(
            SlotRecipient(
                business_id=b.id,
                offer_id=offer.id,
                customer_id=customer_id,
                position=position,
                reason=reason,
                token_hash=digest(f"pending:{uuid.uuid4()}"),
            )
        )
    audit.record(db, b.id, "slot.created", "slot_offer", offer.id, ctx.staff.id)
    return offer


def _offer(
    db: Session, business_id: uuid.UUID, offer_id: uuid.UUID, lock: bool = False
) -> SlotOffer:
    stmt = select(SlotOffer).where(SlotOffer.id == offer_id, SlotOffer.business_id == business_id)
    offer = db.scalar(stmt.with_for_update() if lock else stmt)
    if offer is None:
        raise NotFound("slot_not_found")
    return offer


def skip_recipient(
    db: Session, ctx: StaffContext, offer_id: uuid.UUID, customer_id: uuid.UUID
) -> None:
    _offer(db, ctx.business.id, offer_id)
    done = db.execute(
        update(SlotRecipient)
        .where(
            SlotRecipient.offer_id == offer_id,
            SlotRecipient.customer_id == customer_id,
            SlotRecipient.business_id == ctx.business.id,
            SlotRecipient.status == "queued",
        )
        .values(status="skipped")
        .returning(SlotRecipient.id)
    ).scalar_one_or_none()
    if done is None:
        raise Conflict("recipient_not_queued")


def start_sending(db: Session, ctx: StaffContext, offer_id: uuid.UUID) -> int:
    offer = _offer(db, ctx.business.id, offer_id, lock=True)
    if offer.status != SlotStatus.OPEN:
        raise Conflict("slot_not_open")
    if not offer.sending_started:
        offer.sending_started = True
        offer.next_send_at = utcnow()
        audit.record(
            db, ctx.business.id, "slot.sending_started", "slot_offer", offer.id, ctx.staff.id
        )
    return send_due(db, ctx.business)


def close(db: Session, ctx: StaffContext, offer_id: uuid.UUID, status: SlotStatus) -> None:
    if status not in (SlotStatus.FILLED, SlotStatus.CLOSED):
        raise DomainError("bad_status")
    offer = _offer(db, ctx.business.id, offer_id, lock=True)
    if offer.status == SlotStatus.OPEN:
        offer.status = status
        offer.next_send_at = None
        audit.record(
            db, ctx.business.id, f"slot.{status.value}", "slot_offer", offer.id, ctx.staff.id
        )


def _expire_if_past(offer: SlotOffer, now: datetime) -> None:
    if offer.status == SlotStatus.OPEN and offer.book_by <= now:
        offer.status = SlotStatus.EXPIRED
        offer.next_send_at = None


def send_due(db: Session, business: Business, now: datetime | None = None) -> int:
    """Send the next group of every offer whose wait is over. Returns messages queued."""
    now = now or utcnow()
    sent = 0
    offers = db.scalars(
        select(SlotOffer)
        .where(
            SlotOffer.business_id == business.id,
            SlotOffer.status == SlotStatus.OPEN,
            SlotOffer.sending_started.is_(True),
            SlotOffer.next_send_at <= now,
        )
        .with_for_update(skip_locked=True)
    ).all()
    base = get_settings().public_base_url
    for offer in offers:
        _expire_if_past(offer, now)
        if offer.status != SlotStatus.OPEN:
            continue
        group = db.scalars(
            select(SlotRecipient)
            .where(SlotRecipient.offer_id == offer.id, SlotRecipient.status == "queued")
            .order_by(SlotRecipient.position)
            .limit(offer.group_size)
        ).all()
        for r in group:
            customer = db.get(Customer, r.customer_id)
            # Consent is checked again at the moment of sending: it may be withdrawn.
            if customer is None or not customer.email or not has_slot_consent(db, customer.id):
                r.status = "skipped"
                continue
            token = new_secret()
            r.token_hash = digest(token)
            r.status = "sent"
            r.sent_at = now
            db.add(
                OutboxMessage(
                    customer_id=customer.id,
                    business_id=business.id,
                    channel="email",
                    recipient=customer.email,
                    template="slot_offer",
                    payload={
                        "url": f"{base}/plek/{business.slug}/{token}",
                        "offer_id": str(offer.id),
                    },
                )
            )
            sent += 1
        left = db.scalar(
            select(SlotRecipient.id)
            .where(SlotRecipient.offer_id == offer.id, SlotRecipient.status == "queued")
            .limit(1)
        )
        offer.next_send_at = now + timedelta(minutes=offer.wait_minutes) if left else None
    return sent


# --- Customer side ----------------------------------------------------------


def _recipient(db: Session, business: Business, token: str) -> SlotRecipient:
    r = db.scalar(
        select(SlotRecipient).where(
            SlotRecipient.business_id == business.id,
            SlotRecipient.token_hash == digest(token),
            SlotRecipient.status == "sent",
        )
    )
    if r is None:
        raise NotFound("offer_not_found")
    return r


def describe(db: Session, business: Business, offer: SlotOffer) -> dict[str, object]:
    service = db.get(Service, offer.service_id) if offer.service_id else None
    tz = ZoneInfo(business.timezone)
    return {
        "id": str(offer.id),
        "service": service.name if service else None,
        "staff_name": offer.staff_name,
        "starts_at": offer.starts_at.astimezone(tz).isoformat(),
        "book_by": offer.book_by.astimezone(tz).isoformat(),
        "benefit": offer.benefit.value,
        "benefit_value": offer.benefit_value,
        "benefit_text": offer.benefit_text,
        "capacity": offer.capacity,
        "claims": offer.claims_count,
        "status": offer.status.value,
    }


def offer_for_token(db: Session, business: Business, token: str) -> dict[str, object]:
    r = _recipient(db, business, token)
    offer = _offer(db, business.id, r.offer_id)
    _expire_if_past(offer, utcnow())
    claimed = db.scalar(
        select(SlotClaim.id).where(
            SlotClaim.offer_id == offer.id, SlotClaim.customer_id == r.customer_id
        )
    )
    return {
        **describe(db, business, offer),
        "claimed": claimed is not None,
        "available": offer.status == SlotStatus.OPEN and claimed is None,
        "booking_url": business.booking_url,
    }


def claim(db: Session, business: Business, token: str) -> dict[str, object]:
    r = _recipient(db, business, token)
    now = utcnow()
    offer = _offer(db, business.id, r.offer_id, lock=True)
    _expire_if_past(offer, now)
    if offer.status != SlotStatus.OPEN:
        raise Conflict("slot_no_longer_available")
    try:
        with db.begin_nested():
            db.add(
                SlotClaim(
                    business_id=business.id,
                    offer_id=offer.id,
                    customer_id=r.customer_id,
                    claimed_at=now,
                )
            )
            db.flush()
    except IntegrityError as exc:
        raise Conflict("already_claimed") from exc
    offer.claims_count += 1
    if offer.claims_count >= offer.capacity:
        offer.status = SlotStatus.FILLED
        offer.next_send_at = None
    audit.record(db, business.id, "slot.claimed", "slot_offer", offer.id)
    return {"claimed": True, "booking_url": business.booking_url}


# --- At the counter ---------------------------------------------------------


def _claim_in_window(
    db: Session, business_id: uuid.UUID, customer_id: uuid.UUID, at: datetime
) -> tuple[SlotClaim, SlotOffer] | None:
    row = db.execute(
        select(SlotClaim, SlotOffer)
        .join(SlotOffer, SlotOffer.id == SlotClaim.offer_id)
        .where(
            SlotClaim.business_id == business_id,
            SlotClaim.customer_id == customer_id,
            SlotClaim.applied_at.is_(None),
            SlotOffer.starts_at - APPLY_BEFORE <= at,
            SlotOffer.starts_at + APPLY_AFTER >= at,
        )
        .order_by(SlotOffer.starts_at)
        .limit(1)
    ).first()
    return (row[0], row[1]) if row else None


def pending_claim(db: Session, ctx: StaffContext, customer: Customer) -> dict[str, object] | None:
    found = _claim_in_window(db, ctx.business.id, customer.id, utcnow())
    return describe(db, ctx.business, found[1]) if found else None


def apply_claim(
    db: Session, ctx: StaffContext, customer: Customer, at: datetime | None = None
) -> dict[str, object] | None:
    """Apply a claimed benefit once, and only when the visit falls inside the slot."""
    at = at or utcnow()
    found = _claim_in_window(db, ctx.business.id, customer.id, at)
    if found is None:
        return None
    claim_row, offer = found
    won = db.execute(
        update(SlotClaim)
        .where(SlotClaim.id == claim_row.id, SlotClaim.applied_at.is_(None))
        .values(applied_at=at, applied_by=ctx.staff.id)
        .returning(SlotClaim.id)
    ).scalar_one_or_none()
    if won is None:
        return None
    if offer.benefit == SlotBenefit.STAMPS:
        program = active_program(db, ctx.business.id)
        cp = db.scalar(
            select(CustomerProgram)
            .where(
                CustomerProgram.customer_id == customer.id, CustomerProgram.program_id == program.id
            )
            .with_for_update()
        )
        if cp is not None:
            event = ledger.append(
                db,
                cp,
                LedgerKind.BONUS,
                offer.benefit_value,
                f"slot:{claim_row.id}",
                staff_id=ctx.staff.id,
                at=at,
            )
            if event is not None:
                ledger.convert_to_rewards(db, cp, program, event)
    audit.record(db, ctx.business.id, "slot.applied", "slot_offer", offer.id, ctx.staff.id)
    return {
        "benefit": offer.benefit.value,
        "benefit_value": offer.benefit_value,
        "benefit_text": offer.benefit_text,
    }


def list_offers(db: Session, ctx: StaffContext) -> list[dict[str, object]]:
    now = utcnow()
    offers = db.scalars(
        select(SlotOffer)
        .where(SlotOffer.business_id == ctx.business.id)
        .order_by(SlotOffer.starts_at.desc())
        .limit(30)
    ).all()
    out = []
    for o in offers:
        _expire_if_past(o, now)
        rec = db.execute(
            select(SlotRecipient, Customer.first_name)
            .join(Customer, Customer.id == SlotRecipient.customer_id)
            .where(SlotRecipient.offer_id == o.id)
            .order_by(SlotRecipient.position)
        ).all()
        out.append(
            {
                **describe(db, ctx.business, o),
                "sending_started": o.sending_started,
                "next_send_at": o.next_send_at.isoformat() if o.next_send_at else None,
                "group_size": o.group_size,
                "wait_minutes": o.wait_minutes,
                "recipients": [
                    {
                        "customer_id": str(r.customer_id),
                        "first_name": name,
                        "reason": r.reason,
                        "status": r.status,
                    }
                    for r, name in rec
                ],
            }
        )
    return out
