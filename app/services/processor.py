"""Background processing of certificate generation jobs.

`process_job(job_id)` is a plain function that only needs a job id. All
state lives in the database, so the same function can be run by:
  * the in-process thread pool used here (default),
  * synchronously in tests (settings.sync_processing = True),
  * a Celery/RQ worker in a scaled-out deployment (wrap it in a task).
"""

import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.models import (
    ACTIVE_JOB_STATUSES,
    UNFINISHED_CERT_STATUSES,
    Certificate,
    CertificateStatus,
    Job,
    JobStatus,
    utcnow,
)
from app.services.generator import CertificateContent, render_certificate
from app.services.jobs import count_by_status, final_status

logger = logging.getLogger(__name__)

_executor: ThreadPoolExecutor | None = None


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(
            max_workers=settings.max_workers, thread_name_prefix="cert-worker"
        )
    return _executor


def shutdown_executor() -> None:
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=True)
        _executor = None


def submit_job(job_id: str) -> None:
    """Queue a job for processing (or run it now in sync mode)."""
    if settings.sync_processing:
        _run_safely(job_id)
    else:
        _get_executor().submit(_run_safely, job_id)


def certificate_path(job_id: str, certificate_id: str) -> Path:
    return settings.output_dir / job_id / f"{certificate_id}.pdf"


def _run_safely(job_id: str) -> None:
    """Never let an unexpected error kill the worker silently."""
    try:
        process_job(job_id)
    except Exception as exc:
        logger.exception("Job %s crashed", job_id)
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            if job is not None:
                job.status = JobStatus.FAILED
                job.error_message = f"Unexpected error: {exc}"[:1000]
                job.completed_at = utcnow()
                db.commit()


def process_job(job_id: str) -> None:
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if job is None:
            logger.warning("Job %s not found", job_id)
            return

        job.status = JobStatus.PROCESSING
        job.started_at = job.started_at or utcnow()
        db.commit()

        # PROCESSING is included so certificates interrupted by a crash or
        # restart are picked up again.
        cert_ids = db.scalars(
            select(Certificate.id)
            .where(Certificate.job_id == job_id, Certificate.status.in_(UNFINISHED_CERT_STATUSES))
            .order_by(Certificate.row_index)
        ).all()

        for cert_id in cert_ids:
            _generate_one(db, job, cert_id)

        job.status = final_status(count_by_status(db, job_id))
        job.completed_at = utcnow()
        db.commit()
        logger.info("Job %s finished with status %s", job_id, job.status.value)


def _generate_one(db, job: Job, cert_id: str) -> None:
    """Generate a single certificate. Any failure is recorded on this
    certificate only; the loop in process_job carries on with the next one."""
    cert = db.get(Certificate, cert_id)
    cert.status = CertificateStatus.PROCESSING
    db.commit()

    try:
        content = CertificateContent(
            recipient_name=cert.recipient_name,
            course_name=job.course_name,
            issue_date=job.issue_date,
            issuer=job.issuer,
            verification_code=cert.verification_code,
        )
        path = render_certificate(content, certificate_path(job.id, cert.id))
        cert.file_path = str(path)
        cert.status = CertificateStatus.SUCCESS
        cert.error_message = None
        cert.generated_at = utcnow()
    except Exception as exc:
        logger.warning("Certificate %s in job %s failed: %s", cert.id, job.id, exc)
        cert.status = CertificateStatus.FAILED
        cert.error_message = f"{type(exc).__name__}: {exc}"[:1000]

    # Commit after every certificate so progress is visible to the API live.
    db.commit()


def recover_unfinished_jobs() -> int:
    """Re-queue jobs that were pending/processing when the server stopped."""
    with SessionLocal() as db:
        job_ids = db.scalars(select(Job.id).where(Job.status.in_(ACTIVE_JOB_STATUSES))).all()
    for job_id in job_ids:
        logger.info("Recovering unfinished job %s", job_id)
        submit_job(job_id)
    return len(job_ids)
