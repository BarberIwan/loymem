"""A new business signs up and gets a working card in minutes.

Sign-up is closed unless LOYMEM_SIGNUP_CODE is set; the pilot hands that code to
the businesses it invites. The business row is created through one narrow
database function; everything else runs inside the new business's own scope.
"""

from __future__ import annotations

import hmac
import re
import unicodedata
import uuid

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import set_tenant
from app.models import Business, Program, Role, StaffMember
from app.security import hash_password
from app.services import DomainError, Forbidden, NotFound, audit
from app.services.cards import StaffContext


def slugify(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")
    return slug[:50] or "zaak"


def sign_up(
    db: Session, *, code: str, business_name: str, owner_name: str, email: str, password: str
) -> tuple[Business, StaffMember]:
    expected = get_settings().signup_code
    if not expected:
        raise NotFound("signup_closed")
    if not hmac.compare_digest(expected, code.strip()):
        raise Forbidden("signup_code_invalid")
    email = email.strip().lower()
    taken = db.execute(text("select 1 from loymem_staff_login(:e)"), {"e": email}).first()
    if taken:
        raise DomainError("email_in_use")
    base = slugify(business_name)
    slug = base
    for n in range(2, 100):
        if db.scalar(select(Business.id).where(Business.slug == slug)) is None:
            break
        slug = f"{base}-{n}"
    business_id: uuid.UUID = db.execute(
        text("select loymem_create_business(:s, :n)"), {"s": slug, "n": business_name.strip()[:120]}
    ).scalar_one()
    set_tenant(db, business_id)
    owner = StaffMember(
        business_id=business_id,
        name=owner_name.strip(),
        email=email,
        role=Role.OWNER,
        password_hash=hash_password(password),
    )
    db.add(owner)
    # A sensible start the owner can change in settings: ten visits, the tenth free.
    db.add(
        Program(
            business_id=business_id,
            name="Stempelkaart",
            stamps_required=10,
            reward_description="een gratis behandeling",
        )
    )
    db.flush()
    business = db.get(Business, business_id)
    assert business is not None
    audit.record(db, business_id, "business.signed_up", "business", business_id, owner.id)
    return business, owner


def set_staff_active(db: Session, ctx: StaffContext, staff_id: uuid.UUID, active: bool) -> None:
    if staff_id == ctx.staff.id:
        raise DomainError("cannot_change_self")
    member = db.scalar(
        select(StaffMember).where(
            StaffMember.id == staff_id, StaffMember.business_id == ctx.business.id
        )
    )
    if member is None:
        raise NotFound("staff_not_found")
    if member.role == Role.OWNER:
        raise Forbidden("one_owner")
    member.active = active
    audit.record(
        db,
        ctx.business.id,
        "staff.activated" if active else "staff.deactivated",
        "staff",
        member.id,
        ctx.staff.id,
    )
