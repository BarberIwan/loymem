"""Phase 1c: free slots, manual route."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select, text

from app.models import SlotRecipient
from app.services import slots
from tests.conftest import Api, Clock, Shop, app_session, card, scan, signup

# The clock starts Monday 2 November 2026, 10:00 UTC = 11:00 in Amsterdam.
SLOT = {"starts_at": "2026-11-02T14:30:00", "book_by": "2026-11-02T13:45:00"}


def waitlisted(api: Api, shop: Shop, n: int, **prefs: object) -> list[str]:
    secrets = []
    for i in range(n):
        s = signup(
            api,
            shop.business.slug,
            phone=f"06200000{i:02d}",
            email=f"k{i}@example.org",
            first_name=f"K{i}",
        )
        r = api.put(f"/api/v1/public/{shop.business.slug}/card/{s}/waitlist", json=prefs)
        assert r.status_code == 200, r.text
        secrets.append(s)
    return secrets


def offer(owner: Api, **kw: object) -> str:
    body = {**SLOT, "benefit": "stamps", "benefit_value": 2, **kw}
    r = owner.post("/api/v1/slots", json=body)
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


def slot(owner: Api, offer_id: str) -> dict:  # type: ignore[type-arg]
    return next(o for o in owner.get("/api/v1/slots").json() if o["id"] == offer_id)


def tokens(shop: Shop) -> list[str]:
    db = app_session(shop.business.id)
    urls = (
        db.execute(
            text(
                "select payload->>'url' from outbox where template='slot_offer' order by created_at"
            )
        )
        .scalars()
        .all()
    )
    db.close()
    return [u.rsplit("/", 1)[-1] for u in urls]


def test_slot_offer_closes_and_rejects_second_claim(
    api: Api, shop: Shop, clock: Clock, new_client
) -> None:  # type: ignore[no-untyped-def]
    waitlisted(api, shop, 2)
    owner = new_client().login(shop.owner)
    oid = offer(owner)
    assert owner.post(f"/api/v1/slots/{oid}/send").json() == {"sent": 2}
    first, second = tokens(shop)
    slug = shop.business.slug
    assert api.post(f"/api/v1/public/{slug}/plek/{first}/claim").status_code == 200
    r = api.post(f"/api/v1/public/{slug}/plek/{second}/claim")
    assert r.status_code == 409 and r.json()["detail"] == "slot_no_longer_available"
    assert api.get(f"/api/v1/public/{slug}/plek/{second}").json()["available"] is False
    assert slot(owner, oid)["status"] == "filled"


def test_closed_or_expired_offer_cannot_be_claimed(
    api: Api, shop: Shop, clock: Clock, new_client
) -> None:  # type: ignore[no-untyped-def]
    waitlisted(api, shop, 2)
    owner = new_client().login(shop.owner)
    a = offer(owner)
    owner.post(f"/api/v1/slots/{a}/send")
    t1, t2 = tokens(shop)
    owner.post(f"/api/v1/slots/{a}/close", json={"status": "closed"})
    assert api.post(f"/api/v1/public/{shop.business.slug}/plek/{t1}/claim").status_code == 409
    clock.advance(hours=4)  # past the deadline of 13:45
    assert api.get(f"/api/v1/public/{shop.business.slug}/plek/{t2}").json()["available"] is False


def test_staged_send_waits_before_next_group(
    api: Api, shop: Shop, clock: Clock, new_client
) -> None:  # type: ignore[no-untyped-def]
    waitlisted(api, shop, 5)
    owner = new_client().login(shop.owner)
    oid = offer(owner, group_size=2, wait_minutes=10)
    assert owner.post(f"/api/v1/slots/{oid}/send").json() == {"sent": 2}
    db = app_session(shop.business.id)
    from app.models import Business

    b = db.get(Business, shop.business.id)
    assert b is not None
    assert slots.send_due(db, b, clock.now + timedelta(minutes=5)) == 0
    assert slots.send_due(db, b, clock.now + timedelta(minutes=10)) == 2
    db.commit()
    db.close()
    api.post(f"/api/v1/public/{shop.business.slug}/plek/{tokens(shop)[0]}/claim")
    db = app_session(shop.business.id)
    b = db.get(Business, shop.business.id)
    assert b is not None
    assert slots.send_due(db, b, clock.now + timedelta(minutes=30)) == 0
    db.close()
    assert len(tokens(shop)) == 4


def test_claimed_offer_applied_once_only_within_slot(
    api: Api, shop: Shop, clock: Clock, new_client
) -> None:  # type: ignore[no-untyped-def]
    (secret,) = waitlisted(api, shop, 1)
    owner = new_client().login(shop.owner)
    oid = offer(owner, benefit="stamps", benefit_value=2)
    owner.post(f"/api/v1/slots/{oid}/send")
    api.post(f"/api/v1/public/{shop.business.slug}/plek/{tokens(shop)[0]}/claim")
    api.login(shop.staff)
    cid = scan(api, card(api, shop.business.slug, secret)["scan_token"])["customer_id"]
    early = api.post(
        "/api/v1/stamps", json={"customer_id": cid}
    ).json()  # 11:00 local, slot at 14:30
    assert early["applied_offer"] is None and early["stamps"] == 1
    clock.advance(hours=3, minutes=30)  # 14:30 local, inside the slot
    assert scan(api, card(api, shop.business.slug, secret)["scan_token"])["claimed_offer"]
    on_time = api.post("/api/v1/stamps", json={"customer_id": cid}).json()
    assert on_time["applied_offer"]["benefit_value"] == 2 and on_time["stamps"] == 3
    clock.advance(minutes=30)
    again = api.post("/api/v1/stamps", json={"customer_id": cid}).json()
    assert again["applied_offer"] is None and card(api, shop.business.slug, secret)["stamps"] == 3


def test_waitlist_consent_does_not_allow_other_marketing(
    api: Api, shop: Shop, clock: Clock, new_client
) -> None:  # type: ignore[no-untyped-def]
    (secret,) = waitlisted(api, shop, 1)
    assert card(api, shop.business.slug, secret)["marketing"] is False
    api.login(shop.staff)
    cid = scan(api, card(api, shop.business.slug, secret)["scan_token"])["customer_id"]
    api.post("/api/v1/stamps", json={"customer_id": cid, "service_id": str(shop.beard.id)})
    clock.advance(days=20)
    items = new_client().login(shop.owner).get("/api/v1/inbox").json()["items"]
    assert [i["action"] for i in items] == ["in_person"]


def test_leaving_the_waitlist_stops_offers(api: Api, shop: Shop, clock: Clock, new_client) -> None:  # type: ignore[no-untyped-def]
    a, _ = waitlisted(api, shop, 2)
    assert api.delete(f"/api/v1/public/{shop.business.slug}/card/{a}/waitlist").status_code == 200
    owner = new_client().login(shop.owner)
    oid = offer(owner)
    assert [r["first_name"] for r in slot(owner, oid)["recipients"]] == ["K1"]


def test_last_minute_discount_limit_per_customer(
    api: Api, shop: Shop, clock: Clock, new_client
) -> None:  # type: ignore[no-untyped-def]
    waitlisted(api, shop, 1)
    owner = new_client().login(shop.owner)
    first = offer(owner, benefit="discount", benefit_value=15)
    owner.post(f"/api/v1/slots/{first}/send")
    api.post(f"/api/v1/public/{shop.business.slug}/plek/{tokens(shop)[0]}/claim")
    clock.advance(days=10)
    later = {"starts_at": "2026-11-12T14:30:00", "book_by": "2026-11-12T13:45:00"}
    discount = offer(owner, benefit="discount", benefit_value=15, **later)
    stamps = offer(owner, benefit="stamps", benefit_value=1, **later)
    assert slot(owner, discount)["recipients"] == []
    assert len(slot(owner, stamps)["recipients"]) == 1
    clock.advance(days=51)
    much_later = {"starts_at": "2027-01-02T14:30:00", "book_by": "2027-01-02T13:45:00"}
    assert (
        len(
            slot(owner, offer(owner, benefit="discount", benefit_value=15, **much_later))[
                "recipients"
            ]
        )
        == 1
    )


def test_free_slot_offer_has_no_holdout(api: Api, shop: Shop, clock: Clock, new_client) -> None:  # type: ignore[no-untyped-def]
    waitlisted(api, shop, 12)
    owner = new_client().login(shop.owner)
    oid = offer(owner, group_size=50)
    assert len(slot(owner, oid)["recipients"]) == 12
    assert owner.post(f"/api/v1/slots/{oid}/send").json() == {"sent": 12}


def test_preferences_decide_who_matches_and_due_customers_go_first(
    api: Api,
    shop: Shop,
    clock: Clock,
    new_client,  # type: ignore[no-untyped-def]
) -> None:
    slug = shop.business.slug
    waitlisted(api, shop, 1)  # K0: anything
    for i, prefs in enumerate(
        [
            {"days_mask": 2},
            {"dayparts_mask": 1},
            {"service_id": str(shop.beard.id)},
            {"min_notice_minutes": 600},
        ],
        start=1,
    ):
        s = signup(
            api, slug, phone=f"06300000{i:02d}", email=f"x{i}@example.org", first_name=f"X{i}"
        )
        api.put(f"/api/v1/public/{slug}/card/{s}/waitlist", json=prefs)
    due = signup(api, slug, phone="0630000099", email="due@example.org", first_name="Due")
    api.put(f"/api/v1/public/{slug}/card/{due}/waitlist", json={})
    api.login(shop.staff)
    cid = scan(api, card(api, slug, due)["scan_token"])["customer_id"]
    clock.advance(days=-30)
    api.post("/api/v1/stamps", json={"customer_id": cid, "service_id": str(shop.cut.id)})
    clock.advance(days=30)
    owner = new_client().login(shop.owner)
    oid = offer(owner, service_id=str(shop.cut.id))
    got = [(r["first_name"], r["reason"]) for r in slot(owner, oid)["recipients"]]
    assert got == [("Due", "due_for_visit"), ("K0", "waitlist")]


def test_owner_can_remove_a_recipient_before_sending(
    api: Api, shop: Shop, clock: Clock, new_client
) -> None:  # type: ignore[no-untyped-def]
    waitlisted(api, shop, 2)
    owner = new_client().login(shop.owner)
    oid = offer(owner)
    first = slot(owner, oid)["recipients"][0]["customer_id"]
    assert owner.post(f"/api/v1/slots/{oid}/skip", json={"customer_id": first}).status_code == 200
    assert owner.post(f"/api/v1/slots/{oid}/send").json() == {"sent": 1}
    db = app_session(shop.business.id)
    statuses = sorted(db.scalars(select(SlotRecipient.status)).all())
    db.close()
    assert statuses == ["sent", "skipped"]


def test_slots_are_for_owner_and_manager_and_per_business(
    api: Api, shop: Shop, other_shop: Shop, clock: Clock, new_client
) -> None:  # type: ignore[no-untyped-def]
    api.login(shop.staff)
    assert api.get("/api/v1/slots").status_code == 403
    owner = new_client().login(shop.owner)
    oid = offer(owner)
    other = new_client().login(other_shop.owner)
    assert other.post(f"/api/v1/slots/{oid}/send").status_code == 404
    assert other.post(f"/api/v1/slots/{oid}/close", json={"status": "closed"}).status_code == 404
