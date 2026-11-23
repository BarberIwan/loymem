"""Who is due for a visit.

Without a booking integration we only know registered visits (stamps). So the
honest wording is "no visit registered since ...", never "has no appointment".
The return period of the last service decides; a personal rhythm is only
suggested once a customer has three registered visits.
"""

from __future__ import annotations

import statistics
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from app.models import Customer, CustomerProgram, LedgerEvent, LedgerKind, Service, utcnow

MIN_VISITS_FOR_RHYTHM = 3


@dataclass(frozen=True)
class VisitStatus:
    customer_id: uuid.UUID
    last_visit: datetime
    visits: int
    service_name: str | None
    return_period_days: int | None
    personal_rhythm_days: int | None
    days_since: int

    @property
    def due(self) -> bool:
        return self.return_period_days is not None and self.days_since >= self.return_period_days


def visit_statuses(
    db: Session, business_id: uuid.UUID, now: datetime | None = None
) -> list[VisitStatus]:
    now = now or utcnow()
    reversal = aliased(LedgerEvent)
    rows = db.execute(
        select(CustomerProgram.customer_id, LedgerEvent.created_at, LedgerEvent.service_id)
        .join(CustomerProgram, CustomerProgram.id == LedgerEvent.customer_program_id)
        .join(Customer, Customer.id == CustomerProgram.customer_id)
        .outerjoin(reversal, reversal.reverses_id == LedgerEvent.id)
        .where(
            LedgerEvent.business_id == business_id,
            LedgerEvent.kind == LedgerKind.STAMP,
            reversal.id.is_(None),
            Customer.anonymised_at.is_(None),
        )
        .order_by(CustomerProgram.customer_id, LedgerEvent.created_at)
    ).all()
    services = {
        s.id: s for s in db.scalars(select(Service).where(Service.business_id == business_id))
    }
    visits: dict[uuid.UUID, list[tuple[datetime, uuid.UUID | None]]] = defaultdict(list)
    for customer_id, at, service_id in rows:
        visits[customer_id].append((at, service_id))

    out: list[VisitStatus] = []
    for customer_id, items in visits.items():
        last_at, last_service = items[-1]
        service = services.get(last_service) if last_service else None
        rhythm = None
        if len(items) >= MIN_VISITS_FOR_RHYTHM:
            gaps = [(b[0] - a[0]).days for a, b in zip(items, items[1:], strict=False)]
            rhythm = max(1, round(statistics.median(gaps)))
        out.append(
            VisitStatus(
                customer_id=customer_id,
                last_visit=last_at,
                visits=len(items),
                service_name=service.name if service else None,
                return_period_days=service.return_period_days if service else None,
                personal_rhythm_days=rhythm,
                days_since=(now - last_at).days,
            )
        )
    return out
