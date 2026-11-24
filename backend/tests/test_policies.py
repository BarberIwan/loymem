"""Terms are chosen from fixed, lawyer-checked sentences."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from app.models import Business, CreditEvent, Plan, Subscription
from app.services import memberships, policies
from tests.conftest import Api, Shop, app_session, card
from tests.test_memberships import PLAN, bought, plan

ROOT = Path(__file__).resolve().parents[2]


def test_unknown_or_missing_rules_are_refused(new_client, shop: Shop) -> None:  # type: ignore[no-untyped-def]
    owner = new_client().login(shop.owner)
    for bad in ({"unused_rule": "nooit"}, {"no_show_rule": None}, {"unused_rule": None}):
        assert owner.post("/api/v1/plans", json={**PLAN, **bad}).status_code == 422, bad
    # A free text in place of a choice is ignored, never shown.
    p = plan(owner, unused_policy="Nooit geld terug, wat er ook gebeurt.")
    assert p["unused_policy"] == policies.UNUSED_MEMBERSHIP["expire_period"]


def test_plan_shows_the_chosen_sentences_and_a_new_choice_is_a_new_version(
    new_client, shop: Shop
) -> None:  # type: ignore[no-untyped-def]
    owner = new_client().login(shop.owner)
    p = plan(owner)
    assert p["no_show_policy"] == policies.NO_SHOW["no_show_counts"]
    assert p["pause_policy"] == policies.PAUSE
    changed = owner.put(f"/api/v1/plans/{p['id']}", json={**PLAN, "no_show_rule": "late_24h"})
    assert changed.json()["terms_version"] == 2
    assert changed.json()["no_show_policy"] == policies.NO_SHOW["late_24h"]
    bundle = plan(owner, kind="bundle", validity_days=180, unused_rule="roll_one_period")
    assert (bundle["unused_rule"], bundle["unused_policy"]) == (None, policies.UNUSED_BUNDLE)
    listed = owner.get("/api/v1/plans").json()["policy_options"]
    assert set(listed["no_show"]) == policies.NO_SHOW_RULES


def test_roll_over_keeps_one_period_and_expires_the_rest(
    api: Api, shop: Shop, fake, new_client
) -> None:  # type: ignore[no-untyped-def]
    secret, _ = bought(api, shop, fake, new_client, unused_rule="roll_one_period", credits=2)
    db = app_session(shop.business.id)
    sub = db.query(Subscription).one()
    sub.provider_mandate_id = "mdt_1"  # renewing
    sub.provider_customer_id = "cst_1"
    db.add(
        CreditEvent(
            business_id=sub.business_id,
            subscription_id=sub.id,
            kind="grant",
            delta=2,
            idempotency_key="grant:extra",
        )
    )  # four unused: two older, two from this period
    db.commit()
    db.close()
    db = app_session(shop.business.id)
    b = db.get(Business, shop.business.id)
    sub = db.query(Subscription).one()
    assert (
        memberships.daily(db, b, now=sub.period_end + timedelta(minutes=1))["renewals_started"] == 1
    )  # type: ignore[arg-type,operator]
    assert memberships.available(db, sub.id) == 2
    db.commit()
    db.close()
    assert card(api, shop.business.slug, secret)["memberships"]["subscriptions"][0]["credits"] == 2


def test_expire_period_rule_expires_everything(api: Api, shop: Shop, fake, new_client) -> None:  # type: ignore[no-untyped-def]
    bought(api, shop, fake, new_client)
    db = app_session(shop.business.id)
    b = db.get(Business, shop.business.id)
    sub = db.query(Subscription).one()
    memberships.daily(db, b, now=sub.period_end + timedelta(minutes=1))  # type: ignore[arg-type,operator]
    assert memberships.available(db, sub.id) == 0
    db.rollback()
    db.close()


def test_every_sentence_is_in_the_list_for_the_lawyer() -> None:
    doc = (ROOT / "docs" / "legal" / "voorwaarden-zinnen.md").read_text(encoding="utf-8")
    flat = " ".join(doc.split())
    missing = [s for s in policies.all_sentences() if " ".join(s.split()) not in flat]
    assert missing == []


def test_plan_model_rules_match_the_catalogue() -> None:
    checks = " ".join(str(c.sqltext) for c in Plan.__table__.constraints if hasattr(c, "sqltext"))
    for rule in policies.UNUSED_RULES | policies.NO_SHOW_RULES:
        assert f"'{rule}'" in checks
