import io
import re
import zipfile
from pathlib import Path

from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.docs import JOB_BUSY, JOB_CREATE_EXAMPLES, NOT_FOUND, PDF_RESPONSE, ZIP_RESPONSE, error
from app.database import get_db
from app.models import ACTIVE_JOB_STATUSES, Certificate, CertificateStatus, Job
from app.schemas import (
    CertificateListResponse,
    CertificateOut,
    InvalidRecipient,
    JobCreate,
    JobCreatedResponse,
    JobStatusResponse,
)
from app.services import processor
from app.services.jobs import count_by_status, create_job, progress_percent, reset_failed_certificates, total_of
from app.services.validation import validate_recipients

API_PREFIX = "/api/v1"
router = APIRouter(prefix=API_PREFIX)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _job_url(job_id: str) -> str:
    return f"{API_PREFIX}/jobs/{job_id}"


def _get_job_or_404(db: Session, job_id: str) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Job {job_id} not found")
    return job


def _job_status_response(db: Session, job: Job) -> JobStatusResponse:
    counts = count_by_status(db, job.id)
    return JobStatusResponse(
        job_id=job.id,
        status=job.status,
        course_name=job.course_name,
        issue_date=job.issue_date,
        issuer=job.issuer,
        total_recipients=total_of(counts),
        counts=counts,
        progress_percent=progress_percent(counts),
        error_message=job.error_message,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        certificates_url=f"{_job_url(job.id)}/certificates",
        download_url=f"{_job_url(job.id)}/download" if counts.success else None,
    )


def _certificate_out(cert: Certificate) -> CertificateOut:
    download_url = None
    if cert.status == CertificateStatus.SUCCESS:
        download_url = f"{API_PREFIX}/certificates/{cert.id}/download"
    return CertificateOut(
        id=cert.id,
        row_index=cert.row_index,
        recipient_name=cert.recipient_name,
        email=cert.email,
        status=cert.status,
        error_message=cert.error_message,
        verification_code=cert.verification_code,
        generated_at=cert.generated_at,
        download_url=download_url,
    )


def _safe_filename(cert: Certificate) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", cert.recipient_name or "certificate").strip("_")
    return f"{cert.row_index + 1:04d}_{slug or 'certificate'}.pdf"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/jobs",
    response_model=JobCreatedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["Jobs"],
    summary="Submit a bulk certificate generation job",
    description=(
        "Validates every recipient, stores the job and returns **202** immediately. "
        "Certificates are generated in the background; poll the `status_url` for progress. "
        "Invalid recipients are reported in `invalid_recipients` and do not block valid ones."
    ),
    responses={422: {"description": "Malformed request, or no valid recipients"}},
)
def submit_job(
    payload: Annotated[JobCreate, Body(openapi_examples=JOB_CREATE_EXAMPLES)],
    db: Session = Depends(get_db),
) -> JobCreatedResponse:
    results = validate_recipients(payload.recipients)
    invalid = [InvalidRecipient(index=r.index, errors=r.errors) for r in results if not r.is_valid]

    # If nothing is valid there is no work to do: reject instead of creating
    # a job that is "FAILED" before it starts.
    if len(invalid) == len(results):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "message": "No valid recipients in the request",
                "invalid_recipients": [i.model_dump() for i in invalid],
            },
        )

    job = create_job(db, payload, results)
    processor.submit_job(job.id)
    db.refresh(job)

    return JobCreatedResponse(
        job_id=job.id,
        status=job.status,
        total_recipients=len(results),
        accepted=len(results) - len(invalid),
        rejected=len(invalid),
        invalid_recipients=invalid,
        status_url=_job_url(job.id),
        certificates_url=f"{_job_url(job.id)}/certificates",
    )


@router.get(
    "/jobs/{job_id}",
    response_model=JobStatusResponse,
    tags=["Jobs"],
    summary="Job status and progress",
    responses={404: NOT_FOUND},
)
def get_job(job_id: str, db: Session = Depends(get_db)) -> JobStatusResponse:
    return _job_status_response(db, _get_job_or_404(db, job_id))


@router.get(
    "/jobs/{job_id}/certificates",
    response_model=CertificateListResponse,
    tags=["Jobs"],
    summary="Per-recipient results of a job",
    description="Filter with `status` (e.g. `FAILED` or `INVALID`) and page with `limit`/`offset`.",
    responses={404: NOT_FOUND},
)
def list_certificates(
    job_id: str,
    status_filter: CertificateStatus | None = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> CertificateListResponse:
    _get_job_or_404(db, job_id)

    query = select(Certificate).where(Certificate.job_id == job_id)
    if status_filter is not None:
        query = query.where(Certificate.status == status_filter)

    total = db.scalar(select(func.count()).select_from(query.subquery()))
    certs = db.scalars(query.order_by(Certificate.row_index).limit(limit).offset(offset)).all()

    return CertificateListResponse(
        job_id=job_id,
        total=total,
        limit=limit,
        offset=offset,
        items=[_certificate_out(c) for c in certs],
    )


@router.get(
    "/jobs/{job_id}/download",
    tags=["Jobs"],
    summary="Download all generated certificates as a ZIP",
    response_class=Response,
    responses={200: ZIP_RESPONSE, 404: NOT_FOUND, 409: JOB_BUSY},
)
def download_job(job_id: str, db: Session = Depends(get_db)) -> Response:
    job = _get_job_or_404(db, job_id)
    if job.status in ACTIVE_JOB_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT, "Job is still being processed")

    certs = db.scalars(
        select(Certificate)
        .where(Certificate.job_id == job_id, Certificate.status == CertificateStatus.SUCCESS)
        .order_by(Certificate.row_index)
    ).all()
    if not certs:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job has no generated certificates")

    # Each PDF is a few KB, so building the archive in memory is fine for the
    # job size limit. For much larger jobs, stream from a temp file instead.
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for cert in certs:
            archive.write(cert.file_path, arcname=_safe_filename(cert))

    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="certificates_{job_id}.zip"'},
    )


@router.post(
    "/jobs/{job_id}/retry",
    response_model=JobStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["Jobs"],
    summary="Retry certificates that failed during generation",
    description="Only `FAILED` certificates are regenerated; `INVALID` ones are not retried.",
    responses={404: NOT_FOUND, 409: error("Job busy or nothing to retry", "Job has no failed certificates to retry")},
)
def retry_job(job_id: str, db: Session = Depends(get_db)) -> JobStatusResponse:
    job = _get_job_or_404(db, job_id)
    if job.status in ACTIVE_JOB_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT, "Job is still being processed")

    if reset_failed_certificates(db, job) == 0:
        raise HTTPException(status.HTTP_409_CONFLICT, "Job has no failed certificates to retry")

    processor.submit_job(job.id)
    db.refresh(job)
    return _job_status_response(db, job)


@router.get(
    "/certificates/{certificate_id}",
    response_model=CertificateOut,
    tags=["Certificates"],
    summary="Details of a single certificate",
    responses={404: NOT_FOUND},
)
def get_certificate(certificate_id: str, db: Session = Depends(get_db)) -> CertificateOut:
    cert = db.get(Certificate, certificate_id)
    if cert is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Certificate {certificate_id} not found")
    return _certificate_out(cert)


@router.get(
    "/certificates/{certificate_id}/download",
    tags=["Certificates"],
    summary="Download a single certificate PDF",
    response_class=FileResponse,
    responses={
        200: PDF_RESPONSE,
        404: NOT_FOUND,
        409: error("Certificate not generated", "Certificate is not available (status: FAILED)"),
        410: error("File missing from storage", "Certificate file is missing from storage"),
    },
)
def download_certificate(certificate_id: str, db: Session = Depends(get_db)) -> FileResponse:
    cert = db.get(Certificate, certificate_id)
    if cert is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Certificate {certificate_id} not found")
    if cert.status != CertificateStatus.SUCCESS:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Certificate is not available (status: {cert.status.value})",
        )
    if not cert.file_path or not Path(cert.file_path).exists():
        raise HTTPException(status.HTTP_410_GONE, "Certificate file is missing from storage")

    return FileResponse(cert.file_path, media_type="application/pdf", filename=_safe_filename(cert))
