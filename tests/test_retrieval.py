"""Retrieving generated certificates (single PDF and ZIP)."""

import io
import zipfile
from pathlib import Path

from app.models import Certificate
from app.services import processor
from tests.conftest import make_payload


def _first_success(client, job_id: str) -> dict:
    items = client.get(f"/api/v1/jobs/{job_id}/certificates", params={"status": "SUCCESS"}).json()
    return items["items"][0]


def test_list_certificates_returns_download_links(client):
    job_id = client.post("/api/v1/jobs", json=make_payload(3)).json()["job_id"]

    body = client.get(f"/api/v1/jobs/{job_id}/certificates").json()

    assert body["total"] == 3
    assert [i["row_index"] for i in body["items"]] == [0, 1, 2]
    for item in body["items"]:
        assert item["status"] == "SUCCESS"
        assert item["download_url"] == f"/api/v1/certificates/{item['id']}/download"


def test_list_certificates_pagination(client):
    job_id = client.post("/api/v1/jobs", json=make_payload(5)).json()["job_id"]

    page = client.get(f"/api/v1/jobs/{job_id}/certificates", params={"limit": 2, "offset": 2}).json()

    assert page["total"] == 5
    assert [i["recipient_name"] for i in page["items"]] == ["Student 2", "Student 3"]


def test_get_single_certificate_details(client):
    job_id = client.post("/api/v1/jobs", json=make_payload(1)).json()["job_id"]
    cert = _first_success(client, job_id)

    body = client.get(f"/api/v1/certificates/{cert['id']}").json()
    assert body["recipient_name"] == "Student 0"
    assert body["verification_code"] == cert["verification_code"]


def test_download_single_certificate_pdf(client):
    job_id = client.post("/api/v1/jobs", json=make_payload(1)).json()["job_id"]
    cert = _first_success(client, job_id)

    response = client.get(cert["download_url"])

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert "0001_Student_0.pdf" in response.headers["content-disposition"]
    assert response.content.startswith(b"%PDF")


def test_download_job_zip_contains_only_successful_certificates(client):
    payload = make_payload(
        recipients=[
            {"name": "Asha Rao", "email": "asha@example.com"},
            {"name": "", "email": "invalid"},
            {"name": "Rahul Mehta", "email": "rahul@example.com"},
        ]
    )
    job_id = client.post("/api/v1/jobs", json=payload).json()["job_id"]

    response = client.get(f"/api/v1/jobs/{job_id}/download")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    assert sorted(archive.namelist()) == ["0001_Asha_Rao.pdf", "0003_Rahul_Mehta.pdf"]
    assert archive.read("0001_Asha_Rao.pdf").startswith(b"%PDF")


def test_download_zip_while_job_is_pending_returns_409(client, monkeypatch):
    monkeypatch.setattr(processor, "submit_job", lambda job_id: None)
    job_id = client.post("/api/v1/jobs", json=make_payload(1)).json()["job_id"]

    assert client.get(f"/api/v1/jobs/{job_id}/download").status_code == 409


def test_download_of_unavailable_certificate(client, monkeypatch):
    monkeypatch.setattr(processor, "submit_job", lambda job_id: None)
    job_id = client.post("/api/v1/jobs", json=make_payload(1)).json()["job_id"]
    cert_id = client.get(f"/api/v1/jobs/{job_id}/certificates").json()["items"][0]["id"]

    response = client.get(f"/api/v1/certificates/{cert_id}/download")
    assert response.status_code == 409
    assert "PENDING" in response.json()["detail"]


def test_download_unknown_certificate_returns_404(client):
    assert client.get("/api/v1/certificates/nope/download").status_code == 404
    assert client.get("/api/v1/certificates/nope").status_code == 404


def test_download_when_file_was_deleted_returns_410(client, db):
    job_id = client.post("/api/v1/jobs", json=make_payload(1)).json()["job_id"]
    cert = db.query(Certificate).filter_by(job_id=job_id).one()
    Path(cert.file_path).unlink()

    assert client.get(f"/api/v1/certificates/{cert.id}/download").status_code == 410
