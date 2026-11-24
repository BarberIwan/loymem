"""Tegoed: prepaid balance in euros with an optional bonus."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy.exc import DBAPIError

from app.integrations.payments import FakeProvider
from app.models import BalanceEvent, Business, Subscription
from app.services import memberships
from tests.conftest import Api, Clock, Shop, app_session, card, scan, signup
from tests.test_memberships import PLAN, connect, plan, webhook

CREDIT = {
    **PLAN,
    "kind": "credit",
    "name": "Tegoed 50",
    "price_cents": 5000,
    "value_cents": 7500,
    "validity_days": 365,
}


def buy(api: Api, slug: str, secret: str, p: dict, fake: FakeProvider) -> str:  # type: ignore[type-arg]
    r = api.post(
        f"/api/v1/public/{slug}/card/{secret}/plans/{p['id']}/buy",
        json={"terms_version": p["terms_version"]},
    )
    assert r.status_code == 200, r.text
    pid = str(r.json()["checkout_url"]).rsplit("/", 1)[-1]
    fake.set_status(pid, "paid")
    assert webhook(api, slug, pid) == "paid"
    return pid


@pytest.fixture
def setup(api: Api, shop: Shop, fake: FakeProvider, new_client, clock: Clock):  # type: ignore[no-untyped-def]
    connect(shop)
    p = plan(new_client().login(shop.owner), **CREDIT)
    secret = signup(api, shop.business.slug)
    pid = buy(api, shop.business.slug, secret, p, fake)
    return p, secret, pid


def spend(api: Api, customer_id: str, cents: int, rid: str | None = None):  # type: ignore[no-untyped-def]
    return api.post(
        "/api/v1/balance/spend",
        json={
            "customer_id": customer_id,
            "amount_cents": cents,
            "request_id": rid or str(uuid.uuid4()),
        },
    )


def test_plan_value_must_lie_between_price_and_double(new_client, shop: Shop, fake) -> None:  # type: ignore[no-untyped-def]
    owner = new_client().login(shop.owner)
    for bad in (
        {"value_cents": 4000},  # worth less than it costs
        {"value_cents": 10_001},  # more than double
        {"value_cents": None},
        {"validity_days": 180},  # a balance stays valid at least a year
    ):
        assert owner.post("/api/v1/plans", json={**CREDIT, **bad}).status_code == 422, bad
    p = plan(owner, **{**CREDIT, "value_cents": 10_000})
    assert (p["value_cents"], p["bonus_percent"], p["credits"]) == (10_000, 100, 0)
    # A bundle never carries a euro value.
    b = plan(owner, kind="bundle", validity_days=180, value_cents=9000)
    assert b["value_cents"] is None


def test_database_refuses_a_value_above_double(shop: Shop) -> None:
    from app.models import Plan, PlanKind

    db = app_session(shop.business.id)
    db.add(
        Plan(
            business_id=shop.business.id,
            kind=PlanKind.CREDIT,
            name="Te gul",
            price_cents=5000,
            value_cents=10_001,
            credits=0,
            validity_days=365,
            unused_policy="x" * 10,
            no_show_policy="",
            pause_policy="",
        )
    )
    with pytest.raises(DBAPIError):
        db.flush()
    db.rollback()
    db.close()


def test_paid_credit_plan_tops_up_once_and_shows_on_card(api: Api, shop: Shop, setup) -> None:  # type: ignore[no-untyped-def]
    p, secret, pid = setup
    assert webhook(api, shop.business.slug, pid) == "already_processed"
    view = card(api, shop.business.slug, secret)["memberships"]
    assert view["balance"]["cents"] == 7500
    [sub] = view["subscriptions"]
    assert (sub["kind"], sub["balance_cents"], sub["credits"]) == ("credit", 7500, None)
    assert view["balance_history"][0]["kind"] == "topup"


def test_spend_is_idempotent_and_refuses_more_than_the_balance(api: Api, shop: Shop, setup) -> None:  # type: ignore[no-untyped-def]
    _, secret, _ = setup
    api.login(shop.staff)
    found = scan(api, card(api, shop.business.slug, secret)["scan_token"])
    assert found["balance"]["cents"] == 7500
    assert found["membership"] is None  # a euro balance is not a visit bundle
    rid = str(uuid.uuid4())
    first = spend(api, found["customer_id"], 3250, rid)
    assert first.json()["balance_cents"] == 4250
    again = spend(api, found["customer_id"], 3250, rid)
    assert again.json() == first.json()  # a retried tap spends nothing extra
    too_much = spend(api, found["customer_id"], 4251)
    assert too_much.status_code == 409
    assert too_much.json()["detail"] == "balance_too_low"
    assert spend(api, found["customer_id"], 4250).json()["balance_cents"] == 0


def test_spend_takes_from_the_balance_that_expires_first(
    api: Api, shop: Shop, setup, fake, new_client, clock: Clock
) -> None:  # type: ignore[no-untyped-def]
    p, secret, _ = setup
    # Make the first purchase expire sooner than a second one bought now.
    db = app_session(shop.business.id)
    first = db.query(Subscription).one()
    first.period_end = first.period_end - timedelta(days=100)  # type: ignore[operator]
    db.commit()
    db.close()
    buy(api, shop.business.slug, secret, p, fake)
    api.login(shop.staff)
    cid = scan(api, card(api, shop.business.slug, secret)["scan_token"])["customer_id"]
    r = spend(api, cid, 9000)  # 7500 from the first, 1500 from the second
    assert r.json()["balance_cents"] == 6000
    db = app_session(shop.business.id)
    subs = {s.id: s for s in db.query(Subscription).all()}
    parts = sorted(
        (subs[e.subscription_id].period_end, e.amount_cents)
        for e in db.query(BalanceEvent).filter(BalanceEvent.kind == "spend")
    )
    assert [c for _, c in parts] == [-7500, -1500]
    db.close()
    history = card(api, shop.business.slug, secret)["memberships"]["balance_history"]
    assert history[0]["kind"] == "spend" and history[0]["cents"] == -9000  # one line


def test_undo_once_with_reason_and_only_by_whom_may(
    api: Api, shop: Shop, setup, new_client, clock: Clock
) -> None:  # type: ignore[no-untyped-def]
    _, secret, _ = setup
    api.login(shop.staff)
    cid = scan(api, card(api, shop.business.slug, secret)["scan_token"])["customer_id"]
    rid = str(uuid.uuid4())
    spend(api, cid, 2000, rid)
    body = {"customer_id": cid, "request_id": rid, "reason": "verkeerd bedrag"}
    clock.advance(minutes=11)
    assert api.post("/api/v1/balance/undo", json=body).status_code == 403  # too late for staff
    manager = new_client().login(shop.manager)
    r = manager.post("/api/v1/balance/undo", json=body)
    assert r.json() == {"restored_cents": 2000, "balance_cents": 7500}
    assert manager.post("/api/v1/balance/undo", json=body).json()["restored_cents"] == 0
    line = card(api, shop.business.slug, secret)["memberships"]["balance_history"][0]
    assert (line["kind"], line["undone"]) == ("spend", True)
    # The staff member's own correction, within the window, is allowed.
    rid2 = str(uuid.uuid4())
    spend(api, cid, 500, rid2)
    ok = api.post("/api/v1/balance/undo", json={**body, "request_id": rid2})
    assert ok.json()["restored_cents"] == 500


def test_balance_expires_once_at_end_of_validity(api: Api, shop: Shop, setup) -> None:  # type: ignore[no-untyped-def]
    _, secret, _ = setup
    api.login(shop.staff)
    cid = scan(api, card(api, shop.business.slug, secret)["scan_token"])["customer_id"]
    spend(api, cid, 2500)
    db = app_session(shop.business.id)
    b = db.get(Business, shop.business.id)
    sub = db.query(Subscription).one()
    later = sub.period_end + timedelta(minutes=1)  # type: ignore[operator]
    assert memberships.daily(db, b, now=later) == {"ended": 1, "renewals_started": 0}  # type: ignore[arg-type]
    assert memberships.daily(db, b, now=later) == {"ended": 0, "renewals_started": 0}  # type: ignore[arg-type]
    expired = db.query(BalanceEvent).filter(BalanceEvent.kind == "expire").all()
    assert [e.amount_cents for e in expired] == [-5000]
    db.commit()
    db.close()


def test_ledger_is_append_only_and_tenant_bound(
    api: Api, shop: Shop, other_shop: Shop, setup
) -> None:  # type: ignore[no-untyped-def]
    db = app_session(shop.business.id)
    with pytest.raises(DBAPIError):
        db.query(BalanceEvent).update({"amount_cents": 99_999})
        db.flush()
    db.rollback()
    db.close()
    other = app_session(other_shop.business.id)
    assert other.query(BalanceEvent).count() == 0
    other.close()


def test_other_business_cannot_spend_this_balance(
    api: Api, shop: Shop, other_shop: Shop, setup, new_client
) -> None:  # type: ignore[no-untyped-def]
    _, secret, _ = setup
    api.login(shop.staff)
    cid = scan(api, card(api, shop.business.slug, secret)["scan_token"])["customer_id"]
    stranger = new_client().login(other_shop.staff)
    r = spend(stranger, cid, 100)
    assert r.status_code == 409 and r.json()["detail"] == "balance_too_low"
