"""Campagnes met controlegroep (fase 1e).

Twee nieuwe tabellen met RLS. Een controlegroeplid kan in de database nooit een
verzendtijd hebben (check). Er worden geen rijen verplaatst of weggegooid.
"""

import sqlalchemy as sa
from alembic import op

revision = "v006_campagnes"
down_revision = "v005_memberships"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "campaigns",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("business_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("audience", sa.String(length=30), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("holdout_percent", sa.SmallInteger(), nullable=False),
        sa.Column("window_days", sa.SmallInteger(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("holdout_percent between 5 and 50", name="holdout_range"),
        sa.CheckConstraint("window_days between 7 and 90", name="window_range"),
        sa.ForeignKeyConstraint(
            ["business_id"],
            ["businesses.id"],
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["staff_members.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_campaigns_business_id"), "campaigns", ["business_id"], unique=False)
    op.create_table(
        "campaign_members",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("business_id", sa.UUID(), nullable=False),
        sa.Column("campaign_id", sa.UUID(), nullable=False),
        sa.Column("customer_id", sa.UUID(), nullable=False),
        sa.Column("holdout", sa.Boolean(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("not (holdout and sent_at is not null)", name="holdout_never_sent"),
        sa.ForeignKeyConstraint(
            ["business_id"],
            ["businesses.id"],
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["campaigns.id"],
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("campaign_id", "customer_id", name="uq_campaign_member"),
    )
    op.create_index(
        op.f("ix_campaign_members_business_id"), "campaign_members", ["business_id"], unique=False
    )
    scope = "nullif(current_setting('app.current_business_id', true), '')::uuid"
    for t in ("campaigns", "campaign_members"):
        op.execute(f"alter table {t} enable row level security")
        op.execute(f"alter table {t} force row level security")
        op.execute(
            f"create policy tenant_isolation on {t} using (business_id = {scope}) "
            f"with check (business_id = {scope})"
        )
    op.execute("""
        do $$ begin
          if exists (select 1 from pg_roles where rolname = 'loymem_app') then
            grant select, insert, update, delete on campaigns, campaign_members to loymem_app;
          end if;
        end $$;
    """)


def downgrade() -> None:
    op.drop_index(op.f("ix_campaign_members_business_id"), table_name="campaign_members")
    op.drop_table("campaign_members")
    op.drop_index(op.f("ix_campaigns_business_id"), table_name="campaigns")
    op.drop_table("campaigns")
