"""Demo data for local work and the click demo. Never run against production.

Usage: LOYMEM_DEMO_PASSWORD=... python scripts/seed_demo.py
Creates "Barber Iwan (demo)" with an owner, a staff member, two services and a
few customers at different points on their card.
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.models import (  # noqa: E402
    Business,
    CustomerSource,
    Program,
    Role,
    Service,
    StaffMember,
)
from app.security import hash_password  # noqa: E402
from app.services import cards, ledger  # noqa: E402
from app.services.cards import StaffContext  # noqa: E402

URL = os.environ.get(
    "LOYMEM_MIGRATION_URL", "postgresql+psycopg://loymem_owner:loymem_owner@localhost:5433/loymem"
)
if "prod" in URL or os.environ.get("LOYMEM_ENVIRONMENT") == "production":
    sys.exit("Niet tegen productie.")
PASSWORD = os.environ.get("LOYMEM_DEMO_PASSWORD")
if not PASSWORD:
    sys.exit("Zet LOYMEM_DEMO_PASSWORD.")

CUSTOMERS = [("Sam", 3, 0), ("Noor", 9, 0), ("Daan", 10, 0), ("Lisa", 6, 40), ("Milan", 1, 3)]


def main() -> None:
    engine = create_engine(URL)
    with Session(engine, expire_on_commit=False) as db, db.begin():
        if db.scalar(select(Business).where(Business.slug == "barber-iwan")):
            print("Bestaat al.")
            return
        b = Business(
            id=uuid.uuid4(),
            slug="barber-iwan",
            name="Barber Iwan",
            brand_colour="#20201E",
            booking_url="https://barberiwan.nl",
        )
        db.add(b)
        db.flush()
        owner = StaffMember(
            business_id=b.id,
            name="Iwan",
            email="eigenaar@demo.loymem.nl",
            role=Role.OWNER,
            password_hash=hash_password(PASSWORD),
        )
        staff = StaffMember(
            business_id=b.id,
            name="Ray",
            email="medewerker@demo.loymem.nl",
            role=Role.STAFF,
            password_hash=hash_password(PASSWORD),
        )
        cut = Service(business_id=b.id, name="Knippen", return_period_days=28)
        beard = Service(business_id=b.id, name="Baard", return_period_days=14)
        db.add_all(
            [
                owner,
                staff,
                cut,
                beard,
                Program(
                    business_id=b.id,
                    name="Stempelkaart",
                    stamps_required=10,
                    reward_description="een gratis knipbeurt",
                ),
            ]
        )
        db.flush()
        ctx = StaffContext(staff, b)
        links = []
        for i, (name, visits, days_ago) in enumerate(CUSTOMERS):
            issued = cards.create_customer(
                db,
                b,
                first_name=name,
                email=None,
                phone=f"06 1000 00{i:02d}",
                source=CustomerSource.SIGNUP,
            )
            start = datetime.now(UTC) - timedelta(days=days_ago + visits * 25)
            for v in range(visits):
                at = start + timedelta(days=v * 25)
                ledger.utcnow = lambda at=at: at  # type: ignore[misc]
                cards.utcnow = ledger.utcnow  # type: ignore[attr-defined]
                cards.stamp(db, ctx, issued.customer.id, cut.id if v % 3 else beard.id)
            links.append(f"/k/{b.slug}/{issued.card_secret}  ({name})")
        print("Kaarten:")
        print("\n".join(links))


if __name__ == "__main__":
    main()
