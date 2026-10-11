"""Swagger/OpenAPI documentation helpers: example payloads and response docs.

Kept separate from the route handlers so the endpoints stay easy to read.
"""

from typing import Any

# Selectable in Swagger UI's "Examples" dropdown on POST /jobs.
JOB_CREATE_EXAMPLES: dict[str, dict[str, Any]] = {
    "all_valid": {
        "summary": "All recipients valid",
        "description": "Every recipient gets a certificate. Job ends as COMPLETED.",
        "value": {
            "course_name": "Python for Data Engineering",
            "issue_date": "2026-10-01",
            "issuer": "Acme Academy",
            "recipients": [
                {"name": "Asha Rao", "email": "asha@example.com"},
                {"name": "Rahul Mehta", "email": "rahul@example.com"},
                {"name": "Priya Singh", "email": "priya@example.com"},
            ],
        },
    },
    "some_invalid": {
        "summary": "Mix of valid and invalid recipients",
        "description": (
            "Blank name, bad email, duplicate email and a non-object row are stored as "
            "INVALID; the valid ones are still generated. Job ends as COMPLETED_WITH_ERRORS."
        ),
        "value": {
            "course_name": "Machine Learning Basics",
            "issuer": "Acme Academy",
            "recipients": [
                {"name": "Asha Rao", "email": "asha@example.com"},
                {"name": "", "email": "not-an-email"},
                {"name": "Asha R.", "email": "ASHA@example.com"},
                "not an object",
                {"name": "Rahul Mehta", "email": "rahul@example.com"},
            ],
        },
    },
    "all_invalid": {
        "summary": "No valid recipients (rejected with 422)",
        "description": "Nothing to generate, so no job is created.",
        "value": {
            "course_name": "Machine Learning Basics",
            "recipients": [{"name": "", "email": "bad"}, {"email": "missing-name@example.com"}],
        },
    },
    "invalid_request": {
        "summary": "Malformed request (rejected with 422)",
        "description": "Missing course_name and an empty recipient list.",
        "value": {"recipients": []},
    },
    "long_name": {
        "summary": "Very long name (font shrinks to fit)",
        "value": {
            "course_name": "Advanced Distributed Systems and Cloud Architecture Programme",
            "recipients": [
                {
                    "name": "Maximilian Alexander Bartholomew Fitzgerald-Montgomery",
                    "email": "max@example.com",
                }
            ],
        },
    },
}


def error(description: str, detail: str) -> dict[str, Any]:
    return {
        "description": description,
        "content": {"application/json": {"example": {"detail": detail}}},
    }


NOT_FOUND = error("Not found", "Job 3fa85f64-5717-4562-b3fc-2c963f66afa6 not found")
JOB_BUSY = error("Job is still pending/processing", "Job is still being processed")

# Declaring a binary content type makes Swagger UI show a "Download file" link.
PDF_RESPONSE = {
    "description": "The certificate PDF",
    "content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}},
}
ZIP_RESPONSE = {
    "description": "ZIP archive with one PDF per successful certificate",
    "content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}},
}

API_DESCRIPTION = """
Generate certificates in bulk: submit a list of recipients, track progress,
download the PDFs.

### Try it in this page
1. **POST /api/v1/jobs**: click *Try it out*, pick an example from the
   **Examples** dropdown, then *Execute*. Copy the `job_id` from the response.
2. **GET /api/v1/jobs/{job_id}**: paste the `job_id` to see status, counts and
   progress. Repeat until the status is no longer `PENDING`/`PROCESSING`.
3. **GET /api/v1/jobs/{job_id}/certificates**: see the result for each recipient.
   Use the `status` filter (e.g. `FAILED`, `INVALID`) to narrow the list.
4. **GET /api/v1/certificates/{certificate_id}/download**: paste a certificate
   `id` and click **Download file** to get the PDF.
5. **GET /api/v1/jobs/{job_id}/download**: download every certificate as a ZIP.

**Job status:** `PENDING` → `PROCESSING` → `COMPLETED` | `COMPLETED_WITH_ERRORS` | `FAILED`
"""

TAGS_METADATA = [
    {"name": "Jobs", "description": "Submit bulk generation jobs and track their progress."},
    {"name": "Certificates", "description": "Inspect and download individual certificates."},
    {"name": "Health", "description": "Service liveness check."},
]
