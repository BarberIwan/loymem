"""Giving money back for a membership, bundle or balance.

The owner refunds; staff cannot. The suggested amount is what the customer paid
for the last paid period, in proportion to what is still unused:

    paid * unused / bought

so within the cooling-off period with nothing used it is everything, and when
the business stops it is the unused part. The owner may give back more (up to
what was paid for that period) or less, with a reason that is recorded.

The money goes back through the business's own payment account to the same
method the customer paid with. Whatever was unused is taken off the card as
"refunded", and the purchase ends. One refund per purchase.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    BalanceEvent,
    BalanceKind,
    CreditEvent,
    CreditKind,
    Customer,
    Payment,
    Plan,
    PlanKind,
    Refund,
    Subscription,
    SubscriptionStatus,
    utcnow,
)
from app.services import Conflict, NotFound, audit, balance, memberships
from app.services.cards import StaffContext

REASONS = ("cooling_off", "business_stops", "goodwill", "other")


def _last_paid(db: Session, sub: Subscription) -> Payment | None:
    return db.scalar(
        select(Payment)
        .where(
            Payment.subscription_id == sub.id,
            Payment.status == "paid",
            Payment.processed_at.is_not(None),
        )
        .order_by(Payment.processed_at.desc())
    )


def _unused_and_bought(db: Session, sub: Subscription, plan: Plan, pay: Payment) -> tuple[int, int]:
    """In the unit of the plan: cents of balance, or visits."""
    if plan.kind == PlanKind.CREDIT:
        bought = int(
            db.scalar(
                select(func.coalesce(func.sum(BalanceEvent.amount_cents), 0)).where(
                    BalanceEvent.subscription_id == sub.id, BalanceEvent.kind == BalanceKind.TOPUP
                )
            )
            or 0
        )
        return max(balance.of_subscription(db, sub.id), 0), bought
    if plan.kind == PlanKind.MEMBERSHIP:
        # Only this period's visits were paid by this payment.
        bought = int(
            db.scalar(
                select(CreditEvent.delta).where(CreditEvent.idempotency_key == f"grant:{pay.id}")
            )
            or 0
        )
        return min(memberships.available(db, sub.id), bought), bought
    bought = int(
        db.scalar(
            select(func.coalesce(func.sum(CreditEvent.delta), 0)).where(
                CreditEvent.subscription_id == sub.id, CreditEvent.kind == CreditKind.GRANT
            )
        )
        or 0
    )
    return memberships.available(db, sub.id), bought


def quote(db: Session, business_id: uuid.UUID, sub: Subscription) -> dict[str, object] | None:
    if sub.status not in (SubscriptionStatus.ACTIVE, SubscriptionStatus.CANCELLED):
        return None
    if db.scalar(select(Refund.id).where(Refund.subscription_id == sub.id)):
        return None
    pay = _last_paid(db, sub)
    plan = db.get(Plan, sub.plan_id)
    if pay is None or plan is None:
        return None
    unused, bought = _unused_and_bought(db, sub, plan, pay)
    suggested = pay.amount_cents * unused // bought if bought > 0 else 0
    cooling = (
        pay.processed_at is not None and (utcnow() - pay.processed_at).days < plan.cooling_off_days
    )
    return {
        "paid_cents": pay.amount_cents,
        "unused": unused,
        "bought": bought,
        "suggested_cents": suggested,
        "within_cooling_off": cooling,
    }


def overview(db: Session, ctx: StaffContext) -> list[dict[str, object]]:
    """Purchases that are running, for the owner, newest first."""
    rows = db.execute(
        select(Subscription, Plan, Customer)
        .join(Plan, Plan.id == Subscription.plan_id)
        .join(Customer, Customer.id == Subscription.customer_id)
        .where(
            Subscription.business_id == ctx.business.id,
            Subscription.status.in_([SubscriptionStatus.ACTIVE, SubscriptionStatus.CANCELLED]),
        )
        .order_by(Subscription.created_at.desc())
        .limit(200)
    ).all()
    out: list[dict[str, object]] = []
    for sub, plan, customer in rows:
        q = quote(db, ctx.business.id, sub)
        out.append(
            {
                "id": str(sub.id),
                "customer": customer.first_name or "",
                "plan": plan.name,
                "kind": plan.kind.value,
                "status": sub.status.value,
                "renews": sub.renews,
                "period_end": sub.period_end.isoformat() if sub.period_end else None,
                "refund": q,
            }
        )
    return out


def refund(
    db: Session, ctx: StaffContext, subscription_id: uuid.UUID, amount_cents: int, reason: str
) -> dict[str, object]:
    if reason not in REASONS:
        raise Conflict("unknown_reason")
    sub = db.scalar(
        select(Subscription)
        .where(Subscription.id == subscription_id, Subscription.business_id == ctx.business.id)
        .with_for_update()
    )
    if sub is None:
        raise NotFound("subscription_not_found")
    q = quote(db, ctx.business.id, sub)
    if q is None:
        raise Conflict("nothing_to_refund")
    if not 1 <= amount_cents <= int(str(q["paid_cents"])):
        raise Conflict("refund_amount_out_of_range")
    plan = db.get(Plan, sub.plan_id)
    pay = _last_paid(db, sub)
    assert plan is not None and pay is not None
    # The purchase is locked above and the quote is None once refunded, so a
    # second refund cannot start; the unique key on refunds is the backstop.
    key = f"refund:{sub.id}"
    if plan.kind == PlanKind.CREDIT:
        left = balance.of_subscription(db, sub.id)
        if left > 0:
            balance._event(db, sub, BalanceKind.REFUND, -left, key, staff_id=ctx.staff.id)
    else:
        left = memberships.available(db, sub.id)
        if left > 0:
            memberships._event(db, sub, CreditKind.REFUND, -left, key, staff_id=ctx.staff.id)
    sub.renews = False
    sub.cancelled_at = sub.cancelled_at or utcnow()
    sub.status = SubscriptionStatus.ENDED
    db.flush()
    # Money last: if the provider refuses, the transaction rolls back and nothing
    # above happened.
    provider_id = memberships.provider().refund(
        memberships._access_token(db, ctx.business.id),
        pay.provider_payment_id,
        amount_cents,
        f"{ctx.business.name}: terugbetaling {plan.name}",
    )
    db.add(
        Refund(
            business_id=ctx.business.id,
            subscription_id=sub.id,
            payment_id=pay.id,
            amount_cents=amount_cents,
            provider_refund_id=provider_id,
            reason=reason,
            staff_id=ctx.staff.id,
        )
    )
    audit.record(
        db,
        ctx.business.id,
        "subscription.refunded",
        "subscription",
        sub.id,
        ctx.staff.id,
        amount_cents=amount_cents,
        reason=reason,
        suggested_cents=q["suggested_cents"],
    )
    return {"refunded_cents": amount_cents, "status": sub.status.value}
