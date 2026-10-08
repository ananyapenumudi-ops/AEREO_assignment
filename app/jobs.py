import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app import generator
from app.config import settings
from app.db import SessionLocal
from app.models import Certificate, CertStatus, Job, JobStatus, utcnow
from app.recipients import check_recipient, clean

log = logging.getLogger(__name__)

# one thread per job; certificates within a job are generated in order
_executor = ThreadPoolExecutor(max_workers=settings.worker_threads, thread_name_prefix="certgen")


def create_job(
    db: Session,
    course_name: str,
    issued_on: date | None,
    issued_by: str | None,
    recipients: list[dict],
) -> Job:
    job = Job(
        course_name=course_name.strip(),
        issued_on=issued_on or date.today(),
        issued_by=clean(issued_by) or None,
        total=len(recipients),
    )
    db.add(job)

    seen_emails: set[str] = set()
    for row_number, recipient in enumerate(recipients, start=1):
        name = clean(recipient.get("name"))
        email = clean(recipient.get("email"))
        error = check_recipient(name, email, seen_emails)
        job.certificates.append(
            Certificate(
                row_number=row_number,
                recipient_name=name or None,
                recipient_email=email or None,
                status=CertStatus.INVALID if error else CertStatus.PENDING,
                error=error,
            )
        )

    if all(cert.status == CertStatus.INVALID for cert in job.certificates):
        job.status = JobStatus.FAILED
        job.error = "every recipient failed validation"
        job.finished_at = utcnow()

    db.commit()
    if job.status != JobStatus.FAILED:
        enqueue(job.id)
    return job


def retry_failed(db: Session, job: Job) -> int:
    queued = db.execute(
        update(Certificate)
        .where(Certificate.job_id == job.id, Certificate.status == CertStatus.FAILED)
        .values(status=CertStatus.PENDING, error=None)
    ).rowcount
    if queued:
        job.status = JobStatus.PENDING
        job.error = None
        job.finished_at = None
    db.commit()
    if queued:
        enqueue(job.id)
    return queued


def enqueue(job_id: str) -> None:
    if settings.run_jobs_inline:
        process_job(job_id)
    else:
        _executor.submit(process_job, job_id)


def process_job(job_id: str) -> None:
    try:
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            job.status = JobStatus.PROCESSING
            job.started_at = job.started_at or utcnow()
            db.commit()

            pending_ids = db.scalars(
                select(Certificate.id)
                .where(Certificate.job_id == job_id, Certificate.status == CertStatus.PENDING)
                .order_by(Certificate.row_number)
            ).all()

        for cert_id in pending_ids:
            _generate_one(cert_id)

        _finish_job(job_id)
    except Exception as exc:
        log.exception("job %s crashed", job_id)
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            job.status = JobStatus.FAILED
            job.error = str(exc)[:1000]
            job.finished_at = utcnow()
            db.commit()


def _generate_one(cert_id: str) -> None:
    with SessionLocal() as db:
        cert = db.get(Certificate, cert_id)
        job = cert.job
        path = settings.output_dir / job.id / f"{cert.id}.pdf"
        try:
            generator.render_certificate(
                path,
                name=cert.recipient_name,
                course_name=job.course_name,
                issued_on=job.issued_on,
                issued_by=job.issued_by,
                verification_code=cert.verification_code,
            )
            cert.status = CertStatus.GENERATED
            cert.file_path = str(path)
            cert.generated_at = utcnow()
        except Exception as exc:
            # one bad certificate shouldn't stop the rest of the job
            log.warning("certificate %s (row %s) failed: %s", cert.id, cert.row_number, exc)
            cert.status = CertStatus.FAILED
            cert.error = f"{type(exc).__name__}: {exc}"[:1000]
            path.unlink(missing_ok=True)
        db.commit()


def _finish_job(job_id: str) -> None:
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        counts = count_by_status(db, job_id)
        if counts[CertStatus.GENERATED] == 0:
            job.status = JobStatus.FAILED
            job.error = "no certificates could be generated"
        elif counts[CertStatus.FAILED] or counts[CertStatus.INVALID]:
            job.status = JobStatus.COMPLETED_WITH_ERRORS
        else:
            job.status = JobStatus.COMPLETED
        job.finished_at = utcnow()
        db.commit()


def count_by_status(db: Session, job_id: str) -> dict[str, int]:
    # counted from the rows rather than stored on the job, so it can't go out of sync
    rows = db.execute(
        select(Certificate.status, func.count())
        .where(Certificate.job_id == job_id)
        .group_by(Certificate.status)
    ).all()
    return {status: 0 for status in CertStatus.ALL} | dict(rows)


def resume_unfinished_jobs() -> int:
    """Re-queue jobs that were cut off by a restart. Only pending rows get
    processed, so certificates that were already generated aren't redone."""
    with SessionLocal() as db:
        job_ids = db.scalars(
            select(Job.id).where(Job.status.in_(JobStatus.UNFINISHED)).order_by(Job.created_at)
        ).all()
    for job_id in job_ids:
        log.info("resuming job %s", job_id)
        enqueue(job_id)
    return len(job_ids)
