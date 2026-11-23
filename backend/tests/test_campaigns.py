"""Phase 1e: campaigns with a control group and an honest report."""

from __future__ import annotations

from sqlalchemy import select, text

from app.models import CampaignMember, Customer
from tests.conftest import Api, Clock, Shop, app_session, card, scan, signup

MSG = {
    "name": "Terugkom",
    "audience": "all_consented",
    "message": "Hoi, kom je weer eens langs? Boeken kan via de site.",
}


def consented(api: Api, shop: Shop, n: int) -> dict[str, str]:
    """Returns customer id -> card secret."""
    out = {}
    for i in range(n):
        s = signup(
            api,
            shop.business.slug,
            phone=f"0640{i:06d}",
            email=f"c{i}@example.org",
            marketing_consent=True,
            first_name=f"C{i}",
        )
        out[s] = s
    db = app_session(shop.business.id)
    ids = {str(c.id): c.email for c in db.scalars(select(Customer))}
    db.close()
    secrets = list(out)
    return {cid: secrets[int(email[1:].split("@")[0])] for cid, email in ids.items()}


def members(shop: Shop) -> dict[str, bool]:
    db = app_session(shop.business.id)
    rows = {str(m.customer_id): m.holdout for m in db.scalars(select(CampaignMember))}
    db.close()
    return rows


def test_campaign_holdout_never_receives_message(
    api: Api, shop: Shop, clock: Clock, new_client
) -> None:  # type: ignore[no-untyped-def]
    consented(api, shop, 40)
    signup(api, shop.business.slug, phone="0649999999", email="geen@example.org")
    owner = new_client().login(shop.owner)
    cid = owner.post("/api/v1/campaigns", json={**MSG, "holdout_percent": 20}).json()["id"]
    groups = members(shop)
    assert len(groups) == 40  # the customer without consent is not in the audience
    holdout = {c for c, h in groups.items() if h}
    assert 0 < len(holdout) < 40
    sent = owner.post(f"/api/v1/campaigns/{cid}/send").json()["sent"]
    assert sent == 40 - len(holdout)
    db = app_session(shop.business.id)
    recipients = set(
        db.execute(text("select recipient from outbox where template='campaign'")).scalars()
    )
    emails = {str(c.id): c.email for c in db.scalars(select(Customer))}
    db.close()
    assert not {emails[c] for c in holdout} & recipients
    assert "geen@example.org" not in recipients
    assert owner.post(f"/api/v1/campaigns/{cid}/send").status_code == 409


def _run(
    api: Api, shop: Shop, clock: Clock, owner: Api, n: int, treated_back: float, control_back: float
) -> dict:  # type: ignore[type-arg]
    secrets = consented(api, shop, n)
    cid = owner.post("/api/v1/campaigns", json={**MSG, "holdout_percent": 50}).json()["id"]
    owner.post(f"/api/v1/campaigns/{cid}/send")
    groups = members(shop)
    clock.advance(days=2)
    api.login(shop.staff)
    for group, share in ((False, treated_back), (True, control_back)):
        ids = sorted(c for c, h in groups.items() if h is group)
        for c in ids[: round(len(ids) * share)]:
            token = card(api, shop.business.slug, secrets[c])["scan_token"]
            api.post("/api/v1/stamps", json={"customer_id": scan(api, token)["customer_id"]})
    clock.advance(days=40)
    return owner.get(f"/api/v1/campaigns/{cid}/report").json()  # type: ignore[no-any-return]


def test_report_says_not_demonstrable_without_significant_difference(
    api: Api,
    shop: Shop,
    clock: Clock,
    new_client,  # type: ignore[no-untyped-def]
) -> None:
    r = _run(api, shop, clock, new_client().login(shop.owner), 80, 0.30, 0.25)
    assert r["verdict"] == "not_demonstrable"
    assert "estimated_extra_visits" not in r
    assert r["observed"]["returned"] > 0


def test_report_states_effect_only_when_it_holds(
    api: Api, shop: Shop, clock: Clock, new_client
) -> None:  # type: ignore[no-untyped-def]
    r = _run(api, shop, clock, new_client().login(shop.owner), 100, 0.7, 0.1)
    assert r["verdict"] == "demonstrable" and r["estimated_extra_visits"] > 0


def test_small_campaign_is_too_small_to_judge(
    api: Api, shop: Shop, clock: Clock, new_client
) -> None:  # type: ignore[no-untyped-def]
    r = _run(api, shop, clock, new_client().login(shop.owner), 12, 1.0, 0.0)
    assert r["verdict"] == "too_small" and "estimated_extra_visits" not in r


def test_report_waits_for_the_window(api: Api, shop: Shop, clock: Clock, new_client) -> None:  # type: ignore[no-untyped-def]
    consented(api, shop, 3)
    owner = new_client().login(shop.owner)
    cid = owner.post("/api/v1/campaigns", json=MSG).json()["id"]
    owner.post(f"/api/v1/campaigns/{cid}/send")
    assert owner.get(f"/api/v1/campaigns/{cid}/report").json()["verdict"] == "window_open"


def test_campaigns_are_for_owner_and_manager(api: Api, shop: Shop) -> None:
    api.login(shop.staff)
    assert api.get("/api/v1/campaigns").status_code == 403
    assert api.post("/api/v1/campaigns", json=MSG).status_code == 403
