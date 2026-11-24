"""Keeping wallet passes current.

The pass shows stamps and, when there is one, the prepaid balance. We remember
a digest of what each pass last showed; a regular round compares it with the
card as it is now and, where it differs, tells the phones (Apple) or patches the
saved object (Google). A phone then fetches the new pass from us.

Serial number: ``<business slug>.<customer id>``. The token a phone uses to talk
to us about a pass is derived from the server key and the customer id: never the
card secret, which must not leave the customer's own link.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import datetime

from sqlalchemy import delete, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config import get_settings
from app.integrations import wallet
from app.models import Business, Customer, WalletPass, WalletRegistration, utcnow
from app.services import balance, cards
from app.services.brand import card_palette
from app.services.cards import scan_token_for


def serial_for(business: Business, customer: Customer) -> str:
    return f"{business.slug}.{customer.id}"


def parse_serial(serial: str) -> tuple[str, uuid.UUID] | None:
    slug, _, raw = serial.rpartition(".")
    try:
        return slug, uuid.UUID(raw)
    except ValueError:
        return None


def auth_token(customer_id: uuid.UUID) -> str:
    key = get_settings().secret_key.encode()
    return hmac.new(key, f"wallet:{customer_id}".encode(), hashlib.sha256).hexdigest()[:40]


def token_ok(customer_id: uuid.UUID, header: str | None) -> bool:
    given = (header or "").removeprefix("ApplePass ").strip()
    return bool(given) and hmac.compare_digest(given, auth_token(customer_id))


def _money(cents: int) -> str:
    whole, rest = divmod(cents, 100)
    return f"€ {whole:,}".replace(",", ".") + f",{rest:02d}"


def pass_data(db: Session, business: Business, customer: Customer) -> wallet.PassData:
    view = cards.card_view(db, business, customer)
    program = view["program"]
    assert isinstance(program, dict)
    palette = card_palette(business.brand_colour)
    cents = int(str(balance.summary(db, business.id, customer.id)["cents"]))
    return wallet.PassData(
        serial=serial_for(business, customer),
        business_name=business.name,
        program_name=str(program["name"]),
        first_name=customer.first_name,
        stamps=int(str(view["stamps"])),
        stamps_required=int(program["stamps_required"]),
        reward=str(program["reward"]),
        scan_token=scan_token_for(customer),
        background=palette["background"],
        foreground=palette["text"],
        link_url=business.booking_url,
        balance=_money(cents) if cents > 0 else None,
        web_service_url=f"{get_settings().public_base_url}/api/v1/wallet/apple",
        auth_token=auth_token(customer.id),
    )


def _digest(data: wallet.PassData) -> str:
    return hashlib.sha256(json.dumps(data.shown(), sort_keys=True).encode()).hexdigest()


def remember(
    db: Session, business: Business, customer: Customer, data: wallet.PassData, google: bool = False
) -> datetime:
    """Record what the pass shows now. Returns when its content last changed."""
    now = utcnow()
    digest = _digest(data)
    stmt = insert(WalletPass).values(
        id=uuid.uuid4(),
        business_id=business.id,
        customer_id=customer.id,
        digest=digest,
        changed_at=now,
        google_issued=google,
        created_at=now,
    )
    db.execute(
        stmt.on_conflict_do_update(
            index_elements=["customer_id"],
            set_={
                "changed_at": text(
                    "case when wallet_passes.digest = excluded.digest "
                    "then wallet_passes.changed_at else excluded.changed_at end"
                ),
                "digest": stmt.excluded.digest,
                "google_issued": text("wallet_passes.google_issued or excluded.google_issued"),
            },
        )
    )
    changed = db.scalar(select(WalletPass.changed_at).where(WalletPass.customer_id == customer.id))
    assert changed is not None
    return changed


def register(
    db: Session, business: Business, customer: Customer, device_id: str, push_token: str
) -> bool:
    """A phone added the pass. Returns True the first time."""
    stmt = insert(WalletRegistration).values(
        id=uuid.uuid4(),
        business_id=business.id,
        customer_id=customer.id,
        device_id=device_id,
        push_token=push_token,
        created_at=utcnow(),
    )
    created = db.execute(
        stmt.on_conflict_do_nothing(constraint="uq_wallet_device_pass").returning(
            WalletRegistration.id
        )
    ).scalar_one_or_none()
    if created is None:
        db.execute(
            update(WalletRegistration)
            .where(
                WalletRegistration.device_id == device_id,
                WalletRegistration.customer_id == customer.id,
            )
            .values(push_token=push_token)
        )
        return False
    remember(db, business, customer, pass_data(db, business, customer))
    return True


def unregister(db: Session, business: Business, customer: Customer, device_id: str) -> None:
    db.execute(
        delete(WalletRegistration).where(
            WalletRegistration.business_id == business.id,
            WalletRegistration.customer_id == customer.id,
            WalletRegistration.device_id == device_id,
        )
    )


def changed_serials(
    db: Session, device_id: str, since: datetime | None
) -> list[tuple[str, datetime]]:
    rows = db.execute(
        text("select serial, changed_at from loymem_wallet_serials(:d, :s)"),
        {"d": device_id, "s": since},
    ).all()
    return [(str(r[0]), r[1]) for r in rows]


def refresh(db: Session, business: Business) -> dict[str, int]:
    """Compare every pass with the card now; tell phones and Google what changed."""
    apple_tokens: list[str] = []
    google: list[wallet.PassData] = []
    changed = 0
    for wp in db.scalars(select(WalletPass).where(WalletPass.business_id == business.id)).all():
        customer = db.get(Customer, wp.customer_id)
        if customer is None or customer.anonymised_at is not None:
            continue
        data = pass_data(db, business, customer)
        digest = _digest(data)
        if digest == wp.digest:
            continue
        wp.digest = digest
        wp.changed_at = utcnow()
        changed += 1
        apple_tokens += list(
            db.scalars(
                select(WalletRegistration.push_token).where(
                    WalletRegistration.customer_id == customer.id
                )
            )
        )
        if wp.google_issued:
            google.append(data)
    pushed = gone = patched = 0
    if apple_tokens and wallet.apple_configured():
        dead = wallet.apns_push(apple_tokens)
        pushed, gone = len(apple_tokens) - len(dead), len(dead)
        if dead:
            db.execute(
                delete(WalletRegistration).where(
                    WalletRegistration.business_id == business.id,
                    WalletRegistration.push_token.in_(dead),
                )
            )
    if google and wallet.google_configured():
        patched = wallet.google_update(google)
    return {"changed": changed, "pushed": pushed, "gone": gone, "patched": patched}
