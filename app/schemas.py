from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator

from app.config import settings


class RecipientIn(BaseModel):
    # optional on purpose - a bad row is marked invalid instead of failing the whole request
    name: str | None = None
    email: str | None = None


class JobCreate(BaseModel):
    course_name: str = Field(min_length=1, max_length=120)
    issued_on: date | None = None
    issued_by: str | None = Field(default=None, max_length=80)
    recipients: list[RecipientIn] = Field(min_length=1)

    model_config = {
        "json_schema_extra": {
            "example": {
                "course_name": "DGCA Small Category Drone Pilot Training",
                "issued_on": "2026-10-04",
                "issued_by": "Skyline Drone Academy",
                "recipients": [
                    {"name": "Ananya Penumudi", "email": "ananya@example.com"},
                    {"name": "Rahul Varma", "email": "rahul@example.com"},
                ],
            }
        }
    }

    @field_validator("course_name")
    @classmethod
    def course_name_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("course_name cannot be blank")
        return value

    @field_validator("recipients")
    @classmethod
    def within_limit(cls, value: list[RecipientIn]) -> list[RecipientIn]:
        if len(value) > settings.max_recipients_per_job:
            raise ValueError(f"a job can have at most {settings.max_recipients_per_job} recipients")
        return value


class JobAccepted(BaseModel):
    id: str
    status: str
    total: int
    queued: int
    invalid: int
    status_url: str


class Progress(BaseModel):
    pending: int
    generated: int
    failed: int
    invalid: int
    percent_complete: float


class RowProblem(BaseModel):
    certificate_id: str
    row_number: int
    name: str | None
    email: str | None
    status: str
    error: str | None


class JobOut(BaseModel):
    id: str
    course_name: str
    issued_on: date
    issued_by: str | None
    status: str
    total: int
    progress: Progress
    problems: list[RowProblem]
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class CertificateOut(BaseModel):
    id: str
    job_id: str
    row_number: int
    name: str | None
    email: str | None
    status: str
    error: str | None
    verification_code: str | None
    download_url: str | None
    generated_at: datetime | None


class VerifyOut(BaseModel):
    valid: bool
    verification_code: str
    name: str
    course_name: str
    issued_on: date
    issued_by: str | None
