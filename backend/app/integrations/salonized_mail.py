"""Reading Salonized notification mails.

Salonized has no public API. It does mail the business about every online
booking, every online move and every cancellation. A business forwards those
mails to its own inbound address with us; this module turns one mail into an
appointment event. Nothing else of the mail is kept.

Layout as Salonized sends it in Dutch (checked against real mails, November
2026). Only these three mails are understood; anything else is ignored.

- "Nieuwe online afspraak bij <zaak>": table rows Tijd, Klant (Naam,
  E-mailadres, Mobiel nummer), Diensten (naam, medewerker, duur) and a link
  ending in /calendar/appointment/<id>.
- "Afspraak online verplaatst": Vorig tijdstip, Nieuw tijdstip, Klant, link.
- "Afspraak geannuleerd": one paragraph, "Je klant <naam> heeft net een afspraak
  geannuleerd. Datum: 26 november 2026 om 09:00 Diensten: ...". No id, no contact.

Mails are in the business's language; English labels are accepted too, but only
the Dutch layout is verified.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

SENDER_DOMAIN = "salonized.com"

MONTHS = {
    "januari": 1, "februari": 2, "maart": 3, "april": 4, "mei": 5, "juni": 6,
    "juli": 7, "augustus": 8, "september": 9, "oktober": 10, "november": 11, "december": 12,
    "january": 1, "february": 2, "march": 3, "may": 5, "june": 6, "july": 7,
    "august": 8, "october": 10,
}  # fmt: skip

LABELS = {
    "time": ("tijd", "time"),
    "previous": ("vorig tijdstip", "previous time"),
    "new_time": ("nieuw tijdstip", "new time"),
    "name": ("naam", "name"),
    "email": ("e-mailadres", "email address", "email"),
    "phone": ("mobiel nummer", "mobile number", "phone number"),
}


@dataclass(frozen=True)
class MailEvent:
    kind: str  # booked | moved | cancelled
    starts_at: datetime
    ends_at: datetime | None
    previous_starts_at: datetime | None
    external_id: str | None
    name: str | None
    email: str | None
    phone: str | None
    service: str | None
    staff: str | None


class _Text(HTMLParser):
    """Visible text as lines, plus every link."""

    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []
        self.links: list[str] = []
        self._buf: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("style", "script", "head"):
            self._skip += 1
        if tag == "a":
            self.links += [v for k, v in attrs if k == "href" and v]
        if tag in ("td", "th", "p", "br", "tr", "h1", "h2", "h3", "h4", "div", "li"):
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if tag in ("style", "script", "head"):
            self._skip = max(0, self._skip - 1)
        if tag in ("td", "th", "p", "tr", "h1", "h2", "h3", "h4", "div", "li"):
            self._flush()

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self._buf.append(data)

    def _flush(self) -> None:
        text = " ".join("".join(self._buf).split())
        if text:
            self.lines.append(text)
        self._buf = []

    def close(self) -> None:
        super().close()
        self._flush()


def _text(html: str) -> tuple[list[str], list[str]]:
    p = _Text()
    p.feed(html)
    p.close()
    return p.lines, p.links


def _after(lines: list[str], labels: tuple[str, ...], start: int = 0) -> str | None:
    for i in range(start, len(lines) - 1):
        if lines[i].strip().lower() in labels:
            return lines[i + 1].strip()
    return None


DATE = re.compile(
    r"(\d{1,2})\s+([a-z]+)\s+(\d{4})\s*(?:,|om|at)?\s*(\d{1,2}):(\d{2})"
    r"(?:\s*-\s*(\d{1,2}):(\d{2}))?",
    re.IGNORECASE,
)


def _when(value: str | None, tz: ZoneInfo) -> tuple[datetime, datetime | None] | None:
    if not value:
        return None
    m = DATE.search(value)
    if not m or m.group(2).lower() not in MONTHS:
        return None
    day, month, year = int(m.group(1)), MONTHS[m.group(2).lower()], int(m.group(3))
    start = datetime(year, month, day, int(m.group(4)), int(m.group(5)), tzinfo=tz)
    end = None
    if m.group(6):
        end = start.replace(hour=int(m.group(6)), minute=int(m.group(7)))
        if end <= start:
            end += timedelta(days=1)
    return start, end


def _appointment_id(links: list[str]) -> str | None:
    for link in links:
        m = re.search(r"/calendar/appointment/(\d{1,20})", link)
        if m:
            return m.group(1)
    return None


def _service_and_staff(lines: list[str]) -> tuple[str | None, str | None]:
    """First row under the Diensten header (Naam, Medewerker, Duur)."""
    for i, line in enumerate(lines):
        if line.lower() in ("diensten", "services") and i + 4 < len(lines):
            head = [x.lower() for x in lines[i + 1 : i + 4]]
            if head[:2] in (["naam", "medewerker"], ["name", "employee"]):
                service = lines[i + 4].lstrip("•· \t").strip()
                staff = lines[i + 5].strip() if i + 5 < len(lines) else None
                return service[:120] or None, (staff or None) and staff[:60]
    return None, None


def is_from_salonized(sender: str) -> bool:
    address = sender.strip().lower().rsplit("<", 1)[-1].rstrip(">")
    return address.endswith("@" + SENDER_DOMAIN) or address.endswith("." + SENDER_DOMAIN)


def parse(subject: str, html: str, timezone: str = "Europe/Amsterdam") -> MailEvent | None:
    tz = ZoneInfo(timezone)
    s = subject.strip().lower()
    lines, links = _text(html)
    if s.startswith(("nieuwe online afspraak", "new online appointment")):
        when = _when(_after(lines, LABELS["time"]), tz)
        kind = "booked"
        previous = None
    elif s.startswith(("afspraak online verplaatst", "appointment rescheduled")):
        when = _when(_after(lines, LABELS["new_time"]), tz)
        prev = _when(_after(lines, LABELS["previous"]), tz)
        previous = prev[0] if prev else None
        kind = "moved"
    elif s.startswith(("afspraak geannuleerd", "appointment cancelled", "appointment canceled")):
        body = " ".join(lines)
        m = re.search(
            r"(?:je klant|your client)\s+(.+?)\s+(?:heeft net|has just)", body, re.IGNORECASE
        )
        d = re.search(r"(?:datum|date):\s*([^:]+?\d{1,2}:\d{2})", body, re.IGNORECASE)
        when = _when(d.group(1) if d else None, tz)
        if when is None:
            return None
        return MailEvent(
            "cancelled",
            when[0],
            None,
            None,
            _appointment_id(links),
            (m.group(1).strip()[:120] if m else None),
            None,
            None,
            None,
            None,
        )
    else:
        return None
    if when is None:
        return None
    # Customer fields sit after the "Klant" header; the location row also says "Naam"-less.
    klant = next((i for i, x in enumerate(lines) if x.lower() in ("klant", "client")), 0)
    service, staff = _service_and_staff(lines)
    return MailEvent(
        kind,
        when[0],
        when[1],
        previous,
        _appointment_id(links),
        _after(lines, LABELS["name"], klant),
        _after(lines, LABELS["email"], klant),
        _after(lines, LABELS["phone"], klant),
        service,
        staff,
    )


GMAIL_CODE = re.compile(r"(?:confirmation code|bevestigingscode):\s*(\d{6,12})", re.IGNORECASE)


def gmail_confirmation(sender: str, subject: str, text: str) -> str | None:
    """Gmail asks to confirm a forwarding address with a code mailed to it."""
    if "forwarding-noreply@google.com" not in sender.lower():
        return None
    m = GMAIL_CODE.search(text) or GMAIL_CODE.search(subject)
    return m.group(1) if m else None
