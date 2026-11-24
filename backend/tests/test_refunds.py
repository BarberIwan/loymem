"""Money back: a fixed sentence in every plan, and a refund by the owner."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import DBAPIError

from app.integrations.payments import FakeProvider
from app.models import Refund
from app.services import policies
from tests.conftest import Api, Shop, app_session, card, scan
from tests.test_balance import CREDIT, buy, spend
from tests.test_memberships import bought, connect, plan


def subs(owner: Api) -> list[dict]:  # type: ignore[type-arg]
    r = owner.get("/api/v1/subscriptions")
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


def test_every_plan_carries_the_refund_sentence(new_client, shop: Shop) -> None:  # type: ignore[no-untyped-def]
    owner = new_client().login(shop.owner)
    for kw in ({}, {"kind": "bundle", "validity_days": 180}, CREDIT):
        assert plan(owner, **kw)["refund_policy"] == policies.REFUND


def test_untouched_bundle_within_cooling_off_is_refunded_in_full(
    api: Api, shop: Shop, fake: FakeProvider, new_client
) -> None:  # type: ignore[no-untyped-def]
    secret, pid = bought(api, shop, fake, new_client, kind="bundle", validity_days=180)
    owner = new_client().login(shop.owner)
    [s] = subs(owner)
    q = s["refund"]
    assert (q["suggested_cents"], q["within_cooling_off"], q["unused"]) == (3500, True, 2)
    r = owner.post(
        f"/api/v1/subscriptions/{s['id']}/refund",
        json={"amount_cents": q["suggested_cents"], "reason": "cooling_off"},
    )
    assert r.json() == {"refunded_cents": 3500, "status": "ended"}
    assert fake.refunds == [(pid, 3500)]
    assert card(api, shop.business.slug, secret)["memberships"]["subscriptions"] == []
    again = owner.post(
        f"/api/v1/subscriptions/{s['id']}/refund", json={"amount_cents": 1, "reason": "other"}
    )
    assert again.status_code == 409 and len(fake.refunds) == 1


def test_used_visits_are_deducted_in_proportion(
    api: Api, shop: Shop, fake: FakeProvider, new_client
) -> None:  # type: ignore[no-untyped-def]
    secret, _ = bought(api, shop, fake, new_client, kind="bundle", validity_days=180, credits=4)
    api.login(shop.staff)
    cid = scan(api, card(api, shop.business.slug, secret)["scan_token"])["customer_id"]
    api.post("/api/v1/credits/use", json={"customer_id": cid, "request_id": str(uuid.uuid4())})
    owner = new_client().login(shop.owner)
    [s] = subs(owner)
    assert (s["refund"]["unused"], s["refund"]["suggested_cents"]) == (3, 3500 * 3 // 4)


def test_balance_refund_takes_the_rest_off_and_shows_as_refunded(
    api: Api, shop: Shop, fake: FakeProvider, new_client
) -> None:  # type: ignore[no-untyped-def]
    connect(shop)
    owner = new_client().login(shop.owner)
    p = plan(owner, **CREDIT)
    from tests.conftest import signup

    secret = signup(api, shop.business.slug)
    buy(api, shop.business.slug, secret, p, fake)
    api.login(shop.staff)
    cid = scan(api, card(api, shop.business.slug, secret)["scan_token"])["customer_id"]
    spend(api, cid, 2500)  # 5000 left of 7500 bought for 5000 paid
    [s] = subs(owner)
    assert s["refund"]["suggested_cents"] == 5000 * 5000 // 7500
    owner.post(
        f"/api/v1/subscriptions/{s['id']}/refund",
        json={"amount_cents": s["refund"]["suggested_cents"], "reason": "business_stops"},
    )
    view = card(api, shop.business.slug, secret)["memberships"]
    assert view["balance"]["cents"] == 0
    assert view["balance_history"][0]["kind"] == "refund"


def test_only_the_owner_refunds_and_never_more_than_was_paid(
    api: Api, shop: Shop, fake: FakeProvider, new_client
) -> None:  # type: ignore[no-untyped-def]
    bought(api, shop, fake, new_client)
    owner = new_client().login(shop.owner)
    [s] = subs(owner)
    url = f"/api/v1/subscriptions/{s['id']}/refund"
    for person in (shop.staff, shop.manager):
        c = new_client().login(person)
        assert c.get("/api/v1/subscriptions").status_code == 403
        assert c.post(url, json={"amount_cents": 100, "reason": "other"}).status_code == 403
    assert owner.post(url, json={"amount_cents": 3501, "reason": "other"}).status_code == 409
    assert owner.post(url, json={"amount_cents": 100, "reason": "zomaar"}).status_code == 409
    assert fake.refunds == []


def test_provider_refusal_changes_nothing(
    api: Api, shop: Shop, fake: FakeProvider, new_client, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    secret, _ = bought(api, shop, fake, new_client)

    def refuse(*a: object, **kw: object) -> str:
        raise RuntimeError("provider down")

    monkeypatch.setattr(fake, "refund", refuse)
    owner = new_client().login(shop.owner)
    [s] = subs(owner)
    with pytest.raises(RuntimeError):
        owner.post(
            f"/api/v1/subscriptions/{s['id']}/refund",
            json={"amount_cents": 3500, "reason": "other"},
        )
    [still] = subs(owner)
    assert still["status"] == "active" and still["refund"]["unused"] == 2
    assert card(api, shop.business.slug, secret)["memberships"]["subscriptions"][0]["credits"] == 2


def test_refunds_are_append_only(api: Api, shop: Shop, fake, new_client) -> None:  # type: ignore[no-untyped-def]
    bought(api, shop, fake, new_client)
    owner = new_client().login(shop.owner)
    [s] = subs(owner)
    owner.post(
        f"/api/v1/subscriptions/{s['id']}/refund", json={"amount_cents": 3500, "reason": "other"}
    )
    db = app_session(shop.business.id)
    with pytest.raises(DBAPIError):
        db.query(Refund).update({"amount_cents": 1})
        db.flush()
    db.rollback()
    db.close()
