"""Tests run against PostgreSQL: row level security, unique constraints and
concurrency are the point, and SQLite has none of them.

The app connects as ``loymem_app`` (no BYPASSRLS); seeding and cleanup use the
owner role, the way a migration would.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

BASE = os.environ.get("LOYMEM_TEST_DB_HOST", "localhost:5433")
APP_URL = f"postgresql+psycopg://loymem_app:loymem_app@{BASE}/loymem_test"
OWNER_URL = f"postgresql+psycopg://loymem_owner:loymem_owner@{BASE}/loymem_test"
os.environ["LOYMEM_DATABASE_URL"] = APP_URL
os.environ["LOYMEM_SECRET_KEY"] = "toets-" + "x" * 40
os.environ.setdefault("LOYMEM_MIGRATION_URL", OWNER_URL)

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import reset_engine, session_factory, set_tenant  # noqa: E402
from app.integrations.payments import FakeProvider  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    TENANT_TABLES,
    Business,
    Program,
    Role,
    Service,
    StaffMember,
)
from app.security import hash_password  # noqa: E402

PASSWORD = "een-lang-wachtwoord"
_HASH = hash_password(PASSWORD)
owner_engine = create_engine(OWNER_URL)


@pytest.fixture(scope="session", autouse=True)
def _schema() -> Iterator[None]:
    root = Path(__file__).resolve().parents[1]
    for step in (["downgrade", "base"], ["upgrade", "head"]):
        subprocess.run(["alembic", *step], cwd=root, check=True, capture_output=True)
    yield
    reset_engine()


@pytest.fixture(autouse=True)
def _clean() -> Iterator[None]:
    yield
    with owner_engine.begin() as c:
        c.execute(text(f"truncate {', '.join(TENANT_TABLES)}, businesses cascade"))


@dataclass
class Shop:
    business: Business
    owner: StaffMember
    manager: StaffMember
    staff: StaffMember
    program: Program
    cut: Service
    beard: Service


def make_shop(slug: str, colour: str = "#1F4A38") -> Shop:
    with Session(owner_engine, expire_on_commit=False) as db, db.begin():
        b = Business(
            id=uuid.uuid4(),
            slug=slug,
            name=slug.replace("-", " ").title(),
            brand_colour=colour,
            booking_url="https://example.org/boeken",
        )
        db.add(b)
        db.flush()

        def person(role: Role, name: str) -> StaffMember:
            s = StaffMember(
                business_id=b.id,
                name=name,
                email=f"{name}@{slug}.example",
                phone=None,
                role=role,
                password_hash=_HASH,
            )
            db.add(s)
            return s

        shop = Shop(
            business=b,
            owner=person(Role.OWNER, "eigenaar"),
            manager=person(Role.MANAGER, "manager"),
            staff=person(Role.STAFF, "medewerker"),
            program=Program(
                business_id=b.id,
                name="Stempelkaart",
                stamps_required=5,
                reward_description="Gratis knipbeurt",
            ),
            cut=Service(business_id=b.id, name="Knippen", return_period_days=28),
            beard=Service(business_id=b.id, name="Baard", return_period_days=14),
        )
        db.add_all([shop.program, shop.cut, shop.beard])
        db.flush()
    return shop


@pytest.fixture
def shop() -> Shop:
    return make_shop("barber-iwan")


@pytest.fixture
def other_shop() -> Shop:
    return make_shop("salon-elders", "#F2D16B")


class Api(TestClient):
    def login(self, person: StaffMember) -> Api:
        r = self.post("/api/v1/auth/login", json={"email": person.email, "password": PASSWORD})
        assert r.status_code == 200, r.text
        return self


def client() -> Api:
    return Api(app, headers={"X-Loymem": "1"})


@pytest.fixture
def api() -> Api:
    return client()


@pytest.fixture
def new_client():  # type: ignore[no-untyped-def]
    return client


def app_session(business_id: uuid.UUID) -> Session:
    db = session_factory()()
    db.begin()
    set_tenant(db, business_id)
    return db


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kw: float) -> None:
        self.now += timedelta(**kw)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    c = Clock()
    for mod in (
        "app.services.cards",
        "app.services.ledger",
        "app.services.owner",
        "app.services.inbox",
        "app.services.slots",
        "app.services.campaigns",
        "app.services.balance",
    ):
        monkeypatch.setattr(f"{mod}.utcnow", c)
    return c


def signup(api: Api, slug: str, **kw: object) -> str:
    body = {"first_name": "Sam", "phone": "06 12345678", **kw}
    r = api.post(f"/api/v1/public/{slug}/signup", json=body)
    assert r.status_code == 201, r.text
    return str(r.json()["card_url"]).rsplit("/", 1)[-1]


def card(api: Api, slug: str, secret: str) -> dict:  # type: ignore[type-arg]
    r = api.get(f"/api/v1/public/{slug}/card/{secret}")
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


def scan(api: Api, token: str) -> dict:  # type: ignore[type-arg]
    r = api.post("/api/v1/scan", json={"scan_token": token})
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeProvider]:
    """A payment provider that pays when told to; selling switched on."""
    from app.config import get_settings
    from app.services import memberships

    p = FakeProvider()
    memberships.set_provider(p)
    monkeypatch.setattr(get_settings(), "memberships_enabled", True)
    yield p
    memberships.set_provider(None)


def _cert() -> tuple[bytes, bytes, rsa.RSAPrivateKey]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "toets")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(1)
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    return (
        cert.public_bytes(serialization.Encoding.PEM),
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
        key,
    )


@pytest.fixture
def wallet_keys(monkeypatch: pytest.MonkeyPatch) -> rsa.RSAPrivateKey:
    s = get_settings()
    cert, key, raw = _cert()
    wwdr, _, _ = _cert()
    b64 = lambda v: base64.b64encode(v).decode()  # noqa: E731
    account = {"client_email": "pas@toets.example", "private_key": key.decode()}
    for name, value in {
        "wallet_enabled": True,
        "apple_pass_type_id": "pass.example.toets",
        "apple_team_id": "TEAM123456",
        "apple_pass_cert_pem_b64": b64(cert),
        "apple_pass_key_pem_b64": b64(key),
        "apple_wwdr_pem_b64": b64(wwdr),
        "google_wallet_issuer_id": "3388000000000000000",
        "google_wallet_service_account_b64": b64(json.dumps(account).encode()),
    }.items():
        monkeypatch.setattr(s, name, value)
    return raw
