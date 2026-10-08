import io
import zipfile
from datetime import date

import pytest
from pypdf import PdfReader

from app import generator
from tests.conftest import make_payload

real_render = generator.render_certificate


def pdf_text(data: bytes) -> str:
    return " ".join(page.extract_text() for page in PdfReader(io.BytesIO(data)).pages)


@pytest.fixture
def broken_for_rahul(monkeypatch):
    def render(path, name, **kwargs):
        if name == "Rahul Varma":
            raise RuntimeError("font file could not be loaded")
        return real_render(path, name, **kwargs)

    monkeypatch.setattr(generator, "render_certificate", render)


def test_pdf_contains_recipient_details(tmp_path):
    path = generator.render_certificate(
        tmp_path / "out.pdf",
        name="Ananya Penumudi",
        course_name="Drone Survey & Mapping Basics",
        issued_on=date(2026, 10, 4),
        issued_by="Skyline Drone Academy",
        verification_code="ABC123DEF4",
    )
    text = pdf_text(path.read_bytes())

    assert "Ananya Penumudi" in text
    assert "Drone Survey & Mapping Basics" in text
    assert "04 October 2026" in text
    assert "Skyline Drone Academy" in text
    assert "ABC123DEF4" in text


def test_long_names_still_render(tmp_path):
    long_name = "Venkata Sai Lakshmi Narasimha Ananya Penumudi Srinivasa Rao Chowdary"
    path = generator.render_certificate(
        tmp_path / "long.pdf", long_name, "Course", date(2026, 1, 1), None, "X"
    )
    assert long_name in pdf_text(path.read_bytes())


def test_one_failure_does_not_stop_the_others(client, broken_for_rahul):
    job_id = client.post("/jobs", json=make_payload()).json()["id"]
    job = client.get(f"/jobs/{job_id}").json()

    assert job["status"] == "completed_with_errors"
    assert job["progress"]["generated"] == 2
    assert job["progress"]["failed"] == 1
    assert job["problems"] == [
        {
            "certificate_id": job["problems"][0]["certificate_id"],
            "row_number": 2,
            "name": "Rahul Varma",
            "email": "rahul@example.com",
            "status": "failed",
            "error": "RuntimeError: font file could not be loaded",
        }
    ]


def test_job_fails_when_every_certificate_fails(client, monkeypatch):
    def always_fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(generator, "render_certificate", always_fail)

    job_id = client.post("/jobs", json=make_payload()).json()["id"]
    job = client.get(f"/jobs/{job_id}").json()
    assert job["status"] == "failed"
    assert job["progress"]["failed"] == 3


def test_retry_regenerates_only_failed_certificates(client, broken_for_rahul, monkeypatch):
    job_id = client.post("/jobs", json=make_payload()).json()["id"]
    first_round = {c["name"]: c["generated_at"] for c in client.get(f"/jobs/{job_id}/certificates").json()}

    monkeypatch.setattr(generator, "render_certificate", real_render)
    res = client.post(f"/jobs/{job_id}/retry")
    assert res.status_code == 202
    assert res.json()["queued"] == 1

    job = client.get(f"/jobs/{job_id}").json()
    assert job["status"] == "completed"
    assert job["problems"] == []

    second_round = {c["name"]: c["generated_at"] for c in client.get(f"/jobs/{job_id}/certificates").json()}
    assert second_round["Ananya Penumudi"] == first_round["Ananya Penumudi"]
    assert second_round["Rahul Varma"] is not None


def test_retry_with_nothing_failed_is_409(client):
    job_id = client.post("/jobs", json=make_payload()).json()["id"]
    assert client.post(f"/jobs/{job_id}/retry").status_code == 409


def test_list_certificates_and_filter_by_status(client):
    payload = make_payload(
        {"name": "Ananya Penumudi", "email": "ananya@example.com"},
        {"name": "Bad Row", "email": "nope"},
    )
    job_id = client.post("/jobs", json=payload).json()["id"]

    certs = client.get(f"/jobs/{job_id}/certificates").json()
    assert [c["status"] for c in certs] == ["generated", "invalid"]
    assert certs[0]["download_url"] == f"/certificates/{certs[0]['id']}/download"
    assert certs[1]["download_url"] is None

    assert len(client.get(f"/jobs/{job_id}/certificates?status=generated").json()) == 1
    assert client.get(f"/jobs/{job_id}/certificates?status=banana").status_code == 422


def test_download_single_certificate(client):
    job_id = client.post("/jobs", json=make_payload()).json()["id"]
    cert = client.get(f"/jobs/{job_id}/certificates").json()[0]

    res = client.get(cert["download_url"])
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/pdf"
    assert "0001_Ananya_Penumudi.pdf" in res.headers["content-disposition"]
    assert "Ananya Penumudi" in pdf_text(res.content)


def test_download_of_invalid_certificate_is_409(client):
    payload = make_payload({"name": "Ok Person", "email": "ok@example.com"}, {"name": ""})
    job_id = client.post("/jobs", json=payload).json()["id"]
    invalid = client.get(f"/jobs/{job_id}/certificates?status=invalid").json()[0]

    assert client.get(f"/certificates/{invalid['id']}/download").status_code == 409


def test_download_job_as_zip(client):
    job_id = client.post("/jobs", json=make_payload()).json()["id"]

    res = client.get(f"/jobs/{job_id}/download")
    assert res.status_code == 200
    assert zipfile.ZipFile(io.BytesIO(res.content)).namelist() == [
        "0001_Ananya_Penumudi.pdf",
        "0002_Rahul_Varma.pdf",
        "0003_Sneha_Reddy.pdf",
    ]


def test_verify_certificate(client):
    job_id = client.post("/jobs", json=make_payload()).json()["id"]
    cert = client.get(f"/jobs/{job_id}/certificates").json()[0]

    res = client.get(f"/verify/{cert['verification_code'].lower()}")
    assert res.status_code == 200
    assert res.json()["name"] == "Ananya Penumudi"
    assert res.json()["course_name"] == "Drone Survey & Mapping Basics"

    assert client.get("/verify/NOTAREALCODE").status_code == 404
