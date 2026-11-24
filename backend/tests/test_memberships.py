"""Phase 1d: memberships and bundles."""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError

from app.integrations.payments import FakeProvider, Tokens
from app.models import Business, CreditEvent, Customer, Subscription
from app.services import Conflict, memberships
from tests.conftest import Api, Clock, Shop, app_session, card, scan, signup

PLAN = {
    "kind": "membership",
    "name": "Knipabonnement",
    "price_cents": 3500,
    "credits": 2,
    "cancel_notice_days": 0,
    "cooling_off_days": 14,
    "unused_rule": "expire_period",
    "no_show_rule": "no_show_counts",
}


def connect(shop: Shop) -> None:
    db = app_session(shop.business.id)
    b = db.get(Business, shop.business.id)
    assert b is not None
    memberships.store_tokens(db, b, Tokens("a", "r", datetime(2099, 1, 1).astimezone()))
    db.commit()
    db.close()


def plan(owner: Api, **kw: object) -> dict:  # type: ignore[type-arg]
    r = owner.post("/api/v1/plans", json={**PLAN, **kw})
    assert r.status_code == 201, r.text
    return r.json()  # type: ignore[no-any-return]


def webhook(api: Api, slug: str, pid: str) -> str:
    from fastapi.testclient import TestClient

    from app.main import app

    r = TestClient(app).post(f"/api/v1/payments/{slug}/webhook", data={"id": pid})
    assert r.status_code == 200, r.text
    return str(r.json()["result"])


def bought(api: Api, shop: Shop, fake: FakeProvider, new_client, **kw: object) -> tuple[str, str]:  # type: ignore[no-untyped-def]
    connect(shop)
    p = plan(new_client().login(shop.owner), **kw)
    secret = signup(api, shop.business.slug)
    r = api.post(
        f"/api/v1/public/{shop.business.slug}/card/{secret}/plans/{p['id']}/buy",
        json={"terms_version": p["terms_version"]},
    )
    assert r.status_code == 200, r.text
    pid = r.json()["checkout_url"].rsplit("/", 1)[-1]
    fake.set_status(pid, "paid")
    assert webhook(api, shop.business.slug, pid) == "paid"
    return secret, pid


def test_payment_webhook_is_idempotent_and_reads_status_back(
    api: Api, shop: Shop, fake, new_client
) -> None:  # type: ignore[no-untyped-def]
    secret, pid = bought(api, shop, fake, new_client)
    assert webhook(api, shop.business.slug, pid) == "already_processed"
    view = card(api, shop.business.slug, secret)["memberships"]["subscriptions"]
    assert [(s["status"], s["credits"]) for s in view] == [("active", 2)]
    assert webhook(api, shop.business.slug, "tr_unknown") == "unknown"


def test_selling_is_off_until_enabled(
    api: Api, shop: Shop, monkeypatch: pytest.MonkeyPatch, new_client
) -> None:  # type: ignore[no-untyped-def]
    memberships.set_provider(FakeProvider())
    connect(shop)
    p = plan(new_client().login(shop.owner))
    secret = signup(api, shop.business.slug)
    assert card(api, shop.business.slug, secret)["memberships"]["plans"] == []
    r = api.post(
        f"/api/v1/public/{shop.business.slug}/card/{secret}/plans/{p['id']}/buy",
        json={"terms_version": 1},
    )
    assert r.status_code == 403
    memberships.set_provider(None)


def test_terms_version_is_recorded_and_changes_refuse_old_acceptance(
    api: Api,
    shop: Shop,
    fake,
    new_client,  # type: ignore[no-untyped-def]
) -> None:
    connect(shop)
    owner = new_client().login(shop.owner)
    p = plan(owner)
    changed = owner.put(f"/api/v1/plans/{p['id']}", json={**PLAN, "price_cents": 3900}).json()
    assert changed["terms_version"] == 2
    renamed = owner.put(
        f"/api/v1/plans/{p['id']}", json={**PLAN, "price_cents": 3900, "name": "Abonnement"}
    ).json()
    assert renamed["terms_version"] == 2
    secret = signup(api, shop.business.slug)
    path = f"/api/v1/public/{shop.business.slug}/card/{secret}/plans/{p['id']}/buy"
    assert api.post(path, json={"terms_version": 1}).status_code == 409
    assert api.post(path, json={"terms_version": 2}).status_code == 200
    db = app_session(shop.business.id)
    assert db.scalar(select(Subscription.terms_version)) == 2
    db.close()


def test_membership_cancel_online(api: Api, shop: Shop, fake, clock: Clock, new_client) -> None:  # type: ignore[no-untyped-def]
    secret, _ = bought(api, shop, fake, new_client)
    sub = card(api, shop.business.slug, secret)["memberships"]["subscriptions"][0]
    r = api.post(
        f"/api/v1/public/{shop.business.slug}/card/{secret}/subscriptions/{sub['id']}/cancel"
    )
    assert r.status_code == 200 and r.json()["renews"] is False
    # Still usable until the end of the paid period, then it ends without renewing.
    after = card(api, shop.business.slug, secret)["memberships"]["subscriptions"][0]
    assert after["status"] == "active" and after["credits"] == 2
    db = app_session(shop.business.id)
    b = db.get(Business, shop.business.id)
    assert b is not None
    result = memberships.daily(db, b, datetime(2100, 1, 1).astimezone())
    db.commit()
    db.close()
    assert result == {"ended": 1, "renewals_started": 0}
    assert len(fake.payments) == 1


def test_credit_reserved_then_consumed_or_released_once(
    api: Api, shop: Shop, fake, new_client
) -> None:  # type: ignore[no-untyped-def]
    bought(api, shop, fake, new_client)
    db = app_session(shop.business.id)
    cid = db.scalar(select(Customer.id))
    sub_id = db.scalar(select(Subscription.id))
    assert cid and sub_id
    bid = shop.business.id
    first = memberships.reserve(db, bid, cid, "booking-1")
    assert memberships.reserve(db, bid, cid, "booking-1") == first  # same booking, same hold
    second = memberships.reserve(db, bid, cid, "booking-2")
    assert memberships.available(db, sub_id) == 0
    with pytest.raises(Conflict):
        memberships.reserve(db, bid, cid, "booking-3")
    assert memberships.settle(db, bid, first, consume=True) is True
    assert memberships.settle(db, bid, first, consume=False) is False  # settled once
    assert memberships.settle(db, bid, second, consume=False) is True
    assert memberships.settle(db, bid, second, consume=True) is False
    assert memberships.available(db, sub_id) == 1
    kinds = sorted(k.value for k in db.scalars(select(CreditEvent.kind)))
    assert kinds == ["consume", "grant", "release", "reserve", "reserve"]
    db.commit()
    with pytest.raises(DBAPIError):
        db.execute(select(func.count()).select_from(CreditEvent))
        db.execute(CreditEvent.__table__.delete())
    db.rollback()
    db.close()


def test_staff_uses_a_credit_at_the_counter_and_cannot_change_status(
    api: Api,
    shop: Shop,
    fake,
    new_client,  # type: ignore[no-untyped-def]
) -> None:
    secret, _ = bought(api, shop, fake, new_client)
    api.login(shop.staff)
    found = scan(api, card(api, shop.business.slug, secret)["scan_token"])
    assert found["membership"] == {"plan": "Knipabonnement", "credits": 2}
    rid = str(uuid.uuid4())
    r = api.post(
        "/api/v1/credits/use", json={"customer_id": found["customer_id"], "request_id": rid}
    )
    assert r.json() == {"used": True, "credits_left": 1}
    again = api.post(
        "/api/v1/credits/use", json={"customer_id": found["customer_id"], "request_id": rid}
    )
    assert again.json()["credits_left"] == 1  # a retried tap uses nothing extra
    for method, path in (("get", "/api/v1/plans"), ("post", "/api/v1/plans")):
        assert (
            getattr(api, method)(path, **({"json": PLAN} if method == "post" else {})).status_code
            == 403
        )


def test_failed_first_payment_never_activates(api: Api, shop: Shop, fake, new_client) -> None:  # type: ignore[no-untyped-def]
    connect(shop)
    p = plan(new_client().login(shop.owner))
    secret = signup(api, shop.business.slug)
    url = api.post(
        f"/api/v1/public/{shop.business.slug}/card/{secret}/plans/{p['id']}/buy",
        json={"terms_version": 1},
    ).json()["checkout_url"]
    pid = url.rsplit("/", 1)[-1]
    fake.set_status(pid, "failed")
    assert webhook(api, shop.business.slug, pid) == "failed"
    assert card(api, shop.business.slug, secret)["memberships"]["subscriptions"] == []
