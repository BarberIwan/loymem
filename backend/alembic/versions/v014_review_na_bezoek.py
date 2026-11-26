"""Een reviewverzoek na ieder bezoek.

- ``businesses.review_url``: de link waar de klant een review achterlaat (de
  "schrijf een review"-link van het Google-bedrijfsprofiel, of een andere
  https-link). Leeg betekent uit, en dat is wat elke bestaande zaak krijgt.
- ``businesses.review_request_days``: de rust die een vaste klant krijgt.
  Standaard ``0``: na ieder bezoek.
- ``outbox.send_after``: niet versturen voor dit moment. Leeg bij alle
  bestaande berichten, dus die gaan ongewijzigd mee met de eerste ronde.

Er worden geen rijen verplaatst of weggegooid.
"""

import sqlalchemy as sa
from alembic import op

revision = "v014_review_na_bezoek"
down_revision = "v013_afspraken_uit_mail"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("businesses", sa.Column("review_url", sa.String(length=500), nullable=True))
    op.add_column(
        "businesses",
        sa.Column(
            "review_request_days",
            sa.SmallInteger(),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_check_constraint(
        "review_request_days_range",
        "businesses",
        "review_request_days between 0 and 3650",
    )
    op.add_column("outbox", sa.Column("send_after", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("outbox", "send_after")
    op.drop_constraint("review_request_days_range", "businesses", type_="check")
    op.drop_column("businesses", "review_request_days")
    op.drop_column("businesses", "review_url")
