"""A review request after every visit: only with a link, and only with consent."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app.models import Business, OutboxMessage, utcnow
from app.services import mailer, reviews
from tests.conftest import Api, Clock, Shop, app_session, card, scan, signup

LINK = "https://g.page/r/barber-iwan/review"


def set_link(api: Api, shop: Shop, url: str | None = LINK, **body: object) -> dict:  # type: ignore[type-arg]
    api.login(shop.owner)
    r = api.patch("/api/v1/settings", json={"review_url": url, **body})
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


def visit(api: Api, shop: Shop, secret: str) -> dict:  # type: ignore[type-arg]
    api.login(shop.staff)
    info = scan(api, card(api, shop.business.slug, secret)["scan_token"])
    r = api.post("/api/v1/stamps", json={"customer_id": info["customer_id"]})
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


def requests_of(shop: Shop) -> list[dict]:  # type: ignore[type-arg]
    db = app_session(shop.business.id)
    rows = [
        {
            "recipient": m.recipient,
            "payload": m.payload,
            "send_after": m.send_after,
            "sent_at": m.sent_at,
        }
        for m in db.scalars(
            select(OutboxMessage)
            .where(OutboxMessage.template == reviews.TEMPLATE)
            .order_by(OutboxMessage.created_at)
        )
    ]
    db.close()
    return rows


def customer(api: Api, shop: Shop, consent: bool = True) -> str:
    return signup(
        api,
        shop.business.slug,
        email="sam@example.org",
        marketing_consent=consent,
    )


def test_no_request_while_the_shop_has_no_link(api: Api, shop: Shop, clock: Clock) -> None:
    secret = customer(api, shop)
    assert visit(api, shop, secret)["stamped"]
    assert requests_of(shop) == []


def test_every_visit_asks_once(api: Api, shop: Shop, clock: Clock) -> None:
    secret = customer(api, shop)
    set_link(api, shop)
    assert visit(api, shop, secret)["stamped"]
    first = requests_of(shop)
    assert len(first) == 1
    assert first[0]["recipient"] == "sam@example.org"
    assert first[0]["payload"]["url"] == LINK
    assert shop.business.name in str(first[0]["payload"]["text"])
    # Not while the customer is still at the counter.
    assert first[0]["send_after"] == clock.now + reviews.DELAY

    # The same day is the same visit: no second request.
    assert not visit(api, shop, secret)["stamped"]
    assert len(requests_of(shop)) == 1

    clock.advance(days=1)
    assert visit(api, shop, secret)["stamped"]
    assert len(requests_of(shop)) == 2


def test_no_request_without_marketing_consent(api: Api, shop: Shop, clock: Clock) -> None:
    secret = customer(api, shop, consent=False)
    set_link(api, shop)
    assert visit(api, shop, secret)["stamped"]
    assert requests_of(shop) == []


def test_rest_period_skips_the_next_visits(api: Api, shop: Shop, clock: Clock) -> None:
    secret = customer(api, shop)
    assert set_link(api, shop, review_request_days=180)["review_request_days"] == 180
    assert visit(api, shop, secret)["stamped"]
    clock.advance(days=30)
    assert visit(api, shop, secret)["stamped"]
    assert len(requests_of(shop)) == 1


def test_emptying_the_link_switches_it_off(api: Api, shop: Shop, clock: Clock) -> None:
    secret = customer(api, shop)
    set_link(api, shop)
    assert set_link(api, shop, url=None)["review_url"] is None
    assert visit(api, shop, secret)["stamped"]
    assert requests_of(shop) == []


def test_http_link_refused(api: Api, shop: Shop) -> None:
    api.login(shop.owner)
    r = api.patch("/api/v1/settings", json={"review_url": "http://example.org/review"})
    assert r.status_code == 422, r.text


def send(shop: Shop) -> dict[str, int]:
    db = app_session(shop.business.id)
    b = db.get(Business, shop.business.id)
    assert b is not None
    result = mailer.send_pending(db, b)
    db.commit()
    db.close()
    return result


def test_mail_waits_for_send_after_and_can_be_unsubscribed(api: Api, shop: Shop) -> None:
    """No clock here: the visit is now, so the request is still in its two hours."""
    secret = customer(api, shop)
    set_link(api, shop)
    assert visit(api, shop, secret)["stamped"]
    assert send(shop) == {"sent": 0, "failed": 0}
    assert requests_of(shop)[0]["sent_at"] is None

    db = app_session(shop.business.id)
    msg = db.scalar(select(OutboxMessage).where(OutboxMessage.template == reviews.TEMPLATE))
    assert msg is not None
    b = db.get(Business, shop.business.id)
    assert b is not None
    rendered = mailer.render(msg, b)
    body = rendered.get_body(preferencelist=("plain",))
    assert body is not None
    text = body.get_content()
    assert LINK in text and "afmelden/" in text
    assert rendered["List-Unsubscribe"]
    msg.send_after = utcnow() - timedelta(minutes=1)
    db.commit()
    db.close()

    assert send(shop) == {"sent": 1, "failed": 0}
    assert requests_of(shop)[0]["sent_at"] is not None
