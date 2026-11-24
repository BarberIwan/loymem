"""Tegoed: vooraf betaald saldo in euro's, eventueel met bonus.

Een plan van soort ``credit`` heeft een prijs (wat de klant betaalt) en een
waarde (wat hij kan besteden), hoogstens het dubbele van de prijs. Het saldo
staat in de nieuwe tabel ``balance_events``, alleen toevoegen, net als
``credit_events``: opwaarderen +, besteden -, terugdraaien + (wijst naar de
besteding, één keer), vervallen -.

Er worden geen rijen verplaatst of weggegooid. De downgrade weigert zolang er
tegoedplannen bestaan, want zonder die soort kan zo'n rij niet bestaan.
"""

import sqlalchemy as sa
from alembic import op

revision = "v009_tegoed"
down_revision = "v008_zaak_aanmelden"
branch_labels = None
depends_on = None

SCOPE = "nullif(current_setting('app.current_business_id', true), '')::uuid"


def upgrade() -> None:
    # A new enum value cannot be compared in the same transaction; the checks
    # below therefore compare kind as text.
    op.execute("alter type plan_kind add value if not exists 'credit'")
    op.add_column("plans", sa.Column("value_cents", sa.Integer(), nullable=True))
    op.drop_constraint("credits_range", "plans", type_="check")
    op.create_check_constraint(
        "credits_range",
        "plans",
        "(kind::text = 'credit' and credits = 0) or "
        "(kind::text <> 'credit' and credits between 1 and 100)",
    )
    op.create_check_constraint(
        "credit_value",
        "plans",
        "(kind::text = 'credit') = (value_cents is not null) and "
        "(value_cents is null or value_cents between price_cents and price_cents * 2)",
    )
    op.create_check_constraint(
        "credit_validity",
        "plans",
        "kind::text <> 'credit' or validity_days between 365 and 1095",
    )

    op.create_table(
        "balance_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("business_id", sa.UUID(), nullable=False),
        sa.Column("subscription_id", sa.UUID(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum("topup", "spend", "reversal", "expire", name="balance_kind"),
            nullable=False,
        ),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("reverses_id", sa.UUID(), nullable=True),
        sa.Column("staff_id", sa.UUID(), nullable=True),
        sa.Column("note", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(kind in ('topup', 'reversal') and amount_cents > 0) or "
            "(kind in ('spend', 'expire') and amount_cents < 0)",
            name="balance_sign",
        ),
        sa.CheckConstraint(
            "(kind = 'reversal') = (reverses_id is not null)", name="reversal_points_back"
        ),
        sa.CheckConstraint("kind <> 'reversal' or note is not null", name="reversal_has_reason"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(["subscription_id"], ["subscriptions.id"]),
        sa.ForeignKeyConstraint(["reverses_id"], ["balance_events.id"]),
        sa.ForeignKeyConstraint(["staff_id"], ["staff_members.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
        sa.UniqueConstraint("reverses_id"),
    )
    op.create_index(
        op.f("ix_balance_events_business_id"), "balance_events", ["business_id"], unique=False
    )
    op.create_index(
        op.f("ix_balance_events_subscription_id"),
        "balance_events",
        ["subscription_id"],
        unique=False,
    )
    op.execute("alter table balance_events enable row level security")
    op.execute("alter table balance_events force row level security")
    op.execute(
        f"create policy tenant_isolation on balance_events using (business_id = {SCOPE}) "
        f"with check (business_id = {SCOPE})"
    )
    op.execute(
        "create trigger balance_events_append_only before update or delete on "
        "balance_events for each row execute function loymem_refuse_change()"
    )
    op.execute("""
        do $$ begin
          if exists (select 1 from pg_roles where rolname = 'loymem_app') then
            grant select, insert on balance_events to loymem_app;
          end if;
        end $$;
    """)


def downgrade() -> None:
    op.execute("""
        do $$ begin
          if exists (select 1 from plans where kind::text = 'credit') then
            raise exception 'er bestaan tegoedplannen; terugdraaien zou ze weggooien';
          end if;
        end $$;
    """)
    op.drop_index(op.f("ix_balance_events_subscription_id"), table_name="balance_events")
    op.drop_index(op.f("ix_balance_events_business_id"), table_name="balance_events")
    op.drop_table("balance_events")
    op.execute("drop type if exists balance_kind")
    op.drop_constraint("credit_validity", "plans", type_="check")
    op.drop_constraint("credit_value", "plans", type_="check")
    op.drop_constraint("credits_range", "plans", type_="check")
    op.drop_column("plans", "value_cents")
    # The bundle check compares kind with a literal of the old type; it has to go
    # while the column changes type.
    op.drop_constraint("bundle_validity", "plans", type_="check")
    op.execute("alter type plan_kind rename to plan_kind_old")
    op.execute("create type plan_kind as enum ('membership', 'bundle')")
    op.execute("alter table plans alter column kind type plan_kind using kind::text::plan_kind")
    op.execute("drop type plan_kind_old")
    op.create_check_constraint("credits_range", "plans", "credits between 1 and 100")
    op.create_check_constraint(
        "bundle_validity", "plans", "kind <> 'bundle' or validity_days between 30 and 1095"
    )
