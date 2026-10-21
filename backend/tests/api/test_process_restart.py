"""Real HTTP request across a complete uvicorn process stop/start."""
import os
import socket
import subprocess
import sys
import time
from contextlib import contextmanager

import httpx
import pytest
from conftest import BACKEND, CLIENT_PASSWORD, SECRET

pytestmark = pytest.mark.postgres


@contextmanager
def running_server(settings, log_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    environment = {**os.environ,
                   "DATABASE_URL": settings.database_url.get_secret_value(),
                   "JWT_SECRET": SECRET, "PYTHONDONTWRITEBYTECODE": "1"}
    with log_path.open("w") as output:
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:create_app", "--factory", "--host", "127.0.0.1",
             "--port", str(port), "--no-access-log"],
            cwd=BACKEND, env=environment, stdout=output, stderr=output,
        )
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=3, trust_env=False) as client:
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        pytest.fail("uvicorn exited: " + log_path.read_text())
                    try:
                        if client.get("/ready").status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.1)
                else:
                    pytest.fail("uvicorn did not become ready: " + log_path.read_text())
                yield client
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def login(client):
    response = client.post("/api/v1/auth/login", data={"username": "client1", "password": CLIENT_PASSWORD})
    assert response.status_code == 200
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def test_draft_survives_real_server_process_restart(application, settings, tmp_path):
    with running_server(settings, tmp_path / "first-server.log") as client:
        headers = login(client)
        response = client.post("/api/v1/applications", headers=headers,
                               json={"product_code": "equipment", "requested_amount": "700000.12", "purpose": "Станок"})
        assert response.status_code == 201
        draft = response.json()
    # A different OS process, a new SQLAlchemy engine and a new login.
    with running_server(settings, tmp_path / "second-server.log") as client:
        response = client.get(f"/api/v1/applications/{draft['id']}", headers=login(client))
        assert response.status_code == 200
        assert response.json() == draft
