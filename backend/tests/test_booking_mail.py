"""Appointments from forwarded Salonized mails.

The fixtures follow the exact layout of real Salonized mails (November 2026)
with invented customer data.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.integrations import salonized_mail
from app.main import app
from app.models import Appointment, Business, Customer, LedgerEvent
from app.services import booking_mail
from tests.conftest import Api, Clock, Shop, app_session, signup

FIX = Path(__file__).parent / "fixtures" / "salonized"
AMS = ZoneInfo("Europe/Amsterdam")
NEW = ("Nieuwe online afspraak bij Barber Iwan", (FIX / "nieuw.html").read_text())
MOVED = ("Afspraak online verplaatst", (FIX / "verplaatst.html").read_text())
CANCEL = ("Afspraak geannuleerd", (FIX / "geannuleerd.html").read_text())
KEY = "inkomende-sleutel"


@pytest.fixture(autouse=True)
def inbound(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "inbound_mail_domain", "in.example.nl")
    monkeypatch.setattr(get_settings(), "inbound_mail_key", KEY)


def address(owner: Api) -> str:
    r = owner.post("/api/v1/mail-inbox")
    assert r.status_code == 200, r.text
    return str(r.json()["address"])


def deliver(
    to: str, mail: tuple[str, str], sender: str = "Salonized <noreply@salonized.com>"
) -> str:
    r = TestClient(app).post(
        f"/api/v1/hooks/mail?key={KEY}",
        json={"to": to, "from": sender, "subject": mail[0], "html": mail[1]},
    )
    assert r.status_code == 200, r.text
    return str(r.json()["outcome"])


def appointments(shop: Shop) -> list[Appointment]:
    db = app_session(shop.business.id)
    rows = db.query(Appointment).order_by(Appointment.starts_at).all()
    db.expunge_all()
    db.close()
    return rows


def test_parser_reads_all_three_mails() -> None:
    new = salonized_mail.parse(*NEW)
    assert new is not None
    assert (new.kind, new.external_id, new.email, new.phone, new.staff) == (
        "booked", "100000001", "daan@example.nl", "+31600000001", "Iwan",
    )  # fmt: skip
    assert new.starts_at == datetime(2026, 11, 27, 12, 0, tzinfo=AMS)
    assert new.ends_at == datetime(2026, 11, 27, 12, 30, tzinfo=AMS)
    assert new.service and new.service.startswith("Haircut / Fade")
    moved = salonized_mail.parse(*MOVED)
    assert moved is not None and moved.previous_starts_at == new.starts_at
    assert moved.starts_at == datetime(2026, 11, 28, 11, 30, tzinfo=AMS)
    cancel = salonized_mail.parse(*CANCEL)
    assert cancel is not None
    assert (cancel.kind, cancel.name, cancel.email) == ("cancelled", "Daan Voorbeeld", None)
    assert salonized_mail.parse("Je factuur", NEW[1]) is None


def test_booking_links_an_existing_customer_and_nobody_else(
    api: Api, shop: Shop, new_client
) -> None:  # type: ignore[no-untyped-def]
    to = address(new_client().login(shop.owner))
    assert deliver(to, NEW) == "no_customer"  # not a customer: nothing personal kept
    [a] = appointments(shop)
    assert a.customer_id is None and a.name_hash and a.external_id == "100000001"
    signup(api, shop.business.slug, email="daan@example.nl", phone="06 00000001")
    assert deliver(to, NEW) == "matched"  # the same mail again: same appointment, now linked
    [a] = appointments(shop)
    assert a.customer_id is not None


def test_move_frees_the_old_time_and_cancel_closes_the_new_one(
    api: Api, shop: Shop, new_client, clock: Clock
) -> None:  # type: ignore[no-untyped-def]
    owner = new_client().login(shop.owner)
    to = address(owner)
    deliver(to, NEW)
    deliver(to, MOVED)
    rows = appointments(shop)
    assert [(r.status, r.starts_at.astimezone(AMS).hour) for r in rows] == [
        ("cancelled", 12), ("booked", 11),
    ]  # fmt: skip
    assert deliver(to, CANCEL) == "matched"
    assert {r.status for r in appointments(shop)} == {"cancelled"}
    clock.now = datetime(2026, 11, 25, 9, 0, tzinfo=AMS)
    freed = owner.get("/api/v1/slots/freed").json()
    assert [datetime.fromisoformat(f["starts_at"]).astimezone(AMS).hour for f in freed] == [12, 11]


def test_customers_with_a_booking_are_not_reminded(
    api: Api, shop: Shop, new_client, clock: Clock
) -> None:  # type: ignore[no-untyped-def]
    signup(api, shop.business.slug, email="daan@example.nl")
    clock.now = datetime(2026, 11, 20, 9, 0, tzinfo=AMS)
    db = app_session(shop.business.id)
    c = db.query(Customer).filter(Customer.email == "daan@example.nl").one()
    assert booking_mail.upcoming_customer_ids(db, shop.business.id, clock.now) == set()
    db.close()
    deliver(address(new_client().login(shop.owner)), NEW)
    db = app_session(shop.business.id)
    assert booking_mail.upcoming_customer_ids(db, shop.business.id, clock.now) == {c.id}
    db.close()


def test_counting_visits_is_off_by_default_and_once_when_on(
    api: Api, shop: Shop, new_client, clock: Clock
) -> None:  # type: ignore[no-untyped-def]
    signup(api, shop.business.slug, email="daan@example.nl")
    owner = new_client().login(shop.owner)
    deliver(address(owner), NEW)
    after = datetime(2026, 11, 27, 13, 5, tzinfo=AMS)

    def run() -> int:
        db = app_session(shop.business.id)
        b = db.get(Business, shop.business.id)
        assert b is not None
        n = booking_mail.record_visits(db, b, now=after)
        db.commit()
        db.close()
        return n

    assert run() == 0
    owner.patch("/api/v1/mail-inbox", json={"active": True, "count_visits": True})
    assert run() == 1
    assert run() == 0
    db = app_session(shop.business.id)
    assert db.query(LedgerEvent).filter(LedgerEvent.kind == "stamp").count() == 1
    db.close()


def test_cancelled_appointment_is_never_a_visit(api: Api, shop: Shop, new_client) -> None:  # type: ignore[no-untyped-def]
    signup(api, shop.business.slug, email="daan@example.nl")
    owner = new_client().login(shop.owner)
    to = address(owner)
    owner.patch("/api/v1/mail-inbox", json={"active": True, "count_visits": True})
    deliver(to, MOVED)
    deliver(to, CANCEL)
    db = app_session(shop.business.id)
    b = db.get(Business, shop.business.id)
    assert booking_mail.record_visits(db, b, now=datetime(2026, 11, 28, 13, 0, tzinfo=AMS)) == 0  # type: ignore[arg-type]
    db.close()


def test_only_salonized_mail_and_the_right_key_count(
    shop: Shop, other_shop: Shop, new_client
) -> None:  # type: ignore[no-untyped-def]
    to = address(new_client().login(shop.owner))
    assert deliver(to, NEW, sender="Iemand <noreply@salonized.com.example.org>") == "ignored"
    assert deliver(to, NEW, sender="aanval@example.org") == "ignored"
    assert deliver("onbekend.abc@in.example.nl", NEW) == "unknown_address"
    bad = TestClient(app).post("/api/v1/hooks/mail?key=fout", json={"to": to})
    assert bad.status_code == 403
    assert appointments(shop) == [] and appointments(other_shop) == []


def test_new_address_retires_the_old_one(shop: Shop, new_client) -> None:  # type: ignore[no-untyped-def]
    owner = new_client().login(shop.owner)
    old = address(owner)
    new = owner.post("/api/v1/mail-inbox?rotate=true").json()["address"]
    assert new != old
    assert deliver(old, NEW) == "unknown_address"
    assert deliver(new, NEW) == "no_customer"


def test_gmail_confirmation_code_is_shown_to_the_owner(shop: Shop, new_client) -> None:  # type: ignore[no-untyped-def]
    owner = new_client().login(shop.owner)
    to = address(owner)
    mail = ("(#123) Gmail Forwarding Confirmation", "<p>Confirmation code: 712345678</p>")
    assert deliver(to, mail, sender="forwarding-noreply@google.com") == "code_saved"
    assert owner.get("/api/v1/mail-inbox").json()["gmail_code"] == "712345678"


def test_staff_and_manager_cannot_see_the_address(shop: Shop, new_client) -> None:  # type: ignore[no-untyped-def]
    for person in (shop.staff, shop.manager):
        assert new_client().login(person).get("/api/v1/mail-inbox").status_code == 403


def test_mailgun_form_fields_are_accepted(shop: Shop, new_client) -> None:  # type: ignore[no-untyped-def]
    to = address(new_client().login(shop.owner))
    r = TestClient(app).post(
        f"/api/v1/hooks/mail?key={KEY}",
        data={"recipient": to, "sender": "noreply@salonized.com", "subject": NEW[0],
              "body-html": NEW[1]},
    )  # fmt: skip
    assert r.json()["outcome"] == "no_customer"
    assert appointments(shop)[0].starts_at - timedelta(0) == datetime(
        2026, 11, 27, 12, 0, tzinfo=AMS
    )
