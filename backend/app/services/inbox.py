"""Retention inbox: the owner's start screen.

Each opportunity carries only the facts that caused it, the action that fits and
the booking link. No scores. Without a booking integration we only know
registered visits, so an opportunity never says a customer "has no appointment".

Kinds in phase 1b:
- ``due_for_visit``: the return period of the last service has passed without a
  registered visit.
- ``reward_unused``: a reward was earned and has waited at least two weeks.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    ConsentPurpose,
    Customer,
    CustomerProgram,
    InboxDecision,
    InboxEntry,
    OutboxMessage,
    Reward,
    RewardStatus,
    utcnow,
)
from app.services import DomainError, NotFound, audit
from app.services.cards import StaffContext
from app.services.owner import has_consent
from app.services.rhythm import visit_statuses

REWARD_WAIT_DAYS = 14
# After acting on an opportunity it stays away for this long, so it does not
# come straight back the next morning.
SENT_HIDE_DAYS = 14
KINDS = ("due_for_visit", "reward_unused")


@dataclass
class Opportunity:
    customer_id: uuid.UUID
    kind: str
    first_name: str | None
    facts: dict[str, object]
    can_message: bool
    channel: str | None
    order: float = field(repr=False)

    def as_dict(self, booking_url: str | None) -> dict[str, object]:
        return {
            "customer_id": str(self.customer_id),
            "kind": self.kind,
            "first_name": self.first_name,
            "facts": self.facts,
            "action": "message" if self.can_message else "in_person",
            "channel": self.channel,
            "booking_url": booking_url,
        }


def _hidden(db: Session, business_id: uuid.UUID, now: datetime) -> set[tuple[uuid.UUID, str]]:
    rows = db.execute(
        select(InboxEntry.customer_id, InboxEntry.kind).where(
            InboxEntry.business_id == business_id, InboxEntry.hidden_until > now
        )
    )
    return {(r[0], r[1]) for r in rows}


def opportunities(
    db: Session, ctx: StaffContext, now: datetime | None = None, limit: int | None = None
) -> list[Opportunity]:
    now = now or utcnow()
    bid = ctx.business.id
    hidden = _hidden(db, bid, now)
    customers = {
        c.id: c
        for c in db.scalars(
            select(Customer).where(Customer.business_id == bid, Customer.anonymised_at.is_(None))
        )
    }

    def contact(c: Customer) -> tuple[bool, str | None]:
        channel = "email" if c.email else None  # sms follows the decision on channels
        ok = channel is not None and has_consent(db, c.id, ConsentPurpose.MARKETING)
        return ok, channel if ok else None

    out: list[Opportunity] = []
    # Earned rewards first: the customer already did the work.
    waiting = db.execute(
        select(Reward, CustomerProgram.customer_id)
        .join(CustomerProgram, CustomerProgram.id == Reward.customer_program_id)
        .where(
            Reward.business_id == bid,
            Reward.status == RewardStatus.AVAILABLE,
            Reward.earned_at <= now - timedelta(days=REWARD_WAIT_DAYS),
        )
    ).all()
    seen_reward: set[uuid.UUID] = set()
    for reward, customer_id in waiting:
        c = customers.get(customer_id)
        if c is None or customer_id in seen_reward or (customer_id, "reward_unused") in hidden:
            continue
        seen_reward.add(customer_id)
        ok, channel = contact(c)
        out.append(
            Opportunity(
                customer_id,
                "reward_unused",
                c.first_name,
                {
                    "reward": reward.description,
                    "earned_on": reward.earned_at.date().isoformat(),
                    "days_waiting": (now - reward.earned_at).days,
                },
                ok,
                channel,
                order=-1_000_000 + (now - reward.earned_at).days * -1,
            )
        )

    for s in visit_statuses(db, bid, now):
        c = customers.get(s.customer_id)
        if c is None or not s.due or (s.customer_id, "due_for_visit") in hidden:
            continue
        if s.customer_id in seen_reward:
            continue  # one card per customer; the reward is the better reason
        ok, channel = contact(c)
        assert s.return_period_days is not None
        out.append(
            Opportunity(
                s.customer_id,
                "due_for_visit",
                c.first_name,
                {
                    "last_visit": s.last_visit.date().isoformat(),
                    "days_since": s.days_since,
                    "service": s.service_name,
                    "return_period_days": s.return_period_days,
                    "personal_rhythm_days": s.personal_rhythm_days,
                },
                ok,
                channel,
                order=-(s.days_since / s.return_period_days),
            )
        )

    out.sort(key=lambda o: o.order)
    return out[: limit or ctx.business.inbox_daily_limit]


def _find(db: Session, ctx: StaffContext, customer_id: uuid.UUID, kind: str) -> Opportunity:
    if kind not in KINDS:
        raise DomainError("unknown_kind")
    for o in opportunities(db, ctx, limit=10_000):
        if o.customer_id == customer_id and o.kind == kind:
            return o
    raise NotFound("opportunity_gone")


def decide(
    db: Session,
    ctx: StaffContext,
    customer_id: uuid.UUID,
    kind: str,
    decision: InboxDecision,
    message: str | None = None,
) -> dict[str, object]:
    o = _find(db, ctx, customer_id, kind)
    now = utcnow()
    days = ctx.business.inbox_ignore_days if decision == InboxDecision.IGNORED else SENT_HIDE_DAYS
    text: str | None = None
    if decision == InboxDecision.SENT:
        if not o.can_message:
            raise DomainError("no_consent_or_contact")
        # The text comes from the screen, written in the owner's language and editable.
        text = (message or "").strip()
        if not 5 <= len(text) <= 600:
            raise DomainError("message_length")
        customer = db.get(Customer, customer_id)
        assert customer is not None and customer.email
        db.add(
            OutboxMessage(
                customer_id=customer_id,
                business_id=ctx.business.id,
                channel="email",
                recipient=customer.email,
                template=f"inbox_{kind}",
                payload={"text": text, "business": ctx.business.name},
            )
        )
    db.add(
        InboxEntry(
            business_id=ctx.business.id,
            customer_id=customer_id,
            kind=kind,
            decision=decision,
            hidden_until=now + timedelta(days=days),
            staff_id=ctx.staff.id,
            message=text,
        )
    )
    audit.record(
        db,
        ctx.business.id,
        f"inbox.{decision.value}",
        "customer",
        customer_id,
        ctx.staff.id,
        kind=kind,
    )
    return {"decision": decision.value, "hidden_days": days}
