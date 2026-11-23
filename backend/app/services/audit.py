from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditEntry


def record(
    db: Session,
    business_id: uuid.UUID,
    action: str,
    subject_type: str,
    subject_id: uuid.UUID | None = None,
    actor: uuid.UUID | None = None,
    **details: Any,
) -> None:
    db.add(
        AuditEntry(
            business_id=business_id,
            actor_staff_id=actor,
            action=action,
            subject_type=subject_type,
            subject_id=subject_id,
            details={k: str(v) for k, v in details.items()},
        )
    )
