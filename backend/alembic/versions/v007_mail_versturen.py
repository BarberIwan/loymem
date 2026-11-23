"""Mail versturen: de uitgaande wachtrij krijgt klant, pogingen en laatste fout.

Drie kolommen op ``outbox`` (twee nullable, een met standaard 0) en een index.
Er worden geen rijen verplaatst of weggegooid.
"""

import sqlalchemy as sa
from alembic import op

revision = "v007_mail_versturen"
down_revision = "v006_campagnes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("outbox", sa.Column("customer_id", sa.UUID(), nullable=True))
    op.add_column(
        "outbox", sa.Column("attempts", sa.SmallInteger(), server_default="0", nullable=False)
    )
    op.add_column("outbox", sa.Column("last_error", sa.String(length=300), nullable=True))
    op.create_index(
        "ix_outbox_pending", "outbox", ["business_id", "sent_at", "attempts"], unique=False
    )
    op.create_foreign_key("fk_outbox_customer", "outbox", "customers", ["customer_id"], ["id"])


def downgrade() -> None:
    # WARNING: constraint name is None; this directive will fail as
    # rendered.  Add a name, or use a naming convention; see
    # https://alembic.sqlalchemy.org/en/latest/naming.html
    op.drop_constraint("fk_outbox_customer", "outbox", type_="foreignkey")
    op.drop_index("ix_outbox_pending", table_name="outbox")
    op.drop_column("outbox", "last_error")
    op.drop_column("outbox", "attempts")
    op.drop_column("outbox", "customer_id")
