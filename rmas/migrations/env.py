"""Alembic environment — reads the DB URL from Settings, not a hardcoded string."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

import models.allocation  # noqa: F401 — all models must be imported so that
import models.audit  # noqa: F401   Base.metadata is complete for autogenerate
import models.flow  # noqa: F401
import models.idempotency  # noqa: F401
import models.party  # noqa: F401
import models.sector  # noqa: F401
import models.staging  # noqa: F401
import models.user  # noqa: F401
from config import settings
from database import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Respect a URL supplied by the caller (a test harness, or `-x`/CLI override)
# and only fall back to Settings. Overwriting it unconditionally would make it
# impossible to run migrations against any database but the configured one.
if not config.get_main_option("sqlalchemy.url", None):
    config.set_main_option("sqlalchemy.url", settings.database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        # SQLite's ALTER TABLE support is limited (no DROP/ALTER COLUMN);
        # batch mode has Alembic recreate the table instead. No effect on
        # other dialects, so this is safe to leave on unconditionally.
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=(connection.dialect.name == "sqlite"),
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
