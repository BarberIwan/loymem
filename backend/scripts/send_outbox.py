"""Send pending email from the outbox. Run every minute (cron or a timer)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.db import session_factory, set_tenant  # noqa: E402
from app.models import Business  # noqa: E402
from app.services.mailer import send_pending  # noqa: E402


def main() -> int:
    factory = session_factory()
    with factory() as db:
        businesses = list(db.scalars(select(Business)))
    failed = 0
    for business in businesses:
        with factory() as db, db.begin():
            set_tenant(db, business.id)
            result = send_pending(db, db.merge(business, load=False))
        failed += result["failed"]
        if result["sent"] or result["failed"]:
            print(f"{business.slug}: {result}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
