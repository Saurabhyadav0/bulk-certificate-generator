"""Request-level and recipient-level validation."""

from app.config import settings
from app.services.validation import validate_recipients
from tests.conftest import make_payload

# --- Request-level: the whole request is rejected with 422 ------------------


def test_missing_course_name_is_rejected(client):
    payload = make_payload(1)
    del payload["course_name"]
    assert client.post("/api/v1/jobs", json=payload).status_code == 422


def test_blank_course_name_is_rejected(client):
    assert client.post("/api/v1/jobs", json=make_payload(1, course_name="   ")).status_code == 422


def test_empty_recipient_list_is_rejected(client):
    assert client.post("/api/v1/jobs", json=make_payload(0)).status_code == 422


def test_invalid_issue_date_is_rejected(client):
    assert client.post("/api/v1/jobs", json=make_payload(1, issue_date="31-31-2026")).status_code == 422


def test_too_many_recipients_is_rejected(client, monkeypatch):
    monkeypatch.setattr(settings, "max_recipients_per_job", 3)
    response = client.post("/api/v1/jobs", json=make_payload(4))
    assert response.status_code == 422
    assert "at most 3 recipients" in response.text


def test_request_with_only_invalid_recipients_is_rejected(client):
    payload = make_payload(recipients=[{"name": "", "email": "nope"}, {"email": "a@example.com"}])
    response = client.post("/api/v1/jobs", json=payload)

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["message"] == "No valid recipients in the request"
    assert [r["index"] for r in detail["invalid_recipients"]] == [0, 1]


# --- Recipient-level: bad rows are reported, good rows still processed -----


def test_invalid_recipients_are_reported_and_valid_ones_generated(client):
    payload = make_payload(
        recipients=[
            {"name": "Asha Rao", "email": "asha@example.com"},
            {"name": "", "email": "bad-email"},
            {"name": "Rahul Mehta", "email": "rahul@example.com"},
        ]
    )
    response = client.post("/api/v1/jobs", json=payload)

    assert response.status_code == 202
    body = response.json()
    assert body["accepted"] == 2
    assert body["rejected"] == 1
    assert body["invalid_recipients"][0]["index"] == 1
    errors = " ".join(body["invalid_recipients"][0]["errors"])
    assert "name" in errors and "email" in errors

    status = client.get(body["status_url"]).json()
    assert status["status"] == "COMPLETED_WITH_ERRORS"
    assert status["counts"]["success"] == 2
    assert status["counts"]["invalid"] == 1

    invalid = client.get(f"{body['certificates_url']}?status=INVALID").json()["items"]
    assert len(invalid) == 1
    assert invalid[0]["email"] == "bad-email"
    assert invalid[0]["download_url"] is None


def test_validate_recipients_rules():
    results = validate_recipients(
        [
            {"name": "  Asha Rao  ", "email": "asha@example.com"},  # ok, trimmed
            {"name": "   ", "email": "x@example.com"},  # blank name
            {"name": "No Email"},  # missing email
            {"name": "Bad", "email": "not-an-email"},  # bad email
            {"name": "Dup", "email": "ASHA@example.com"},  # duplicate (case-insensitive)
            "just a string",  # not an object
            {"name": "N" * 101, "email": "long@example.com"},  # name too long
            {"name": 123, "email": "num@example.com"},  # wrong type
        ]
    )

    assert [r.is_valid for r in results] == [True, False, False, False, False, False, False, False]
    assert results[0].recipient.name == "Asha Rao"
    assert "name" in results[1].errors[0]
    assert "email" in results[2].errors[0]
    assert "email" in results[3].errors[0]
    assert "duplicate of recipient at index 0" in results[4].errors[0]
    assert "must be an object" in results[5].errors[0]
    assert "name" in results[6].errors[0]
    assert "name" in results[7].errors[0]


def test_extra_recipient_fields_are_ignored():
    [result] = validate_recipients([{"name": "Asha", "email": "a@example.com", "team": "x"}])
    assert result.is_valid
