"""Alembic environment. Reads DATABASE_URL from rmas.config.get_settings()
rather than alembic.ini, so one .env stays the single source of connection
config (CLAUDE.md: no secrets in code, config.py is the settings loader)."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from rmas.config import get_settings
from rmas.models import Base  # noqa: F401 — imports every model onto Base.metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_settings().database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
