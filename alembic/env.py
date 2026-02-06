from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy.orm import context

# Alembic Config object (from alembic.ini)
config = context.config

# Configure logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ---- IMPORTANT ----
# Import your SQLAlchemy Base metadata so autogenerate can detect models.
#
# You MUST update this import to point to your project's Base.
# Example options (pick the real one used in your app):
#   from app.db.base import Base
#   from app.models import Base
#
# If you don't have a single Base yet, create one and make all models inherit from it.
from app.db.base import Base  # <-- CHANGE if needed

target_metadata = Base.metadata


def get_database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set. Use --env-file .env.docker in docker compose.")
    return url


def run_migrations_offline() -> None:
    """
    Offline mode: generates SQL scripts without connecting to DB.
    """
    url = get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """
    Online mode: connects to DB using async engine.
    """
    url = get_database_url()

    # Inject URL into Alembic config dynamically
    alembic_config = config.get_section(config.config_ini_section) or {}
    alembic_config["sqlalchemy.url"] = url

    connectable = async_engine_from_config(
        alembic_config,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        future=True,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())