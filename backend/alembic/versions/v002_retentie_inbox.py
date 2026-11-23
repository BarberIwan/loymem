"""Retentie-inbox (fase 1b): wat de eigenaar met een kans deed, en twee instellingen.

Nieuwe tabel ``inbox_entries`` met RLS zoals in v001. Twee nieuwe kolommen op
``businesses`` met een standaardwaarde, dus bestaande zaken krijgen 10 kansen per
dag en 30 dagen negeren. Er worden geen rijen verplaatst of weggegooid.
"""

import sqlalchemy as sa
from alembic import op

revision = "v002_retentie_inbox"
down_revision = "v001_fundament"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inbox_entries",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("business_id", sa.UUID(), nullable=False),
        sa.Column("customer_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column(
            "decision", sa.Enum("sent", "done", "ignored", name="inbox_decision"), nullable=False
        ),
        sa.Column("hidden_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("staff_id", sa.UUID(), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
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
            ["staff_id"],
            ["staff_members.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_inbox_entries_business_id"), "inbox_entries", ["business_id"], unique=False
    )
    op.create_index(
        "ix_inbox_lookup",
        "inbox_entries",
        ["business_id", "customer_id", "kind", "hidden_until"],
        unique=False,
    )
    op.add_column(
        "businesses",
        sa.Column("inbox_daily_limit", sa.SmallInteger(), server_default="10", nullable=False),
    )
    op.add_column(
        "businesses",
        sa.Column("inbox_ignore_days", sa.SmallInteger(), server_default="30", nullable=False),
    )
    op.create_check_constraint(
        "inbox_daily_limit_range", "businesses", "inbox_daily_limit between 1 and 50"
    )
    op.create_check_constraint(
        "inbox_ignore_days_range", "businesses", "inbox_ignore_days between 1 and 365"
    )
    scope = "nullif(current_setting('app.current_business_id', true), '')::uuid"
    op.execute("alter table inbox_entries enable row level security")
    op.execute("alter table inbox_entries force row level security")
    op.execute(
        f"create policy tenant_isolation on inbox_entries using (business_id = {scope}) "
        f"with check (business_id = {scope})"
    )
    op.execute("""
        do $$ begin
          if exists (select 1 from pg_roles where rolname = 'loymem_app') then
            grant select, insert, update, delete on inbox_entries to loymem_app;
          end if;
        end $$;
    """)


def downgrade() -> None:
    op.drop_constraint("inbox_ignore_days_range", "businesses", type_="check")
    op.drop_constraint("inbox_daily_limit_range", "businesses", type_="check")
    op.drop_column("businesses", "inbox_ignore_days")
    op.drop_column("businesses", "inbox_daily_limit")
    op.drop_index("ix_inbox_lookup", table_name="inbox_entries")
    op.drop_index(op.f("ix_inbox_entries_business_id"), table_name="inbox_entries")
    op.drop_table("inbox_entries")
    op.execute("drop type if exists inbox_decision")
