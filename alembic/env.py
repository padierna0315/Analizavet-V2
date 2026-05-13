from logging.config import fileConfig
import sys
import os

# Add the project root directory to the path so we can import models as app.xxx
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context
from sqlmodel import SQLModel

# Import all models to ensure they are registered with SQLModel.metadata
from app.domains.patients.models import Patient
from app.domains.exam_order.models import ExamOrder
from app.domains.patients.patient_registry import PatientRegistry
from app.shared.models.doctor import Doctor
from app.shared.models.lab_value import LabValue
from app.shared.models.patient_image import PatientImage
from app.shared.models.test_result import TestResult

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = SQLModel.metadata

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    # For async engines, we need to use a different approach
    from sqlalchemy import create_engine
    
    # Convert async URL to sync for Alembic
    url = config.get_main_option("sqlalchemy.url")
    if url.startswith("sqlite+aiosqlite:"):
        url = url.replace("sqlite+aiosqlite:", "sqlite:")
    
    connectable = create_engine(url, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
