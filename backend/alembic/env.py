"""Migrations run as the owner role (LOYMEM_MIGRATION_URL), never as the app role."""

import os

from sqlalchemy import create_engine

from alembic import context
from app.models import Base

url = os.environ.get(
    "LOYMEM_MIGRATION_URL",
    "postgresql+psycopg://loymem_owner:loymem_owner@localhost:5433/loymem",
)


def run() -> None:
    engine = create_engine(url)
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=Base.metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


run()
