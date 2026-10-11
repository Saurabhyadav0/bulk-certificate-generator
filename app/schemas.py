from datetime import date, datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints, field_validator

from app.config import settings
from app.models import CertificateStatus, JobStatus

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------


class RecipientIn(BaseModel):
    """Validation rules for a single recipient.

    This model is NOT used directly in the request body. Each recipient is
    validated separately (see services/validation.py) so that one bad entry
    does not cause the whole batch to be rejected.
    """

    model_config = ConfigDict(extra="ignore")

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    email: EmailStr


class JobCreate(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "course_name": "Python for Data Engineering",
                "issue_date": "2026-10-01",
                "issuer": "Acme Academy",
                "recipients": [
                    {"name": "Asha Rao", "email": "asha@example.com"},
                    {"name": "Rahul Mehta", "email": "rahul@example.com"},
                ],
            }
        }
    )

    course_name: Annotated[NonEmptyStr, StringConstraints(max_length=150)]
    issue_date: date = Field(default_factory=date.today)
    issuer: Annotated[NonEmptyStr, StringConstraints(max_length=100)] = Field(
        default_factory=lambda: settings.default_issuer
    )
    # Typed loosely on purpose: per-recipient checks happen later, row by row.
    recipients: list[Any] = Field(min_length=1)

    @field_validator("recipients")
    @classmethod
    def limit_batch_size(cls, value: list[Any]) -> list[Any]:
        limit = settings.max_recipients_per_job
        if len(value) > limit:
            raise ValueError(f"A job can contain at most {limit} recipients (got {len(value)})")
        return value


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------


class InvalidRecipient(BaseModel):
    index: int
    errors: list[str]


class JobCreatedResponse(BaseModel):
    job_id: str
    status: JobStatus
    total_recipients: int
    accepted: int
    rejected: int
    invalid_recipients: list[InvalidRecipient]
    status_url: str
    certificates_url: str


class StatusCounts(BaseModel):
    pending: int = 0
    processing: int = 0
    success: int = 0
    failed: int = 0
    invalid: int = 0


class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    course_name: str
    issue_date: date
    issuer: str
    total_recipients: int
    counts: StatusCounts
    progress_percent: float
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    certificates_url: str
    download_url: str | None


class CertificateOut(BaseModel):
    id: str
    row_index: int
    recipient_name: str | None
    email: str | None
    status: CertificateStatus
    error_message: str | None
    verification_code: str | None
    generated_at: datetime | None
    download_url: str | None


class CertificateListResponse(BaseModel):
    job_id: str
    total: int
    limit: int
    offset: int
    items: list[CertificateOut]
