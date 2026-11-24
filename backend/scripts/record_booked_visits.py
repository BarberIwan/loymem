"""Every minute: past appointments from booking mails count as visits, if the business chose so."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.db import session_factory, set_tenant  # noqa: E402
from app.models import Business  # noqa: E402
from app.services import booking_mail  # noqa: E402


def main() -> int:
    factory = session_factory()
    with factory() as db:
        businesses = list(db.scalars(select(Business)))
    failed = 0
    for business in businesses:
        try:
            with factory() as db, db.begin():
                set_tenant(db, business.id)
                result = booking_mail.record_visits(db, db.merge(business, load=False))
            if result:
                print(f"{business.slug}: {result} bezoek(en)")
        except Exception as exc:  # noqa: BLE001 - report and carry on with the next one
            failed += 1
            print(f"{business.slug}: mislukt: {exc}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
