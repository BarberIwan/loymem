from __future__ import annotations

import io
import uuid
import zipfile
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, EmailStr, Field, HttpUrl, field_validator
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.api.deps import (
    SESSION_COOKIE,
    any_staff,
    business_by_slug,
    current_staff,
    manager,
    owner_only,
)
from app.config import get_settings
from app.db import get_db, set_tenant
from app.models import (
    Business,
    ConsentPurpose,
    CustomerSource,
    Program,
    Role,
    Service,
    StaffMember,
)
from app.security import hash_password, issue_session, verify_password
from app.services import DomainError, audit, cards, ledger, owner
from app.services.brand import card_palette
from app.services.cards import StaffContext, scan_token_for
from app.services.rhythm import visit_statuses

api = APIRouter(prefix="/api/v1")
Db = Annotated[Session, Depends(get_db)]
Staff = Annotated[StaffContext, Depends(any_staff)]
Manager = Annotated[StaffContext, Depends(manager)]
Owner = Annotated[StaffContext, Depends(owner_only)]

HEX = r"^#[0-9A-Fa-f]{6}$"


# --- Public: sign up and the card --------------------------------------------


def _public_business(b: Business) -> dict[str, object]:
    return {
        "name": b.name,
        "slug": b.slug,
        "booking_url": b.booking_url,
        "palette": card_palette(b.brand_colour),
    }


@api.get("/public/{slug}")
def public_business(slug: str, db: Db) -> dict[str, object]:
    b = business_by_slug(db, slug)
    program = cards.active_program(db, b.id)
    return {
        **_public_business(b),
        "program": {
            "name": program.name,
            "stamps_required": program.stamps_required,
            "reward": program.reward_description,
        },
    }


class SignupIn(BaseModel):
    first_name: str = Field(min_length=1, max_length=60)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=20)
    birthday_day: int | None = Field(default=None, ge=1, le=31)
    birthday_month: int | None = Field(default=None, ge=1, le=12)
    marketing_consent: bool = False


@api.post("/public/{slug}/signup", status_code=201)
def signup(slug: str, body: SignupIn, db: Db) -> dict[str, str]:
    b = business_by_slug(db, slug)
    birthday = (
        (body.birthday_day, body.birthday_month)
        if body.birthday_day and body.birthday_month
        else None
    )
    issued = cards.create_customer(
        db,
        b,
        first_name=body.first_name,
        email=body.email,
        phone=body.phone,
        source=CustomerSource.SIGNUP,
        birthday=birthday,
        marketing_consent=body.marketing_consent,
    )
    return {"card_url": f"/k/{b.slug}/{issued.card_secret}"}


@api.get("/public/{slug}/card/{secret}")
def card(slug: str, secret: str, db: Db) -> dict[str, object]:
    b = business_by_slug(db, slug)
    customer = cards.customer_by_card(db, b, secret)
    return {
        "business": _public_business(b),
        **cards.card_view(db, b, customer),
        "scan_token": scan_token_for(customer),
        "marketing": owner.has_consent(db, customer.id, ConsentPurpose.MARKETING),
    }


class RewardCodeIn(BaseModel):
    reward_id: uuid.UUID


@api.post("/public/{slug}/card/{secret}/reward-code")
def reward_code(slug: str, secret: str, body: RewardCodeIn, db: Db) -> dict[str, object]:
    b = business_by_slug(db, slug)
    customer = cards.customer_by_card(db, b, secret)
    code, seconds = cards.issue_reward_code(db, b, customer, body.reward_id)
    return {"code": code, "valid_seconds": seconds}


class ConsentIn(BaseModel):
    marketing: bool


@api.put("/public/{slug}/card/{secret}/consent")
def card_consent(slug: str, secret: str, body: ConsentIn, db: Db) -> dict[str, bool]:
    b = business_by_slug(db, slug)
    customer = cards.customer_by_card(db, b, secret)
    owner.set_consent(db, customer, ConsentPurpose.MARKETING, body.marketing, "card")
    return {"marketing": body.marketing}


class ReissueIn(BaseModel):
    contact: str = Field(min_length=5, max_length=254)


@api.post("/public/{slug}/reissue", status_code=202)
def reissue(slug: str, body: ReissueIn, db: Db) -> dict[str, bool]:
    b = business_by_slug(db, slug)
    cards.request_reissue(db, b, body.contact)
    return {"accepted": True}


@api.post("/public/{slug}/reissue/{token}")
def reissue_complete(slug: str, token: str, db: Db) -> dict[str, str]:
    b = business_by_slug(db, slug)
    return {"card_url": f"/k/{b.slug}/{cards.complete_reissue(db, b, token)}"}


# --- Staff sign-in ------------------------------------------------------------


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


@api.post("/auth/login")
def login(body: LoginIn, response: Response, db: Db) -> dict[str, str]:
    row = (
        db.execute(text("select * from loymem_staff_login(:e)"), {"e": body.email.lower()})
        .mappings()
        .first()
    )
    ok = verify_password(row["password_hash"] if row else None, body.password)
    if not row or not ok or not row["active"]:
        raise HTTPException(status_code=401, detail="login_failed")
    set_tenant(db, row["business_id"])
    audit.record(db, row["business_id"], "staff.login", "staff", row["staff_id"], row["staff_id"])
    response.set_cookie(
        SESSION_COOKIE,
        issue_session(row["staff_id"], row["business_id"]),
        httponly=True,
        samesite="lax",
        secure=get_settings().secure_cookies,
        max_age=get_settings().session_hours * 3600,
        path="/",
    )
    return {"role": row["role"]}


@api.post("/auth/logout")
def logout(response: Response) -> dict[str, bool]:
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@api.get("/me")
def me(ctx: Annotated[StaffContext, Depends(current_staff)]) -> dict[str, object]:
    b = ctx.business
    return {
        "name": ctx.staff.name,
        "role": ctx.staff.role.value,
        "business": {"name": b.name, "slug": b.slug, "palette": card_palette(b.brand_colour)},
    }


# --- Staff: scan, stamp, redeem ---------------------------------------------


class ScanIn(BaseModel):
    scan_token: str = Field(min_length=10, max_length=64)


@api.post("/scan")
def scan(body: ScanIn, ctx: Staff, db: Db) -> dict[str, object]:
    customer = cards.customer_by_scan(db, ctx, body.scan_token)
    services = db.scalars(
        select(Service)
        .where(Service.business_id == ctx.business.id, Service.active.is_(True))
        .order_by(Service.name)
    )
    return {
        **cards.scan_summary(db, ctx, customer),
        "services": [{"id": str(s.id), "name": s.name} for s in services],
    }


class StampIn(BaseModel):
    customer_id: uuid.UUID
    service_id: uuid.UUID | None = None


@api.post("/stamps")
def add_stamp(body: StampIn, ctx: Staff, db: Db) -> dict[str, object]:
    return cards.stamp(db, ctx, body.customer_id, body.service_id)


class RedeemIn(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")


@api.post("/redeem")
def redeem(body: RedeemIn, ctx: Staff, db: Db) -> dict[str, object]:
    return cards.redeem(db, ctx, body.code)


# --- Owner and manager ------------------------------------------------------


@api.get("/overview")
def overview(ctx: Manager, db: Db) -> dict[str, object]:
    return {**owner.overview(db, ctx), "recent": owner.recent_events(db, ctx, 30)}


class ReverseIn(BaseModel):
    reason: str = Field(min_length=3, max_length=300)


@api.post("/events/{event_id}/reverse")
def reverse(event_id: uuid.UUID, body: ReverseIn, ctx: Manager, db: Db) -> dict[str, str]:
    new_id = ledger.reverse(db, ctx.business.id, event_id, ctx.staff.id, body.reason)
    audit.record(
        db,
        ctx.business.id,
        "ledger.reversed",
        "ledger_event",
        event_id,
        ctx.staff.id,
        reason=body.reason,
    )
    return {"reversal_id": str(new_id)}


@api.get("/due")
def due(ctx: Manager, db: Db) -> list[dict[str, object]]:
    return [
        {
            "customer_id": str(s.customer_id),
            "last_visit": s.last_visit.isoformat(),
            "days_since": s.days_since,
            "service": s.service_name,
            "return_period_days": s.return_period_days,
            "personal_rhythm_days": s.personal_rhythm_days,
            "visits": s.visits,
        }
        for s in visit_statuses(db, ctx.business.id)
        if s.due
    ]


@api.post("/customers/import")
async def import_customers(
    ctx: Manager, db: Db, file: Annotated[UploadFile, File()]
) -> dict[str, int]:
    data = await file.read(2_000_001)
    if len(data) > 2_000_000:
        raise DomainError("csv_too_large")
    return owner.import_customers(db, ctx, data)


@api.get("/export")
def export(ctx: Owner, db: Db) -> StreamingResponse:
    files = owner.export_csv(db, ctx)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in files.items():
            z.writestr(name, content)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="loymem-{ctx.business.slug}.zip"'},
    )


@api.delete("/customers/{customer_id}", status_code=204)
def anonymise(customer_id: uuid.UUID, ctx: Owner, db: Db) -> Response:
    owner.anonymise(db, ctx, customer_id)
    return Response(status_code=204)


class SettingsIn(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    brand_colour: str | None = Field(default=None, pattern=HEX)
    booking_url: HttpUrl | None = None
    program_name: str | None = Field(default=None, min_length=2, max_length=80)
    stamps_required: int | None = Field(default=None, ge=2, le=30)
    reward_description: str | None = Field(default=None, min_length=2, max_length=120)

    @field_validator("booking_url")
    @classmethod
    def https_only(cls, v: HttpUrl | None) -> HttpUrl | None:
        if v is not None and v.scheme != "https":
            raise ValueError("https_only")
        return v


@api.get("/settings")
def get_settings_route(ctx: Manager, db: Db) -> dict[str, object]:
    b = ctx.business
    p = cards.active_program(db, b.id)
    services = db.scalars(
        select(Service).where(Service.business_id == b.id).order_by(Service.name)
    ).all()
    return {
        "name": b.name,
        "slug": b.slug,
        "brand_colour": b.brand_colour,
        "booking_url": b.booking_url,
        "palette": card_palette(b.brand_colour),
        "program_name": p.name,
        "stamps_required": p.stamps_required,
        "reward_description": p.reward_description,
        "signup_url": f"{get_settings().public_base_url}/aanmelden/{b.slug}",
        "services": [
            {
                "id": str(s.id),
                "name": s.name,
                "return_period_days": s.return_period_days,
                "active": s.active,
            }
            for s in services
        ],
    }


@api.patch("/settings")
def update_settings(body: SettingsIn, ctx: Owner, db: Db) -> dict[str, object]:
    b = db.get(Business, ctx.business.id)
    assert b is not None
    p = db.get(Program, cards.active_program(db, b.id).id)
    assert p is not None
    changes = body.model_dump(exclude_unset=True)
    for field in ("name", "brand_colour"):
        if field in changes:
            setattr(b, field, changes[field].upper() if field == "brand_colour" else changes[field])
    if "booking_url" in changes:
        b.booking_url = str(body.booking_url) if body.booking_url else None
    if "program_name" in changes:
        p.name = changes["program_name"]
    if "stamps_required" in changes:
        p.stamps_required = changes["stamps_required"]
    if "reward_description" in changes:
        p.reward_description = changes["reward_description"]
    audit.record(
        db,
        b.id,
        "settings.updated",
        "business",
        b.id,
        ctx.staff.id,
        fields=",".join(sorted(changes)),
    )
    db.flush()
    return get_settings_route(StaffContext(ctx.staff, b), db)


class ServiceIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    return_period_days: int = Field(ge=1, le=730)


@api.post("/services", status_code=201)
def add_service(body: ServiceIn, ctx: Owner, db: Db) -> dict[str, str]:
    s = Service(
        business_id=ctx.business.id,
        name=body.name.strip(),
        return_period_days=body.return_period_days,
    )
    db.add(s)
    db.flush()
    audit.record(db, ctx.business.id, "service.added", "service", s.id, ctx.staff.id)
    return {"id": str(s.id)}


@api.patch("/services/{service_id}")
def update_service(service_id: uuid.UUID, body: ServiceIn, ctx: Owner, db: Db) -> dict[str, str]:
    s = db.scalar(
        select(Service).where(Service.id == service_id, Service.business_id == ctx.business.id)
    )
    if s is None:
        raise HTTPException(status_code=404, detail="service_not_found")
    s.name, s.return_period_days = body.name.strip(), body.return_period_days
    audit.record(db, ctx.business.id, "service.updated", "service", s.id, ctx.staff.id)
    return {"id": str(s.id)}


class StaffIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=20)
    role: Role
    password: str = Field(min_length=10, max_length=200)


@api.get("/staff")
def list_staff(ctx: Owner, db: Db) -> list[dict[str, object]]:
    rows = db.scalars(
        select(StaffMember)
        .where(StaffMember.business_id == ctx.business.id)
        .order_by(StaffMember.created_at)
    )
    return [
        {
            "id": str(s.id),
            "name": s.name,
            "email": s.email,
            "role": s.role.value,
            "active": s.active,
        }
        for s in rows
    ]


@api.post("/staff", status_code=201)
def add_staff(body: StaffIn, ctx: Owner, db: Db) -> dict[str, str]:
    if body.role == Role.OWNER:
        raise HTTPException(status_code=403, detail="one_owner")
    s = StaffMember(
        business_id=ctx.business.id,
        name=body.name,
        email=body.email.lower(),
        phone=body.phone,
        role=body.role,
        password_hash=hash_password(body.password),
    )
    db.add(s)
    db.flush()
    audit.record(
        db, ctx.business.id, "staff.added", "staff", s.id, ctx.staff.id, role=body.role.value
    )
    return {"id": str(s.id)}
