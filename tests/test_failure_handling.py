"""A failure in one certificate must not stop the rest of the job."""

import pytest

from app.services import generator, processor
from tests.conftest import make_payload


@pytest.fixture
def fail_for(monkeypatch):
    """Make rendering raise for the given recipient names."""

    def configure(*names: str) -> None:
        real_render = generator.render_certificate

        def flaky_render(content, output_path):
            if content.recipient_name in names:
                raise RuntimeError(f"Renderer crashed for {content.recipient_name}")
            return real_render(content, output_path)

        monkeypatch.setattr(processor, "render_certificate", flaky_render)

    return configure


def test_single_failure_does_not_block_other_certificates(client, fail_for):
    fail_for("Student 1")
    job_id = client.post("/api/v1/jobs", json=make_payload(3)).json()["job_id"]

    status = client.get(f"/api/v1/jobs/{job_id}").json()
    assert status["status"] == "COMPLETED_WITH_ERRORS"
    assert status["counts"]["success"] == 2
    assert status["counts"]["failed"] == 1
    assert status["progress_percent"] == 100.0

    items = client.get(f"/api/v1/jobs/{job_id}/certificates").json()["items"]
    by_name = {item["recipient_name"]: item for item in items}
    assert by_name["Student 0"]["status"] == "SUCCESS"
    assert by_name["Student 2"]["status"] == "SUCCESS"
    assert by_name["Student 1"]["status"] == "FAILED"
    assert by_name["Student 1"]["error_message"] == "RuntimeError: Renderer crashed for Student 1"
    assert by_name["Student 1"]["download_url"] is None


def test_failed_certificates_can_be_filtered(client, fail_for):
    fail_for("Student 0", "Student 2")
    job_id = client.post("/api/v1/jobs", json=make_payload(4)).json()["job_id"]

    failed = client.get(f"/api/v1/jobs/{job_id}/certificates", params={"status": "FAILED"}).json()
    assert failed["total"] == 2
    assert [i["recipient_name"] for i in failed["items"]] == ["Student 0", "Student 2"]


def test_job_fails_when_every_certificate_fails(client, fail_for):
    fail_for("Student 0", "Student 1")
    job_id = client.post("/api/v1/jobs", json=make_payload(2)).json()["job_id"]

    status = client.get(f"/api/v1/jobs/{job_id}").json()
    assert status["status"] == "FAILED"
    assert status["counts"]["failed"] == 2
    assert status["download_url"] is None


def test_retry_regenerates_only_failed_certificates(client, fail_for, monkeypatch):
    fail_for("Student 1")
    job_id = client.post("/api/v1/jobs", json=make_payload(3)).json()["job_id"]
    first_ok = client.get(f"/api/v1/jobs/{job_id}/certificates", params={"status": "SUCCESS"}).json()

    # "Fix" the renderer and retry.
    monkeypatch.setattr(processor, "render_certificate", generator.render_certificate)
    response = client.post(f"/api/v1/jobs/{job_id}/retry")

    assert response.status_code == 202
    assert response.json()["status"] == "COMPLETED"
    assert response.json()["counts"]["success"] == 3

    # Previously successful certificates were not regenerated.
    after = client.get(f"/api/v1/jobs/{job_id}/certificates", params={"status": "SUCCESS"}).json()
    before_times = {i["id"]: i["generated_at"] for i in first_ok["items"]}
    for item in after["items"]:
        if item["id"] in before_times:
            assert item["generated_at"] == before_times[item["id"]]


def test_retry_with_nothing_failed_returns_409(client):
    job_id = client.post("/api/v1/jobs", json=make_payload(1)).json()["job_id"]
    assert client.post(f"/api/v1/jobs/{job_id}/retry").status_code == 409


def test_unexpected_job_crash_marks_job_failed(client, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("database went away")

    monkeypatch.setattr(processor, "final_status", boom)
    job_id = client.post("/api/v1/jobs", json=make_payload(1)).json()["job_id"]

    status = client.get(f"/api/v1/jobs/{job_id}").json()
    assert status["status"] == "FAILED"
    assert "database went away" in status["error_message"]
