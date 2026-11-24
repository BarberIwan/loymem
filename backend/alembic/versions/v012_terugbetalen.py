"""Terugbetalen: vaste zin over geld terug, en terugbetalingen vastleggen.

- ``plans.refund_policy``: de vaste zin over geld terug (bedenktijd, en als de
  zaak stopt), zoals hij bij het opslaan van het plan luidde. Bestaande plannen
  krijgen een lege tekst tot ze opnieuw worden opgeslagen.
- ``refunds``: één terugbetaling per aankoop, met bedrag, reden en wie het deed.
- ``credit_kind`` en ``balance_kind`` krijgen ``refund``: wat terugbetaald is,
  gaat van het tegoed af onder die naam, zodat de klant het als terugbetaald ziet
  en niet als vervallen.

Er worden geen rijen verplaatst of weggegooid.
"""

import sqlalchemy as sa
from alembic import op

revision = "v012_terugbetalen"
down_revision = "v011_voorwaarden_keuzes"
branch_labels = None
depends_on = None

SCOPE = "nullif(current_setting('app.current_business_id', true), '')::uuid"


def upgrade() -> None:
    op.execute("alter type credit_kind add value if not exists 'refund'")
    op.execute("alter type balance_kind add value if not exists 'refund'")
    op.add_column("plans", sa.Column("refund_policy", sa.Text(), nullable=False, server_default=""))
    op.drop_constraint("balance_sign", "balance_events", type_="check")
    op.create_check_constraint(
        "balance_sign",
        "balance_events",
        "(kind::text in ('topup', 'reversal') and amount_cents > 0) or "
        "(kind::text in ('spend', 'expire', 'refund') and amount_cents < 0)",
    )
    op.create_table(
        "refunds",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("business_id", sa.UUID(), nullable=False),
        sa.Column("subscription_id", sa.UUID(), nullable=False),
        sa.Column("payment_id", sa.UUID(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("provider_refund_id", sa.String(length=60), nullable=True),
        sa.Column("reason", sa.String(length=40), nullable=False),
        sa.Column("staff_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount_cents > 0", name="refund_positive"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(["subscription_id"], ["subscriptions.id"]),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"]),
        sa.ForeignKeyConstraint(["staff_id"], ["staff_members.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("subscription_id"),
    )
    op.create_index(op.f("ix_refunds_business_id"), "refunds", ["business_id"], unique=False)
    op.execute("alter table refunds enable row level security")
    op.execute("alter table refunds force row level security")
    op.execute(
        f"create policy tenant_isolation on refunds using (business_id = {SCOPE}) "
        f"with check (business_id = {SCOPE})"
    )
    op.execute(
        "create trigger refunds_append_only before update or delete on refunds "
        "for each row execute function loymem_refuse_change()"
    )
    op.execute("""
        do $$ begin
          if exists (select 1 from pg_roles where rolname = 'loymem_app') then
            grant select, insert on refunds to loymem_app;
          end if;
        end $$;
    """)


def downgrade() -> None:
    op.execute("""
        do $$ begin
          if exists (select 1 from refunds) then
            raise exception 'er zijn terugbetalingen vastgelegd; terugdraaien zou ze weggooien';
          end if;
        end $$;
    """)
    op.drop_index(op.f("ix_refunds_business_id"), table_name="refunds")
    op.drop_table("refunds")
    op.drop_constraint("balance_sign", "balance_events", type_="check")
    op.create_check_constraint(
        "balance_sign",
        "balance_events",
        "(kind::text in ('topup', 'reversal') and amount_cents > 0) or "
        "(kind::text in ('spend', 'expire') and amount_cents < 0)",
    )
    op.drop_column("plans", "refund_policy")
    # Enum values cannot be removed without recreating the types; with no refunds
    # recorded no row uses 'refund', so the extra value is left in place.
