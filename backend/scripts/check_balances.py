"""Nightly check: every card balance must equal the sum of its ledger.

Runs per business inside its own tenant scope. Exit code 1 when any balance
differs, so the scheduler marks the run red. It reports; it never repairs.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.db import session_factory, set_tenant  # noqa: E402
from app.models import Business  # noqa: E402
from app.services.ledger import balance_mismatches  # noqa: E402


def main() -> int:
    factory = session_factory()
    with factory() as db:
        ids = list(db.scalars(select(Business.id)))
    bad = 0
    for business_id in ids:
        with factory() as db, db.begin():
            set_tenant(db, business_id)
            wrong = balance_mismatches(db, business_id)
        if wrong:
            bad += len(wrong)
            print(f"{business_id}: {len(wrong)} saldo's wijken af van het logboek")
    print("klopt" if not bad else f"{bad} afwijkingen")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
