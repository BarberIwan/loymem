"""A review request after a visit.

Off until the owner fills in the review link (the "write a review" link from
the Google business profile, or any other https link). From then on every visit
that gets a stamp queues one mail, a couple of hours later so the customer has
left the chair, and only for customers who may be mailed: a review request is
nice to have, not a necessary message, so it needs marketing consent and it
carries an unsubscribe link like any other marketing mail.

``business.review_request_days`` is the rest a regular gets: 0 asks after every
visit, 180 asks a four-weekly customer twice a year.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Business,
    ConsentPurpose,
    ConsentRecord,
    ConsentStatus,
    Customer,
    OutboxMessage,
)

TEMPLATE = "review_request"
# Long enough that the customer has paid and left, short enough to be the same day.
DELAY = timedelta(hours=2)
TEXT = (
    "Bedankt voor je bezoek bij {business}. Heb je een half minuutje? "
    "Met een review help je andere klanten ons te vinden."
)


def _has_marketing_consent(db: Session, customer_id: uuid.UUID) -> bool:
    latest = db.scalar(
        select(ConsentRecord.status)
        .where(
            ConsentRecord.customer_id == customer_id,
            ConsentRecord.purpose == ConsentPurpose.MARKETING,
        )
        .order_by(ConsentRecord.created_at.desc())
        .limit(1)
    )
    return latest == ConsentStatus.GRANTED


def _asked_recently(db: Session, business: Business, customer: Customer, at: datetime) -> bool:
    days = business.review_request_days
    if days <= 0:
        return False
    return (
        db.scalar(
            select(OutboxMessage.id)
            .where(
                OutboxMessage.business_id == business.id,
                OutboxMessage.customer_id == customer.id,
                OutboxMessage.template == TEMPLATE,
                OutboxMessage.created_at >= at - timedelta(days=days),
            )
            .limit(1)
        )
        is not None
    )


def queue_review_request(db: Session, business: Business, customer: Customer, at: datetime) -> bool:
    """Put one review request in the outbox for this visit. Tells whether it did."""
    if not business.review_url or not customer.email or customer.anonymised_at is not None:
        return False
    if not _has_marketing_consent(db, customer.id):
        return False
    if _asked_recently(db, business, customer, at):
        return False
    db.add(
        OutboxMessage(
            customer_id=customer.id,
            business_id=business.id,
            channel="email",
            recipient=customer.email,
            template=TEMPLATE,
            payload={"text": TEXT.format(business=business.name), "url": business.review_url},
            send_after=at + DELAY,
        )
    )
    return True
