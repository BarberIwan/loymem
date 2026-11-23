"""Sending what sits in the outbox.

Provider-neutral: plain SMTP with STARTTLS, so any mail service works once its
address and keys are set (LOYMEM_EMAIL_DELIVERY=smtp, LOYMEM_SMTP_*,
LOYMEM_MAIL_FROM_ADDRESS). In log_only mode nothing leaves the server and the
message is marked as handled, so a test system never mails real customers.

Messages a customer can say no to (marketing, slot alerts) carry an unsubscribe
link and the List-Unsubscribe header. All customer text is escaped in the HTML.
"""

from __future__ import annotations

import hashlib
import hmac
import html
import logging
import smtplib
import uuid
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Business, ConsentPurpose, Customer, OutboxMessage, utcnow
from app.services import NotFound
from app.services.owner import set_consent

log = logging.getLogger("loymem.mail")
MAX_ATTEMPTS = 5
PURPOSE = {"campaign": ConsentPurpose.MARKETING, "slot_offer": ConsentPurpose.SLOT_ALERTS}
for _kind in ("inbox_due_for_visit", "inbox_reward_unused"):
    PURPOSE[_kind] = ConsentPurpose.MARKETING

SUBJECTS = {
    "card_reissue": "Je nieuwe kaartlink",
    "slot_offer": "Er is een plek vrij",
    "campaign": "Bericht van {business}",
    "inbox_due_for_visit": "Bericht van {business}",
    "inbox_reward_unused": "Je beloning staat klaar",
}
LINK_TEXT = {"card_reissue": "Open je kaart", "slot_offer": "Bekijk de plek"}


def unsubscribe_token(customer_id: uuid.UUID, purpose: ConsentPurpose) -> str:
    key = get_settings().secret_key.encode()
    mac = hmac.new(key, f"unsub:{customer_id}:{purpose.value}".encode(), hashlib.sha256)
    return f"{customer_id}.{purpose.value}.{mac.hexdigest()[:32]}"


def unsubscribe(db: Session, business: Business, token: str) -> ConsentPurpose:
    try:
        raw_id, purpose_value, _ = token.split(".")
        customer_id, purpose = uuid.UUID(raw_id), ConsentPurpose(purpose_value)
    except ValueError as exc:
        raise NotFound("link_invalid_or_expired") from exc
    if not hmac.compare_digest(unsubscribe_token(customer_id, purpose), token):
        raise NotFound("link_invalid_or_expired")
    customer = db.scalar(
        select(Customer).where(Customer.id == customer_id, Customer.business_id == business.id)
    )
    if customer is None:
        raise NotFound("link_invalid_or_expired")
    set_consent(db, customer, purpose, False, "unsubscribe_link")
    return purpose


def render(msg: OutboxMessage, business: Business) -> EmailMessage:
    s = get_settings()
    p = msg.payload
    text = str(p.get("text") or "")
    url = p.get("url")
    parts_text = [text] if text else []
    parts_html = [f"<p>{html.escape(text)}</p>"] if text else []
    if url:
        label = LINK_TEXT.get(msg.template, "Openen")
        parts_text.append(f"{label}: {url}")
        parts_html.append(
            f'<p><a href="{html.escape(str(url), quote=True)}">{html.escape(label)}</a></p>'
        )
    purpose = PURPOSE.get(msg.template)
    unsub_url = None
    if purpose and msg.customer_id:
        unsub_url = (
            f"{s.public_base_url}/afmelden/{business.slug}/"
            f"{unsubscribe_token(msg.customer_id, purpose)}"
        )
        parts_text.append(f"Geen berichten meer? {unsub_url}")
        parts_html.append(
            f'<p style="color:#6f685f;font-size:13px">'
            f'<a href="{html.escape(unsub_url, quote=True)}">Afmelden</a></p>'
        )
    em = EmailMessage()
    em["Subject"] = SUBJECTS.get(msg.template, "Bericht van {business}").format(
        business=business.name
    )
    em["From"] = formataddr((business.name, s.mail_from_address or "noreply@localhost"))
    em["To"] = msg.recipient
    em["Message-ID"] = make_msgid(domain=(s.mail_from_address.split("@")[-1] or "localhost"))
    if unsub_url:
        em["List-Unsubscribe"] = f"<{unsub_url}>"
    em.set_content("\n\n".join(parts_text))
    em.add_alternative("".join(parts_html), subtype="html")
    return em


def _deliver(em: EmailMessage) -> None:
    s = get_settings()
    with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=20) as smtp:
        smtp.starttls()
        if s.smtp_username:
            smtp.login(s.smtp_username, s.smtp_password)
        smtp.send_message(em)


def send_pending(db: Session, business: Business, limit: int = 100) -> dict[str, int]:
    s = get_settings()
    rows = db.scalars(
        select(OutboxMessage)
        .where(
            OutboxMessage.business_id == business.id,
            OutboxMessage.sent_at.is_(None),
            OutboxMessage.channel == "email",
            OutboxMessage.attempts < MAX_ATTEMPTS,
        )
        .order_by(OutboxMessage.created_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    ).all()
    sent = failed = 0
    for msg in rows:
        em = render(msg, business)
        try:
            if s.email_delivery == "smtp":
                _deliver(em)
            else:
                log.info("mail (log_only) to=%s subject=%s", msg.recipient, em["Subject"])
            msg.sent_at = utcnow()
            msg.last_error = None
            sent += 1
        except (smtplib.SMTPException, OSError) as exc:
            msg.attempts += 1
            msg.last_error = str(exc)[:300]
            failed += 1
            log.warning("mail failed id=%s attempt=%s: %s", msg.id, msg.attempts, exc)
    return {"sent": sent, "failed": failed}
