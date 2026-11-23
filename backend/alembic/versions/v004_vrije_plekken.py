"""Vrije plekken (fase 1c): meldlijst, aanbiedingen, ontvangers per groep, claims.

Vier nieuwe tabellen met RLS. ``ledger_kind`` krijgt de waarde ``bonus`` voor
extra stempels uit een aanbieding. Er worden geen rijen verplaatst of
weggegooid.

Downgrade verwijdert de tabellen maar laat de enumwaarde ``bonus`` staan:
PostgreSQL kan een enumwaarde niet verwijderen, en logboekregels blijven.
"""

import sqlalchemy as sa
from alembic import op

revision = "v004_vrije_plekken"
down_revision = "v003_webhook_afspraken"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("alter type ledger_kind add value if not exists 'bonus'")
    op.create_table(
        "slot_offers",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("business_id", sa.UUID(), nullable=False),
        sa.Column("service_id", sa.UUID(), nullable=True),
        sa.Column("staff_name", sa.String(length=80), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("book_by", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "benefit", sa.Enum("stamps", "upgrade", "discount", name="slot_benefit"), nullable=False
        ),
        sa.Column("benefit_value", sa.SmallInteger(), nullable=False),
        sa.Column("benefit_text", sa.String(length=120), nullable=True),
        sa.Column("capacity", sa.SmallInteger(), nullable=False),
        sa.Column("claims_count", sa.SmallInteger(), nullable=False),
        sa.Column("group_size", sa.SmallInteger(), nullable=False),
        sa.Column("wait_minutes", sa.SmallInteger(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("open", "filled", "expired", "closed", name="slot_status"),
            nullable=False,
        ),
        sa.Column("sending_started", sa.Boolean(), nullable=False),
        sa.Column("next_send_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "benefit <> 'discount' or benefit_value between 1 and 50", name="discount_range"
        ),
        sa.CheckConstraint(
            "benefit <> 'stamps' or benefit_value between 1 and 10", name="bonus_stamps_range"
        ),
        sa.CheckConstraint("book_by <= starts_at", name="book_before_start"),
        sa.CheckConstraint("capacity between 1 and 20", name="capacity_range"),
        sa.CheckConstraint("claims_count between 0 and capacity", name="claims_within_capacity"),
        sa.CheckConstraint("group_size between 1 and 50", name="group_size_range"),
        sa.CheckConstraint("wait_minutes between 1 and 240", name="wait_range"),
        sa.ForeignKeyConstraint(
            ["business_id"],
            ["businesses.id"],
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["staff_members.id"],
        ),
        sa.ForeignKeyConstraint(
            ["service_id"],
            ["services.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_slot_offer_send", "slot_offers", ["status", "next_send_at"], unique=False)
    op.create_index(
        op.f("ix_slot_offers_business_id"), "slot_offers", ["business_id"], unique=False
    )
    op.create_table(
        "waitlist_entries",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("business_id", sa.UUID(), nullable=False),
        sa.Column("customer_id", sa.UUID(), nullable=False),
        sa.Column("service_id", sa.UUID(), nullable=True),
        sa.Column("days_mask", sa.SmallInteger(), nullable=False),
        sa.Column("dayparts_mask", sa.SmallInteger(), nullable=False),
        sa.Column("min_notice_minutes", sa.SmallInteger(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("dayparts_mask between 1 and 7", name="dayparts_mask_range"),
        sa.CheckConstraint("days_mask between 1 and 127", name="days_mask_range"),
        sa.CheckConstraint("min_notice_minutes between 0 and 1440", name="notice_range"),
        sa.ForeignKeyConstraint(
            ["business_id"],
            ["businesses.id"],
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
        ),
        sa.ForeignKeyConstraint(
            ["service_id"],
            ["services.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("customer_id"),
    )
    op.create_index(
        op.f("ix_waitlist_entries_business_id"), "waitlist_entries", ["business_id"], unique=False
    )
    op.create_table(
        "slot_claims",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("business_id", sa.UUID(), nullable=False),
        sa.Column("offer_id", sa.UUID(), nullable=False),
        sa.Column("customer_id", sa.UUID(), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_by", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["applied_by"],
            ["staff_members.id"],
        ),
        sa.ForeignKeyConstraint(
            ["business_id"],
            ["businesses.id"],
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
        ),
        sa.ForeignKeyConstraint(
            ["offer_id"],
            ["slot_offers.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("offer_id", "customer_id", name="uq_slot_claim"),
    )
    op.create_index(
        op.f("ix_slot_claims_business_id"), "slot_claims", ["business_id"], unique=False
    )
    op.create_table(
        "slot_recipients",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("business_id", sa.UUID(), nullable=False),
        sa.Column("offer_id", sa.UUID(), nullable=False),
        sa.Column("customer_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("reason", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["business_id"],
            ["businesses.id"],
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
        ),
        sa.ForeignKeyConstraint(
            ["offer_id"],
            ["slot_offers.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("offer_id", "customer_id", name="uq_slot_recipient"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        "ix_slot_recipient_queue",
        "slot_recipients",
        ["offer_id", "status", "position"],
        unique=False,
    )
    op.create_index(
        op.f("ix_slot_recipients_business_id"), "slot_recipients", ["business_id"], unique=False
    )
    scope = "nullif(current_setting('app.current_business_id', true), '')::uuid"
    tables = ("waitlist_entries", "slot_offers", "slot_recipients", "slot_claims")
    for t in tables:
        op.execute(f"alter table {t} enable row level security")
        op.execute(f"alter table {t} force row level security")
        op.execute(
            f"create policy tenant_isolation on {t} using (business_id = {scope}) "
            f"with check (business_id = {scope})"
        )
    op.execute(f"""
        do $$ begin
          if exists (select 1 from pg_roles where rolname = 'loymem_app') then
            grant select, insert, update, delete on {", ".join(tables)} to loymem_app;
          end if;
        end $$;
    """)


def downgrade() -> None:
    op.drop_index(op.f("ix_slot_recipients_business_id"), table_name="slot_recipients")
    op.drop_index("ix_slot_recipient_queue", table_name="slot_recipients")
    op.drop_table("slot_recipients")
    op.drop_index(op.f("ix_slot_claims_business_id"), table_name="slot_claims")
    op.drop_table("slot_claims")
    op.drop_index(op.f("ix_waitlist_entries_business_id"), table_name="waitlist_entries")
    op.drop_table("waitlist_entries")
    op.drop_index(op.f("ix_slot_offers_business_id"), table_name="slot_offers")
    op.drop_index("ix_slot_offer_send", table_name="slot_offers")
    op.drop_table("slot_offers")
    op.execute("drop type if exists slot_benefit")
    op.execute("drop type if exists slot_status")
