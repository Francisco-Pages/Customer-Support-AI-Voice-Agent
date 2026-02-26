import asyncio
from logging.config import fileConfig

from dotenv import load_dotenv
from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context

# Load .env before importing app modules that read settings at import time
load_dotenv()

from app.db.models import Base  # noqa: E402
from app.config import settings  # noqa: E402

# ---------------------------------------------------------------------------
# Alembic config
# ---------------------------------------------------------------------------

config = context.config
target_metadata = Base.metadata

if config.config_file_name:
    fileConfig(config.config_file_name)

# Use the asyncpg URL from settings (Alembic infers the pg dialect from it)
config.set_main_option("sqlalchemy.url", settings.database_url)


# ---------------------------------------------------------------------------
# Migration runners
# ---------------------------------------------------------------------------


def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    """Generate SQL without a live DB connection."""
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations against the live database via asyncpg."""
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
