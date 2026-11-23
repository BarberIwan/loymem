"""Een nieuwe zaak meldt zich zelf aan (met uitnodigingscode).

Voegt de functie ``loymem_create_business`` toe: de app-rol mag zelf geen rijen in
``businesses`` invoegen, deze functie doet precies dat en niets anders. Geen
tabellen, geen rijen verplaatst of weggegooid.
"""

from alembic import op

revision = "v008_zaak_aanmelden"
down_revision = "v007_mail_versturen"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        create function loymem_create_business(p_slug text, p_name text)
        returns uuid language plpgsql security definer set search_path = public as $$
        declare new_id uuid := gen_random_uuid();
        begin
          insert into businesses (id, slug, name, brand_colour, timezone, created_at,
                                  inbox_daily_limit, inbox_ignore_days)
          values (new_id, p_slug, p_name, '#1F4A38', 'Europe/Amsterdam', now(), 10, 30);
          return new_id;
        end $$;
    """)
    op.execute("revoke all on function loymem_create_business(text, text) from public")
    op.execute("""
        do $$ begin
          if exists (select 1 from pg_roles where rolname = 'loymem_app') then
            grant execute on function loymem_create_business(text, text) to loymem_app;
          end if;
        end $$;
    """)


def downgrade() -> None:
    op.execute("drop function if exists loymem_create_business(text, text)")
