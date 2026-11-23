"""A new business signs up; owners manage staff."""

from __future__ import annotations

import pytest

from app.config import get_settings
from tests.conftest import Api, Shop

BODY = {
    "code": "pilot-2026",
    "business_name": "Salon Één",
    "owner_name": "Dafna",
    "email": "dafna@example.org",
    "password": "een-lang-wachtwoord",
}


@pytest.fixture
def open_signup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "signup_code", "pilot-2026")


def test_signup_is_closed_without_a_code(api: Api) -> None:
    assert api.post("/api/v1/business-signup", json=BODY).status_code == 404


def test_new_business_gets_a_working_card(api: Api, open_signup: None, new_client) -> None:  # type: ignore[no-untyped-def]
    assert api.post("/api/v1/business-signup", json={**BODY, "code": "fout"}).status_code == 403
    r = api.post("/api/v1/business-signup", json=BODY)
    assert r.status_code == 201 and r.json() == {"slug": "salon-een"}
    assert api.get("/api/v1/me").json()["role"] == "owner"
    public = new_client().get("/api/v1/public/salon-een").json()
    assert public["program"]["stamps_required"] == 10
    again = new_client().post(
        "/api/v1/business-signup", json={**BODY, "email": "ander@example.org"}
    )
    assert again.json() == {"slug": "salon-een-2"}
    dup = new_client().post("/api/v1/business-signup", json=BODY)
    assert dup.status_code == 400 and dup.json()["detail"] == "email_in_use"


def test_owner_deactivates_staff_who_then_cannot_sign_in(api: Api, shop: Shop, new_client) -> None:  # type: ignore[no-untyped-def]
    owner = new_client().login(shop.owner)
    assert owner.patch(f"/api/v1/staff/{shop.staff.id}", json={"active": False}).status_code == 200
    r = api.post(
        "/api/v1/auth/login", json={"email": shop.staff.email, "password": "een-lang-wachtwoord"}
    )
    assert r.status_code == 401
    assert owner.patch(f"/api/v1/staff/{shop.owner.id}", json={"active": False}).status_code == 400
    manager = new_client().login(shop.manager)
    assert manager.patch(f"/api/v1/staff/{shop.staff.id}", json={"active": True}).status_code == 403
