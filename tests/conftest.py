import pytest
from fastapi.testclient import TestClient

from app import db
from app.config import settings
from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    db.use_database(f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setattr(settings, "output_dir", tmp_path / "generated")
    monkeypatch.setattr(settings, "run_jobs_inline", True)

    with TestClient(app) as c:
        yield c

    db.engine.dispose()


@pytest.fixture
def paused_worker(monkeypatch):
    """Jobs get queued but never picked up, to inspect the pending state."""
    monkeypatch.setattr(settings, "run_jobs_inline", False)
    monkeypatch.setattr("app.jobs._executor.submit", lambda *args: None)


def make_payload(*recipients, course="Drone Survey & Mapping Basics"):
    if not recipients:
        recipients = (
            {"name": "Ananya Penumudi", "email": "ananya@example.com"},
            {"name": "Rahul Varma", "email": "rahul@example.com"},
            {"name": "Sneha Reddy", "email": "sneha@example.com"},
        )
    return {
        "course_name": course,
        "issued_on": "2026-10-04",
        "issued_by": "Skyline Drone Academy",
        "recipients": list(recipients),
    }
