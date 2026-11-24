"""Which booking systems' notification mails we can read, and reading one.

Each system gets its own module with ``is_from(sender)`` and ``parse(...)``;
this file only picks the right one, so the core never names a provider.
"""

from __future__ import annotations

from app.integrations import salonized_mail
from app.integrations.salonized_mail import MailEvent, gmail_confirmation

__all__ = ["MailEvent", "gmail_confirmation", "read"]

READERS = (("salonized", salonized_mail),)

# Shown to the owner: which systems, and which sender to forward.
SYSTEMS = [{"name": "Salonized", "sender": "noreply@salonized.com"}]


def read(
    sender: str, subject: str, html: str, timezone: str
) -> tuple[str, MailEvent | None] | None:
    """(source, event) for a mail from a known system; None for any other sender."""
    for source, reader in READERS:
        if reader.is_from_salonized(sender):
            return source, reader.parse(subject, html, timezone)
    return None
