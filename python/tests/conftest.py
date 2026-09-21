import pytest
from testcontainers.postgres import PostgresContainer


@pytest.fixture(scope="session")
def postgres_url():
    with PostgresContainer("postgres:16-alpine", driver=None) as container:
        yield container.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
