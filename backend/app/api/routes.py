from __future__ import annotations

import io
import uuid
import zipfile
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, Response, UploadFile
from fastapi.responses import RedirectResponse, StreamingResponse
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
    Customer,
    CustomerSource,
    InboxDecision,
    Plan,
    PlanKind,
    Program,
    Role,
    Service,
    SlotBenefit,
    SlotStatus,
    StaffMember,
)
from app.security import hash_password, issue_session, verify_password
from app.services import (
    DomainError,
    audit,
    campaigns,
    cards,
    inbox,
    ledger,
    memberships,
    owner,
    slots,
    webhooks,
)
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
        "has_email": bool(customer.email),
        "waitlist": slots.waitlist_view(db, customer),
        "memberships": memberships.customer_view(db, b, customer),
        "services": [
            {"id": str(s.id), "name": s.name}
            for s in db.scalars(
                select(Service)
                .where(Service.business_id == b.id, Service.active.is_(True))
                .order_by(Service.name)
            )
        ],
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
        "claimed_offer": slots.pending_claim(db, ctx, customer),
        "membership": memberships.staff_view(db, ctx.business.id, customer.id),
        "services": [{"id": str(s.id), "name": s.name} for s in services],
    }


class StampIn(BaseModel):
    customer_id: uuid.UUID
    service_id: uuid.UUID | None = None


@api.post("/stamps")
def add_stamp(body: StampIn, ctx: Staff, db: Db) -> dict[str, object]:
    result = cards.stamp(db, ctx, body.customer_id, body.service_id)
    customer = db.get(Customer, body.customer_id)
    assert customer is not None  # cards.stamp already checked business and existence
    result["applied_offer"] = slots.apply_claim(db, ctx, customer)
    if result["applied_offer"]:
        result["stamps"] = cards.card_view(db, ctx.business, customer)["stamps"]
    return result


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


@api.get("/inbox")
def get_inbox(ctx: Manager, db: Db) -> dict[str, object]:
    items = inbox.opportunities(db, ctx)
    return {
        "items": [o.as_dict(ctx.business.booking_url) for o in items],
        "daily_limit": ctx.business.inbox_daily_limit,
        "ignore_days": ctx.business.inbox_ignore_days,
    }


class InboxDecisionIn(BaseModel):
    customer_id: uuid.UUID
    kind: str = Field(max_length=40)
    decision: InboxDecision
    message: str | None = Field(default=None, max_length=600)


@api.post("/inbox/decide")
def decide_inbox(body: InboxDecisionIn, ctx: Manager, db: Db) -> dict[str, object]:
    return inbox.decide(db, ctx, body.customer_id, body.kind, body.decision, body.message)


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
    inbox_daily_limit: int | None = Field(default=None, ge=1, le=50)
    inbox_ignore_days: int | None = Field(default=None, ge=1, le=365)

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
        "inbox_daily_limit": b.inbox_daily_limit,
        "inbox_ignore_days": b.inbox_ignore_days,
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
    for field in ("inbox_daily_limit", "inbox_ignore_days"):
        if field in changes:
            setattr(b, field, changes[field])
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


# --- Booking systems: generic webhook ----------------------------------------


@api.post("/hooks/{slug}/appointments")
async def appointment_webhook(
    slug: str,
    request: Request,
    db: Db,
    x_loymem_timestamp: Annotated[str | None, Header()] = None,
    x_loymem_signature: Annotated[str | None, Header()] = None,
) -> dict[str, str]:
    body = await request.body()
    if len(body) > 64_000:
        raise DomainError("payload_too_large", 413)
    b = business_by_slug(db, slug)
    outcome = webhooks.receive(db, b, body, x_loymem_timestamp, x_loymem_signature)
    return {"outcome": outcome}


@api.get("/webhook")
def get_webhook(ctx: Owner, db: Db) -> dict[str, object]:
    return webhooks.view(db, ctx)


@api.post("/webhook/secret")
def rotate_webhook_secret(ctx: Owner, db: Db) -> dict[str, str]:
    return {"secret": webhooks.rotate_secret(db, ctx)}


class WebhookIn(BaseModel):
    mapping: dict[str, object] | None = None
    active: bool | None = None


@api.patch("/webhook")
def update_webhook(body: WebhookIn, ctx: Owner, db: Db) -> dict[str, object]:
    webhooks.update(db, ctx, body.mapping, body.active)
    return webhooks.view(db, ctx)


# --- Free slots ----------------------------------------------------------------


class WaitlistIn(BaseModel):
    service_id: uuid.UUID | None = None
    days_mask: int = Field(default=127, ge=1, le=127)
    dayparts_mask: int = Field(default=7, ge=1, le=7)
    min_notice_minutes: int = Field(default=60, ge=0, le=1440)
    email: EmailStr | None = None


@api.put("/public/{slug}/card/{secret}/waitlist")
def join_waitlist(slug: str, secret: str, body: WaitlistIn, db: Db) -> dict[str, object]:
    b = business_by_slug(db, slug)
    customer = cards.customer_by_card(db, b, secret)
    if not customer.email and body.email:
        customer.email = body.email.lower()
        db.flush()  # a taken address fails here as 409
    slots.join_waitlist(
        db,
        b,
        customer,
        service_id=body.service_id,
        days_mask=body.days_mask,
        dayparts_mask=body.dayparts_mask,
        min_notice_minutes=body.min_notice_minutes,
    )
    return {"waitlist": slots.waitlist_view(db, customer)}


@api.delete("/public/{slug}/card/{secret}/waitlist")
def leave_waitlist(slug: str, secret: str, db: Db) -> dict[str, object]:
    b = business_by_slug(db, slug)
    slots.leave_waitlist(db, b, cards.customer_by_card(db, b, secret))
    return {"waitlist": None}


@api.get("/public/{slug}/plek/{token}")
def slot_offer(slug: str, token: str, db: Db) -> dict[str, object]:
    b = business_by_slug(db, slug)
    return {"business": _public_business(b), **slots.offer_for_token(db, b, token)}


@api.post("/public/{slug}/plek/{token}/claim")
def claim_slot(slug: str, token: str, db: Db) -> dict[str, object]:
    b = business_by_slug(db, slug)
    return slots.claim(db, b, token)


class SlotIn(BaseModel):
    service_id: uuid.UUID | None = None
    staff_name: str | None = Field(default=None, max_length=80)
    starts_at: datetime
    book_by: datetime
    benefit: SlotBenefit
    benefit_value: int = Field(default=0, ge=0, le=50)
    benefit_text: str | None = Field(default=None, max_length=120)
    capacity: int = Field(default=1, ge=1, le=20)
    group_size: int = Field(default=3, ge=1, le=50)
    wait_minutes: int = Field(default=10, ge=1, le=240)


@api.get("/slots")
def list_slots(ctx: Manager, db: Db) -> list[dict[str, object]]:
    slots.send_due(db, ctx.business)
    return slots.list_offers(db, ctx)


@api.post("/slots", status_code=201)
def create_slot(body: SlotIn, ctx: Manager, db: Db) -> dict[str, str]:
    offer = slots.create_offer(db, ctx, slots.OfferInput(**body.model_dump()))
    return {"id": str(offer.id)}


@api.post("/slots/{offer_id}/send")
def send_slot(offer_id: uuid.UUID, ctx: Manager, db: Db) -> dict[str, int]:
    return {"sent": slots.start_sending(db, ctx, offer_id)}


class SkipIn(BaseModel):
    customer_id: uuid.UUID


@api.post("/slots/{offer_id}/skip")
def skip_slot_recipient(offer_id: uuid.UUID, body: SkipIn, ctx: Manager, db: Db) -> dict[str, bool]:
    slots.skip_recipient(db, ctx, offer_id, body.customer_id)
    return {"skipped": True}


class CloseIn(BaseModel):
    status: SlotStatus


@api.post("/slots/{offer_id}/close")
def close_slot(offer_id: uuid.UUID, body: CloseIn, ctx: Manager, db: Db) -> dict[str, str]:
    slots.close(db, ctx, offer_id, body.status)
    return {"status": body.status.value}


# --- Memberships and bundles --------------------------------------------------


class PlanIn(BaseModel):
    kind: PlanKind
    name: str = Field(min_length=2, max_length=80)
    price_cents: int = Field(ge=100, le=100_000)
    credits: int = Field(ge=1, le=100)
    validity_days: int | None = Field(default=None, ge=30, le=1095)
    cancel_notice_days: int = Field(default=0, ge=0, le=31)
    cooling_off_days: int = Field(default=14, ge=14, le=60)
    unused_policy: str = Field(min_length=10, max_length=600)
    no_show_policy: str = Field(min_length=10, max_length=600)
    pause_policy: str = Field(min_length=10, max_length=600)
    active: bool = True


@api.get("/plans")
def list_plans(ctx: Owner, db: Db) -> dict[str, object]:
    plans = db.scalars(
        select(Plan).where(Plan.business_id == ctx.business.id).order_by(Plan.created_at)
    ).all()
    return {
        "plans": [memberships.plan_terms(p) for p in plans],
        "connected": memberships.is_connected(db, ctx.business.id),
        "selling_enabled": get_settings().memberships_enabled,
    }


@api.post("/plans", status_code=201)
def create_plan(body: PlanIn, ctx: Owner, db: Db) -> dict[str, object]:
    return memberships.plan_terms(memberships.save_plan(db, ctx, None, body.model_dump()))


@api.put("/plans/{plan_id}")
def update_plan(plan_id: uuid.UUID, body: PlanIn, ctx: Owner, db: Db) -> dict[str, object]:
    return memberships.plan_terms(memberships.save_plan(db, ctx, plan_id, body.model_dump()))


def _redirect_uri() -> str:
    return f"{get_settings().public_base_url}/api/v1/payments/connect/callback"


@api.get("/payments/connect")
def payments_connect(ctx: Owner) -> dict[str, str]:
    return {"url": memberships.connect_url(ctx, _redirect_uri())}


@api.get("/payments/connect/callback")
def payments_callback(code: str, state: str, ctx: Owner, db: Db) -> RedirectResponse:
    if state != str(ctx.business.id):
        raise HTTPException(status_code=400, detail="state_mismatch")
    tokens = memberships.provider().exchange_code(code, _redirect_uri())
    memberships.store_tokens(db, ctx.business, tokens)
    audit.record(
        db, ctx.business.id, "payments.connected", "business", ctx.business.id, ctx.staff.id
    )
    return RedirectResponse("/abonnementen", status_code=303)


@api.post("/payments/{slug}/webhook")
async def payments_webhook(slug: str, request: Request, db: Db) -> dict[str, str]:
    form = await request.form()
    payment_id = str(form.get("id") or "")[:60]
    if not payment_id:
        raise HTTPException(status_code=400, detail="missing_id")
    b = business_by_slug(db, slug)
    return {"result": memberships.handle_webhook(db, b, payment_id)}


class BuyIn(BaseModel):
    terms_version: int


@api.post("/public/{slug}/card/{secret}/plans/{plan_id}/buy")
def buy_plan(slug: str, secret: str, plan_id: uuid.UUID, body: BuyIn, db: Db) -> dict[str, str]:
    b = business_by_slug(db, slug)
    customer = cards.customer_by_card(db, b, secret)
    url = memberships.start_purchase(
        db, b, customer, plan_id, body.terms_version, f"/k/{slug}/{secret}"
    )
    return {"checkout_url": url}


@api.post("/public/{slug}/card/{secret}/subscriptions/{subscription_id}/cancel")
def cancel_subscription(
    slug: str, secret: str, subscription_id: uuid.UUID, db: Db
) -> dict[str, object]:
    b = business_by_slug(db, slug)
    customer = cards.customer_by_card(db, b, secret)
    return memberships.cancel_online(db, b, customer, subscription_id)


class CreditUseIn(BaseModel):
    customer_id: uuid.UUID
    request_id: str = Field(min_length=8, max_length=64)


@api.post("/credits/use")
def use_credit(body: CreditUseIn, ctx: Staff, db: Db) -> dict[str, object]:
    return memberships.use_at_counter(db, ctx, body.customer_id, body.request_id)


# --- Campaigns ------------------------------------------------------------------


class CampaignIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    audience: str = Field(max_length=30)
    message: str = Field(min_length=10, max_length=600)
    holdout_percent: int = Field(default=10, ge=5, le=50)
    window_days: int = Field(default=30, ge=7, le=90)


@api.get("/campaigns")
def list_campaigns(ctx: Manager, db: Db) -> list[dict[str, object]]:
    return campaigns.list_campaigns(db, ctx)


@api.post("/campaigns", status_code=201)
def create_campaign(body: CampaignIn, ctx: Manager, db: Db) -> dict[str, str]:
    return {"id": str(campaigns.create(db, ctx, **body.model_dump()).id)}


@api.post("/campaigns/{campaign_id}/send")
def send_campaign(campaign_id: uuid.UUID, ctx: Manager, db: Db) -> dict[str, int]:
    return {"sent": campaigns.send(db, ctx, campaign_id)}


@api.get("/campaigns/{campaign_id}/report")
def campaign_report(campaign_id: uuid.UUID, ctx: Manager, db: Db) -> dict[str, object]:
    return campaigns.report(db, ctx, campaign_id)


@api.post("/public/{slug}/afmelden/{token}")
def unsubscribe(slug: str, token: str, db: Db) -> dict[str, str]:
    from app.services.mailer import unsubscribe as do_unsubscribe

    b = business_by_slug(db, slug)
    return {"purpose": do_unsubscribe(db, b, token).value}
