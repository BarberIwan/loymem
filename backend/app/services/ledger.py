"""The ledger is the truth.

Writes go through ``append``: one INSERT with ``ON CONFLICT (idempotency_key) DO
NOTHING``. When the row already exists nothing changes and the caller gets
``None``, so duplicate scans, retries and simultaneous requests leave one row.
The balance is updated in the same transaction and only when the insert won.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import (
    Business,
    CustomerProgram,
    LedgerEvent,
    LedgerKind,
    Program,
    Reward,
    RewardStatus,
    utcnow,
)
from app.services import Conflict, Forbidden, NotFound


def append(
    db: Session,
    cp: CustomerProgram,
    kind: LedgerKind,
    delta: int,
    key: str,
    *,
    staff_id: uuid.UUID | None = None,
    service_id: uuid.UUID | None = None,
    reward_id: uuid.UUID | None = None,
    reverses_id: uuid.UUID | None = None,
    reason: str | None = None,
    at: datetime | None = None,
) -> uuid.UUID | None:
    event_id = uuid.uuid4()
    stmt = (
        insert(LedgerEvent)
        .values(
            id=event_id,
            business_id=cp.business_id,
            customer_program_id=cp.id,
            kind=kind,
            delta=delta,
            idempotency_key=key,
            staff_id=staff_id,
            service_id=service_id,
            reward_id=reward_id,
            reverses_id=reverses_id,
            reason=reason,
            created_at=at or utcnow(),
        )
        .on_conflict_do_nothing()
        .returning(LedgerEvent.id)
    )
    inserted = db.execute(stmt).scalar_one_or_none()
    if inserted is None:
        return None
    if delta:
        db.execute(
            update(CustomerProgram)
            .where(CustomerProgram.id == cp.id)
            .values(balance=CustomerProgram.balance + delta)
        )
        db.refresh(cp, ["balance"])
    return inserted


def period_bucket(program: Program, business: Business, at: datetime) -> str:
    if program.stamp_period_hours == 0:
        return at.astimezone(ZoneInfo(business.timezone)).date().isoformat()
    block = int(at.timestamp()) // (program.stamp_period_hours * 3600)
    return f"h{program.stamp_period_hours}-{block}"


def ledger_sum(db: Session, cp_id: uuid.UUID) -> int:
    total = db.scalar(
        select(func.coalesce(func.sum(LedgerEvent.delta), 0)).where(
            LedgerEvent.customer_program_id == cp_id
        )
    )
    return int(total or 0)


def recompute_balance(db: Session, cp_id: uuid.UUID) -> int:
    total = ledger_sum(db, cp_id)
    db.execute(update(CustomerProgram).where(CustomerProgram.id == cp_id).values(balance=total))
    return total


def balance_mismatches(db: Session, business_id: uuid.UUID) -> list[uuid.UUID]:
    sums = (
        select(LedgerEvent.customer_program_id, func.sum(LedgerEvent.delta).label("s"))
        .where(LedgerEvent.business_id == business_id)
        .group_by(LedgerEvent.customer_program_id)
        .subquery()
    )
    rows = db.execute(
        select(CustomerProgram.id)
        .outerjoin(sums, sums.c.customer_program_id == CustomerProgram.id)
        .where(CustomerProgram.business_id == business_id)
        .where(CustomerProgram.balance != func.coalesce(sums.c.s, 0))
    )
    return [r[0] for r in rows]


def convert_to_rewards(
    db: Session, cp: CustomerProgram, program: Program, trigger_event: uuid.UUID
) -> list[Reward]:
    """Turn every full card into a reward. Keyed on the triggering event."""
    made: list[Reward] = []
    n = 0
    while cp.balance >= program.stamps_required:
        reward = Reward(
            id=uuid.uuid4(),
            business_id=cp.business_id,
            customer_program_id=cp.id,
            description=program.reward_description,
            earned_at=utcnow(),
        )
        key = f"earn:{trigger_event}:{n}"
        if (
            append(
                db, cp, LedgerKind.REWARD_EARNED, -program.stamps_required, key, reward_id=reward.id
            )
            is None
        ):
            break
        db.add(reward)
        db.flush()
        made.append(reward)
        n += 1
    return made


def reverse(
    db: Session, business_id: uuid.UUID, event_id: uuid.UUID, actor: uuid.UUID, reason: str
) -> uuid.UUID:
    """Correct an event with its exact opposite. Each event can be reversed once."""
    reason = reason.strip()
    if len(reason) < 3:
        raise Conflict("reason_required")
    ev = db.scalar(
        select(LedgerEvent).where(
            LedgerEvent.id == event_id, LedgerEvent.business_id == business_id
        )
    )  # no row lock: the app may not update ledger rows; the card lock below serialises
    if ev is None:
        raise NotFound("event_not_found")
    if ev.kind == LedgerKind.REVERSAL:
        raise Conflict("cannot_reverse_reversal")
    cp = db.get(CustomerProgram, ev.customer_program_id, with_for_update=True)
    assert cp is not None
    if ev.kind == LedgerKind.REWARD_EARNED and ev.reward_id is not None:
        voided = db.execute(
            update(Reward)
            .where(Reward.id == ev.reward_id, Reward.status == RewardStatus.AVAILABLE)
            .values(status=RewardStatus.VOIDED)
            .returning(Reward.id)
        ).scalar_one_or_none()
        if voided is None:
            raise Conflict("reward_already_used")
    if ev.kind == LedgerKind.REWARD_REDEEMED:
        raise Forbidden("redemption_cannot_be_reversed")
    if cp.balance - ev.delta < 0:
        raise Conflict("balance_would_go_negative")
    new_id = append(
        db,
        cp,
        LedgerKind.REVERSAL,
        -ev.delta,
        f"reverse:{ev.id}",
        staff_id=actor,
        reverses_id=ev.id,
        reason=reason,
        reward_id=ev.reward_id,
    )
    if new_id is None:
        raise Conflict("already_reversed")
    return new_id


def stamps_by_staff_last_hour(db: Session, business_id: uuid.UUID) -> list[tuple[uuid.UUID, int]]:
    since = utcnow() - timedelta(hours=1)
    rows = db.execute(
        select(LedgerEvent.staff_id, func.count())
        .where(
            LedgerEvent.business_id == business_id,
            LedgerEvent.kind == LedgerKind.STAMP,
            LedgerEvent.created_at >= since,
            LedgerEvent.staff_id.is_not(None),
        )
        .group_by(LedgerEvent.staff_id)
    )
    return [(r[0], int(r[1])) for r in rows if r[0] is not None]
