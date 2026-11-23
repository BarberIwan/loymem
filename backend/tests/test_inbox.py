"""Phase 1b: the retention inbox."""

from __future__ import annotations

import json
import re
from pathlib import Path

from sqlalchemy import select, text, update

from app.models import Business
from tests.conftest import Api, Clock, Shop, app_session, card, owner_engine, scan, signup

ROOT = Path(__file__).resolve().parents[2]


def visit(api: Api, token: str, service: object) -> None:
    cid = scan(api, token)["customer_id"]
    r = api.post("/api/v1/stamps", json={"customer_id": cid, "service_id": str(service)})
    assert r.status_code == 200, r.text


def customer_with_visit(api: Api, shop: Shop, phone: str, service: object, **kw: object) -> str:
    secret = signup(api, shop.business.slug, phone=phone, **kw)
    visit(api, card(api, shop.business.slug, secret)["scan_token"], service)
    return secret


def inbox(api: Api) -> list[dict]:  # type: ignore[type-arg]
    r = api.get("/api/v1/inbox")
    assert r.status_code == 200, r.text
    return r.json()["items"]  # type: ignore[no-any-return]


def test_due_customer_appears_with_facts_and_no_score(
    api: Api, shop: Shop, clock: Clock, new_client
) -> None:  # type: ignore[no-untyped-def]
    api.login(shop.staff)
    customer_with_visit(api, shop, "0610000001", shop.beard.id, first_name="Sam")
    clock.advance(days=15)
    owner = new_client().login(shop.owner)
    items = inbox(owner)
    assert [i["kind"] for i in items] == ["due_for_visit"]
    facts = items[0]["facts"]
    assert facts["days_since"] == 15 and facts["return_period_days"] == 14
    assert facts["service"] == "Baard"
    assert not {"score", "probability", "stars"} & (set(items[0]) | set(facts))


def test_inbox_without_integration_never_claims_no_appointment(
    api: Api, shop: Shop, clock: Clock, new_client
) -> None:  # type: ignore[no-untyped-def]
    api.login(shop.staff)
    customer_with_visit(api, shop, "0610000002", shop.beard.id)
    clock.advance(days=20)
    body = json.dumps(inbox(new_client().login(shop.owner))).lower()
    assert "appointment" not in body.replace("booking_url", "")
    assert "afspraak" not in body
    for locale in ("nl", "en"):
        msgs = json.loads((ROOT / "frontend/messages" / f"{locale}.json").read_text())
        inbox_text = json.dumps(msgs["inbox"], ensure_ascii=False).lower()
        for claim in (
            r"geen (nieuwe )?afspraak",
            r"no (new |upcoming )?appointment",
            r"has not booked",
            r"niet geboekt",
        ):
            assert not re.search(claim, inbox_text), (locale, claim)


def test_reward_waiting_two_weeks_comes_first_one_card_per_customer(
    api: Api,
    shop: Shop,
    clock: Clock,
    new_client,  # type: ignore[no-untyped-def]
) -> None:
    api.login(shop.staff)
    a = signup(api, shop.business.slug, phone="0610000003", first_name="Noor")
    token = card(api, shop.business.slug, a)["scan_token"]
    for _ in range(shop.program.stamps_required):
        visit(api, token, shop.beard.id)
        clock.advance(days=1)
    customer_with_visit(api, shop, "0610000004", shop.beard.id, first_name="Bas")
    clock.advance(days=16)
    items = inbox(new_client().login(shop.owner))
    assert [(i["first_name"], i["kind"]) for i in items] == [
        ("Noor", "reward_unused"),
        ("Bas", "due_for_visit"),
    ]


def test_ignore_hides_for_the_set_period_and_is_remembered(
    api: Api, shop: Shop, clock: Clock, new_client
) -> None:  # type: ignore[no-untyped-def]
    api.login(shop.staff)
    customer_with_visit(api, shop, "0610000005", shop.beard.id)
    clock.advance(days=15)
    owner = new_client().login(shop.owner)
    assert owner.patch("/api/v1/settings", json={"inbox_ignore_days": 10}).status_code == 200
    item = inbox(owner)[0]
    r = owner.post(
        "/api/v1/inbox/decide",
        json={"customer_id": item["customer_id"], "kind": item["kind"], "decision": "ignored"},
    )
    assert r.json() == {"decision": "ignored", "hidden_days": 10}
    assert inbox(owner) == []
    clock.advance(days=9)
    assert inbox(owner) == []
    clock.advance(days=2)
    assert len(inbox(owner)) == 1


def test_message_needs_consent_and_lands_in_outbox(
    api: Api, shop: Shop, clock: Clock, new_client
) -> None:  # type: ignore[no-untyped-def]
    api.login(shop.staff)
    customer_with_visit(
        api,
        shop,
        "0610000006",
        shop.beard.id,
        email="ja@example.org",
        marketing_consent=True,
        first_name="Ja",
    )
    customer_with_visit(
        api, shop, "0610000007", shop.beard.id, email="nee@example.org", first_name="Nee"
    )
    clock.advance(days=15)
    owner = new_client().login(shop.owner)
    items = {i["first_name"]: i for i in inbox(owner)}
    assert items["Ja"]["action"] == "message" and items["Nee"]["action"] == "in_person"
    refused = owner.post(
        "/api/v1/inbox/decide",
        json={
            "customer_id": items["Nee"]["customer_id"],
            "kind": "due_for_visit",
            "decision": "sent",
            "message": "Hoi, kom je weer eens langs?",
        },
    )
    assert refused.status_code == 400 and refused.json()["detail"] == "no_consent_or_contact"
    ok = owner.post(
        "/api/v1/inbox/decide",
        json={
            "customer_id": items["Ja"]["customer_id"],
            "kind": "due_for_visit",
            "decision": "sent",
            "message": "Hoi Ja, kom je weer eens langs?",
        },
    )
    assert ok.status_code == 200
    db = app_session(shop.business.id)
    rows = db.execute(text("select recipient, payload->>'text' from outbox")).all()
    db.close()
    assert rows == [("ja@example.org", "Hoi Ja, kom je weer eens langs?")]
    assert [i["first_name"] for i in inbox(owner)] == ["Nee"]


def test_daily_limit_keeps_the_inbox_short(api: Api, shop: Shop, clock: Clock, new_client) -> None:  # type: ignore[no-untyped-def]
    with owner_engine.begin() as c:
        c.execute(
            update(Business).where(Business.id == shop.business.id).values(inbox_daily_limit=3)
        )
    api.login(shop.staff)
    for i in range(5):
        customer_with_visit(api, shop, f"061000002{i}", shop.beard.id)
    clock.advance(days=20)
    owner = new_client().login(shop.owner)
    assert len(inbox(owner)) == 3


def test_inbox_is_for_owner_and_manager_only(api: Api, shop: Shop) -> None:
    api.login(shop.staff)
    assert api.get("/api/v1/inbox").status_code == 403
    assert (
        api.post(
            "/api/v1/inbox/decide",
            json={
                "customer_id": "00000000-0000-0000-0000-000000000000",
                "kind": "due_for_visit",
                "decision": "done",
            },
        ).status_code
        == 403
    )


def test_inbox_decision_cannot_touch_another_business(
    api: Api, shop: Shop, other_shop: Shop, clock: Clock, new_client
) -> None:  # type: ignore[no-untyped-def]
    api.login(shop.staff)
    customer_with_visit(api, shop, "0610000030", shop.beard.id)
    clock.advance(days=15)
    db = app_session(shop.business.id)
    from app.models import Customer

    cid = db.scalar(select(Customer.id))
    db.close()
    other = new_client().login(other_shop.owner)
    r = other.post(
        "/api/v1/inbox/decide",
        json={"customer_id": str(cid), "kind": "due_for_visit", "decision": "ignored"},
    )
    assert r.status_code == 404
    assert inbox(other) == []
