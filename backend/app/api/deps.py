from __future__ import annotations

from collections.abc import Callable

from fastapi import Cookie, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db, set_tenant
from app.models import Business, Role, StaffMember
from app.security import read_session
from app.services.cards import StaffContext

SESSION_COOKIE = "loymem_session"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def csrf_guard(request: Request, x_loymem: str | None = Header(default=None)) -> None:
    """A form on another site cannot set a custom header; a fetch from ours does."""
    if request.method not in SAFE_METHODS and x_loymem != "1":
        raise HTTPException(status_code=403, detail="missing_header")


def business_by_slug(db: Session, slug: str) -> Business:
    business = db.scalar(select(Business).where(Business.slug == slug))
    if business is None:
        raise HTTPException(status_code=404, detail="business_not_found")
    set_tenant(db, business.id)
    return business


def current_staff(
    db: Session = Depends(get_db),
    session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> StaffContext:
    parsed = read_session(session) if session else None
    if parsed is None:
        raise HTTPException(status_code=401, detail="not_signed_in")
    staff_id, business_id = parsed
    set_tenant(db, business_id)
    staff = db.scalar(
        select(StaffMember).where(
            StaffMember.id == staff_id,
            StaffMember.business_id == business_id,
            StaffMember.active.is_(True),
        )
    )
    business = db.get(Business, business_id)
    if staff is None or business is None:
        raise HTTPException(status_code=401, detail="not_signed_in")
    return StaffContext(staff=staff, business=business)


def require_roles(*roles: Role) -> Callable[[StaffContext], StaffContext]:
    def check(ctx: StaffContext = Depends(current_staff)) -> StaffContext:
        if ctx.staff.role not in roles:
            raise HTTPException(status_code=403, detail="role_not_allowed")
        return ctx

    return check


any_staff = require_roles(Role.OWNER, Role.MANAGER, Role.STAFF)
manager = require_roles(Role.OWNER, Role.MANAGER)
owner_only = require_roles(Role.OWNER)
