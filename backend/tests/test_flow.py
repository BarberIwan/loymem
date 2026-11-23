"""Phase 1a end to end: sign up, card, stamp, reward, redeem, overview."""

from __future__ import annotations

import io
import threading
import uuid
import zipfile

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError

from app.models import (
    ConsentPurpose,
    ConsentRecord,
    ConsentStatus,
    Customer,
    CustomerProgram,
    LedgerEvent,
    LedgerKind,
    Reward,
    RewardStatus,
)
from app.services import Conflict, NotFound, cards, ledger
from app.services.brand import AA, card_text_colour, contrast
from app.services.cards import StaffContext
from tests.conftest import Api, Clock, Shop, app_session, card, make_shop, scan, signup


def stamp_days(api: Api, clock: Clock, token: str, n: int, service: object = None) -> dict:  # type: ignore[type-arg]
    out: dict = {}  # type: ignore[type-arg]
    for _ in range(n):
        info = scan(api, token)
        body = {"customer_id": info["customer_id"]}
        if service is not None:
            body["service_id"] = str(service)
        r = api.post("/api/v1/stamps", json=body)
        assert r.status_code == 200, r.text
        out = r.json()
        clock.advance(days=1)
    return out


def full_card(api: Api, clock: Clock, shop: Shop) -> tuple[str, dict]:  # type: ignore[type-arg]
    secret = signup(api, shop.business.slug)
    token = card(api, shop.business.slug, secret)["scan_token"]
    api.login(shop.staff)
    stamp_days(api, clock, token, shop.program.stamps_required)
    return secret, card(api, shop.business.slug, secret)


def test_enroll_and_use_without_booking_integration(api: Api, shop: Shop, clock: Clock) -> None:
    secret, view = full_card(api, clock, shop)
    assert view["stamps"] == 0 and len(view["rewards"]) == 1
    r = api.post(
        f"/api/v1/public/{shop.business.slug}/card/{secret}/reward-code",
        json={"reward_id": view["rewards"][0]["id"]},
    )
    code = r.json()["code"]
    r = api.post("/api/v1/redeem", json={"code": code})
    assert r.status_code == 200 and r.json()["description"] == "Gratis knipbeurt"
    assert card(api, shop.business.slug, secret)["rewards"] == []
    api.login(shop.owner)
    ov = api.get("/api/v1/overview").json()
    assert ov["customers"] == 1 and ov["stamps_30d"] == 5 and ov["rewards_redeemed_30d"] == 1


def test_duplicate_scan_single_stamp(api: Api, shop: Shop, clock: Clock) -> None:
    secret = signup(api, shop.business.slug)
    token = card(api, shop.business.slug, secret)["scan_token"]
    api.login(shop.staff)
    cid = scan(api, token)["customer_id"]
    first = api.post("/api/v1/stamps", json={"customer_id": cid}).json()
    clock.advance(hours=3)
    second = api.post("/api/v1/stamps", json={"customer_id": cid}).json()
    assert first["stamped"] and not second["stamped"]
    assert second["reason"] == "already_stamped_this_period"
    assert card(api, shop.business.slug, secret)["stamps"] == 1


def test_concurrent_scan_single_stamp(api: Api, shop: Shop) -> None:
    secret = signup(api, shop.business.slug)
    api.login(shop.staff)
    cid = uuid.UUID(scan(api, card(api, shop.business.slug, secret)["scan_token"])["customer_id"])
    barrier = threading.Barrier(6)
    results: list[object] = []

    def worker() -> None:
        db = app_session(shop.business.id)
        ctx = StaffContext(db.merge(shop.staff, load=False), db.merge(shop.business, load=False))
        barrier.wait()
        try:
            results.append(cards.stamp(db, ctx, cid, None)["stamped"])
            db.commit()
        finally:
            db.close()

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(True) == 1 and results.count(False) == 5
    assert card(api, shop.business.slug, secret)["stamps"] == 1


def test_reward_redeemed_once_concurrently(api: Api, shop: Shop, clock: Clock) -> None:
    secret, view = full_card(api, clock, shop)
    code = api.post(
        f"/api/v1/public/{shop.business.slug}/card/{secret}/reward-code",
        json={"reward_id": view["rewards"][0]["id"]},
    ).json()["code"]
    barrier = threading.Barrier(4)
    outcomes: list[str] = []

    def worker() -> None:
        db = app_session(shop.business.id)
        ctx = StaffContext(db.merge(shop.staff, load=False), db.merge(shop.business, load=False))
        barrier.wait()
        try:
            cards.redeem(db, ctx, code)
            db.commit()
            outcomes.append("ok")
        except (Conflict, NotFound):
            db.rollback()
            outcomes.append("refused")
        finally:
            db.close()

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert outcomes.count("ok") == 1
    db = app_session(shop.business.id)
    n = db.scalar(
        select(func.count())
        .select_from(LedgerEvent)
        .where(LedgerEvent.kind == LedgerKind.REWARD_REDEEMED)
    )
    db.close()
    assert n == 1


def test_screenshot_of_reward_code_is_rejected(api: Api, shop: Shop, clock: Clock) -> None:
    secret, view = full_card(api, clock, shop)
    path = f"/api/v1/public/{shop.business.slug}/card/{secret}/reward-code"
    old = api.post(path, json={"reward_id": view["rewards"][0]["id"]}).json()["code"]
    clock.advance(seconds=91)
    assert api.post("/api/v1/redeem", json={"code": old}).status_code == 404
    # A newer code replaces an older one that has not expired yet.
    a = api.post(path, json={"reward_id": view["rewards"][0]["id"]}).json()["code"]
    b = api.post(path, json={"reward_id": view["rewards"][0]["id"]}).json()["code"]
    if a != b:
        assert api.post("/api/v1/redeem", json={"code": a}).status_code == 404
    assert api.post("/api/v1/redeem", json={"code": b}).status_code == 200
    assert api.post("/api/v1/redeem", json={"code": b}).status_code == 404


def test_balance_matches_ledger(api: Api, shop: Shop, clock: Clock) -> None:
    full_card(api, clock, shop)
    secret = signup(api, shop.business.slug, phone="0612000000", first_name="Noor")
    stamp_days(api, clock, card(api, shop.business.slug, secret)["scan_token"], 3)
    db = app_session(shop.business.id)
    assert ledger.balance_mismatches(db, shop.business.id) == []
    cp = db.scalars(select(CustomerProgram)).first()
    assert cp is not None
    db.execute(update(CustomerProgram).where(CustomerProgram.id == cp.id).values(balance=4))
    assert ledger.balance_mismatches(db, shop.business.id) == [cp.id]
    ledger.recompute_balance(db, cp.id)
    assert ledger.balance_mismatches(db, shop.business.id) == []
    db.rollback()
    db.close()


def test_ledger_rows_cannot_be_changed(api: Api, shop: Shop, clock: Clock) -> None:
    full_card(api, clock, shop)
    db = app_session(shop.business.id)
    with pytest.raises(DBAPIError):
        db.execute(text("update ledger_events set delta = 5"))
    db.rollback()
    set_db = app_session(shop.business.id)
    with pytest.raises(DBAPIError):
        set_db.execute(text("delete from ledger_events"))
    set_db.rollback()
    db.close()
    set_db.close()


def test_correction_is_reversal_by_manager_only(
    api: Api, shop: Shop, clock: Clock, new_client
) -> None:  # type: ignore[no-untyped-def]
    secret = signup(api, shop.business.slug)
    api.login(shop.staff)
    stamp_days(api, clock, card(api, shop.business.slug, secret)["scan_token"], 2)
    m = new_client().login(shop.manager)
    event = next(e for e in m.get("/api/v1/overview").json()["recent"] if e["kind"] == "stamp")
    path = f"/api/v1/events/{event['id']}/reverse"
    assert api.post(path, json={"reason": "per ongeluk"}).status_code == 403
    assert m.post(path, json={"reason": "per ongeluk"}).status_code == 200
    assert m.post(path, json={"reason": "nog een keer"}).status_code == 409
    assert card(api, shop.business.slug, secret)["stamps"] == 1
    db = app_session(shop.business.id)
    kinds = db.scalars(select(LedgerEvent.kind)).all()
    db.close()
    assert sorted(k.value for k in kinds) == ["reversal", "stamp", "stamp"]


def test_staff_cannot_stamp_own_profile(api: Api, shop: Shop) -> None:
    secret = signup(api, shop.business.slug, email=shop.staff.email.upper(), phone=None)
    token = card(api, shop.business.slug, secret)["scan_token"]
    api.login(shop.staff)
    assert api.post("/api/v1/scan", json={"scan_token": token}).status_code == 403
    db = app_session(shop.business.id)
    cid = db.scalar(select(Customer.id))
    db.close()
    r = api.post("/api/v1/stamps", json={"customer_id": str(cid)})
    assert r.status_code == 403 and r.json()["detail"] == "own_profile"


def test_staff_scope_is_narrow(api: Api, shop: Shop) -> None:
    secret = signup(api, shop.business.slug, email="sam@example.org")
    api.login(shop.staff)
    info = scan(api, card(api, shop.business.slug, secret)["scan_token"])
    assert "email" not in str(info) and "0612345678" not in str(info).replace(" ", "")
    for method, path in [
        ("get", "/api/v1/export"),
        ("get", "/api/v1/overview"),
        ("get", "/api/v1/due"),
        ("get", "/api/v1/settings"),
        ("get", "/api/v1/staff"),
        ("patch", "/api/v1/settings"),
    ]:
        assert (
            getattr(api, method)(path, **({"json": {}} if method == "patch" else {})).status_code
            == 403
        ), path


def test_mutations_need_header(shop: Shop) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    bare = TestClient(app)
    r = bare.post(
        f"/api/v1/public/{shop.business.slug}/signup",
        json={"first_name": "X", "phone": "0611111111"},
    )
    assert r.status_code == 403


def test_tenant_isolation(api: Api, shop: Shop, other_shop: Shop, new_client) -> None:  # type: ignore[no-untyped-def]
    secret_a = signup(api, shop.business.slug)
    token_a = card(api, shop.business.slug, secret_a)["scan_token"]
    # The same card link does not open at another business.
    assert api.get(f"/api/v1/public/{other_shop.business.slug}/card/{secret_a}").status_code == 404
    other = new_client().login(other_shop.staff)
    assert other.post("/api/v1/scan", json={"scan_token": token_a}).status_code == 404
    db = app_session(shop.business.id)
    cid = db.scalar(select(Customer.id))
    db.close()
    assert other.post("/api/v1/stamps", json={"customer_id": str(cid)}).status_code == 404
    # Row level security: a session scoped to B sees nothing of A, even unfiltered.
    db = app_session(other_shop.business.id)
    assert db.scalar(select(func.count()).select_from(Customer)) == 0
    with pytest.raises(DBAPIError):
        db.execute(
            text(
                "insert into services (id, business_id, name, return_period_days, "
                "active, created_at) values (gen_random_uuid(), :b, 'x', 5, true, now())"
            ),
            {"b": shop.business.id},
        )
    db.rollback()
    db.close()
    # Without any scope nothing is visible at all.
    from app.db import session_factory

    raw = session_factory()()
    assert raw.scalar(select(func.count()).select_from(Customer)) == 0
    raw.close()


def test_customer_profiles_never_shared_between_businesses(
    api: Api, shop: Shop, other_shop: Shop, new_client
) -> None:  # type: ignore[no-untyped-def]
    signup(api, shop.business.slug, phone="06 99999999")
    signup(api, other_shop.business.slug, phone="06 99999999")
    db_a, db_b = app_session(shop.business.id), app_session(other_shop.business.id)
    a, b = db_a.scalar(select(Customer)), db_b.scalar(select(Customer))
    assert a and b and a.id != b.id and a.card_secret_hash != b.card_secret_hash
    db_a.close()
    db_b.close()
    owner_b = new_client().login(other_shop.owner)
    z = zipfile.ZipFile(io.BytesIO(owner_b.get("/api/v1/export").content))
    assert str(a.id) not in z.read("customers.csv").decode()


def test_import_grants_no_marketing_consent(api: Api, shop: Shop) -> None:
    api.login(shop.manager)
    csv = "voornaam;telefoon;email\nAnna;0611112222;anna@example.org\nBas;0611113333;\n"
    r = api.post("/api/v1/customers/import", files={"file": ("k.csv", csv, "text/csv")})
    assert r.json() == {"added": 2, "skipped": 0}
    db = app_session(shop.business.id)
    granted = db.scalar(
        select(func.count())
        .select_from(ConsentRecord)
        .where(ConsentRecord.status == ConsentStatus.GRANTED)
    )
    db.close()
    assert granted == 0


def test_opt_out_keeps_rewards(api: Api, shop: Shop, clock: Clock) -> None:
    secret = signup(api, shop.business.slug, marketing_consent=True)
    assert card(api, shop.business.slug, secret)["marketing"] is True
    api.login(shop.staff)
    stamp_days(api, clock, card(api, shop.business.slug, secret)["scan_token"], 5)
    r = api.put(
        f"/api/v1/public/{shop.business.slug}/card/{secret}/consent", json={"marketing": False}
    )
    assert r.status_code == 200
    view = card(api, shop.business.slug, secret)
    assert view["marketing"] is False and len(view["rewards"]) == 1


def test_return_period_per_service_drives_opportunity(
    api: Api, shop: Shop, clock: Clock, new_client
) -> None:  # type: ignore[no-untyped-def]
    a = signup(api, shop.business.slug, phone="0610000001")
    b = signup(api, shop.business.slug, phone="0610000002")
    api.login(shop.staff)
    stamp_days(api, clock, card(api, shop.business.slug, a)["scan_token"], 1, shop.cut.id)
    stamp_days(api, clock, card(api, shop.business.slug, b)["scan_token"], 1, shop.beard.id)
    clock.advance(days=15)
    from app.services.rhythm import visit_statuses

    db = app_session(shop.business.id)
    due = {s.service_name: s.due for s in visit_statuses(db, shop.business.id, clock.now)}
    db.close()
    assert due == {"Knippen": False, "Baard": True}


def test_personal_rhythm_only_suggested_after_three_visits(
    api: Api, shop: Shop, clock: Clock
) -> None:
    from app.services.rhythm import visit_statuses

    secret = signup(api, shop.business.slug)
    token = card(api, shop.business.slug, secret)["scan_token"]
    api.login(shop.staff)
    seen = []
    for _ in range(3):
        stamp_days(api, clock, token, 1, shop.cut.id)
        clock.advance(days=20)
        db = app_session(shop.business.id)
        seen.append(visit_statuses(db, shop.business.id, clock.now)[0].personal_rhythm_days)
        db.close()
    assert seen == [None, None, 21]


def test_exit_export_contains_all_customers_and_ledger(api: Api, shop: Shop, clock: Clock) -> None:
    full_card(api, clock, shop)
    signup(api, shop.business.slug, phone="0610000009", first_name="Lot")
    assert api.get("/api/v1/export").status_code == 403
    api.login(shop.owner)
    z = zipfile.ZipFile(io.BytesIO(api.get("/api/v1/export").content))
    customers = z.read("customers.csv").decode().strip().splitlines()
    events = z.read("ledger.csv").decode().strip().splitlines()
    db = app_session(shop.business.id)
    n_events = db.scalar(select(func.count()).select_from(LedgerEvent))
    db.close()
    assert len(customers) == 3 and len(events) == 1 + n_events and n_events == 6


def test_reissued_card_link_invalidates_old_link(api: Api, shop: Shop) -> None:
    old = signup(api, shop.business.slug, email="sam@example.org")
    old_token = card(api, shop.business.slug, old)["scan_token"]
    slug = shop.business.slug
    assert (
        api.post(f"/api/v1/public/{slug}/reissue", json={"contact": "SAM@example.org"}).status_code
        == 202
    )
    assert (
        api.post(
            f"/api/v1/public/{slug}/reissue", json={"contact": "niemand@example.org"}
        ).status_code
        == 202
    )
    db = app_session(shop.business.id)
    url = db.execute(text("select payload->>'url' from outbox")).scalar_one()
    db.close()
    token = url.rsplit("/", 1)[-1]
    new = api.post(f"/api/v1/public/{slug}/reissue/{token}").json()["card_url"].rsplit("/", 1)[-1]
    assert api.get(f"/api/v1/public/{slug}/card/{old}").status_code == 404
    assert card(api, slug, new)["scan_token"] != old_token
    assert api.post(f"/api/v1/public/{slug}/reissue/{token}").status_code == 404
    api.login(shop.staff)
    assert api.post("/api/v1/scan", json={"scan_token": old_token}).status_code == 404


@pytest.mark.parametrize(
    "colour",
    [
        "#000000",
        "#FFFFFF",
        "#777777",
        "#1F4A38",
        "#F2D16B",
        "#FF0000",
        "#00FF00",
        "#0000FF",
        "#808080",
        "#B5651D",
    ],
)
def test_brand_colour_keeps_contrast_aa(colour: str) -> None:
    assert contrast(colour, card_text_colour(colour)) >= AA


def test_brand_colour_keeps_contrast_aa_everywhere() -> None:
    for r in range(0, 256, 17):
        for g in range(0, 256, 17):
            for b in range(0, 256, 17):
                c = f"#{r:02X}{g:02X}{b:02X}"
                assert contrast(c, card_text_colour(c)) >= AA, c


def test_full_card_becomes_one_reward_and_reversal_voids_it(
    api: Api, shop: Shop, clock: Clock
) -> None:
    full_card(api, clock, shop)
    api.login(shop.owner)
    earned = next(
        e for e in api.get("/api/v1/overview").json()["recent"] if e["kind"] == "reward_earned"
    )
    assert (
        api.post(f"/api/v1/events/{earned['id']}/reverse", json={"reason": "dubbel"}).status_code
        == 200
    )
    db = app_session(shop.business.id)
    assert db.scalar(select(Reward.status)) == RewardStatus.VOIDED
    assert db.scalar(select(CustomerProgram.balance)) == 5
    db.close()


def test_signup_without_consent_records_none(api: Api, shop: Shop) -> None:
    signup(api, shop.business.slug)
    db = app_session(shop.business.id)
    assert (
        db.scalar(
            select(func.count())
            .select_from(ConsentRecord)
            .where(ConsentRecord.purpose == ConsentPurpose.MARKETING)
        )
        == 0
    )
    db.close()


def test_one_business_seed_helper_is_isolated() -> None:
    a, b = make_shop("zaak-a"), make_shop("zaak-b")
    assert a.business.id != b.business.id
