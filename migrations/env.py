# -*- coding: utf-8 -*-
"""Alembic-окружение: метаданные SQLModel + DATABASE_URL из env/.env."""
import os
from logging.config import fileConfig

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool

from backend.database import SQLModel, normalize_database_url
import backend.database  # noqa: F401 — регистрирует таблицы в metadata

load_dotenv()
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Приоритет: config.attributes (программный вызов/тесты) > DATABASE_URL > ini.
_forced_url = config.attributes.get("sqlalchemy_url")
if _forced_url:
    config.set_main_option("sqlalchemy.url", normalize_database_url(_forced_url))
else:
    env_url = os.getenv("DATABASE_URL")
    if env_url:
        config.set_main_option("sqlalchemy.url",
                               normalize_database_url(env_url))

target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection,
                          target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
