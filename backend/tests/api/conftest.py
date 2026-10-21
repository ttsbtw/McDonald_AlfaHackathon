import os
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.config import Settings
from app.main import create_app
from app.seed import seed_demo

BACKEND = Path(__file__).resolve().parents[2]
CLIENT_PASSWORD = "Client-one-test-password!"
SECOND_PASSWORD = "Client-two-test-password!"
EMPLOYEE_PASSWORD = "Employee-test-password!"
SECRET = "test-only-secret-with-more-than-32-characters"


def migration_config(url):
    config = Config(str(BACKEND / "alembic.ini"))
    config.attributes["database_url"] = url
    return config


@pytest.fixture(scope="session")
def postgres_url():
    external = os.environ.get("TEST_DATABASE_URL")
    if external:
        url = make_url(external)
        if url.drivername != "postgresql+psycopg" or not (url.database or "").startswith("test_"):
            pytest.fail("TEST_DATABASE_URL must use psycopg and a dedicated database named test_*")
        yield external
        return
    pgserver = pytest.importorskip("pgserver", reason="Set TEST_DATABASE_URL or install requirements-postgres-test.txt")
    # Short paths also fit PostgreSQL's Unix socket path length limit on macOS.
    with tempfile.TemporaryDirectory(prefix="mcd-pg-", dir="/tmp") as temp:
        server = pgserver.get_server(Path(temp) / "data", cleanup_mode="stop")
        try:
            uri = server.get_uri().replace("postgresql://", "postgresql+psycopg://", 1)
            yield uri
        finally:
            server.cleanup()


@pytest.fixture
def database_url(postgres_url):
    # Each test owns a new schema; never drop existing application tables.
    schema = "test_" + uuid4().hex
    engine = create_engine(postgres_url)
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    url = make_url(postgres_url).update_query_dict({"options": f"-csearch_path={schema}"})
    uri = url.render_as_string(hide_password=False)
    command.upgrade(migration_config(uri), "head")
    try:
        yield uri
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


@pytest.fixture
def settings(database_url):
    return Settings(_env_file=None, database_url=database_url, jwt_secret=SECRET,
                    seed_demo=True, demo_client_password=CLIENT_PASSWORD,
                    demo_second_client_password=SECOND_PASSWORD, demo_employee_password=EMPLOYEE_PASSWORD)


@pytest.fixture
def application(settings):
    app = create_app(settings)
    with app.state.session_factory() as session:
        seed_demo(session, settings)
    yield app
    app.state.engine.dispose()


@pytest.fixture
def client(application):
    with TestClient(application) as http:
        yield http


def auth_headers(client, username="client1", password=CLIENT_PASSWORD):
    response = client.post("/api/v1/auth/login", data={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["access_token"]}


@pytest.fixture
def headers(client):
    return auth_headers(client)
