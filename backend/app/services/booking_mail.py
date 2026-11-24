"""Appointments from forwarded booking mails.

A business forwards the notification mails of its booking system to its own
address with us (integrations/booking_mails.py says which systems we read).
From them we know who is coming and when, which slots came free, and, if the
business wants that, who actually had an appointment.

Rules:
- Only mails from the booking system's own domain count; anything else is
  logged as "ignored" and dropped. The address itself is a secret per business,
  and the mail service must call us with the shared key.
- A customer is linked only when the mail's e-mail address or phone number
  belongs to an existing customer of this business. Nobody is created, and of
  people who are not (yet) a customer nothing personal is kept.
- A cancellation mail has no appointment number; it is matched on start time
  plus a hash of the name.
- Counting an appointment as a visit is off by default. When on, an appointment
  that was not cancelled counts half an hour after its end, once, through the
  same stamp rule as a scan (one per period).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.integrations import booking_mails
from app.models import (
    Appointment,
    Business,
    Customer,
    MailInbox,
    MailReceipt,
    utcnow,
)
from app.security import normalise_email, normalise_phone
from app.services import DomainError, audit
from app.services.cards import StaffContext, record_visit

VISIT_GRACE = timedelta(minutes=30)
MAX_VISIT_AGE = timedelta(days=7)


def _token(business_id: uuid.UUID, generation: int) -> str:
    key = get_settings().secret_key.encode()
    digest = hmac.new(key, f"mail:{business_id}:{generation}".encode(), hashlib.sha256).digest()
    return base64.b32encode(digest[:10]).decode().lower()


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _name_hash(business_id: uuid.UUID, name: str | None) -> str | None:
    if not name:
        return None
    normal = " ".join(name.lower().split())
    return _hash(f"{business_id}:{normal}")


def address(business: Business, inbox: MailInbox) -> str | None:
    domain = get_settings().inbound_mail_domain
    if not domain:
        return None
    return f"{business.slug}.{_token(business.id, inbox.generation)}@{domain}"


def _inbox(db: Session, business_id: uuid.UUID) -> MailInbox | None:
    return db.scalar(select(MailInbox).where(MailInbox.business_id == business_id))


def setup(db: Session, ctx: StaffContext, rotate: bool = False) -> MailInbox:
    inbox = _inbox(db, ctx.business.id)
    if inbox is None:
        inbox = MailInbox(business_id=ctx.business.id, generation=1, token_hash="")
        db.add(inbox)
    elif rotate:
        inbox.generation += 1
        inbox.gmail_code = None
    else:
        return inbox
    inbox.token_hash = _hash(_token(ctx.business.id, inbox.generation))
    db.flush()
    audit.record(db, ctx.business.id, "mail_inbox.address_set", "business", ctx.business.id,
                 ctx.staff.id)  # fmt: skip
    return inbox


def update(db: Session, ctx: StaffContext, *, active: bool, count_visits: bool) -> None:
    inbox = _inbox(db, ctx.business.id)
    if inbox is None:
        raise DomainError("mail_inbox_not_set_up")
    inbox.active, inbox.count_visits = active, count_visits
    audit.record(
        db, ctx.business.id, "mail_inbox.updated", "business", ctx.business.id, ctx.staff.id,
        active=active, count_visits=count_visits,
    )  # fmt: skip


def view(db: Session, ctx: StaffContext) -> dict[str, object]:
    inbox = _inbox(db, ctx.business.id)
    if inbox is None:
        return {
            "set_up": False,
            "domain_ready": bool(get_settings().inbound_mail_domain),
            "systems": booking_mails.SYSTEMS,
        }
    recent = db.execute(
        select(MailReceipt.kind, MailReceipt.outcome, MailReceipt.created_at)
        .where(MailReceipt.business_id == ctx.business.id)
        .order_by(MailReceipt.created_at.desc())
        .limit(10)
    ).all()
    return {
        "set_up": True,
        "domain_ready": bool(get_settings().inbound_mail_domain),
        "systems": booking_mails.SYSTEMS,
        "address": address(ctx.business, inbox),
        "active": inbox.active,
        "count_visits": inbox.count_visits,
        "gmail_code": inbox.gmail_code,
        "last_received_at": inbox.last_received_at.isoformat() if inbox.last_received_at else None,
        "recent": [{"kind": k, "outcome": o, "at": at.isoformat()} for k, o, at in recent],
    }


def business_for_address(db: Session, recipients: list[str]) -> uuid.UUID | None:
    """The business whose secret address is among the recipients."""
    domain = get_settings().inbound_mail_domain.lower()
    for raw in recipients:
        addr = raw.strip().lower().rsplit("<", 1)[-1].rstrip(">")
        local, _, dom = addr.partition("@")
        if not domain or dom != domain or "." not in local:
            continue
        token = local.rsplit(".", 1)[1]
        found = db.execute(text("select loymem_mail_inbox(:h)"), {"h": _hash(token)}).scalar()
        if found:
            return uuid.UUID(str(found))
    return None


def _log(db: Session, business: Business, kind: str, outcome: str) -> str:
    db.add(MailReceipt(business_id=business.id, kind=kind, outcome=outcome))
    return outcome


def _customer(
    db: Session, business: Business, email: str | None, phone: str | None
) -> Customer | None:
    for column, value in (
        (Customer.email, normalise_email(email)),
        (Customer.phone, normalise_phone(phone)),
    ):
        if not value:
            continue
        c = db.scalar(
            select(Customer).where(
                Customer.business_id == business.id,
                column == value,
                Customer.anonymised_at.is_(None),
            )
        )
        if c:
            return c
    return None


def receive(
    db: Session, business: Business, sender: str, subject: str, html: str, plain: str
) -> str:
    inbox = _inbox(db, business.id)
    assert inbox is not None
    inbox.last_received_at = utcnow()
    code = booking_mails.gmail_confirmation(sender, subject, plain or html)
    if code:
        inbox.gmail_code = code
        return _log(db, business, "gmail_confirm", "code_saved")
    read = booking_mails.read(sender, subject, html, business.timezone)
    if read is None:
        return _log(db, business, "other", "ignored")
    source, event = read
    if event is None:
        return _log(db, business, "other", "not_understood")
    now = utcnow()
    nh = _name_hash(business.id, event.name)
    if event.kind == "cancelled":
        appt = db.scalar(
            select(Appointment).where(
                Appointment.business_id == business.id,
                Appointment.source == source,
                Appointment.starts_at == event.starts_at,
                Appointment.name_hash == nh,
                Appointment.status == "booked",
            )
        )
        if appt is None:
            # Booked before forwarding started, or by phone: remember the free time anyway.
            appt = Appointment(
                business_id=business.id, source=source, external_id=None, name_hash=nh,
                starts_at=event.starts_at, ends_at=None, status="cancelled",
                service=event.service, updated_at=now,
            )  # fmt: skip
            db.add(appt)
            return _log(db, business, "cancelled", "recorded")
        appt.status = "cancelled"
        appt.updated_at = now
        return _log(db, business, "cancelled", "matched")

    customer = _customer(db, business, event.email, event.phone)
    appt = None
    if event.external_id:
        appt = db.scalar(
            select(Appointment).where(
                Appointment.business_id == business.id,
                Appointment.source == source,
                Appointment.external_id == event.external_id,
            )
        )
    if appt is None:
        appt = Appointment(business_id=business.id, source=source, external_id=event.external_id)
        db.add(appt)
    appt.customer_id = customer.id if customer else appt.customer_id
    appt.name_hash = nh
    appt.starts_at = event.starts_at
    appt.ends_at = event.ends_at
    appt.status = "booked"
    appt.service = event.service
    appt.staff = event.staff
    appt.updated_at = now
    if event.kind == "moved" and event.previous_starts_at:
        # The old time came free; keep it as a cancelled slot so it can be offered.
        db.add(
            Appointment(
                business_id=business.id, source=source, external_id=None, name_hash=nh,
                starts_at=event.previous_starts_at, ends_at=None, status="cancelled",
                service=event.service, staff=event.staff, updated_at=now,
            )
        )  # fmt: skip
    return _log(db, business, event.kind, "matched" if customer else "no_customer")


def upcoming_customer_ids(db: Session, business_id: uuid.UUID, now: datetime) -> set[uuid.UUID]:
    """Customers who already have a booking: no reason to nudge them."""
    rows = db.scalars(
        select(Appointment.customer_id).where(
            Appointment.business_id == business_id,
            Appointment.status == "booked",
            Appointment.starts_at > now,
            Appointment.customer_id.is_not(None),
        )
    )
    return {r for r in rows if r is not None}


def freed_slots(db: Session, business_id: uuid.UUID, now: datetime) -> list[dict[str, object]]:
    """Cancelled or moved-away times still ahead, at least an hour from now."""
    rows = db.scalars(
        select(Appointment)
        .where(
            Appointment.business_id == business_id,
            Appointment.status == "cancelled",
            Appointment.starts_at > now + timedelta(hours=1),
            Appointment.starts_at < now + timedelta(days=14),
        )
        .order_by(Appointment.starts_at)
        .limit(20)
    )
    seen: set[datetime] = set()
    out: list[dict[str, object]] = []
    for a in rows:
        if a.starts_at in seen:
            continue
        # Someone else may have booked the time since.
        taken = db.scalar(
            select(Appointment.id).where(
                Appointment.business_id == business_id,
                Appointment.status == "booked",
                Appointment.starts_at == a.starts_at,
                Appointment.staff.is_not_distinct_from(a.staff),
            )
        )
        if taken:
            continue
        seen.add(a.starts_at)
        out.append({"starts_at": a.starts_at.isoformat(), "service": a.service, "staff": a.staff})
    return out


def record_visits(db: Session, business: Business, now: datetime | None = None) -> int:
    """For businesses that chose it: a past, not cancelled appointment is a visit."""
    now = now or utcnow()
    inbox = _inbox(db, business.id)
    if inbox is None or not inbox.count_visits:
        return 0
    due = db.scalars(
        select(Appointment)
        .where(
            Appointment.business_id == business.id,
            Appointment.status == "booked",
            Appointment.customer_id.is_not(None),
            Appointment.visit_recorded_at.is_(None),
            Appointment.ends_at.is_not(None),
            Appointment.ends_at <= now - VISIT_GRACE,
            Appointment.ends_at >= now - MAX_VISIT_AGE,
        )
        .with_for_update(skip_locked=True)
    ).all()
    stamped = 0
    for appt in due:
        customer = db.get(Customer, appt.customer_id)
        appt.visit_recorded_at = now
        if customer is None or customer.anonymised_at is not None:
            continue
        assert appt.ends_at is not None
        if record_visit(db, business, customer, None, at=appt.ends_at)["stamped"]:
            stamped += 1
    return stamped
