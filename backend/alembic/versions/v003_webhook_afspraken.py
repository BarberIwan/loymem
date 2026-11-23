"""Generieke webhook voor afgeronde afspraken (koppeling zonder native connector).

Nieuwe tabellen ``webhook_configs`` (een per zaak, geheim versleuteld) en
``webhook_deliveries`` (uitkomst per aanroep, zonder persoonsgegevens), beide
met RLS. Er worden geen rijen verplaatst of weggegooid.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "v003_webhook_afspraken"
down_revision = "v002_retentie_inbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "webhook_configs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("business_id", sa.UUID(), nullable=False),
        sa.Column("secret_encrypted", sa.Text(), nullable=False),
        sa.Column("mapping", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["business_id"],
            ["businesses.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("business_id"),
    )
    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("business_id", sa.UUID(), nullable=False),
        sa.Column("appointment_id", sa.String(length=120), nullable=True),
        sa.Column("outcome", sa.String(length=30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["business_id"],
            ["businesses.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_webhook_deliveries_business_id"),
        "webhook_deliveries",
        ["business_id"],
        unique=False,
    )
    op.create_index(
        "ix_webhook_delivery_time",
        "webhook_deliveries",
        ["business_id", "created_at"],
        unique=False,
    )
    scope = "nullif(current_setting('app.current_business_id', true), '')::uuid"
    for t in ("webhook_configs", "webhook_deliveries"):
        op.execute(f"alter table {t} enable row level security")
        op.execute(f"alter table {t} force row level security")
        op.execute(
            f"create policy tenant_isolation on {t} using (business_id = {scope}) "
            f"with check (business_id = {scope})"
        )
    op.execute("""
        do $$ begin
          if exists (select 1 from pg_roles where rolname = 'loymem_app') then
            grant select, insert, update, delete on webhook_configs, webhook_deliveries
              to loymem_app;
          end if;
        end $$;
    """)


def downgrade() -> None:
    op.drop_index("ix_webhook_delivery_time", table_name="webhook_deliveries")
    op.drop_index(op.f("ix_webhook_deliveries_business_id"), table_name="webhook_deliveries")
    op.drop_table("webhook_deliveries")
    op.drop_table("webhook_configs")
