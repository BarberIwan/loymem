"""Wallet-passen live bijwerken.

Twee tabellen met RLS:
- ``wallet_passes``: per klant de laatst verstuurde inhoud van de pas
  (``digest``) en wanneer die veranderde, plus of er een Google-pas is uitgegeven.
- ``wallet_registrations``: welke toestellen een Apple-pas hebben, met hun
  push-token. Een toestel dat de pas verwijdert, meldt zich af; die rij gaat weg.

``loymem_wallet_serials`` (security definer) beantwoordt de vraag van een
toestel welke van zijn passen veranderd zijn. Die vraag komt zonder zaak erbij,
en een toestel kan passen van meerdere zaken hebben; de functie geeft alleen
serienummers van passen waarvoor dat toestel zelf geregistreerd is.

Er worden geen bestaande rijen verplaatst of weggegooid.
"""

import sqlalchemy as sa
from alembic import op

revision = "v010_wallet_live"
down_revision = "v009_tegoed"
branch_labels = None
depends_on = None

SCOPE = "nullif(current_setting('app.current_business_id', true), '')::uuid"
TABLES = ("wallet_passes", "wallet_registrations")


def upgrade() -> None:
    op.create_table(
        "wallet_passes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("business_id", sa.UUID(), nullable=False),
        sa.Column("customer_id", sa.UUID(), nullable=False),
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("google_issued", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("customer_id"),
    )
    op.create_index(
        op.f("ix_wallet_passes_business_id"), "wallet_passes", ["business_id"], unique=False
    )
    op.create_table(
        "wallet_registrations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("business_id", sa.UUID(), nullable=False),
        sa.Column("customer_id", sa.UUID(), nullable=False),
        sa.Column("device_id", sa.String(length=64), nullable=False),
        sa.Column("push_token", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("device_id", "customer_id", name="uq_wallet_device_pass"),
    )
    op.create_index(
        op.f("ix_wallet_registrations_business_id"),
        "wallet_registrations",
        ["business_id"],
        unique=False,
    )
    op.create_index(
        "ix_wallet_registrations_customer", "wallet_registrations", ["customer_id"], unique=False
    )
    for t in TABLES:
        op.execute(f"alter table {t} enable row level security")
        op.execute(f"alter table {t} force row level security")
        op.execute(
            f"create policy tenant_isolation on {t} using (business_id = {SCOPE}) "
            f"with check (business_id = {SCOPE})"
        )
    op.execute("""
        create function loymem_wallet_serials(p_device text, p_since timestamptz)
        returns table(serial text, changed_at timestamptz)
        language sql security definer set search_path = public as $$
            select b.slug || '.' || p.customer_id::text, p.changed_at
            from wallet_registrations r
            join wallet_passes p on p.customer_id = r.customer_id
            join businesses b on b.id = p.business_id
            where r.device_id = p_device and (p_since is null or p.changed_at > p_since)
        $$;
    """)
    op.execute("revoke all on function loymem_wallet_serials(text, timestamptz) from public")
    op.execute(f"""
        do $$ begin
          if exists (select 1 from pg_roles where rolname = 'loymem_app') then
            grant select, insert, update, delete on {", ".join(TABLES)} to loymem_app;
            grant execute on function loymem_wallet_serials(text, timestamptz) to loymem_app;
          end if;
        end $$;
    """)


def downgrade() -> None:
    op.execute("drop function if exists loymem_wallet_serials(text, timestamptz)")
    op.drop_index("ix_wallet_registrations_customer", table_name="wallet_registrations")
    op.drop_index(op.f("ix_wallet_registrations_business_id"), table_name="wallet_registrations")
    op.drop_table("wallet_registrations")
    op.drop_index(op.f("ix_wallet_passes_business_id"), table_name="wallet_passes")
    op.drop_table("wallet_passes")
