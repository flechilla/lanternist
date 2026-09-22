from alembic import context
from sqlalchemy import engine_from_config, pool

from lanternist.db import Base

config = context.config
target_metadata = Base.metadata

connectable = engine_from_config(
    config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool
)
with connectable.connect() as connection:
    context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()
