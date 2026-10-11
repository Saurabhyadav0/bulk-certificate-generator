"""Database operations for jobs and certificates (no HTTP concerns here)."""

import secrets

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import Certificate, CertificateStatus, Job, JobStatus
from app.schemas import JobCreate, StatusCounts
from app.services.validation import RecipientResult


def new_verification_code() -> str:
    return secrets.token_hex(6).upper()  # e.g. "9F2A61C0B4D7"


def create_job(db: Session, payload: JobCreate, results: list[RecipientResult]) -> Job:
    """Store the job plus one certificate row per submitted recipient.

    Valid recipients start as PENDING; invalid ones are stored as INVALID
    with their validation errors so they show up in the job's results.
    """
    job = Job(
        course_name=payload.course_name,
        issue_date=payload.issue_date,
        issuer=payload.issuer,
        status=JobStatus.PENDING,
    )
    for result in results:
        if result.is_valid:
            cert = Certificate(
                row_index=result.index,
                recipient_name=result.recipient.name,
                email=result.recipient.email,
                status=CertificateStatus.PENDING,
                verification_code=new_verification_code(),
            )
        else:
            cert = Certificate(
                row_index=result.index,
                recipient_name=result.raw_name,
                email=result.raw_email,
                status=CertificateStatus.INVALID,
                error_message="; ".join(result.errors),
            )
        job.certificates.append(cert)

    db.add(job)
    db.commit()
    return job


def count_by_status(db: Session, job_id: str) -> StatusCounts:
    rows = db.execute(
        select(Certificate.status, func.count())
        .where(Certificate.job_id == job_id)
        .group_by(Certificate.status)
    ).all()
    return StatusCounts(**{status.value.lower(): count for status, count in rows})


def total_of(counts: StatusCounts) -> int:
    return counts.pending + counts.processing + counts.success + counts.failed + counts.invalid


def progress_percent(counts: StatusCounts) -> float:
    total = total_of(counts)
    if total == 0:
        return 100.0
    done = counts.success + counts.failed + counts.invalid
    return round(done * 100 / total, 2)


def final_status(counts: StatusCounts) -> JobStatus:
    if counts.success == 0:
        return JobStatus.FAILED
    if counts.failed or counts.invalid:
        return JobStatus.COMPLETED_WITH_ERRORS
    return JobStatus.COMPLETED


def reset_failed_certificates(db: Session, job: Job) -> int:
    """Move FAILED certificates back to PENDING so they can be retried.

    INVALID rows are not retried: their data is wrong and would fail again.
    """
    result = db.execute(
        update(Certificate)
        .where(Certificate.job_id == job.id, Certificate.status == CertificateStatus.FAILED)
        .values(status=CertificateStatus.PENDING, error_message=None)
    )
    if result.rowcount:
        job.status = JobStatus.PENDING
        job.completed_at = None
        job.error_message = None
    db.commit()
    return result.rowcount
