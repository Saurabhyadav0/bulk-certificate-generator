"""Creating jobs and tracking their status/progress."""

from app.config import settings
from app.models import Certificate, CertificateStatus, Job, JobStatus
from app.services import processor
from tests.conftest import make_payload


def test_create_job_returns_202_with_job_id(client):
    response = client.post("/api/v1/jobs", json=make_payload(3))

    assert response.status_code == 202
    body = response.json()
    assert body["job_id"]
    assert body["total_recipients"] == 3
    assert body["accepted"] == 3
    assert body["rejected"] == 0
    assert body["invalid_recipients"] == []
    assert body["status_url"] == f"/api/v1/jobs/{body['job_id']}"


def test_create_job_persists_job_and_certificates(client, db):
    job_id = client.post("/api/v1/jobs", json=make_payload(2)).json()["job_id"]

    job = db.get(Job, job_id)
    assert job.course_name == "Python Bootcamp"
    assert job.issuer == "Acme Academy"
    assert str(job.issue_date) == "2026-10-01"
    assert [c.recipient_name for c in job.certificates] == ["Student 0", "Student 1"]


def test_issuer_and_issue_date_have_defaults(client):
    payload = make_payload(1)
    del payload["issuer"], payload["issue_date"]

    job_id = client.post("/api/v1/jobs", json=payload).json()["job_id"]
    body = client.get(f"/api/v1/jobs/{job_id}").json()

    assert body["issuer"] == settings.default_issuer
    assert body["issue_date"]


def test_job_status_after_successful_processing(client):
    job_id = client.post("/api/v1/jobs", json=make_payload(3)).json()["job_id"]

    body = client.get(f"/api/v1/jobs/{job_id}").json()

    assert body["status"] == "COMPLETED"
    assert body["total_recipients"] == 3
    assert body["counts"] == {"pending": 0, "processing": 0, "success": 3, "failed": 0, "invalid": 0}
    assert body["progress_percent"] == 100.0
    assert body["started_at"] and body["completed_at"]
    assert body["download_url"] == f"/api/v1/jobs/{job_id}/download"


def test_job_progress_before_and_after_processing(client, db, monkeypatch):
    # Queue the job without processing it, to observe the PENDING state.
    monkeypatch.setattr(processor, "submit_job", lambda job_id: None)
    job_id = client.post("/api/v1/jobs", json=make_payload(4)).json()["job_id"]

    pending = client.get(f"/api/v1/jobs/{job_id}").json()
    assert pending["status"] == "PENDING"
    assert pending["counts"]["pending"] == 4
    assert pending["progress_percent"] == 0.0
    assert pending["download_url"] is None

    # Simulate a partially processed job: 1 of 4 certificates done.
    first = db.query(Certificate).filter_by(job_id=job_id, row_index=0).one()
    first.status = CertificateStatus.SUCCESS
    db.query(Job).filter_by(id=job_id).update({"status": JobStatus.PROCESSING})
    db.commit()

    partial = client.get(f"/api/v1/jobs/{job_id}").json()
    assert partial["status"] == "PROCESSING"
    assert partial["progress_percent"] == 25.0

    processor.process_job(job_id)

    done = client.get(f"/api/v1/jobs/{job_id}").json()
    assert done["status"] == "COMPLETED"
    assert done["progress_percent"] == 100.0


def test_unknown_job_returns_404(client):
    assert client.get("/api/v1/jobs/does-not-exist").status_code == 404
    assert client.get("/api/v1/jobs/does-not-exist/certificates").status_code == 404


def test_background_mode_processes_job(client, monkeypatch):
    """The real (threaded) path: POST returns immediately, work finishes later."""
    monkeypatch.setattr(settings, "sync_processing", False)
    job_id = client.post("/api/v1/jobs", json=make_payload(5)).json()["job_id"]

    processor.shutdown_executor()  # waits for queued work to finish

    assert client.get(f"/api/v1/jobs/{job_id}").json()["status"] == "COMPLETED"


def test_unfinished_jobs_are_recovered_on_startup(client, monkeypatch):
    # Simulate a server that stopped before processing the job.
    real_submit = processor.submit_job
    monkeypatch.setattr(processor, "submit_job", lambda job_id: None)
    job_id = client.post("/api/v1/jobs", json=make_payload(2)).json()["job_id"]
    assert client.get(f"/api/v1/jobs/{job_id}").json()["status"] == "PENDING"
    monkeypatch.setattr(processor, "submit_job", real_submit)

    assert processor.recover_unfinished_jobs() == 1
    assert client.get(f"/api/v1/jobs/{job_id}").json()["status"] == "COMPLETED"
