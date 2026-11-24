"""Every minute: push changed stamps and balances to wallet passes."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.db import session_factory, set_tenant  # noqa: E402
from app.integrations import wallet  # noqa: E402
from app.models import Business  # noqa: E402
from app.services import wallet_live  # noqa: E402


def main() -> int:
    if not (wallet.apple_configured() or wallet.google_configured()):
        return 0
    factory = session_factory()
    with factory() as db:
        businesses = list(db.scalars(select(Business)))
    failed = 0
    for business in businesses:
        try:
            with factory() as db, db.begin():
                set_tenant(db, business.id)
                result = wallet_live.refresh(db, db.merge(business, load=False))
            if result["changed"]:
                print(f"{business.slug}: {result}")
        except Exception as exc:  # noqa: BLE001 - report and carry on with the next one
            failed += 1
            print(f"{business.slug}: mislukt: {exc}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
