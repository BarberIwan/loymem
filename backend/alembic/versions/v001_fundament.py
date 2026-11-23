"""Fundament fase 1a: zaken, medewerkers, klanten, programma, logboek, auditlog.

Nieuwe tabellen; er worden geen rijen verplaatst of weggegooid.

Daarnaast:
- Row Level Security op elke tabel met ``business_id`` (FORCE), op
  ``app.current_business_id``. De app-rol ``loymem_app`` heeft geen BYPASSRLS.
- ``ledger_events`` en ``audit_log`` weigeren UPDATE en DELETE (trigger).
- ``loymem_staff_login(email)``: de enige plek die buiten een zaak zoekt; geeft
  alleen wat nodig is om het wachtwoord te toetsen.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# Vastgezet: een latere wijziging aan de modellen mag deze migratie niet veranderen.
TENANT_TABLES = [
    "customers",
    "outbox",
    "programs",
    "services",
    "staff_members",
    "audit_log",
    "card_reissues",
    "consent_records",
    "customer_programs",
    "ledger_events",
    "rewards",
    "reward_codes",
]
APPEND_ONLY_TABLES = ["ledger_events", "audit_log"]
revision = "v001_fundament"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "businesses",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("slug", sa.String(length=60), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("brand_colour", sa.String(length=7), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("booking_url", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("brand_colour ~ '^#[0-9A-Fa-f]{6}$'", name="brand_colour_hex"),
        sa.CheckConstraint("slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'", name="slug_format"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_table(
        "customers",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("business_id", sa.UUID(), nullable=False),
        sa.Column("first_name", sa.String(length=60), nullable=True),
        sa.Column("email", sa.String(length=254), nullable=True),
        sa.Column("phone", sa.String(length=20), nullable=True),
        sa.Column("birthday_day", sa.SmallInteger(), nullable=True),
        sa.Column("birthday_month", sa.SmallInteger(), nullable=True),
        sa.Column("source", sa.Enum("signup", "import", name="customer_source"), nullable=False),
        sa.Column("card_secret_hash", sa.String(length=64), nullable=False),
        sa.Column("scan_token_hash", sa.String(length=64), nullable=False),
        sa.Column("anonymised_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("birthday_day is null or birthday_day between 1 and 31", name="bday"),
        sa.CheckConstraint(
            "birthday_month is null or birthday_month between 1 and 12", name="bmonth"
        ),
        sa.ForeignKeyConstraint(
            ["business_id"],
            ["businesses.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("card_secret_hash"),
        sa.UniqueConstraint("scan_token_hash"),
    )
    op.create_index(op.f("ix_customers_business_id"), "customers", ["business_id"], unique=False)
    op.create_index(
        "uq_customer_email",
        "customers",
        ["business_id", "email"],
        unique=True,
        postgresql_where="email is not null",
    )
    op.create_index(
        "uq_customer_phone",
        "customers",
        ["business_id", "phone"],
        unique=True,
        postgresql_where="phone is not null",
    )
    op.create_table(
        "outbox",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("business_id", sa.UUID(), nullable=False),
        sa.Column("channel", sa.String(length=10), nullable=False),
        sa.Column("recipient", sa.String(length=254), nullable=False),
        sa.Column("template", sa.String(length=60), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["business_id"],
            ["businesses.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_outbox_business_id"), "outbox", ["business_id"], unique=False)
    op.create_table(
        "programs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("business_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("stamps_required", sa.SmallInteger(), nullable=False),
        sa.Column("reward_description", sa.String(length=120), nullable=False),
        sa.Column("stamp_period_hours", sa.SmallInteger(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("stamp_period_hours between 0 and 720", name="stamp_period_range"),
        sa.CheckConstraint("stamps_required between 2 and 30", name="stamps_required_range"),
        sa.ForeignKeyConstraint(
            ["business_id"],
            ["businesses.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_programs_business_id"), "programs", ["business_id"], unique=False)
    op.create_table(
        "services",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("business_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("return_period_days", sa.SmallInteger(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("return_period_days between 1 and 730", name="return_period_range"),
        sa.ForeignKeyConstraint(
            ["business_id"],
            ["businesses.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("business_id", "name", name="uq_service_name"),
    )
    op.create_index(op.f("ix_services_business_id"), "services", ["business_id"], unique=False)
    op.create_table(
        "staff_members",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("business_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=True),
        sa.Column("role", sa.Enum("owner", "manager", "staff", name="staff_role"), nullable=False),
        sa.Column("password_hash", sa.String(length=200), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["business_id"],
            ["businesses.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", name="uq_staff_email"),
    )
    op.create_index(
        op.f("ix_staff_members_business_id"), "staff_members", ["business_id"], unique=False
    )
    op.create_table(
        "audit_log",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("business_id", sa.UUID(), nullable=False),
        sa.Column("actor_staff_id", sa.UUID(), nullable=True),
        sa.Column("action", sa.String(length=60), nullable=False),
        sa.Column("subject_type", sa.String(length=40), nullable=False),
        sa.Column("subject_id", sa.UUID(), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_staff_id"],
            ["staff_members.id"],
        ),
        sa.ForeignKeyConstraint(
            ["business_id"],
            ["businesses.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_audit_business_time", "audit_log", ["business_id", "created_at"], unique=False
    )
    op.create_index(op.f("ix_audit_log_business_id"), "audit_log", ["business_id"], unique=False)
    op.create_table(
        "card_reissues",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("business_id", sa.UUID(), nullable=False),
        sa.Column("customer_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["business_id"],
            ["businesses.id"],
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        op.f("ix_card_reissues_business_id"), "card_reissues", ["business_id"], unique=False
    )
    op.create_table(
        "consent_records",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("business_id", sa.UUID(), nullable=False),
        sa.Column("customer_id", sa.UUID(), nullable=False),
        sa.Column(
            "purpose", sa.Enum("marketing", "slot_alerts", name="consent_purpose"), nullable=False
        ),
        sa.Column("status", sa.Enum("granted", "withdrawn", name="consent_status"), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["business_id"],
            ["businesses.id"],
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_consent_customer",
        "consent_records",
        ["customer_id", "purpose", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_consent_records_business_id"), "consent_records", ["business_id"], unique=False
    )
    op.create_table(
        "customer_programs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("business_id", sa.UUID(), nullable=False),
        sa.Column("customer_id", sa.UUID(), nullable=False),
        sa.Column("program_id", sa.UUID(), nullable=False),
        sa.Column("balance", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("balance >= 0", name="balance_not_negative"),
        sa.ForeignKeyConstraint(
            ["business_id"],
            ["businesses.id"],
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
        ),
        sa.ForeignKeyConstraint(
            ["program_id"],
            ["programs.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("customer_id", "program_id", name="uq_customer_program"),
    )
    op.create_index(
        op.f("ix_customer_programs_business_id"), "customer_programs", ["business_id"], unique=False
    )
    op.create_table(
        "ledger_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("business_id", sa.UUID(), nullable=False),
        sa.Column("customer_program_id", sa.UUID(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum("stamp", "reward_earned", "reward_redeemed", "reversal", name="ledger_kind"),
            nullable=False,
        ),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("reverses_id", sa.UUID(), nullable=True),
        sa.Column("reward_id", sa.UUID(), nullable=True),
        sa.Column("service_id", sa.UUID(), nullable=True),
        sa.Column("staff_id", sa.UUID(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind <> 'reversal' or (reverses_id is not null and reason is not null)",
            name="reversal_has_reason",
        ),
        sa.ForeignKeyConstraint(
            ["business_id"],
            ["businesses.id"],
        ),
        sa.ForeignKeyConstraint(
            ["customer_program_id"],
            ["customer_programs.id"],
        ),
        sa.ForeignKeyConstraint(
            ["reverses_id"],
            ["ledger_events.id"],
        ),
        sa.ForeignKeyConstraint(
            ["service_id"],
            ["services.id"],
        ),
        sa.ForeignKeyConstraint(
            ["staff_id"],
            ["staff_members.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
        sa.UniqueConstraint("reverses_id"),
    )
    op.create_index(
        op.f("ix_ledger_events_business_id"), "ledger_events", ["business_id"], unique=False
    )
    op.create_index(
        op.f("ix_ledger_events_customer_program_id"),
        "ledger_events",
        ["customer_program_id"],
        unique=False,
    )
    op.create_index(
        "ix_ledger_staff_time",
        "ledger_events",
        ["business_id", "staff_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "rewards",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("business_id", sa.UUID(), nullable=False),
        sa.Column("customer_program_id", sa.UUID(), nullable=False),
        sa.Column("description", sa.String(length=120), nullable=False),
        sa.Column(
            "status",
            sa.Enum("available", "redeemed", "voided", name="reward_status"),
            nullable=False,
        ),
        sa.Column("earned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("redeemed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("redeemed_by", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["business_id"],
            ["businesses.id"],
        ),
        sa.ForeignKeyConstraint(
            ["customer_program_id"],
            ["customer_programs.id"],
        ),
        sa.ForeignKeyConstraint(
            ["redeemed_by"],
            ["staff_members.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_rewards_business_id"), "rewards", ["business_id"], unique=False)
    op.create_index(
        op.f("ix_rewards_customer_program_id"), "rewards", ["customer_program_id"], unique=False
    )
    op.create_table(
        "reward_codes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("business_id", sa.UUID(), nullable=False),
        sa.Column("reward_id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(length=6), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["business_id"],
            ["businesses.id"],
        ),
        sa.ForeignKeyConstraint(
            ["reward_id"],
            ["rewards.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_reward_code_lookup", "reward_codes", ["business_id", "code", "expires_at"], unique=False
    )
    op.create_index(
        op.f("ix_reward_codes_business_id"), "reward_codes", ["business_id"], unique=False
    )

    op.execute("""
        create function loymem_refuse_change() returns trigger language plpgsql as $$
        begin raise exception '% is alleen toevoegen', tg_table_name; end $$;
    """)
    for t in APPEND_ONLY_TABLES:
        op.execute(
            f"create trigger {t}_append_only before update or delete on {t} "
            "for each row execute function loymem_refuse_change()"
        )
    scope = "nullif(current_setting('app.current_business_id', true), '')::uuid"
    for t in TENANT_TABLES:
        op.execute(f"alter table {t} enable row level security")
        op.execute(f"alter table {t} force row level security")
        op.execute(
            f"create policy tenant_isolation on {t} using (business_id = {scope}) "
            f"with check (business_id = {scope})"
        )
    op.execute("""
        create function loymem_staff_login(p_email text)
        returns table(business_id uuid, staff_id uuid, password_hash text, active boolean,
                      role text)
        language sql security definer set search_path = public as $$
            select s.business_id, s.id, s.password_hash, s.active, s.role::text
            from staff_members s where s.email = lower(p_email)
        $$;
    """)
    op.execute("revoke all on function loymem_staff_login(text) from public")
    op.execute("""
        do $$ begin
          if exists (select 1 from pg_roles where rolname = 'loymem_app') then
            grant select, insert, update, delete on all tables in schema public to loymem_app;
            revoke update, delete on ledger_events, audit_log from loymem_app;
            revoke insert, update, delete on businesses from loymem_app;
            grant update on businesses to loymem_app;
            grant execute on function loymem_staff_login(text) to loymem_app;
          end if;
        end $$;
    """)


def downgrade() -> None:
    op.execute("drop function if exists loymem_staff_login(text)")
    op.drop_index(op.f("ix_reward_codes_business_id"), table_name="reward_codes")
    op.drop_index("ix_reward_code_lookup", table_name="reward_codes")
    op.drop_table("reward_codes")
    op.drop_index(op.f("ix_rewards_customer_program_id"), table_name="rewards")
    op.drop_index(op.f("ix_rewards_business_id"), table_name="rewards")
    op.drop_table("rewards")
    op.drop_index("ix_ledger_staff_time", table_name="ledger_events")
    op.drop_index(op.f("ix_ledger_events_customer_program_id"), table_name="ledger_events")
    op.drop_index(op.f("ix_ledger_events_business_id"), table_name="ledger_events")
    op.drop_table("ledger_events")
    op.drop_index(op.f("ix_customer_programs_business_id"), table_name="customer_programs")
    op.drop_table("customer_programs")
    op.drop_index(op.f("ix_consent_records_business_id"), table_name="consent_records")
    op.drop_index("ix_consent_customer", table_name="consent_records")
    op.drop_table("consent_records")
    op.drop_index(op.f("ix_card_reissues_business_id"), table_name="card_reissues")
    op.drop_table("card_reissues")
    op.drop_index(op.f("ix_audit_log_business_id"), table_name="audit_log")
    op.drop_index("ix_audit_business_time", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_index(op.f("ix_staff_members_business_id"), table_name="staff_members")
    op.drop_table("staff_members")
    op.drop_index(op.f("ix_services_business_id"), table_name="services")
    op.drop_table("services")
    op.drop_index(op.f("ix_programs_business_id"), table_name="programs")
    op.drop_table("programs")
    op.drop_index(op.f("ix_outbox_business_id"), table_name="outbox")
    op.drop_table("outbox")
    op.drop_index("uq_customer_phone", table_name="customers", postgresql_where="phone is not null")
    op.drop_index("uq_customer_email", table_name="customers", postgresql_where="email is not null")
    op.drop_index(op.f("ix_customers_business_id"), table_name="customers")
    op.drop_table("customers")
    op.drop_table("businesses")
    op.execute("drop function if exists loymem_refuse_change()")
    for e in (
        "staff_role",
        "customer_source",
        "consent_purpose",
        "consent_status",
        "ledger_kind",
        "reward_status",
    ):
        op.execute(f"drop type if exists {e}")
