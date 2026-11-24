"""Tegoed: a prepaid balance in euros, bought through a credit plan.

Rules:
- The money goes to the business's own payment account, exactly like bundles;
  the balance is only a record of what the customer may still spend there.
- Every change is one line in ``balance_events`` (append-only). The balance is
  the sum; nothing is ever edited.
- Spending takes from the balance that expires first, so a customer never loses
  money that could have been used.
- A retried tap spends nothing extra: every spend carries the request id of the
  tap. A spend can be undone once, with a reason, by a manager or the owner, or
  by the staff member who made it within ``OWN_UNDO_WINDOW``.
- Unspent balance expires at the end of its validity, as the plan terms said.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import (
    BalanceEvent,
    BalanceKind,
    Plan,
    PlanKind,
    Role,
    Subscription,
    SubscriptionStatus,
    utcnow,
)
from app.services import Conflict, Forbidden, NotFound, audit
from app.services.cards import StaffContext

OWN_UNDO_WINDOW = timedelta(minutes=10)
MAX_SPEND_CENTS = 100_000


def _event(
    db: Session,
    sub: Subscription,
    kind: BalanceKind,
    amount_cents: int,
    key: str,
    *,
    reverses: uuid.UUID | None = None,
    staff_id: uuid.UUID | None = None,
    note: str | None = None,
) -> uuid.UUID | None:
    stmt = (
        insert(BalanceEvent)
        .values(
            id=uuid.uuid4(),
            business_id=sub.business_id,
            subscription_id=sub.id,
            kind=kind,
            amount_cents=amount_cents,
            idempotency_key=key,
            reverses_id=reverses,
            staff_id=staff_id,
            note=note,
            created_at=utcnow(),
        )
        .on_conflict_do_nothing()
        .returning(BalanceEvent.id)
    )
    return db.execute(stmt).scalar_one_or_none()


def of_subscription(db: Session, subscription_id: uuid.UUID) -> int:
    return int(
        db.scalar(
            select(func.coalesce(func.sum(BalanceEvent.amount_cents), 0)).where(
                BalanceEvent.subscription_id == subscription_id
            )
        )
        or 0
    )


def _open(
    db: Session, business_id: uuid.UUID, customer_id: uuid.UUID, lock: bool = False
) -> list[Subscription]:
    """Active credit subscriptions, the one that expires first first."""
    q = (
        select(Subscription)
        .join(Plan, Plan.id == Subscription.plan_id)
        .where(
            Subscription.business_id == business_id,
            Subscription.customer_id == customer_id,
            Subscription.status == SubscriptionStatus.ACTIVE,
            Subscription.period_end > utcnow(),
            Plan.kind == PlanKind.CREDIT,
        )
        .order_by(Subscription.period_end, Subscription.created_at)
    )
    if lock:
        q = q.with_for_update(of=Subscription)
    return list(db.scalars(q))


def summary(db: Session, business_id: uuid.UUID, customer_id: uuid.UUID) -> dict[str, object]:
    parts = []
    for sub in _open(db, business_id, customer_id):
        cents = of_subscription(db, sub.id)
        if cents > 0:
            assert sub.period_end is not None
            parts.append({"cents": cents, "expires": sub.period_end.isoformat()})
    return {"cents": sum(int(str(p["cents"])) for p in parts), "parts": parts}


def topup(db: Session, sub: Subscription, plan: Plan, payment_id: uuid.UUID) -> None:
    """Called once a payment for a credit plan is verified as paid."""
    assert plan.kind == PlanKind.CREDIT and plan.value_cents
    _event(db, sub, BalanceKind.TOPUP, plan.value_cents, f"topup:{payment_id}")


def spend(
    db: Session,
    ctx: StaffContext,
    customer_id: uuid.UUID,
    amount_cents: int,
    request_id: str,
    note: str | None = None,
) -> dict[str, object]:
    if not 1 <= amount_cents <= MAX_SPEND_CENTS:
        raise Conflict("amount_out_of_range")
    group = f"spend:{request_id}"
    done = db.scalar(
        select(func.coalesce(func.sum(BalanceEvent.amount_cents), 0)).where(
            BalanceEvent.business_id == ctx.business.id,
            BalanceEvent.idempotency_key.like(f"{group}:%"),
        )
    )
    subs = _open(db, ctx.business.id, customer_id, lock=True)
    if done:
        # The same tap again: report what it did, change nothing.
        return {
            "request_id": request_id,
            "spent_cents": -int(done),
            "balance_cents": sum(of_subscription(db, s.id) for s in subs),
        }
    available = [(s, of_subscription(db, s.id)) for s in subs]
    total = sum(c for _, c in available)
    if total < amount_cents:
        raise Conflict("balance_too_low")
    left = amount_cents
    n = 0
    for sub, cents in available:
        if left == 0:
            break
        take = min(cents, left)
        if take <= 0:
            continue
        _event(
            db,
            sub,
            BalanceKind.SPEND,
            -take,
            f"{group}:{n}",
            staff_id=ctx.staff.id,
            note=note,
        )
        left -= take
        n += 1
    audit.record(
        db,
        ctx.business.id,
        "balance.spent",
        "customer",
        customer_id,
        ctx.staff.id,
        amount_cents=amount_cents,
        request_id=request_id,
    )
    return {
        "request_id": request_id,
        "spent_cents": amount_cents,
        "balance_cents": total - amount_cents,
    }


def undo(
    db: Session, ctx: StaffContext, customer_id: uuid.UUID, request_id: str, reason: str
) -> dict[str, object]:
    spends = list(
        db.scalars(
            select(BalanceEvent)
            .join(Subscription, Subscription.id == BalanceEvent.subscription_id)
            .where(
                BalanceEvent.business_id == ctx.business.id,
                BalanceEvent.kind == BalanceKind.SPEND,
                BalanceEvent.idempotency_key.like(f"spend:{request_id}:%"),
                Subscription.customer_id == customer_id,
            )
        )
    )
    if not spends:
        raise NotFound("spend_not_found")
    own_and_recent = all(
        e.staff_id == ctx.staff.id and utcnow() - e.created_at <= OWN_UNDO_WINDOW for e in spends
    )
    if ctx.staff.role not in (Role.OWNER, Role.MANAGER) and not own_and_recent:
        raise Forbidden("undo_not_allowed")
    restored = 0
    for e in spends:
        sub = db.get(Subscription, e.subscription_id)
        assert sub is not None
        if _event(
            db,
            sub,
            BalanceKind.REVERSAL,
            -e.amount_cents,
            f"reverse:{e.id}",
            reverses=e.id,
            staff_id=ctx.staff.id,
            note=reason,
        ):
            restored += -e.amount_cents
    if restored:
        audit.record(
            db,
            ctx.business.id,
            "balance.reversed",
            "customer",
            customer_id,
            ctx.staff.id,
            amount_cents=restored,
            request_id=request_id,
        )
    return {
        "restored_cents": restored,
        "balance_cents": int(str(summary(db, ctx.business.id, customer_id)["cents"])),
    }


def expire(db: Session, sub: Subscription) -> int:
    """At the end of the validity: whatever is left expires, once."""
    left = of_subscription(db, sub.id)
    if left > 0:
        _event(db, sub, BalanceKind.EXPIRE, -left, f"expire:{sub.id}")
    return max(left, 0)


def history(
    db: Session, business_id: uuid.UUID, customer_id: uuid.UUID, limit: int = 10
) -> list[dict[str, object]]:
    """Recent lines, newest first. The parts of one spend (split over two
    balances) show as one line, and a reversal shows on the line it undid."""
    rows = db.scalars(
        select(BalanceEvent)
        .join(Subscription, Subscription.id == BalanceEvent.subscription_id)
        .where(BalanceEvent.business_id == business_id, Subscription.customer_id == customer_id)
        .order_by(BalanceEvent.created_at.desc(), BalanceEvent.idempotency_key)
        .limit(limit * 4)
    ).all()
    undone = {e.reverses_id for e in rows if e.reverses_id}
    out: list[dict[str, object]] = []
    groups: dict[str, dict[str, object]] = {}
    for e in rows:
        if e.kind == BalanceKind.REVERSAL:
            continue
        if e.kind == BalanceKind.SPEND:
            group = e.idempotency_key.rsplit(":", 1)[0]
            if group in groups:
                groups[group]["cents"] = int(str(groups[group]["cents"])) + e.amount_cents
                continue
            line: dict[str, object] = {
                "kind": "spend",
                "cents": e.amount_cents,
                "at": e.created_at.isoformat(),
                "request_id": group.split(":", 1)[1],
                "undone": e.id in undone,
            }
            groups[group] = line
        else:
            line = {
                "kind": e.kind.value,
                "cents": e.amount_cents,
                "at": e.created_at.isoformat(),
                "request_id": None,
                "undone": False,
            }
        out.append(line)
    return out[:limit]
