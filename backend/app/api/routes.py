from __future__ import annotations

import hmac
import io
import json
import logging
import uuid
import zipfile
from collections.abc import Mapping
from datetime import UTC, datetime
from email.utils import format_datetime, parsedate_to_datetime
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    Header,
    HTTPException,
    Path,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel, EmailStr, Field, HttpUrl, field_validator, model_validator
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
from app.integrations import wallet
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
    utcnow,
)
from app.security import hash_password, issue_session, verify_password
from app.services import (
    DomainError,
    audit,
    balance,
    booking_mail,
    campaigns,
    cards,
    inbox,
    ledger,
    memberships,
    onboarding,
    owner,
    policies,
    refunds,
    slots,
    wallet_live,
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
        "wallet": {"apple": wallet.apple_configured(), "google": wallet.google_configured()},
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
        "balance": {
            **balance.summary(db, ctx.business.id, customer.id),
            "history": balance.history(db, ctx.business.id, customer.id, limit=3),
        },
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
    review_url: HttpUrl | None = None
    review_request_days: int | None = Field(default=None, ge=0, le=3650)
    program_name: str | None = Field(default=None, min_length=2, max_length=80)
    stamps_required: int | None = Field(default=None, ge=2, le=30)
    reward_description: str | None = Field(default=None, min_length=2, max_length=120)
    inbox_daily_limit: int | None = Field(default=None, ge=1, le=50)
    inbox_ignore_days: int | None = Field(default=None, ge=1, le=365)

    @field_validator("booking_url", "review_url")
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
        "review_url": b.review_url,
        "review_request_days": b.review_request_days,
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
    for field in ("inbox_daily_limit", "inbox_ignore_days", "review_request_days"):
        if field in changes:
            setattr(b, field, changes[field])
    for field in ("name", "brand_colour"):
        if field in changes:
            setattr(b, field, changes[field].upper() if field == "brand_colour" else changes[field])
    if "booking_url" in changes:
        b.booking_url = str(body.booking_url) if body.booking_url else None
    if "review_url" in changes:
        b.review_url = str(body.review_url) if body.review_url else None
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


def _mail_fields(data: Mapping[str, Any]) -> tuple[list[str], str, str, str, str]:
    """Recipients, sender, subject, html and text from the inbound mail services we
    accept: a plain JSON shape, Postmark's JSON, or Mailgun's form fields."""

    def first(*keys: str) -> str:
        for k in keys:
            v = data.get(k)
            if isinstance(v, str) and v:
                return v
        return ""

    to: list[str] = []
    for k in ("to", "To", "recipient", "OriginalRecipient"):
        v = data.get(k)
        if isinstance(v, str):
            to += [x for x in v.split(",") if x.strip()]
    for item in data.get("ToFull") or []:
        if isinstance(item, dict) and isinstance(item.get("Email"), str):
            to.append(item["Email"])
    return (
        to,
        first("from", "From", "sender"),
        first("subject", "Subject"),
        first("html", "HtmlBody", "body-html"),
        first("text", "TextBody", "body-plain"),
    )


@api.post("/hooks/mail")
async def inbound_mail(request: Request, db: Db, key: str = "") -> dict[str, str]:
    """Forwarded booking mails, delivered by the mail service. Always answers 200 for a
    mail we cannot place, so the service does not keep retrying it."""
    expected = get_settings().inbound_mail_key
    if not expected or not hmac.compare_digest(key, expected):
        raise HTTPException(status_code=403)
    body = await request.body()
    if len(body) > 512_000:
        raise DomainError("payload_too_large", 413)
    if request.headers.get("content-type", "").startswith("application/json"):
        try:
            data: Mapping[str, Any] = json.loads(body)
        except ValueError:
            return {"outcome": "invalid"}
    else:
        data = dict(await request.form())
    to, sender, subject, html, plain = _mail_fields(data)
    business_id = booking_mail.business_for_address(db, to)
    if business_id is None:
        return {"outcome": "unknown_address"}
    set_tenant(db, business_id)
    business = db.get(Business, business_id)
    assert business is not None
    return {"outcome": booking_mail.receive(db, business, sender, subject, html, plain)}


@api.get("/mail-inbox")
def mail_inbox_view(ctx: Owner, db: Db) -> dict[str, object]:
    return booking_mail.view(db, ctx)


@api.post("/mail-inbox")
def mail_inbox_setup(ctx: Owner, db: Db, rotate: bool = False) -> dict[str, object]:
    booking_mail.setup(db, ctx, rotate=rotate)
    return booking_mail.view(db, ctx)


class MailInboxIn(BaseModel):
    active: bool
    count_visits: bool


@api.patch("/mail-inbox")
def mail_inbox_update(body: MailInboxIn, ctx: Owner, db: Db) -> dict[str, object]:
    booking_mail.update(db, ctx, active=body.active, count_visits=body.count_visits)
    return booking_mail.view(db, ctx)


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


@api.get("/slots/freed")
def freed_slots(ctx: Manager, db: Db) -> list[dict[str, object]]:
    """Times that came free in the booking system (cancelled or moved), to offer."""
    return booking_mail.freed_slots(db, ctx.business.id, utcnow())


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
    credits: int = Field(default=0, ge=0, le=100)
    value_cents: int | None = Field(default=None, ge=100, le=200_000)
    validity_days: int | None = Field(default=None, ge=30, le=1095)
    cancel_notice_days: int = Field(default=0, ge=0, le=31)
    cooling_off_days: int = Field(default=14, ge=14, le=60)
    # Chosen from a fixed list (services/policies.py); the texts follow from them.
    unused_rule: str | None = Field(default=None, max_length=30)
    no_show_rule: str | None = Field(default=None, max_length=30)
    active: bool = True

    @model_validator(mode="after")
    def _kind_rules(self) -> PlanIn:
        if self.kind == PlanKind.CREDIT:
            if self.value_cents is None:
                raise ValueError("value_required")
            if not self.price_cents <= self.value_cents <= self.price_cents * 2:
                raise ValueError("value_between_price_and_double")
            if self.validity_days is None or self.validity_days < 365:
                raise ValueError("credit_valid_at_least_a_year")
            self.credits = 0
            self.unused_rule = self.no_show_rule = None
        else:
            if self.credits < 1:
                raise ValueError("credits_required")
            self.value_cents = None
            if self.kind != PlanKind.MEMBERSHIP:
                self.unused_rule = None
        policies.texts(self.kind, self.unused_rule, self.no_show_rule)  # raises on unknown
        return self

    def to_plan(self) -> dict[str, object]:
        data = self.model_dump()
        data.update(policies.texts(self.kind, self.unused_rule, self.no_show_rule))
        return data


@api.get("/plans")
def list_plans(ctx: Owner, db: Db) -> dict[str, object]:
    plans = db.scalars(
        select(Plan).where(Plan.business_id == ctx.business.id).order_by(Plan.created_at)
    ).all()
    return {
        "plans": [memberships.plan_terms(p) for p in plans],
        "connected": memberships.is_connected(db, ctx.business.id),
        "selling_enabled": get_settings().memberships_enabled,
        "policy_options": {
            "unused_membership": policies.UNUSED_MEMBERSHIP,
            "no_show": policies.NO_SHOW,
            "unused_bundle": policies.UNUSED_BUNDLE,
            "unused_credit": policies.UNUSED_CREDIT,
            "pause": policies.PAUSE,
            "refund": policies.REFUND,
        },
    }


@api.post("/plans", status_code=201)
def create_plan(body: PlanIn, ctx: Owner, db: Db) -> dict[str, object]:
    return memberships.plan_terms(memberships.save_plan(db, ctx, None, body.to_plan()))


@api.put("/plans/{plan_id}")
def update_plan(plan_id: uuid.UUID, body: PlanIn, ctx: Owner, db: Db) -> dict[str, object]:
    return memberships.plan_terms(memberships.save_plan(db, ctx, plan_id, body.to_plan()))


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


@api.get("/subscriptions")
def list_subscriptions(ctx: Owner, db: Db) -> list[dict[str, object]]:
    return refunds.overview(db, ctx)


class RefundIn(BaseModel):
    amount_cents: int = Field(ge=1, le=100_000)
    reason: str = Field(max_length=40)


@api.post("/subscriptions/{subscription_id}/refund")
def refund_subscription(
    subscription_id: uuid.UUID, body: RefundIn, ctx: Owner, db: Db
) -> dict[str, object]:
    return refunds.refund(db, ctx, subscription_id, body.amount_cents, body.reason)


class SpendIn(BaseModel):
    customer_id: uuid.UUID
    amount_cents: int = Field(ge=1, le=balance.MAX_SPEND_CENTS)
    request_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9-]+$")
    note: str | None = Field(default=None, max_length=200)


@api.post("/balance/spend")
def spend_balance(body: SpendIn, ctx: Staff, db: Db) -> dict[str, object]:
    return balance.spend(db, ctx, body.customer_id, body.amount_cents, body.request_id, body.note)


class UndoIn(BaseModel):
    customer_id: uuid.UUID
    request_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9-]+$")
    reason: str = Field(min_length=3, max_length=200)


@api.post("/balance/undo")
def undo_balance(body: UndoIn, ctx: Staff, db: Db) -> dict[str, object]:
    return balance.undo(db, ctx, body.customer_id, body.request_id, body.reason)


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


# --- Wallet passes ----------------------------------------------------------------


@api.get("/public/{slug}/card/{secret}/wallet/apple")
def apple_wallet(slug: str, secret: str, db: Db) -> Response:
    if not wallet.apple_configured():
        raise HTTPException(status_code=404, detail="wallet_not_available")
    b = business_by_slug(db, slug)
    customer = cards.customer_by_card(db, b, secret)
    data = wallet_live.pass_data(db, b, customer)
    wallet_live.remember(db, b, customer, data)
    return Response(
        wallet.apple_pass(data),
        media_type="application/vnd.apple.pkpass",
        headers={"Content-Disposition": f'attachment; filename="{b.slug}.pkpass"'},
    )


@api.get("/public/{slug}/card/{secret}/wallet/google")
def google_wallet(slug: str, secret: str, db: Db) -> dict[str, str]:
    if not wallet.google_configured():
        raise HTTPException(status_code=404, detail="wallet_not_available")
    b = business_by_slug(db, slug)
    customer = cards.customer_by_card(db, b, secret)
    data = wallet_live.pass_data(db, b, customer)
    wallet_live.remember(db, b, customer, data, google=True)
    return {"url": wallet.google_save_url(data, b.slug)}


# Apple's pass web service. Paths and status codes are Apple's; the phone calls
# these by itself. See docs/integrations.md.
APPLE = "/wallet/apple/v1"


def _apple_pass(
    db: Session, pass_type: str, serial: str, authorization: str | None
) -> tuple[Business, Customer]:
    if not wallet.apple_configured() or pass_type != get_settings().apple_pass_type_id:
        raise HTTPException(status_code=404)
    parsed = wallet_live.parse_serial(serial)
    if parsed is None:
        raise HTTPException(status_code=404)
    slug, customer_id = parsed
    if not wallet_live.token_ok(customer_id, authorization):
        raise HTTPException(status_code=401)
    b = business_by_slug(db, slug)
    customer = db.scalar(
        select(Customer).where(
            Customer.id == customer_id,
            Customer.business_id == b.id,
            Customer.anonymised_at.is_(None),
        )
    )
    if customer is None:
        raise HTTPException(status_code=401)
    return b, customer


class AppleRegistrationIn(BaseModel):
    pushToken: str = Field(min_length=8, max_length=200, pattern=r"^[A-Za-z0-9]+$")  # noqa: N815


DEVICE = Annotated[str, Path(min_length=4, max_length=64, pattern=r"^[A-Za-z0-9]+$")]


@api.post(APPLE + "/devices/{device}/registrations/{pass_type}/{serial}")
def apple_register(
    device: DEVICE,
    pass_type: str,
    serial: str,
    body: AppleRegistrationIn,
    db: Db,
    authorization: str | None = Header(default=None),
) -> Response:
    b, customer = _apple_pass(db, pass_type, serial, authorization)
    created = wallet_live.register(db, b, customer, device, body.pushToken)
    return Response(status_code=201 if created else 200)


@api.delete(APPLE + "/devices/{device}/registrations/{pass_type}/{serial}")
def apple_unregister(
    device: DEVICE,
    pass_type: str,
    serial: str,
    db: Db,
    authorization: str | None = Header(default=None),
) -> Response:
    b, customer = _apple_pass(db, pass_type, serial, authorization)
    wallet_live.unregister(db, b, customer, device)
    return Response(status_code=200)


@api.get(APPLE + "/devices/{device}/registrations/{pass_type}")
def apple_changed(
    device: DEVICE,
    pass_type: str,
    db: Db,
    passesUpdatedSince: str | None = None,  # noqa: N803
) -> Response:
    if not wallet.apple_configured() or pass_type != get_settings().apple_pass_type_id:
        raise HTTPException(status_code=404)
    since = None
    if passesUpdatedSince:
        try:
            since = datetime.fromisoformat(passesUpdatedSince)
        except ValueError:
            since = None
    rows = wallet_live.changed_serials(db, device, since)
    if not rows:
        return Response(status_code=204)
    last = max(changed for _, changed in rows)
    return JSONResponse({"serialNumbers": [s for s, _ in rows], "lastUpdated": last.isoformat()})


@api.get(APPLE + "/passes/{pass_type}/{serial}")
def apple_latest(
    pass_type: str,
    serial: str,
    db: Db,
    authorization: str | None = Header(default=None),
    if_modified_since: str | None = Header(default=None),
) -> Response:
    b, customer = _apple_pass(db, pass_type, serial, authorization)
    data = wallet_live.pass_data(db, b, customer)
    changed = wallet_live.remember(db, b, customer, data).astimezone(UTC).replace(microsecond=0)
    if if_modified_since:
        try:
            if parsedate_to_datetime(if_modified_since) >= changed:
                return Response(status_code=304)
        except (TypeError, ValueError):
            pass
    return Response(
        wallet.apple_pass(data),
        media_type="application/vnd.apple.pkpass",
        headers={"Last-Modified": format_datetime(changed, usegmt=True)},
    )


@api.post(APPLE + "/log")
async def apple_log(request: Request) -> Response:
    body = await request.body()
    logging.getLogger("wallet").warning("pass log: %r", body[:500])  # errors the phone reports
    return Response(status_code=200)


# --- New business and staff -----------------------------------------------------


class BusinessSignupIn(BaseModel):
    code: str = Field(min_length=4, max_length=100)
    business_name: str = Field(min_length=2, max_length=120)
    owner_name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=10, max_length=200)


@api.post("/business-signup", status_code=201)
def business_signup(body: BusinessSignupIn, response: Response, db: Db) -> dict[str, str]:
    business, owner = onboarding.sign_up(
        db,
        code=body.code,
        business_name=body.business_name,
        owner_name=body.owner_name,
        email=str(body.email),
        password=body.password,
    )
    response.set_cookie(
        SESSION_COOKIE,
        issue_session(owner.id, business.id),
        httponly=True,
        samesite="lax",
        secure=get_settings().secure_cookies,
        max_age=get_settings().session_hours * 3600,
        path="/",
    )
    return {"slug": business.slug}


class StaffActiveIn(BaseModel):
    active: bool


@api.patch("/staff/{staff_id}")
def update_staff(staff_id: uuid.UUID, body: StaffActiveIn, ctx: Owner, db: Db) -> dict[str, bool]:
    onboarding.set_staff_active(db, ctx, staff_id, body.active)
    return {"active": body.active}
