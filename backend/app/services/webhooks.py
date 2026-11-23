"""Generic webhook for completed appointments.

Any booking system that can send a signed HTTP call can report a finished visit,
without a native connector. The business decides where each field lives in the
JSON (``mapping``) and which status values mean "completed".

Rules:
- Only a status the business listed as completed counts. A calendar entry
  (booked, scheduled) or an unknown status never becomes a stamp.
- A visit gives at most one stamp per period, also when the same visit is
  reported twice or was already scanned at the counter (see cards.record_visit).
- An unknown customer is not created: signing up and consent stay with the
  customer. The call is logged as unmatched.
- Nothing personal is stored about the call itself.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from cryptography.fernet import Fernet
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Business, Customer, Service, WebhookConfig, WebhookDelivery, utcnow
from app.security import new_secret, normalise_email, normalise_phone
from app.services import DomainError, Forbidden, NotFound, audit
from app.services.cards import StaffContext, record_visit

MAX_SKEW_SECONDS = 300
MAX_AGE = timedelta(days=30)

DEFAULT_MAPPING: dict[str, Any] = {
    "appointment_id": "id",
    "status": "status",
    "completed_statuses": ["completed"],
    "customer_email": "customer.email",
    "customer_phone": "customer.phone",
    "service": "service",
    "ended_at": "ended_at",
}
PATH_FIELDS = (
    "appointment_id",
    "status",
    "customer_email",
    "customer_phone",
    "service",
    "ended_at",
)


def _fernet() -> Fernet:
    key = hashlib.sha256(b"webhook:" + get_settings().secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def validate_mapping(mapping: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for field in PATH_FIELDS:
        value = mapping.get(field, DEFAULT_MAPPING[field])
        if value is not None and (not isinstance(value, str) or not 0 < len(value) <= 120):
            raise DomainError("mapping_invalid")
        out[field] = value
    statuses = mapping.get("completed_statuses", DEFAULT_MAPPING["completed_statuses"])
    if (
        not isinstance(statuses, list)
        or not 1 <= len(statuses) <= 10
        or not all(isinstance(s, str) and s.strip() for s in statuses)
    ):
        raise DomainError("mapping_invalid")
    out["completed_statuses"] = [s.strip().lower() for s in statuses]
    if not out["appointment_id"] or not out["status"]:
        raise DomainError("mapping_invalid")
    if not out["customer_email"] and not out["customer_phone"]:
        raise DomainError("mapping_invalid")
    return out


def rotate_secret(db: Session, ctx: StaffContext) -> str:
    """Create or replace the secret. It is shown once; we cannot show it again."""
    secret = "whsec_" + new_secret(32)
    cfg = db.scalar(select(WebhookConfig).where(WebhookConfig.business_id == ctx.business.id))
    token = _fernet().encrypt(secret.encode()).decode()
    if cfg is None:
        db.add(
            WebhookConfig(
                business_id=ctx.business.id, secret_encrypted=token, mapping=dict(DEFAULT_MAPPING)
            )
        )
    else:
        cfg.secret_encrypted = token
    audit.record(
        db, ctx.business.id, "webhook.secret_rotated", "business", ctx.business.id, ctx.staff.id
    )
    return secret


def update(
    db: Session, ctx: StaffContext, mapping: dict[str, Any] | None, active: bool | None
) -> None:
    cfg = db.scalar(select(WebhookConfig).where(WebhookConfig.business_id == ctx.business.id))
    if cfg is None:
        raise NotFound("webhook_not_set_up")
    if mapping is not None:
        cfg.mapping = validate_mapping(mapping)
    if active is not None:
        cfg.active = active
    audit.record(db, ctx.business.id, "webhook.updated", "business", ctx.business.id, ctx.staff.id)


def view(db: Session, ctx: StaffContext) -> dict[str, object]:
    cfg = db.scalar(select(WebhookConfig).where(WebhookConfig.business_id == ctx.business.id))
    deliveries = db.scalars(
        select(WebhookDelivery)
        .where(WebhookDelivery.business_id == ctx.business.id)
        .order_by(WebhookDelivery.created_at.desc())
        .limit(20)
    ).all()
    return {
        "set_up": cfg is not None,
        "active": bool(cfg and cfg.active),
        "url": f"{get_settings().public_base_url}/api/v1/hooks/{ctx.business.slug}/appointments",
        "mapping": cfg.mapping if cfg else DEFAULT_MAPPING,
        "deliveries": [
            {
                "appointment_id": d.appointment_id,
                "outcome": d.outcome,
                "at": d.created_at.isoformat(),
            }
            for d in deliveries
        ],
    }


def sign(secret: str, timestamp: str, body: bytes) -> str:
    mac = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256)
    return "sha256=" + mac.hexdigest()


def _get(data: Any, path: str | None) -> Any:
    if not path:
        return None
    for part in path.split("."):
        if not isinstance(data, dict):
            return None
        data = data.get(part)
    return data


def _log(db: Session, business: Business, outcome: str, appointment_id: str | None) -> str:
    db.add(
        WebhookDelivery(
            business_id=business.id,
            outcome=outcome,
            appointment_id=(appointment_id or None) and appointment_id[:120],
        )
    )
    return outcome


def receive(
    db: Session, business: Business, body: bytes, timestamp: str | None, signature: str | None
) -> str:
    cfg = db.scalar(select(WebhookConfig).where(WebhookConfig.business_id == business.id))
    if cfg is None or not cfg.active:
        raise NotFound("webhook_not_active")
    secret = _fernet().decrypt(cfg.secret_encrypted.encode()).decode()
    try:
        skew = abs(time.time() - int(timestamp or ""))
    except ValueError:
        skew = MAX_SKEW_SECONDS + 1
    expected = sign(secret, timestamp or "", body)
    if skew > MAX_SKEW_SECONDS or not hmac.compare_digest(expected, signature or ""):
        # Not logged: an unsigned call may be anyone, and must not fill our tables.
        raise Forbidden("bad_signature")
    try:
        data = json.loads(body)
    except ValueError:
        return _log(db, business, "invalid", None)
    m = cfg.mapping
    appointment_id = _get(data, m.get("appointment_id"))
    appointment_id = str(appointment_id) if appointment_id is not None else None
    status = str(_get(data, m.get("status")) or "").strip().lower()
    if not appointment_id:
        return _log(db, business, "invalid", None)
    if status not in m.get("completed_statuses", []):
        return _log(db, business, "not_completion", appointment_id)

    now = utcnow()
    at = now
    raw_end = _get(data, m.get("ended_at"))
    if raw_end:
        try:
            at = datetime.fromisoformat(str(raw_end).replace("Z", "+00:00"))
            at = at if at.tzinfo else at.replace(tzinfo=UTC)
        except ValueError:
            return _log(db, business, "invalid", appointment_id)
    if at > now + timedelta(hours=1) or at < now - MAX_AGE:
        return _log(db, business, "out_of_range", appointment_id)

    email = normalise_email(str(_get(data, m.get("customer_email")) or ""))
    phone = normalise_phone(str(_get(data, m.get("customer_phone")) or ""))
    conds = [
        c
        for c in (
            Customer.email == email if email else None,
            Customer.phone == phone if phone else None,
        )
        if c is not None
    ]
    customer = None
    for cond in conds:
        customer = db.scalar(
            select(Customer).where(
                Customer.business_id == business.id, cond, Customer.anonymised_at.is_(None)
            )
        )
        if customer:
            break
    if customer is None:
        return _log(db, business, "unmatched", appointment_id)

    service_name = _get(data, m.get("service"))
    service_id = None
    if service_name:
        service_id = db.scalar(
            select(Service.id).where(
                Service.business_id == business.id,
                func.lower(Service.name) == str(service_name).strip().lower(),
            )
        )
    result = record_visit(db, business, customer, service_id, at=at)
    return _log(db, business, "stamped" if result["stamped"] else "duplicate", appointment_id)
