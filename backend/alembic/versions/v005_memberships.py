"""Memberships en bundels (fase 1d): plannen, abonnementen, betalingen, credits.

Vijf nieuwe tabellen met RLS. ``credit_events`` is alleen toevoegen, net als
``ledger_events``. ``provider_connections`` bewaart de tokens van het eigen
betaalaccount van de zaak versleuteld. Er worden geen rijen verplaatst of
weggegooid. Verkopen staat uit tot de juridische toets (``LOYMEM_MEMBERSHIPS_ENABLED``).
"""

import sqlalchemy as sa
from alembic import op

revision = "v005_memberships"
down_revision = "v004_vrije_plekken"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "plans",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("business_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.Enum("membership", "bundle", name="plan_kind"), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.Column("credits", sa.SmallInteger(), nullable=False),
        sa.Column("validity_days", sa.SmallInteger(), nullable=True),
        sa.Column("cancel_notice_days", sa.SmallInteger(), nullable=False),
        sa.Column("cooling_off_days", sa.SmallInteger(), nullable=False),
        sa.Column("unused_policy", sa.Text(), nullable=False),
        sa.Column("no_show_policy", sa.Text(), nullable=False),
        sa.Column("pause_policy", sa.Text(), nullable=False),
        sa.Column("terms_version", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind <> 'bundle' or validity_days between 30 and 1095", name="bundle_validity"
        ),
        sa.CheckConstraint("cancel_notice_days between 0 and 31", name="notice_at_most_month"),
        sa.CheckConstraint("credits between 1 and 100", name="credits_range"),
        sa.CheckConstraint("price_cents between 100 and 100000", name="price_range"),
        sa.ForeignKeyConstraint(
            ["business_id"],
            ["businesses.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_plans_business_id"), "plans", ["business_id"], unique=False)
    op.create_table(
        "provider_connections",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("business_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("access_token_encrypted", sa.Text(), nullable=False),
        sa.Column("refresh_token_encrypted", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("profile_id", sa.String(length=60), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["business_id"],
            ["businesses.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("business_id"),
    )
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("business_id", sa.UUID(), nullable=False),
        sa.Column("customer_id", sa.UUID(), nullable=False),
        sa.Column("plan_id", sa.UUID(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending", "active", "cancelled", "ended", "failed", name="subscription_status"
            ),
            nullable=False,
        ),
        sa.Column("terms_version", sa.Integer(), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("renews", sa.Boolean(), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_customer_id", sa.String(length=60), nullable=True),
        sa.Column("provider_mandate_id", sa.String(length=60), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["business_id"],
            ["businesses.id"],
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["plans.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_subscriptions_business_id"), "subscriptions", ["business_id"], unique=False
    )
    op.create_index(
        op.f("ix_subscriptions_customer_id"), "subscriptions", ["customer_id"], unique=False
    )
    op.create_table(
        "credit_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("business_id", sa.UUID(), nullable=False),
        sa.Column("subscription_id", sa.UUID(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum("grant", "reserve", "consume", "release", "expire", name="credit_kind"),
            nullable=False,
        ),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("settles_id", sa.UUID(), nullable=True),
        sa.Column("staff_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["business_id"],
            ["businesses.id"],
        ),
        sa.ForeignKeyConstraint(
            ["settles_id"],
            ["credit_events.id"],
        ),
        sa.ForeignKeyConstraint(
            ["staff_id"],
            ["staff_members.id"],
        ),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["subscriptions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
        sa.UniqueConstraint("settles_id"),
    )
    op.create_index(
        op.f("ix_credit_events_business_id"), "credit_events", ["business_id"], unique=False
    )
    op.create_index(
        op.f("ix_credit_events_subscription_id"), "credit_events", ["subscription_id"], unique=False
    )
    op.create_table(
        "payments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("business_id", sa.UUID(), nullable=False),
        sa.Column("subscription_id", sa.UUID(), nullable=False),
        sa.Column("provider_payment_id", sa.String(length=60), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("sequence", sa.String(length=12), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["business_id"],
            ["businesses.id"],
        ),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["subscriptions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_payment_id"),
    )
    op.create_index(op.f("ix_payments_business_id"), "payments", ["business_id"], unique=False)
    scope = "nullif(current_setting('app.current_business_id', true), '')::uuid"
    tables = ("plans", "subscriptions", "payments", "credit_events", "provider_connections")
    for t in tables:
        op.execute(f"alter table {t} enable row level security")
        op.execute(f"alter table {t} force row level security")
        op.execute(
            f"create policy tenant_isolation on {t} using (business_id = {scope}) "
            f"with check (business_id = {scope})"
        )
    op.execute(
        "create trigger credit_events_append_only before update or delete on "
        "credit_events for each row execute function loymem_refuse_change()"
    )
    op.execute(f"""
        do $$ begin
          if exists (select 1 from pg_roles where rolname = 'loymem_app') then
            grant select, insert, update, delete on {", ".join(tables)} to loymem_app;
            revoke update, delete on credit_events from loymem_app;
          end if;
        end $$;
    """)


def downgrade() -> None:
    op.drop_index(op.f("ix_payments_business_id"), table_name="payments")
    op.drop_table("payments")
    op.drop_index(op.f("ix_credit_events_subscription_id"), table_name="credit_events")
    op.drop_index(op.f("ix_credit_events_business_id"), table_name="credit_events")
    op.drop_table("credit_events")
    op.drop_index(op.f("ix_subscriptions_customer_id"), table_name="subscriptions")
    op.drop_index(op.f("ix_subscriptions_business_id"), table_name="subscriptions")
    op.drop_table("subscriptions")
    op.drop_table("provider_connections")
    op.drop_index(op.f("ix_plans_business_id"), table_name="plans")
    op.drop_table("plans")
    for e in ("plan_kind", "subscription_status", "credit_kind"):
        op.execute(f"drop type if exists {e}")
