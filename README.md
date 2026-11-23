# Loymem

Vaste klanten, vaste omzet. Loyalty en memberships naast je eigen agenda.

## Wat er staat (fase 1a)

Inschrijven via QR, de klantkaart op het web, stempelen door een medewerker,
een beloning één keer inwisselen, het overzicht voor de eigenaar, instellingen
met terugkeerperiodes per behandeling, CSV-import en -export.

- `backend/` FastAPI, PostgreSQL. Logboek is alleen toevoegen; tenant-scheiding
  ook in de database (RLS).
- `frontend/` Next.js met next-intl (`messages/nl.json`, `messages/en.json`).
- `DESIGN.md` het ontwerpsysteem; `docs/decisions.md` de beslissingen;
  `docs/spec/` de opdracht en de productdocumenten.

## Lokaal draaien

PostgreSQL 16 met twee rollen: `loymem_owner` (eigenaar, BYPASSRLS, voor
migraties) en `loymem_app` (de app, zonder BYPASSRLS). Zie de stap
"Database roles" in `.github/workflows/ci.yml`.

```bash
cd backend
pip install -e ".[dev]"
LOYMEM_MIGRATION_URL=postgresql+psycopg://loymem_owner:loymem_owner@localhost:5433/loymem alembic upgrade head
LOYMEM_DEMO_PASSWORD=... python scripts/seed_demo.py
uvicorn app.main:app --port 8000

cd ../frontend
pnpm install && pnpm dev
```

Toetsen: `cd backend && pytest -q` (tegen PostgreSQL, database `loymem_test`).
