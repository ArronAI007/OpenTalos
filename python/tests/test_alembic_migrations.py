"""Proves the Alembic migration chain actually produces the same schema as the SQLAlchemy
metadata the application code uses at runtime -- without this, schema.py and alembic/versions/*.py
are two hand-maintained sources of truth that nothing reconciles if they drift, which is exactly
the class of problem Alembic was adopted to eliminate (see the design spec)."""

from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import MetaData, create_engine as create_sync_engine

from opentalos.checkpoint.schema import metadata as checkpoint_metadata
from opentalos.tracing.schema import metadata as tracing_metadata

_ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"


def test_migrations_match_the_application_metadata(postgres_url, monkeypatch):
    # alembic/env.py prefers the DATABASE_URL environment variable (and rewrites a plain
    # "postgresql://" URL to "postgresql+asyncpg://" itself), so this runs the exact same
    # migration chain a real deployment would, against a fresh container.
    #
    # Note: this is intentionally a plain (non-async) test function, not `async def` +
    # @pytest.mark.asyncio -- env.py's run_migrations_online() calls asyncio.run(...)
    # internally, which raises if invoked from inside an already-running event loop. Since
    # nothing else in this test needs to await anything, staying fully synchronous sidesteps
    # that nested-event-loop problem entirely.
    monkeypatch.setenv("DATABASE_URL", postgres_url)
    config = Config(str(_ALEMBIC_INI))
    command.upgrade(config, "head")
    try:
        # compare_metadata needs a plain (sync) DBAPI connection; psycopg2 (a dev-only
        # dependency, see pyproject.toml) is used here purely as that sync bridge for
        # Alembic's comparison tooling -- the application itself only ever uses asyncpg.
        sync_url = postgres_url.replace("postgresql://", "postgresql+psycopg2://", 1)
        sync_engine = create_sync_engine(sync_url)
        try:
            # MigrationContext.configure() reflects the WHOLE database, so comparing that
            # reflection against checkpoint_metadata and tracing_metadata one at a time (as
            # sketched originally) produces false-positive "remove_table" diffs -- each single
            # metadata object doesn't know about the other schema module's table, which the
            # reflection still sees sitting in the database. Combine both into one throwaway
            # MetaData for the actual comparison instead (Table.to_metadata() copies each table
            # into it; it does NOT mutate the source checkpoint_metadata/tracing_metadata
            # singletons, so this is unrelated to the import-time-mutation bug Fix 2 addressed
            # in alembic/env.py).
            combined_metadata = MetaData()
            for table in [*checkpoint_metadata.tables.values(), *tracing_metadata.tables.values()]:
                table.to_metadata(combined_metadata)

            with sync_engine.connect() as conn:
                mc = MigrationContext.configure(conn)
                diff = compare_metadata(mc, combined_metadata)
            assert diff == [], f"schema.py and the applied migrations disagree: {diff}"
        finally:
            sync_engine.dispose()
    finally:
        # postgres_url is a session-scoped fixture shared with every other Postgres test
        # module in this suite -- leave the container exactly as this test found it by
        # downgrading all the way back to base, the same way every other Postgres fixture
        # here tears down its own tables/policies/grants.
        command.downgrade(config, "base")
