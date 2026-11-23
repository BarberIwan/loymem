"""Everything only an owner or manager can do."""

from __future__ import annotations

import csv
import io
import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    ConsentPurpose,
    ConsentRecord,
    ConsentStatus,
    Customer,
    CustomerProgram,
    CustomerSource,
    LedgerEvent,
    LedgerKind,
    Reward,
    RewardStatus,
    StaffMember,
    utcnow,
)
from app.services import Conflict, DomainError, audit, ledger
from app.services.cards import StaffContext, create_customer
from app.services.rhythm import visit_statuses

MAX_IMPORT_ROWS = 5000


def import_customers(db: Session, ctx: StaffContext, data: bytes) -> dict[str, int]:
    """CSV with first_name, email, phone. Never records marketing consent."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DomainError("csv_not_utf8") from exc
    sample = text[:2048]
    dialect = csv.Sniffer().sniff(sample, delimiters=",;") if sample else csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    fields = {(f or "").strip().lower() for f in reader.fieldnames or []}
    if not fields & {"email", "phone", "telefoon", "e-mail"}:
        raise DomainError("csv_needs_email_or_phone")
    added = skipped = 0
    for i, row in enumerate(reader):
        if i >= MAX_IMPORT_ROWS:
            raise DomainError("csv_too_long")
        r = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        try:
            create_customer(
                db,
                ctx.business,
                first_name=r.get("first_name") or r.get("voornaam"),
                email=r.get("email") or r.get("e-mail"),
                phone=r.get("phone") or r.get("telefoon"),
                source=CustomerSource.IMPORT,
            )
            added += 1
        except (Conflict, DomainError):
            skipped += 1
    audit.record(
        db,
        ctx.business.id,
        "customers.imported",
        "business",
        ctx.business.id,
        ctx.staff.id,
        added=added,
        skipped=skipped,
    )
    return {"added": added, "skipped": skipped}


def export_csv(db: Session, ctx: StaffContext) -> dict[str, str]:
    """Everything a business takes with it: all customers and the full ledger."""
    customers = db.scalars(
        select(Customer)
        .where(Customer.business_id == ctx.business.id)
        .order_by(Customer.created_at)
    ).all()
    c_out = io.StringIO()
    w = csv.writer(c_out)
    w.writerow(
        ["customer_id", "first_name", "email", "phone", "source", "created_at", "anonymised_at"]
    )
    for c in customers:
        w.writerow(
            [
                c.id,
                c.first_name or "",
                c.email or "",
                c.phone or "",
                c.source.value,
                c.created_at.isoformat(),
                c.anonymised_at.isoformat() if c.anonymised_at else "",
            ]
        )
    events = db.execute(
        select(LedgerEvent, CustomerProgram.customer_id)
        .join(CustomerProgram, CustomerProgram.id == LedgerEvent.customer_program_id)
        .where(LedgerEvent.business_id == ctx.business.id)
        .order_by(LedgerEvent.created_at)
    ).all()
    l_out = io.StringIO()
    w = csv.writer(l_out)
    w.writerow(
        [
            "event_id",
            "customer_id",
            "kind",
            "delta",
            "staff_id",
            "reverses_id",
            "reason",
            "created_at",
        ]
    )
    for ev, customer_id in events:
        w.writerow(
            [
                ev.id,
                customer_id,
                ev.kind.value,
                ev.delta,
                ev.staff_id or "",
                ev.reverses_id or "",
                ev.reason or "",
                ev.created_at.isoformat(),
            ]
        )
    audit.record(
        db,
        ctx.business.id,
        "export.downloaded",
        "business",
        ctx.business.id,
        ctx.staff.id,
        customers=len(customers),
        events=len(events),
    )
    return {"customers.csv": c_out.getvalue(), "ledger.csv": l_out.getvalue()}


def anonymise(db: Session, ctx: StaffContext, customer_id: uuid.UUID) -> None:
    c = db.scalar(
        select(Customer).where(Customer.id == customer_id, Customer.business_id == ctx.business.id)
    )
    if c is None or c.anonymised_at:
        return
    c.first_name = c.email = c.phone = None
    c.birthday_day = c.birthday_month = None
    c.anonymised_at = utcnow()
    audit.record(db, ctx.business.id, "customer.anonymised", "customer", c.id, ctx.staff.id)


def set_consent(
    db: Session, customer: Customer, purpose: ConsentPurpose, granted: bool, source: str
) -> None:
    db.add(
        ConsentRecord(
            business_id=customer.business_id,
            customer_id=customer.id,
            purpose=purpose,
            status=ConsentStatus.GRANTED if granted else ConsentStatus.WITHDRAWN,
            source=source,
        )
    )


def has_consent(db: Session, customer_id: uuid.UUID, purpose: ConsentPurpose) -> bool:
    latest = db.scalar(
        select(ConsentRecord.status)
        .where(ConsentRecord.customer_id == customer_id, ConsentRecord.purpose == purpose)
        .order_by(ConsentRecord.created_at.desc())
        .limit(1)
    )
    return latest == ConsentStatus.GRANTED


def overview(db: Session, ctx: StaffContext) -> dict[str, object]:
    bid = ctx.business.id
    since = utcnow() - timedelta(days=30)

    def count(stmt: object) -> int:
        return int(db.scalar(stmt) or 0)  # type: ignore[call-overload]

    customers = count(
        select(func.count())
        .select_from(Customer)
        .where(Customer.business_id == bid, Customer.anonymised_at.is_(None))
    )
    new_30 = count(
        select(func.count())
        .select_from(Customer)
        .where(Customer.business_id == bid, Customer.created_at >= since)
    )
    stamps_30 = count(
        select(func.count())
        .select_from(LedgerEvent)
        .where(
            LedgerEvent.business_id == bid,
            LedgerEvent.kind == LedgerKind.STAMP,
            LedgerEvent.created_at >= since,
        )
    )
    redeemed_30 = count(
        select(func.count())
        .select_from(Reward)
        .where(
            Reward.business_id == bid,
            Reward.status == RewardStatus.REDEEMED,
            Reward.redeemed_at >= since,
        )
    )
    open_rewards = count(
        select(func.count())
        .select_from(Reward)
        .where(Reward.business_id == bid, Reward.status == RewardStatus.AVAILABLE)
    )
    corrections_30 = count(
        select(func.count())
        .select_from(LedgerEvent)
        .where(
            LedgerEvent.business_id == bid,
            LedgerEvent.kind == LedgerKind.REVERSAL,
            LedgerEvent.created_at >= since,
        )
    )

    names = {
        sid: name
        for sid, name in db.execute(
            select(StaffMember.id, StaffMember.name).where(StaffMember.business_id == bid)
        )
    }
    limit = get_settings().unusual_stamps_per_hour
    signals: list[dict[str, object]] = [
        {"kind": "many_stamps_one_staff", "staff": names.get(sid, ""), "count": n}
        for sid, n in ledger.stamps_by_staff_last_hour(db, bid)
        if n >= limit
    ]
    if corrections_30 >= 10:
        signals.append({"kind": "many_corrections", "count": corrections_30})
    if ledger.balance_mismatches(db, bid):
        signals.append({"kind": "balance_mismatch"})

    statuses = visit_statuses(db, bid)
    return {
        "customers": customers,
        "new_customers_30d": new_30,
        "stamps_30d": stamps_30,
        "rewards_redeemed_30d": redeemed_30,
        "rewards_open": open_rewards,
        "corrections_30d": corrections_30,
        "due_for_visit": sum(1 for s in statuses if s.due),
        "signals": signals,
    }


def recent_events(db: Session, ctx: StaffContext, limit: int = 50) -> list[dict[str, object]]:
    rows = db.execute(
        select(LedgerEvent, Customer.first_name, StaffMember.name)
        .join(CustomerProgram, CustomerProgram.id == LedgerEvent.customer_program_id)
        .join(Customer, Customer.id == CustomerProgram.customer_id)
        .outerjoin(StaffMember, StaffMember.id == LedgerEvent.staff_id)
        .where(LedgerEvent.business_id == ctx.business.id)
        .order_by(LedgerEvent.created_at.desc())
        .limit(limit)
    ).all()
    reversed_ids = set(
        db.scalars(
            select(LedgerEvent.reverses_id).where(
                LedgerEvent.business_id == ctx.business.id, LedgerEvent.reverses_id.is_not(None)
            )
        )
    )
    return [
        {
            "id": str(ev.id),
            "kind": ev.kind.value,
            "delta": ev.delta,
            "customer": first or "",
            "staff": staff or "",
            "reason": ev.reason,
            "at": ev.created_at.isoformat(),
            "reversible": ev.kind in (LedgerKind.STAMP, LedgerKind.REWARD_EARNED)
            and ev.id not in reversed_ids,
        }
        for ev, first, staff in rows
    ]
