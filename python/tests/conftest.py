import os

# testcontainers' Ryuk/Reaper sidecar consistently loses a Docker-Desktop-for-Mac port-publish
# race on this kind of local setup (docker.api.port() returns empty immediately after container
# start, succeeds ~2s later on reload) -- disabling it only removes the crash-safety-net cleanup
# (containers a crashed test run would otherwise leave behind); the normal happy-path teardown via
# PostgresContainer's own context manager is unaffected. Must be set before testcontainers is
# imported/used anywhere, so this lives at the very top of the shared conftest.
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")

import pytest
from testcontainers.postgres import PostgresContainer


@pytest.fixture(scope="session")
def postgres_url():
    with PostgresContainer("postgres:16-alpine", driver=None) as container:
        yield container.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
