"""Wallet passes stay current: Apple's pass web service and the update round."""

from __future__ import annotations

import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.integrations import wallet
from app.main import app
from app.models import Business, WalletPass, WalletRegistration
from app.services import wallet_live
from tests.conftest import Api, Shop, app_session, card, scan, signup

PASS_TYPE = "pass.example.toets"
TOKEN_A, TOKEN_B, TOKEN_C = "a1" * 32, "b2" * 32, "c3" * 32  # APNs tokens are 64 hex


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> dict[str, list]:  # type: ignore[type-arg]
    """Record pushes and Google patches instead of calling out."""
    log: dict[str, list] = {"apple": [], "google": [], "gone": []}  # type: ignore[type-arg]

    def push(tokens: list[str]) -> list[str]:
        log["apple"].append(list(tokens))
        return [t for t in tokens if t in log["gone"]]

    def patch(updates: list[wallet.PassData]) -> int:
        log["google"].append([u.serial for u in updates])
        return len(updates)

    monkeypatch.setattr(wallet, "apns_push", push)
    monkeypatch.setattr(wallet, "google_update", patch)
    return log


def phone() -> TestClient:
    return TestClient(app)  # no session, no CSRF header: a phone, not our site


def pass_json(api: Api, slug: str, secret: str) -> dict:  # type: ignore[type-arg]
    r = api.get(f"/api/v1/public/{slug}/card/{secret}/wallet/apple")
    assert r.status_code == 200, r.text
    return json.loads(zipfile.ZipFile(io.BytesIO(r.content)).read("pass.json"))  # type: ignore[no-any-return]


def reg_url(device: str, serial: str) -> str:
    return f"/api/v1/wallet/apple/v1/devices/{device}/registrations/{PASS_TYPE}/{serial}"


def refresh(shop: Shop) -> dict[str, int]:
    db = app_session(shop.business.id)
    b = db.get(Business, shop.business.id)
    assert b is not None
    result = wallet_live.refresh(db, b)
    db.commit()
    db.close()
    return result


def stamp(api: Api, shop: Shop, secret: str) -> None:
    api.login(shop.staff)
    found = scan(api, card(api, shop.business.slug, secret)["scan_token"])
    assert api.post("/api/v1/stamps", json={"customer_id": found["customer_id"]}).status_code == 200


def test_pass_points_phones_at_us_without_the_card_secret(
    api: Api, shop: Shop, wallet_keys: object
) -> None:
    secret = signup(api, shop.business.slug)
    p = pass_json(api, shop.business.slug, secret)
    assert p["webServiceURL"].endswith("/api/v1/wallet/apple")
    assert len(p["authenticationToken"]) >= 16
    assert p["serialNumber"].startswith(f"{shop.business.slug}.")
    assert secret not in json.dumps(p)


def test_register_needs_the_pass_token_and_lists_only_own_passes(
    api: Api, shop: Shop, other_shop: Shop, wallet_keys: object
) -> None:
    secret = signup(api, shop.business.slug)
    p = pass_json(api, shop.business.slug, secret)
    url = reg_url("device1", p["serialNumber"])
    body = {"pushToken": "abc123def456"}
    assert phone().post(url, json=body).status_code == 401
    bad = phone().post(url, json=body, headers={"Authorization": "ApplePass verkeerd0000000000"})
    assert bad.status_code == 401
    auth = {"Authorization": f"ApplePass {p['authenticationToken']}"}
    assert phone().post(url, json=body, headers=auth).status_code == 201
    assert phone().post(url, json=body, headers=auth).status_code == 200  # again: no duplicate

    other = signup(api, other_shop.business.slug, phone="06 99999999")
    op = pass_json(api, other_shop.business.slug, other)
    phone().post(
        reg_url("device2", op["serialNumber"]),
        json=body,
        headers={"Authorization": f"ApplePass {op['authenticationToken']}"},
    )
    listed = phone().get(f"/api/v1/wallet/apple/v1/devices/device1/registrations/{PASS_TYPE}")
    assert listed.json()["serialNumbers"] == [p["serialNumber"]]
    # Another shop's token never opens this pass.
    other_auth = {"Authorization": f"ApplePass {op['authenticationToken']}"}
    assert phone().post(url, json=body, headers=other_auth).status_code == 401


def test_a_stamp_pushes_and_the_phone_fetches_the_new_pass(
    api: Api, shop: Shop, wallet_keys: object, sent: dict
) -> None:  # type: ignore[type-arg]
    secret = signup(api, shop.business.slug)
    p = pass_json(api, shop.business.slug, secret)
    auth = {"Authorization": f"ApplePass {p['authenticationToken']}"}
    phone().post(reg_url("device1", p["serialNumber"]), json={"pushToken": TOKEN_A}, headers=auth)
    assert refresh(shop)["changed"] == 0  # nothing changed since the phone got it
    assert sent["apple"] == []

    first = phone().get(
        f"/api/v1/wallet/apple/v1/passes/{PASS_TYPE}/{p['serialNumber']}", headers=auth
    )
    modified = first.headers["Last-Modified"]
    same = phone().get(
        f"/api/v1/wallet/apple/v1/passes/{PASS_TYPE}/{p['serialNumber']}",
        headers={**auth, "If-Modified-Since": modified},
    )
    assert same.status_code == 304

    stamp(api, shop, secret)
    result = refresh(shop)
    assert (result["changed"], result["pushed"]) == (1, 1)
    assert sent["apple"] == [[TOKEN_A]]
    assert refresh(shop)["changed"] == 0  # pushed once, not every minute

    latest = phone().get(
        f"/api/v1/wallet/apple/v1/passes/{PASS_TYPE}/{p['serialNumber']}", headers=auth
    )
    assert latest.status_code == 200
    new = json.loads(zipfile.ZipFile(io.BytesIO(latest.content)).read("pass.json"))
    assert new["storeCard"]["primaryFields"][0]["value"].startswith("1 /")


def test_gone_devices_are_forgotten_and_unregister_works(
    api: Api, shop: Shop, wallet_keys: object, sent: dict
) -> None:  # type: ignore[type-arg]
    secret = signup(api, shop.business.slug)
    p = pass_json(api, shop.business.slug, secret)
    auth = {"Authorization": f"ApplePass {p['authenticationToken']}"}
    phone().post(reg_url("device1", p["serialNumber"]), json={"pushToken": TOKEN_B}, headers=auth)
    phone().post(reg_url("device2", p["serialNumber"]), json={"pushToken": TOKEN_C}, headers=auth)
    sent["gone"].append(TOKEN_B)
    stamp(api, shop, secret)
    assert refresh(shop)["gone"] == 1
    db = app_session(shop.business.id)
    assert [r.device_id for r in db.query(WalletRegistration).all()] == ["device2"]
    db.close()
    assert phone().delete(reg_url("device2", p["serialNumber"]), headers=auth).status_code == 200
    gone = phone().get(f"/api/v1/wallet/apple/v1/devices/device2/registrations/{PASS_TYPE}")
    assert gone.status_code == 204


def test_saved_google_pass_is_patched_after_a_change(
    api: Api, shop: Shop, wallet_keys: object, sent: dict
) -> None:  # type: ignore[type-arg]
    secret = signup(api, shop.business.slug)
    api.get(f"/api/v1/public/{shop.business.slug}/card/{secret}/wallet/google")
    db = app_session(shop.business.id)
    assert db.query(WalletPass).one().google_issued
    db.close()
    stamp(api, shop, secret)
    assert refresh(shop)["patched"] == 1
    assert len(sent["google"]) == 1


def test_unknown_pass_type_or_serial_is_not_found(
    api: Api, shop: Shop, wallet_keys: object
) -> None:
    assert phone().get("/api/v1/wallet/apple/v1/passes/pass.other/x.y").status_code == 404
    assert phone().get(f"/api/v1/wallet/apple/v1/passes/{PASS_TYPE}/geen-serie").status_code == 404
    assert phone().post("/api/v1/wallet/apple/v1/log", json={"logs": ["x"]}).status_code == 200
