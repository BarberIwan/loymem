"""Generic webhook for completed appointments (§6)."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.models import LedgerEvent, LedgerKind
from app.services.webhooks import sign
from tests.conftest import Api, Shop, app_session, card, scan, signup


def setup_hook(owner: Api) -> str:
    r = owner.post("/api/v1/webhook/secret")
    assert r.status_code == 200, r.text
    return str(r.json()["secret"])


def send(
    api: Api, slug: str, secret: str | None, payload: object, ts: int | None = None
) -> tuple[int, str]:
    body = json.dumps(payload).encode()
    stamp = str(ts or int(time.time()))
    headers = {"Content-Type": "application/json", "X-Loymem-Timestamp": stamp}
    if secret:
        headers["X-Loymem-Signature"] = sign(secret, stamp, body)
    # A booking system does not send our browser header.
    from fastapi.testclient import TestClient

    from app.main import app

    r = TestClient(app).post(f"/api/v1/hooks/{slug}/appointments", content=body, headers=headers)
    return r.status_code, r.json().get("outcome") or r.json().get("detail")


def appointment(**kw: object) -> dict:  # type: ignore[type-arg]
    return {
        "id": "a-1",
        "status": "completed",
        "customer": {"phone": "06 12345678"},
        "service": "knippen",
        "ended_at": datetime.now(UTC).isoformat(),
        **kw,
    }


def stamps(shop: Shop) -> int:
    db = app_session(shop.business.id)
    n = db.scalar(
        select(func.count()).select_from(LedgerEvent).where(LedgerEvent.kind == LedgerKind.STAMP)
    )
    db.close()
    return int(n or 0)


def test_generic_webhook_completion_single_ledger_event(api: Api, shop: Shop, new_client) -> None:  # type: ignore[no-untyped-def]
    secret_card = signup(api, shop.business.slug)
    secret = setup_hook(new_client().login(shop.owner))
    slug = shop.business.slug
    assert send(api, slug, secret, appointment()) == (200, "stamped")
    assert send(api, slug, secret, appointment()) == (200, "duplicate")
    # The same visit scanned at the counter adds nothing either.
    api.login(shop.staff)
    cid = scan(api, card(api, slug, secret_card)["scan_token"])["customer_id"]
    assert api.post("/api/v1/stamps", json={"customer_id": cid}).json()["stamped"] is False
    assert stamps(shop) == 1
    db = app_session(shop.business.id)
    svc = db.scalar(select(LedgerEvent.service_id))
    db.close()
    assert svc == shop.cut.id  # matched "knippen" to "Knippen"


def test_calendar_item_is_not_completion(api: Api, shop: Shop, new_client) -> None:  # type: ignore[no-untyped-def]
    signup(api, shop.business.slug)
    secret = setup_hook(new_client().login(shop.owner))
    for status in ("booked", "scheduled", "confirmed"):
        later = (datetime.now(UTC) + timedelta(days=3)).isoformat()
        assert send(
            api, shop.business.slug, secret, appointment(status=status, ended_at=later)
        ) == (200, "not_completion")
    assert stamps(shop) == 0


def test_unknown_status_is_not_completion(api: Api, shop: Shop, new_client) -> None:  # type: ignore[no-untyped-def]
    signup(api, shop.business.slug)
    secret = setup_hook(new_client().login(shop.owner))
    for status in ("done-ish", "", None, "no_show", "cancelled"):
        assert send(api, shop.business.slug, secret, appointment(status=status)) == (
            200,
            "not_completion",
        )
    assert stamps(shop) == 0


def test_webhook_rejects_bad_or_old_signature(api: Api, shop: Shop, new_client) -> None:  # type: ignore[no-untyped-def]
    signup(api, shop.business.slug)
    secret = setup_hook(new_client().login(shop.owner))
    slug = shop.business.slug
    assert send(api, slug, None, appointment())[0] == 403
    assert send(api, slug, "whsec_wrong", appointment())[0] == 403
    assert send(api, slug, secret, appointment(), ts=int(time.time()) - 3600)[0] == 403
    assert stamps(shop) == 0


def test_webhook_never_creates_a_customer(api: Api, shop: Shop, new_client) -> None:  # type: ignore[no-untyped-def]
    secret = setup_hook(new_client().login(shop.owner))
    assert send(api, shop.business.slug, secret, appointment(customer={"phone": "0699999999"})) == (
        200,
        "unmatched",
    )
    assert stamps(shop) == 0


def test_webhook_mapping_is_per_business(api: Api, shop: Shop, new_client) -> None:  # type: ignore[no-untyped-def]
    signup(api, shop.business.slug, phone="0611112222")
    owner = new_client().login(shop.owner)
    secret = setup_hook(owner)
    r = owner.patch(
        "/api/v1/webhook",
        json={
            "mapping": {
                "appointment_id": "booking.ref",
                "status": "booking.state",
                "completed_statuses": ["Afgerond"],
                "customer_phone": "client.mobile",
                "customer_email": None,
                "service": None,
                "ended_at": "booking.end",
            }
        },
    )
    assert r.status_code == 200, r.text
    payload = {
        "booking": {"ref": 77, "state": "afgerond", "end": datetime.now(UTC).isoformat()},
        "client": {"mobile": "+31611112222"},
    }
    assert send(api, shop.business.slug, secret, payload) == (200, "stamped")
    view = owner.get("/api/v1/webhook").json()
    assert view["deliveries"][0]["outcome"] == "stamped"
    assert "secret" not in json.dumps(view).lower().replace("whsec", "")


def test_webhook_secret_of_one_business_does_not_work_for_another(
    api: Api,
    shop: Shop,
    other_shop: Shop,
    new_client,  # type: ignore[no-untyped-def]
) -> None:
    signup(api, other_shop.business.slug)
    secret_a = setup_hook(new_client().login(shop.owner))
    setup_hook(new_client().login(other_shop.owner))
    assert send(api, other_shop.business.slug, secret_a, appointment())[0] == 403
    assert stamps(other_shop) == 0


def test_webhook_settings_are_owner_only(api: Api, shop: Shop) -> None:
    api.login(shop.manager)
    assert api.get("/api/v1/webhook").status_code == 403
    assert api.post("/api/v1/webhook/secret").status_code == 403
