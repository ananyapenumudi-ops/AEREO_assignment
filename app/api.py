import io
import re
import zipfile
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import jobs
from app.config import settings
from app.db import get_db
from app.models import Certificate, CertStatus, Job, JobStatus
from app.recipients import parse_csv
from app.schemas import (
    CertificateOut,
    JobAccepted,
    JobCreate,
    JobOut,
    Progress,
    RowProblem,
    VerifyOut,
)

router = APIRouter()


@router.post("/jobs", status_code=202, response_model=JobAccepted, tags=["jobs"])
def create_job(payload: JobCreate, db: Session = Depends(get_db)):
    """Submit recipients as JSON. Certificates are generated in the background."""
    job = jobs.create_job(
        db,
        course_name=payload.course_name,
        issued_on=payload.issued_on,
        issued_by=payload.issued_by,
        recipients=[r.model_dump() for r in payload.recipients],
    )
    return _accepted(db, job)


@router.post("/jobs/upload", status_code=202, response_model=JobAccepted, tags=["jobs"])
async def create_job_from_csv(
    file: UploadFile = File(..., description="CSV with 'name' and 'email' columns"),
    course_name: str = Form(..., min_length=1, max_length=120),
    issued_on: date | None = Form(None),
    issued_by: str | None = Form(None, max_length=80),
    db: Session = Depends(get_db),
):
    """Submit recipients as a CSV file."""
    if not course_name.strip():
        raise HTTPException(422, "course_name cannot be blank")
    try:
        recipients = parse_csv(await file.read())
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if len(recipients) > settings.max_recipients_per_job:
        raise HTTPException(422, f"a job can have at most {settings.max_recipients_per_job} recipients")

    job = jobs.create_job(db, course_name, issued_on, issued_by, recipients)
    return _accepted(db, job)


@router.get("/jobs/{job_id}", response_model=JobOut, tags=["jobs"])
def get_job(job_id: str, db: Session = Depends(get_db)):
    """Job status, progress counts, and every row that didn't produce a certificate."""
    job = _get_job(db, job_id)
    counts = jobs.count_by_status(db, job_id)
    done = job.total - counts[CertStatus.PENDING]

    problems = db.scalars(
        select(Certificate)
        .where(
            Certificate.job_id == job_id,
            Certificate.status.in_([CertStatus.FAILED, CertStatus.INVALID]),
        )
        .order_by(Certificate.row_number)
    )

    return JobOut(
        id=job.id,
        course_name=job.course_name,
        issued_on=job.issued_on,
        issued_by=job.issued_by,
        status=job.status,
        total=job.total,
        progress=Progress(
            pending=counts[CertStatus.PENDING],
            generated=counts[CertStatus.GENERATED],
            failed=counts[CertStatus.FAILED],
            invalid=counts[CertStatus.INVALID],
            percent_complete=round(100 * done / job.total, 1),
        ),
        problems=[
            RowProblem(
                certificate_id=c.id,
                row_number=c.row_number,
                name=c.recipient_name,
                email=c.recipient_email,
                status=c.status,
                error=c.error,
            )
            for c in problems
        ],
        error=job.error,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


@router.post("/jobs/{job_id}/retry", status_code=202, response_model=JobAccepted, tags=["jobs"])
def retry_job(job_id: str, db: Session = Depends(get_db)):
    """Re-run only the certificates that failed during generation."""
    job = _get_job(db, job_id)
    if job.status in JobStatus.UNFINISHED:
        raise HTTPException(409, "job is still running")
    queued = jobs.retry_failed(db, job)
    if not queued:
        raise HTTPException(409, "job has no failed certificates to retry")
    return _accepted(db, job, queued)


@router.get("/jobs/{job_id}/certificates", response_model=list[CertificateOut], tags=["certificates"])
def list_certificates(
    job_id: str,
    status: str | None = Query(None, description="pending, generated, failed or invalid"),
    db: Session = Depends(get_db),
):
    _get_job(db, job_id)
    if status and status not in CertStatus.ALL:
        raise HTTPException(422, f"status must be one of: {', '.join(CertStatus.ALL)}")

    query = select(Certificate).where(Certificate.job_id == job_id)
    if status:
        query = query.where(Certificate.status == status)
    return [_cert_out(c) for c in db.scalars(query.order_by(Certificate.row_number))]


@router.get("/jobs/{job_id}/download", tags=["certificates"])
def download_job(job_id: str, db: Session = Depends(get_db)):
    """All generated certificates of a job as a ZIP."""
    job = _get_job(db, job_id)
    if job.status in JobStatus.UNFINISHED:
        raise HTTPException(409, "job is still running")

    certs = db.scalars(
        select(Certificate)
        .where(Certificate.job_id == job_id, Certificate.status == CertStatus.GENERATED)
        .order_by(Certificate.row_number)
    ).all()
    if not certs:
        raise HTTPException(404, "job has no generated certificates")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for cert in certs:
            zf.write(cert.file_path, arcname=_download_name(cert))
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="certificates-{job_id[:8]}.zip"'},
    )


@router.get("/certificates/{cert_id}", response_model=CertificateOut, tags=["certificates"])
def get_certificate(cert_id: str, db: Session = Depends(get_db)):
    return _cert_out(_get_cert(db, cert_id))


@router.get("/certificates/{cert_id}/download", tags=["certificates"])
def download_certificate(cert_id: str, db: Session = Depends(get_db)):
    cert = _get_cert(db, cert_id)
    if cert.status != CertStatus.GENERATED:
        raise HTTPException(409, f"certificate is {cert.status}, nothing to download")
    if not Path(cert.file_path).exists():
        raise HTTPException(410, "certificate file is missing from storage")
    return FileResponse(cert.file_path, media_type="application/pdf", filename=_download_name(cert))


@router.get("/verify/{code}", response_model=VerifyOut, tags=["verification"])
def verify_certificate(code: str, db: Session = Depends(get_db)):
    """Check a certificate is genuine using the code printed on it."""
    cert = db.scalar(
        select(Certificate).where(
            Certificate.verification_code == code.strip().upper(),
            Certificate.status == CertStatus.GENERATED,
        )
    )
    if cert is None:
        raise HTTPException(404, "no certificate found with this code")
    return VerifyOut(
        valid=True,
        verification_code=cert.verification_code,
        name=cert.recipient_name,
        course_name=cert.job.course_name,
        issued_on=cert.job.issued_on,
        issued_by=cert.job.issued_by,
    )


def _accepted(db: Session, job: Job, queued: int | None = None) -> JobAccepted:
    db.refresh(job)
    invalid = jobs.count_by_status(db, job.id)[CertStatus.INVALID]
    return JobAccepted(
        id=job.id,
        status=job.status,
        total=job.total,
        queued=job.total - invalid if queued is None else queued,
        invalid=invalid,
        status_url=f"/jobs/{job.id}",
    )


def _get_job(db: Session, job_id: str) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    return job


def _get_cert(db: Session, cert_id: str) -> Certificate:
    cert = db.get(Certificate, cert_id)
    if cert is None:
        raise HTTPException(404, "certificate not found")
    return cert


def _cert_out(cert: Certificate) -> CertificateOut:
    generated = cert.status == CertStatus.GENERATED
    return CertificateOut(
        id=cert.id,
        job_id=cert.job_id,
        row_number=cert.row_number,
        name=cert.recipient_name,
        email=cert.recipient_email,
        status=cert.status,
        error=cert.error,
        verification_code=cert.verification_code if generated else None,
        download_url=f"/certificates/{cert.id}/download" if generated else None,
        generated_at=cert.generated_at,
    )


def _download_name(cert: Certificate) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", cert.recipient_name or "").strip("_") or "certificate"
    return f"{cert.row_number:04d}_{slug}.pdf"
