"""Memberships and visit bundles (phase 1d).

Rules from §8 and §9:
- Loymem holds no customer money: payments run in the business's own account.
- Every condition is visible before purchase; the purchase records the accepted
  ``terms_version`` and is refused when the customer saw an older version.
- A membership bought online is cancelled online from the card, in one step,
  without a call or a win-back screen. It then stops renewing and runs to the end
  of the paid period.
- Status changes only from verified payment status (read back from the provider)
  or the customer's own cancellation. Staff have no way to change it.
- Credits: reserve, then consume or release, each one ledger line; a reservation
  is settled exactly once.
"""

from __future__ import annotations

import base64
import hashlib
import uuid
from datetime import datetime, timedelta

from cryptography.fernet import Fernet
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config import get_settings
from app.integrations.payments import PaymentProvider, Tokens
from app.models import (
    Business,
    CreditEvent,
    CreditKind,
    Customer,
    Payment,
    Plan,
    PlanKind,
    ProviderConnection,
    Subscription,
    SubscriptionStatus,
    utcnow,
)
from app.services import Conflict, DomainError, Forbidden, NotFound, audit, balance
from app.services.cards import StaffContext

PERIOD = timedelta(days=30)
TERM_FIELDS = (
    "price_cents",
    "credits",
    "value_cents",
    "unused_rule",
    "no_show_rule",
    "validity_days",
    "cancel_notice_days",
    "cooling_off_days",
    "unused_policy",
    "no_show_policy",
    "pause_policy",
    "refund_policy",
)

_provider: PaymentProvider | None = None


def provider() -> PaymentProvider:
    global _provider
    if _provider is None:
        from app.integrations.mollie import MollieProvider

        _provider = MollieProvider()
    return _provider


def set_provider(p: PaymentProvider | None) -> None:
    global _provider
    _provider = p


def _fernet() -> Fernet:
    key = hashlib.sha256(b"payments:" + get_settings().secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


# --- Plans --------------------------------------------------------------------


def bonus_percent(price_cents: int, value_cents: int | None) -> int | None:
    """How much more the balance is worth than it costs, rounded down."""
    if not value_cents:
        return None
    return (value_cents - price_cents) * 100 // price_cents


def plan_terms(plan: Plan) -> dict[str, object]:
    return {
        "id": str(plan.id),
        "kind": plan.kind.value,
        "name": plan.name,
        "price_cents": plan.price_cents,
        "credits": plan.credits,
        "value_cents": plan.value_cents,
        "bonus_percent": bonus_percent(plan.price_cents, plan.value_cents),
        "validity_days": plan.validity_days,
        "unused_rule": plan.unused_rule,
        "no_show_rule": plan.no_show_rule,
        "cancel_notice_days": plan.cancel_notice_days,
        "cooling_off_days": plan.cooling_off_days,
        "unused_policy": plan.unused_policy,
        "no_show_policy": plan.no_show_policy,
        "pause_policy": plan.pause_policy,
        "refund_policy": plan.refund_policy,
        "terms_version": plan.terms_version,
        "renews": plan.kind == PlanKind.MEMBERSHIP,
        "active": plan.active,
    }


def save_plan(
    db: Session, ctx: StaffContext, plan_id: uuid.UUID | None, data: dict[str, object]
) -> Plan:
    if plan_id is None:
        plan = Plan(business_id=ctx.business.id, terms_version=1, **data)
        db.add(plan)
    else:
        found = db.scalar(
            select(Plan).where(Plan.id == plan_id, Plan.business_id == ctx.business.id)
        )
        if found is None:
            raise NotFound("plan_not_found")
        plan = found
        changed = any(k in data and data[k] != getattr(plan, k) for k in TERM_FIELDS)
        for k, v in data.items():
            if k != "kind":
                setattr(plan, k, v)
        if changed:
            plan.terms_version += 1
    db.flush()
    audit.record(
        db,
        ctx.business.id,
        "plan.saved",
        "plan",
        plan.id,
        ctx.staff.id,
        terms_version=plan.terms_version,
    )
    return plan


# --- Connecting the business's own payment account ------------------------------


def connect_url(ctx: StaffContext, redirect_uri: str) -> str:
    return provider().authorize_url(f"{ctx.business.id}", redirect_uri)


def store_tokens(db: Session, business: Business, tokens: Tokens) -> None:
    f = _fernet()
    stmt = insert(ProviderConnection).values(
        id=uuid.uuid4(),
        business_id=business.id,
        provider=provider().name,
        access_token_encrypted=f.encrypt(tokens.access_token.encode()).decode(),
        refresh_token_encrypted=f.encrypt(tokens.refresh_token.encode()).decode(),
        expires_at=tokens.expires_at,
        created_at=utcnow(),
    )
    db.execute(
        stmt.on_conflict_do_update(
            index_elements=["business_id"],
            set_={
                "access_token_encrypted": stmt.excluded.access_token_encrypted,
                "refresh_token_encrypted": stmt.excluded.refresh_token_encrypted,
                "expires_at": stmt.excluded.expires_at,
            },
        )
    )


def _access_token(db: Session, business_id: uuid.UUID) -> str:
    conn = db.scalar(
        select(ProviderConnection).where(ProviderConnection.business_id == business_id)
    )
    if conn is None:
        raise DomainError("payments_not_connected")
    f = _fernet()
    if conn.expires_at <= utcnow():
        tokens = provider().refresh(f.decrypt(conn.refresh_token_encrypted.encode()).decode())
        conn.access_token_encrypted = f.encrypt(tokens.access_token.encode()).decode()
        conn.refresh_token_encrypted = f.encrypt(tokens.refresh_token.encode()).decode()
        conn.expires_at = tokens.expires_at
    return f.decrypt(conn.access_token_encrypted.encode()).decode()


def is_connected(db: Session, business_id: uuid.UUID) -> bool:
    return (
        db.scalar(
            select(ProviderConnection.id).where(ProviderConnection.business_id == business_id)
        )
        is not None
    )


# --- Buying ---------------------------------------------------------------------


def _urls(business: Business) -> tuple[str, str]:
    base = get_settings().public_base_url
    return (f"{base}/api/v1/payments/{business.slug}/webhook", base)


def start_purchase(
    db: Session,
    business: Business,
    customer: Customer,
    plan_id: uuid.UUID,
    accepted_terms_version: int,
    card_path: str,
) -> str:
    if not get_settings().memberships_enabled:
        raise Forbidden("memberships_not_enabled")
    plan = db.scalar(
        select(Plan).where(
            Plan.id == plan_id, Plan.business_id == business.id, Plan.active.is_(True)
        )
    )
    if plan is None:
        raise NotFound("plan_not_found")
    if accepted_terms_version != plan.terms_version:
        raise Conflict("terms_changed")
    token = _access_token(db, business.id)
    sub = Subscription(
        business_id=business.id,
        customer_id=customer.id,
        plan_id=plan.id,
        status=SubscriptionStatus.PENDING,
        terms_version=plan.terms_version,
        renews=plan.kind == PlanKind.MEMBERSHIP,
    )
    db.add(sub)
    db.flush()
    webhook, base = _urls(business)
    sequence = "first" if plan.kind == PlanKind.MEMBERSHIP else "oneoff"
    new = provider().create_payment(
        token,
        amount_cents=plan.price_cents,
        description=f"{business.name}: {plan.name}",
        sequence=sequence,
        redirect_url=f"{base}{card_path}",
        webhook_url=webhook,
        metadata={"subscription_id": str(sub.id)},
    )
    db.add(
        Payment(
            business_id=business.id,
            subscription_id=sub.id,
            provider_payment_id=new.payment_id,
            amount_cents=plan.price_cents,
            status="open",
            sequence=sequence,
        )
    )
    audit.record(
        db,
        business.id,
        "subscription.started",
        "subscription",
        sub.id,
        terms_version=plan.terms_version,
    )
    if not new.checkout_url:
        raise DomainError("payment_provider_error")
    return new.checkout_url


def handle_webhook(db: Session, business: Business, payment_id: str) -> str:
    """Process a provider notification. The status is always read back from the
    provider; the incoming call is only a hint that something changed."""
    payment = db.scalar(
        select(Payment)
        .where(Payment.business_id == business.id, Payment.provider_payment_id == payment_id)
        .with_for_update()
    )
    if payment is None:
        return "unknown"
    info = provider().get_payment(_access_token(db, business.id), payment_id)
    if info.amount_cents != payment.amount_cents or info.metadata.get("subscription_id") != str(
        payment.subscription_id
    ):
        audit.record(db, business.id, "payment.mismatch", "payment", payment.id)
        return "mismatch"
    payment.status = info.status
    sub = db.get(Subscription, payment.subscription_id)
    assert sub is not None
    if info.status != "paid":
        if info.status in ("failed", "canceled", "expired"):
            if sub.status == SubscriptionStatus.PENDING:
                sub.status = SubscriptionStatus.FAILED
            elif (
                sub.status == SubscriptionStatus.ACTIVE
                and payment.sequence == "recurring"
                and sub.period_end
                and sub.period_end <= utcnow()
            ):
                sub.status = SubscriptionStatus.ENDED  # renewal failed; nothing is owed
        return info.status
    won = db.execute(
        update(Payment)
        .where(Payment.id == payment.id, Payment.processed_at.is_(None))
        .values(processed_at=utcnow())
        .returning(Payment.id)
    ).scalar_one_or_none()
    if won is None:
        return "already_processed"
    plan = db.get(Plan, sub.plan_id)
    assert plan is not None
    now = utcnow()
    start = sub.period_end if sub.period_end and sub.period_end > now else now
    sub.period_start = start
    sub.period_end = start + (
        PERIOD if plan.kind == PlanKind.MEMBERSHIP else timedelta(days=plan.validity_days or 365)
    )
    if sub.status in (SubscriptionStatus.PENDING, SubscriptionStatus.FAILED):
        sub.status = SubscriptionStatus.ACTIVE
    sub.provider_customer_id = info.customer_id or sub.provider_customer_id
    sub.provider_mandate_id = info.mandate_id or sub.provider_mandate_id
    if plan.kind == PlanKind.CREDIT:
        balance.topup(db, sub, plan, payment.id)
    else:
        _event(db, sub, CreditKind.GRANT, plan.credits, f"grant:{payment.id}")
    audit.record(db, business.id, "payment.paid", "subscription", sub.id)
    return "paid"


def cancel_online(
    db: Session, business: Business, customer: Customer, subscription_id: uuid.UUID
) -> dict[str, object]:
    """One step, from the card. No call, no win-back screen."""
    sub = db.scalar(
        select(Subscription).where(
            Subscription.id == subscription_id,
            Subscription.business_id == business.id,
            Subscription.customer_id == customer.id,
        )
    )
    if sub is None:
        raise NotFound("subscription_not_found")
    if sub.status in (SubscriptionStatus.ACTIVE, SubscriptionStatus.PENDING):
        sub.renews = False
        sub.cancelled_at = sub.cancelled_at or utcnow()
        if sub.status == SubscriptionStatus.PENDING:
            sub.status = SubscriptionStatus.CANCELLED
        audit.record(
            db, business.id, "subscription.cancelled", "subscription", sub.id, source="card"
        )
    return {
        "status": sub.status.value,
        "renews": sub.renews,
        "runs_until": sub.period_end.isoformat() if sub.period_end else None,
    }


# --- Credits ----------------------------------------------------------------------


def _event(
    db: Session,
    sub: Subscription,
    kind: CreditKind,
    delta: int,
    key: str,
    settles: uuid.UUID | None = None,
    staff_id: uuid.UUID | None = None,
) -> uuid.UUID | None:
    stmt = (
        insert(CreditEvent)
        .values(
            id=uuid.uuid4(),
            business_id=sub.business_id,
            subscription_id=sub.id,
            kind=kind,
            delta=delta,
            idempotency_key=key,
            settles_id=settles,
            staff_id=staff_id,
            created_at=utcnow(),
        )
        .on_conflict_do_nothing()
        .returning(CreditEvent.id)
    )
    return db.execute(stmt).scalar_one_or_none()


def available(db: Session, subscription_id: uuid.UUID) -> int:
    return int(
        db.scalar(
            select(func.coalesce(func.sum(CreditEvent.delta), 0)).where(
                CreditEvent.subscription_id == subscription_id
            )
        )
        or 0
    )


def _usable(db: Session, business_id: uuid.UUID, customer_id: uuid.UUID) -> Subscription:
    now = utcnow()
    sub = db.scalar(
        select(Subscription)
        .join(Plan, Plan.id == Subscription.plan_id)
        .where(
            Subscription.business_id == business_id,
            Subscription.customer_id == customer_id,
            Subscription.status == SubscriptionStatus.ACTIVE,
            Subscription.period_end > now,
            Plan.kind != PlanKind.CREDIT,  # a euro balance is spent with balance.spend
        )
        .order_by(Subscription.period_end)
        .with_for_update(of=Subscription)
    )
    if sub is None:
        raise NotFound("no_active_membership")
    return sub


def reserve(db: Session, business_id: uuid.UUID, customer_id: uuid.UUID, key: str) -> uuid.UUID:
    sub = _usable(db, business_id, customer_id)
    if available(db, sub.id) < 1:
        raise Conflict("no_credits_left")
    event = _event(db, sub, CreditKind.RESERVE, -1, f"reserve:{key}")
    if event is None:
        existing = db.scalar(
            select(CreditEvent.id).where(CreditEvent.idempotency_key == f"reserve:{key}")
        )
        assert existing is not None
        return existing
    return event


def settle(
    db: Session,
    business_id: uuid.UUID,
    reservation_id: uuid.UUID,
    consume: bool,
    staff_id: uuid.UUID | None = None,
) -> bool:
    """Consume or release a reservation. Returns False if it was already settled."""
    res = db.scalar(
        select(CreditEvent).where(
            CreditEvent.id == reservation_id,
            CreditEvent.business_id == business_id,
            CreditEvent.kind == CreditKind.RESERVE,
        )
    )
    if res is None:
        raise NotFound("reservation_not_found")
    sub = db.get(Subscription, res.subscription_id)
    assert sub is not None
    kind = CreditKind.CONSUME if consume else CreditKind.RELEASE
    return (
        _event(
            db,
            sub,
            kind,
            0 if consume else 1,
            f"settle:{res.id}",
            settles=res.id,
            staff_id=staff_id,
        )
        is not None
    )


def use_at_counter(
    db: Session, ctx: StaffContext, customer_id: uuid.UUID, request_id: str
) -> dict[str, object]:
    reservation = reserve(db, ctx.business.id, customer_id, f"counter:{request_id}")
    settle(db, ctx.business.id, reservation, consume=True, staff_id=ctx.staff.id)
    sub = _usable(db, ctx.business.id, customer_id)
    return {"used": True, "credits_left": available(db, sub.id)}


def customer_view(db: Session, business: Business, customer: Customer) -> dict[str, object]:
    subs = db.scalars(
        select(Subscription).where(
            Subscription.business_id == business.id,
            Subscription.customer_id == customer.id,
            Subscription.status.in_([SubscriptionStatus.ACTIVE, SubscriptionStatus.PENDING]),
        )
    ).all()
    plans = db.scalars(
        select(Plan)
        .where(Plan.business_id == business.id, Plan.active.is_(True))
        .order_by(Plan.price_cents)
    ).all()
    mine = []
    for s in subs:
        plan = db.get(Plan, s.plan_id)
        assert plan is not None
        is_credit = plan.kind == PlanKind.CREDIT
        mine.append(
            {
                "id": str(s.id),
                "plan": plan.name,
                "kind": plan.kind.value,
                "status": s.status.value,
                "renews": s.renews,
                "period_end": s.period_end.isoformat() if s.period_end else None,
                "credits": None if is_credit else available(db, s.id),
                "balance_cents": balance.of_subscription(db, s.id) if is_credit else None,
            }
        )
    on_sale = get_settings().memberships_enabled and is_connected(db, business.id)
    return {
        "subscriptions": mine,
        "balance": balance.summary(db, business.id, customer.id),
        "balance_history": balance.history(db, business.id, customer.id, limit=5),
        "plans": [plan_terms(p) for p in plans] if on_sale else [],
    }


def staff_view(
    db: Session, business_id: uuid.UUID, customer_id: uuid.UUID
) -> dict[str, object] | None:
    try:
        sub = _usable(db, business_id, customer_id)
    except NotFound:
        return None
    plan = db.get(Plan, sub.plan_id)
    assert plan is not None
    return {"plan": plan.name, "credits": available(db, sub.id)}


# --- Daily job ----------------------------------------------------------------------


def daily(db: Session, business: Business, now: datetime | None = None) -> dict[str, int]:
    """End cancelled or lapsed periods and expire their credits; start renewals."""
    now = now or utcnow()
    ended = renewed = 0
    subs = db.scalars(
        select(Subscription)
        .where(
            Subscription.business_id == business.id,
            Subscription.status == SubscriptionStatus.ACTIVE,
            Subscription.period_end <= now,
        )
        .with_for_update(skip_locked=True)
    ).all()
    for sub in subs:
        plan = db.get(Plan, sub.plan_id)
        assert plan is not None
        if plan.kind == PlanKind.CREDIT:
            balance.expire(db, sub)
            sub.status = SubscriptionStatus.ENDED
            ended += 1
            continue
        left = available(db, sub.id)
        # Rolling over keeps at most one period's worth; visits are used oldest
        # first, so what carries is always the newest, and older ones expire.
        renewing = sub.renews and plan.active and bool(sub.provider_mandate_id)
        carry = min(left, plan.credits) if renewing and plan.unused_rule == "roll_one_period" else 0
        if left - carry > 0:
            _event(db, sub, CreditKind.EXPIRE, -(left - carry), f"expire:{sub.id}:{sub.period_end}")
        if sub.renews and plan.active and sub.provider_mandate_id:
            key = f"renew:{sub.id}:{sub.period_end}"
            if db.scalar(
                select(Payment.id).where(
                    Payment.subscription_id == sub.id, Payment.created_at >= sub.period_end
                )
            ):
                continue
            webhook, base = _urls(business)
            new = provider().create_payment(
                _access_token(db, business.id),
                amount_cents=plan.price_cents,
                description=f"{business.name}: {plan.name}",
                sequence="recurring",
                redirect_url=base,
                webhook_url=webhook,
                metadata={"subscription_id": str(sub.id), "renewal": key},
                customer_id=sub.provider_customer_id,
                mandate_id=sub.provider_mandate_id,
            )
            db.add(
                Payment(
                    business_id=business.id,
                    subscription_id=sub.id,
                    provider_payment_id=new.payment_id,
                    amount_cents=plan.price_cents,
                    status="open",
                    sequence="recurring",
                    created_at=now,
                )
            )
            renewed += 1
        else:
            sub.status = SubscriptionStatus.ENDED
            ended += 1
    return {"ended": ended, "renewals_started": renewed}
