from app import db
from app.config import settings
from app.jobs import resume_unfinished_jobs
from app.models import Job, JobStatus
from tests.conftest import make_payload


def test_create_job_returns_202_with_job_id(client):
    res = client.post("/jobs", json=make_payload())

    assert res.status_code == 202
    body = res.json()
    assert body["total"] == 3
    assert body["queued"] == 3
    assert body["invalid"] == 0
    assert body["status_url"] == f"/jobs/{body['id']}"


def test_job_status_when_finished(client):
    job_id = client.post("/jobs", json=make_payload()).json()["id"]

    job = client.get(f"/jobs/{job_id}").json()
    assert job["status"] == "completed"
    assert job["progress"] == {
        "pending": 0,
        "generated": 3,
        "failed": 0,
        "invalid": 0,
        "percent_complete": 100.0,
    }
    assert job["problems"] == []
    assert job["finished_at"] is not None


def test_job_status_while_pending(client, paused_worker):
    job_id = client.post("/jobs", json=make_payload()).json()["id"]

    job = client.get(f"/jobs/{job_id}").json()
    assert job["status"] == "pending"
    assert job["progress"]["pending"] == 3
    assert job["progress"]["percent_complete"] == 0.0


def test_unknown_job_is_404(client):
    assert client.get("/jobs/does-not-exist").status_code == 404


def test_empty_recipient_list_is_rejected(client):
    payload = make_payload()
    payload["recipients"] = []
    assert client.post("/jobs", json=payload).status_code == 422


def test_missing_course_name_is_rejected(client):
    payload = make_payload()
    del payload["course_name"]
    assert client.post("/jobs", json=payload).status_code == 422


def test_blank_course_name_is_rejected(client):
    assert client.post("/jobs", json=make_payload(course="   ")).status_code == 422


def test_too_many_recipients_is_rejected(client, monkeypatch):
    monkeypatch.setattr(settings, "max_recipients_per_job", 2)
    assert client.post("/jobs", json=make_payload()).status_code == 422


def test_invalid_rows_are_marked_and_valid_rows_still_generate(client):
    payload = make_payload(
        {"name": "Ananya Penumudi", "email": "ananya@example.com"},
        {"name": "", "email": "blank@example.com"},
        {"name": "No Email"},
        {"name": "Bad Email", "email": "bad-email.com"},
        {"name": "Duplicate", "email": "ANANYA@example.com"},
        {"name": "12345", "email": "numbers@example.com"},
        {"name": "Rahul Varma", "email": "rahul@example.com"},
    )
    created = client.post("/jobs", json=payload).json()
    assert created["invalid"] == 5
    assert created["queued"] == 2

    job = client.get(f"/jobs/{created['id']}").json()
    assert job["status"] == "completed_with_errors"
    assert job["progress"]["generated"] == 2

    errors = {p["row_number"]: p["error"] for p in job["problems"]}
    assert errors == {
        2: "name is required",
        3: "email is required",
        4: "'bad-email.com' is not a valid email address",
        5: "duplicate email 'ANANYA@example.com' in this job",
        6: "name must contain at least one letter",
    }


def test_whitespace_is_normalised(client):
    payload = make_payload({"name": "  Ananya    Penumudi ", "email": " a@example.com "})
    job_id = client.post("/jobs", json=payload).json()["id"]

    cert = client.get(f"/jobs/{job_id}/certificates").json()[0]
    assert cert["name"] == "Ananya Penumudi"
    assert cert["email"] == "a@example.com"


def test_job_with_only_invalid_rows_fails_immediately(client):
    payload = make_payload({"name": "", "email": "x"}, {"name": "Y", "email": ""})
    created = client.post("/jobs", json=payload).json()

    assert created["status"] == "failed"
    assert created["queued"] == 0
    assert client.get(created["status_url"]).json()["error"] == "every recipient failed validation"


def test_csv_upload(client):
    csv_data = (
        "Name,Email,Batch\n"
        "Ananya Penumudi,ananya@example.com,B1\n"
        ",,\n"
        "Rahul Varma,rahul@example.com,B1\n"
    )
    res = client.post(
        "/jobs/upload",
        files={"file": ("participants.csv", csv_data, "text/csv")},
        data={"course_name": "Drone Survey & Mapping Basics", "issued_on": "2026-10-04"},
    )
    assert res.status_code == 202
    assert res.json()["total"] == 2

    job = client.get(res.json()["status_url"]).json()
    assert job["progress"]["generated"] == 2


def test_csv_without_email_column_is_400(client):
    res = client.post(
        "/jobs/upload",
        files={"file": ("people.csv", "name\nAnanya\n", "text/csv")},
        data={"course_name": "Drone Basics"},
    )
    assert res.status_code == 400
    assert res.json()["detail"] == "CSV is missing column(s): email"


def test_unfinished_jobs_resume_on_startup(client, paused_worker, monkeypatch):
    job_id = client.post("/jobs", json=make_payload()).json()["id"]

    with db.SessionLocal() as session:
        session.get(Job, job_id).status = JobStatus.PROCESSING
        session.commit()

    monkeypatch.setattr(settings, "run_jobs_inline", True)
    assert resume_unfinished_jobs() == 1
    assert client.get(f"/jobs/{job_id}").json()["status"] == "completed"


def test_csv_over_size_limit_is_413(client, monkeypatch):
    monkeypatch.setattr(settings, "max_upload_bytes", 100)
    csv_data = "name,email\n" + "Ananya Penumudi,ananya@example.com\n" * 10
    res = client.post(
        "/jobs/upload",
        files={"file": ("big.csv", csv_data, "text/csv")},
        data={"course_name": "Drone Basics"},
    )
    assert res.status_code == 413


def test_oversized_values_are_rejected_without_breaking_the_job(client):
    payload = make_payload(
        {"name": "A" * 300, "email": "long.name@example.com"},
        {"name": "Long Email", "email": "x" * 400 + "@example.com"},
        {"name": "Ananya Penumudi", "email": "ananya@example.com"},
    )
    created = client.post("/jobs", json=payload)
    assert created.status_code == 202
    assert created.json()["invalid"] == 2

    job = client.get(created.json()["status_url"]).json()
    assert job["progress"]["generated"] == 1
    assert [p["error"] for p in job["problems"]] == [
        "name is longer than 80 characters",
        "email is longer than 254 characters",
    ]
