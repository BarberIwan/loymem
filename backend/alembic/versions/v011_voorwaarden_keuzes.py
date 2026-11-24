"""Voorwaarden kiezen in plaats van zelf schrijven.

Twee kolommen op ``plans``: ``unused_rule`` en ``no_show_rule``, de gekozen
optie uit de vaste lijst (``app/services/policies.py``). De tekst die de klant
ziet en accepteert blijft in de bestaande tekstkolommen staan, zoals hij bij het
opslaan was. Bestaande plannen houden hun tekst en krijgen geen keuze (leeg).
Er worden geen rijen verplaatst of weggegooid.
"""

import sqlalchemy as sa
from alembic import op

revision = "v011_voorwaarden_keuzes"
down_revision = "v010_wallet_live"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("plans", sa.Column("unused_rule", sa.String(length=30), nullable=True))
    op.add_column("plans", sa.Column("no_show_rule", sa.String(length=30), nullable=True))
    op.create_check_constraint(
        "unused_rule_known",
        "plans",
        "unused_rule is null or unused_rule in ('expire_period', 'roll_one_period')",
    )
    op.create_check_constraint(
        "no_show_rule_known",
        "plans",
        "no_show_rule is null or no_show_rule in "
        "('free', 'no_show_counts', 'late_24h', 'late_24h_first_free')",
    )
    # Rolling over only means something for a membership that renews.
    op.create_check_constraint(
        "roll_only_membership",
        "plans",
        "unused_rule is null or kind::text = 'membership'",
    )


def downgrade() -> None:
    op.drop_constraint("roll_only_membership", "plans", type_="check")
    op.drop_constraint("no_show_rule_known", "plans", type_="check")
    op.drop_constraint("unused_rule_known", "plans", type_="check")
    op.drop_column("plans", "no_show_rule")
    op.drop_column("plans", "unused_rule")
