"""Campaigns with a control group, and an honest report (phase 1e, §10).

- Only customers with marketing consent and an email address are in the audience.
- A fixed share (default 10%) is the control group. Assignment is a stable hash of
  campaign and customer, so it cannot be steered, and control-group members are
  never sent anything (also enforced by a database check).
- The report shows observed counts first. An effect is only stated when the
  difference between the groups holds up statistically (two-sided two-proportion
  z-test, p < 0.05) and both groups are large enough; otherwise it says plainly
  that an effect is not demonstrable.
"""

from __future__ import annotations

import hashlib
import math
import uuid
from datetime import timedelta

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.models import (
    Campaign,
    CampaignMember,
    ConsentPurpose,
    Customer,
    CustomerProgram,
    LedgerEvent,
    LedgerKind,
    OutboxMessage,
    utcnow,
)
from app.services import Conflict, DomainError, NotFound, audit
from app.services.cards import StaffContext
from app.services.owner import has_consent
from app.services.rhythm import visit_statuses

AUDIENCES = ("due_for_visit", "lapsed_60", "all_consented")
MIN_GROUP = 30
ALPHA = 0.05


def _audience(db: Session, ctx: StaffContext, audience: str) -> list[Customer]:
    bid = ctx.business.id
    customers = db.scalars(
        select(Customer)
        .where(
            Customer.business_id == bid,
            Customer.anonymised_at.is_(None),
            Customer.email.is_not(None),
        )
        .order_by(Customer.created_at)
    ).all()
    eligible = [c for c in customers if has_consent(db, c.id, ConsentPurpose.MARKETING)]
    if audience == "all_consented":
        return eligible
    statuses = {s.customer_id: s for s in visit_statuses(db, bid)}
    if audience == "due_for_visit":
        return [c for c in eligible if c.id in statuses and statuses[c.id].due]
    if audience == "lapsed_60":
        return [c for c in eligible if c.id in statuses and statuses[c.id].days_since >= 60]
    raise DomainError("unknown_audience")


def in_holdout(campaign_id: uuid.UUID, customer_id: uuid.UUID, percent: int) -> bool:
    h = hashlib.sha256(f"{campaign_id}:{customer_id}".encode()).digest()
    return int.from_bytes(h[:4], "big") % 100 < percent


def create(
    db: Session,
    ctx: StaffContext,
    *,
    name: str,
    audience: str,
    message: str,
    holdout_percent: int,
    window_days: int,
) -> Campaign:
    if audience not in AUDIENCES:
        raise DomainError("unknown_audience")
    c = Campaign(
        id=uuid.uuid4(),
        business_id=ctx.business.id,
        name=name.strip(),
        audience=audience,
        message=message.strip(),
        holdout_percent=holdout_percent,
        window_days=window_days,
        created_by=ctx.staff.id,
    )
    db.add(c)
    db.flush()
    for customer in _audience(db, ctx, audience):
        db.add(
            CampaignMember(
                business_id=ctx.business.id,
                campaign_id=c.id,
                customer_id=customer.id,
                holdout=in_holdout(c.id, customer.id, holdout_percent),
            )
        )
    audit.record(db, ctx.business.id, "campaign.created", "campaign", c.id, ctx.staff.id)
    return c


def send(db: Session, ctx: StaffContext, campaign_id: uuid.UUID) -> int:
    c = db.scalar(
        select(Campaign)
        .where(Campaign.id == campaign_id, Campaign.business_id == ctx.business.id)
        .with_for_update()
    )
    if c is None:
        raise NotFound("campaign_not_found")
    if c.sent_at is not None:
        raise Conflict("campaign_already_sent")
    now = utcnow()
    sent = 0
    members = db.execute(
        select(CampaignMember, Customer)
        .join(Customer, Customer.id == CampaignMember.customer_id)
        .where(CampaignMember.campaign_id == c.id, CampaignMember.holdout.is_(False))
    ).all()
    for member, customer in members:
        # Consent is checked again now: it may have been withdrawn since creating.
        if not customer.email or not has_consent(db, customer.id, ConsentPurpose.MARKETING):
            continue
        db.add(
            OutboxMessage(
                business_id=ctx.business.id,
                channel="email",
                recipient=customer.email,
                template="campaign",
                payload={"text": c.message, "campaign_id": str(c.id)},
            )
        )
        member.sent_at = now
        sent += 1
    c.sent_at = now
    audit.record(db, ctx.business.id, "campaign.sent", "campaign", c.id, ctx.staff.id, sent=sent)
    return sent


def _returned(db: Session, campaign: Campaign, holdout: bool) -> tuple[int, int]:
    assert campaign.sent_at is not None
    end = campaign.sent_at + timedelta(days=campaign.window_days)
    visit = (
        select(LedgerEvent.id)
        .join(CustomerProgram, CustomerProgram.id == LedgerEvent.customer_program_id)
        .where(
            CustomerProgram.customer_id == CampaignMember.customer_id,
            LedgerEvent.kind == LedgerKind.STAMP,
            LedgerEvent.created_at > campaign.sent_at,
            LedgerEvent.created_at <= end,
        )
    )
    stmt = select(CampaignMember.id, exists(visit)).where(
        CampaignMember.campaign_id == campaign.id, CampaignMember.holdout.is_(holdout)
    )
    if not holdout:
        stmt = stmt.where(CampaignMember.sent_at.is_not(None))
    rows = db.execute(stmt).all()
    return len(rows), sum(1 for _, came in rows if came)


def _p_value(x1: int, n1: int, x2: int, n2: int) -> float:
    if not n1 or not n2:
        return 1.0
    p = (x1 + x2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    if se == 0:
        return 1.0
    z = (x1 / n1 - x2 / n2) / se
    return math.erfc(abs(z) / math.sqrt(2))


def report(db: Session, ctx: StaffContext, campaign_id: uuid.UUID) -> dict[str, object]:
    c = db.scalar(
        select(Campaign).where(Campaign.id == campaign_id, Campaign.business_id == ctx.business.id)
    )
    if c is None:
        raise NotFound("campaign_not_found")
    if c.sent_at is None:
        return {"status": "not_sent"}
    n_t, x_t = _returned(db, c, holdout=False)
    n_c, x_c = _returned(db, c, holdout=True)
    window_over = utcnow() >= c.sent_at + timedelta(days=c.window_days)
    p = _p_value(x_t, n_t, x_c, n_c)
    rate_t = x_t / n_t if n_t else 0.0
    rate_c = x_c / n_c if n_c else 0.0
    if not window_over:
        verdict = "window_open"
    elif n_t < MIN_GROUP or n_c < MIN_GROUP:
        verdict = "too_small"
    elif p < ALPHA and rate_t > rate_c:
        verdict = "demonstrable"
    else:
        verdict = "not_demonstrable"
    out: dict[str, object] = {
        "status": "sent",
        "verdict": verdict,
        "window_days": c.window_days,
        "observed": {"sent": n_t, "returned": x_t, "control": n_c, "control_returned": x_c},
    }
    if verdict == "demonstrable":
        out["estimated_extra_visits"] = round((rate_t - rate_c) * n_t, 1)
        out["p_value"] = round(p, 4)
    return out


def list_campaigns(db: Session, ctx: StaffContext) -> list[dict[str, object]]:
    rows = db.scalars(
        select(Campaign)
        .where(Campaign.business_id == ctx.business.id)
        .order_by(Campaign.created_at.desc())
        .limit(30)
    ).all()
    out = []
    for c in rows:
        members = db.scalars(
            select(CampaignMember.holdout).where(CampaignMember.campaign_id == c.id)
        ).all()
        out.append(
            {
                "id": str(c.id),
                "name": c.name,
                "audience": c.audience,
                "message": c.message,
                "holdout_percent": c.holdout_percent,
                "window_days": c.window_days,
                "sent_at": c.sent_at.isoformat() if c.sent_at else None,
                "size": len(members),
                "control": sum(1 for h in members if h),
                "report": report(db, ctx, c.id),
            }
        )
    return out
