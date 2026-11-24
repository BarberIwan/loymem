"""Afspraken uit doorgestuurde boekingsmails (Salonized).

- ``mail_inboxes``: per zaak een eigen ontvangstadres. Het geheime deel staat
  alleen als hash in de database; het adres zelf wordt uit de serversleutel
  afgeleid. Plus de keuze of afgelopen afspraken als bezoek tellen (standaard
  uit), en de bevestigingscode van Gmail als die binnenkomt.
- ``appointments``: wat de mails zeggen over een afspraak: tijden, status,
  dienst, en de klant alleen als die al klant is bij de zaak. Van wie (nog) geen
  klant is, wordt niets persoonlijks bewaard; om een annulering zonder nummer
  terug te vinden staat er een hash van de naam.
- ``mail_receipts``: per ontvangen mail alleen soort en uitkomst.

``loymem_mail_inbox(hash)`` (security definer) vindt bij een binnenkomende mail
de zaak; die vraag komt zonder zaak erbij.

Er worden geen rijen verplaatst of weggegooid.
"""

import sqlalchemy as sa
from alembic import op

revision = "v013_afspraken_uit_mail"
down_revision = "v012_terugbetalen"
branch_labels = None
depends_on = None

SCOPE = "nullif(current_setting('app.current_business_id', true), '')::uuid"
TABLES = ("mail_inboxes", "appointments", "mail_receipts")


def upgrade() -> None:
    op.create_table(
        "mail_inboxes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("business_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("generation", sa.SmallInteger(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("count_visits", sa.Boolean(), nullable=False),
        sa.Column("gmail_code", sa.String(length=12), nullable=True),
        sa.Column("last_received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("business_id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_table(
        "appointments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("business_id", sa.UUID(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("external_id", sa.String(length=40), nullable=True),
        sa.Column("customer_id", sa.UUID(), nullable=True),
        sa.Column("name_hash", sa.String(length=64), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("service", sa.String(length=120), nullable=True),
        sa.Column("staff", sa.String(length=60), nullable=True),
        sa.Column("visit_recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status in ('booked', 'cancelled')", name="appointment_status"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("business_id", "source", "external_id", name="uq_appointment_ext"),
    )
    op.create_index("ix_appointments_business_id", "appointments", ["business_id"])
    op.create_index("ix_appointments_business_start", "appointments", ["business_id", "starts_at"])
    op.create_index("ix_appointments_customer", "appointments", ["customer_id"])
    op.create_table(
        "mail_receipts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("business_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_mail_receipts_business_id", "mail_receipts", ["business_id"])
    op.create_index("ix_mail_receipts_business", "mail_receipts", ["business_id", "created_at"])
    for t in TABLES:
        op.execute(f"alter table {t} enable row level security")
        op.execute(f"alter table {t} force row level security")
        op.execute(
            f"create policy tenant_isolation on {t} using (business_id = {SCOPE}) "
            f"with check (business_id = {SCOPE})"
        )
    op.execute("""
        create function loymem_mail_inbox(p_hash text)
        returns uuid language sql security definer set search_path = public as $$
            select business_id from mail_inboxes where token_hash = p_hash and active
        $$;
    """)
    op.execute("revoke all on function loymem_mail_inbox(text) from public")
    op.execute(f"""
        do $$ begin
          if exists (select 1 from pg_roles where rolname = 'loymem_app') then
            grant select, insert, update on {", ".join(TABLES)} to loymem_app;
            grant execute on function loymem_mail_inbox(text) to loymem_app;
          end if;
        end $$;
    """)


def downgrade() -> None:
    op.execute("drop function if exists loymem_mail_inbox(text)")
    op.drop_index("ix_mail_receipts_business", table_name="mail_receipts")
    op.drop_index("ix_mail_receipts_business_id", table_name="mail_receipts")
    op.drop_table("mail_receipts")
    op.drop_index("ix_appointments_customer", table_name="appointments")
    op.drop_index("ix_appointments_business_start", table_name="appointments")
    op.drop_index("ix_appointments_business_id", table_name="appointments")
    op.drop_table("appointments")
    op.drop_table("mail_inboxes")
