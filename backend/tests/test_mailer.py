"""Sending email from the outbox."""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.models import Business, Customer, OutboxMessage
from app.services import mailer
from tests.conftest import Api, Shop, app_session, card, signup


def outbox_for(shop: Shop, **kw: object) -> None:
    db = app_session(shop.business.id)
    cid = db.scalar(select(Customer.id))
    db.add(
        OutboxMessage(
            business_id=shop.business.id,
            channel="email",
            recipient="sam@example.org",
            customer_id=cid,
            **kw,
        )
    )
    db.commit()
    db.close()


def send(shop: Shop) -> dict[str, int]:
    db = app_session(shop.business.id)
    b = db.get(Business, shop.business.id)
    assert b is not None
    r = mailer.send_pending(db, b)
    db.commit()
    db.close()
    return r


class FakeSMTP:
    sent: list[EmailMessage] = []
    fail = False

    def __init__(self, *a: object, **k: object) -> None: ...
    def __enter__(self) -> FakeSMTP:
        return self

    def __exit__(self, *a: object) -> None: ...
    def starttls(self) -> None: ...
    def login(self, *a: object) -> None: ...

    def send_message(self, em: EmailMessage) -> None:
        if FakeSMTP.fail:
            raise smtplib.SMTPServerDisconnected("down")
        FakeSMTP.sent.append(em)


@pytest.fixture
def smtp(monkeypatch: pytest.MonkeyPatch) -> type[FakeSMTP]:
    FakeSMTP.sent, FakeSMTP.fail = [], False
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    s = get_settings()
    monkeypatch.setattr(s, "email_delivery", "smtp")
    monkeypatch.setattr(s, "mail_from_address", "post@loymem.example")
    return FakeSMTP


def test_marketing_mail_is_escaped_and_can_be_unsubscribed(
    api: Api, shop: Shop, smtp: type[FakeSMTP]
) -> None:
    secret = signup(api, shop.business.slug, email="sam@example.org", marketing_consent=True)
    outbox_for(shop, template="campaign", payload={"text": "Kom langs <script>x</script>"})
    assert send(shop) == {"sent": 1, "failed": 0}
    em = smtp.sent[0]
    body = em.get_body(("html",))
    assert body is not None and "<script>" not in body.get_content()
    assert "&lt;script&gt;" in body.get_content()
    link = em["List-Unsubscribe"].strip("<>")
    token = link.rsplit("/", 1)[-1]
    assert card(api, shop.business.slug, secret)["marketing"] is True
    r = api.post(f"/api/v1/public/{shop.business.slug}/afmelden/{token}")
    assert r.json() == {"purpose": "marketing"}
    assert card(api, shop.business.slug, secret)["marketing"] is False
    assert (
        api.post(f"/api/v1/public/{shop.business.slug}/afmelden/{token[:-1]}x").status_code == 404
    )


def test_service_mail_has_no_unsubscribe(api: Api, shop: Shop, smtp: type[FakeSMTP]) -> None:
    signup(api, shop.business.slug, email="sam@example.org")
    outbox_for(shop, template="card_reissue", payload={"url": "https://x.example/k/a/b"})
    send(shop)
    assert smtp.sent[0]["List-Unsubscribe"] is None


def test_failed_mail_is_retried_then_left(api: Api, shop: Shop, smtp: type[FakeSMTP]) -> None:
    signup(api, shop.business.slug, email="sam@example.org")
    outbox_for(shop, template="card_reissue", payload={"url": "https://x.example"})
    smtp.fail = True
    for _ in range(mailer.MAX_ATTEMPTS):
        assert send(shop) == {"sent": 0, "failed": 1}
    assert send(shop) == {"sent": 0, "failed": 0}  # given up, waits for someone to look
    db = app_session(shop.business.id)
    row = db.scalar(select(OutboxMessage))
    db.close()
    assert row is not None and row.attempts == 5 and row.last_error == "down"


def test_log_only_sends_nothing(api: Api, shop: Shop, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(smtplib, "SMTP", None)  # any real attempt would crash
    signup(api, shop.business.slug, email="sam@example.org")
    outbox_for(shop, template="card_reissue", payload={"url": "https://x.example"})
    assert send(shop) == {"sent": 1, "failed": 0}


def test_unsubscribe_token_is_per_business(
    api: Api, shop: Shop, other_shop: Shop, smtp: type[FakeSMTP]
) -> None:
    signup(api, shop.business.slug, email="sam@example.org", marketing_consent=True)
    outbox_for(shop, template="campaign", payload={"text": "Hoi"})
    send(shop)
    token = smtp.sent[0]["List-Unsubscribe"].strip("<>").rsplit("/", 1)[-1]
    r = api.post(f"/api/v1/public/{other_shop.business.slug}/afmelden/{token}")
    assert r.status_code == 404
