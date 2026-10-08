import secrets
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


def _verification_code() -> str:
    return secrets.token_hex(5).upper()


class JobStatus:
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    FAILED = "failed"

    UNFINISHED = (PENDING, PROCESSING)


class CertStatus:
    PENDING = "pending"
    GENERATED = "generated"
    FAILED = "failed"    # input was fine, PDF generation broke - can be retried
    INVALID = "invalid"  # rejected by validation, never attempted

    ALL = (PENDING, GENERATED, FAILED, INVALID)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    course_name: Mapped[str] = mapped_column(String(120))
    issued_on: Mapped[date] = mapped_column(Date)
    issued_by: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(32), default=JobStatus.PENDING, index=True)
    total: Mapped[int] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    certificates: Mapped[list["Certificate"]] = relationship(
        back_populates="job", order_by="Certificate.row_number"
    )


class Certificate(Base):
    __tablename__ = "certificates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    row_number: Mapped[int] = mapped_column(Integer)
    recipient_name: Mapped[str | None] = mapped_column(String(200))
    recipient_email: Mapped[str | None] = mapped_column(String(320))
    status: Mapped[str] = mapped_column(String(32), default=CertStatus.PENDING, index=True)
    error: Mapped[str | None] = mapped_column(Text)
    file_path: Mapped[str | None] = mapped_column(String(500))
    verification_code: Mapped[str] = mapped_column(
        String(16), unique=True, default=_verification_code
    )
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    job: Mapped[Job] = relationship(back_populates="certificates")
