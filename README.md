# Bulk Certificate Generator

A backend API that takes a list of recipients in **one request**, validates each one, generates a PDF certificate for every valid recipient from a single predefined template, tracks progress, and serves the generated certificates one at a time or as a ZIP.

**Stack:** Python 3.11+ (tested on 3.11 and 3.14) · FastAPI · SQLAlchemy 2 · SQLite (any SQLAlchemy-supported RDBMS works) · ReportLab · pytest

---

## 1. Setup

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

No other services are needed. The SQLite database file and the PDF folder are created automatically on first start.

### Configuration (optional)

Each setting can be overridden with an environment variable (or a `.env` file):

| Variable | Default | Purpose |
|---|---|---|
| `CERT_DATABASE_URL` | `sqlite:///./certificates.db` | Any SQLAlchemy URL. A plain `postgresql://...` URL (e.g. copied from Neon) works as-is |
| `CERT_OUTPUT_DIR` | `generated_certificates` | Where PDFs are stored |
| `CERT_MAX_RECIPIENTS_PER_JOB` | `1000` | Upper limit on recipients in one request |
| `CERT_MAX_WORKERS` | `2` | Jobs processed in parallel |
| `CERT_DEFAULT_ISSUER` | `Certificate Authority` | Used when the request has no `issuer` |

To use PostgreSQL, copy `.env.example` to `.env` and set `CERT_DATABASE_URL`. Tables are created automatically on startup. `.env` is git-ignored so credentials aren't committed.

## 2. Run the application

```bash
uvicorn app.main:app --reload
```

- API: http://127.0.0.1:8000
- Interactive docs (Swagger UI): http://127.0.0.1:8000/docs. You can try every endpoint from the browser. `POST /api/v1/jobs` has an **Examples** dropdown with ready-made requests (all valid, some invalid, all invalid, malformed, long name), and the PDF/ZIP endpoints show a **Download file** link.

## 3. Run the tests

```bash
pytest
```

Each test uses its own temporary SQLite database and output folder, so the tests never touch your real data.

| Test file | Covers |
|---|---|
| `tests/test_jobs.py` | Creating a job, job status/progress, background mode, recovery after restart |
| `tests/test_validation.py` | Request-level (422) and per-recipient validation |
| `tests/test_generation.py` | PDF template content, long-name handling, one PDF per recipient |
| `tests/test_failure_handling.py` | One certificate failing without stopping the others, all certificates failing, retry, job crash |
| `tests/test_retrieval.py` | Listing, filtering, pagination, single PDF download, ZIP download, error cases |

---

## 4. Submitting a generation request

`POST /api/v1/jobs`

```bash
curl -X POST http://127.0.0.1:8000/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d @examples/sample_request.json
```

Request body:

```json
{
  "course_name": "Python for Data Engineering",
  "issue_date": "2026-10-01",
  "issuer": "Acme Academy",
  "recipients": [
    {"name": "Asha Rao", "email": "asha@example.com"},
    {"name": "", "email": "not-an-email"}
  ]
}
```

| Field | Required | Rules |
|---|---|---|
| `course_name` | yes | 1–150 chars |
| `issue_date` | no (defaults to today) | `YYYY-MM-DD` |
| `issuer` | no (defaults to config) | 1–100 chars |
| `recipients` | yes | 1 to `MAX_RECIPIENTS_PER_JOB` items |
| `recipients[].name` | yes | 1–100 chars, trimmed |
| `recipients[].email` | yes | valid email, unique within the job (case-insensitive) |

Response: **`202 Accepted`**, returned immediately, before generation finishes:

```json
{
  "job_id": "1a263b22-3cb9-4e09-b44d-bf6a72324fe1",
  "status": "PENDING",
  "total_recipients": 2,
  "accepted": 1,
  "rejected": 1,
  "invalid_recipients": [
    {"index": 1, "errors": ["name: String should have at least 1 character",
                             "email: value is not a valid email address: ..."]}
  ],
  "status_url": "/api/v1/jobs/1a263b22-...",
  "certificates_url": "/api/v1/jobs/1a263b22-.../certificates"
}
```

### Tracking progress

`GET /api/v1/jobs/{job_id}`

```json
{
  "job_id": "1a263b22-...",
  "status": "COMPLETED_WITH_ERRORS",
  "total_recipients": 5,
  "counts": {"pending": 0, "processing": 0, "success": 3, "failed": 0, "invalid": 2},
  "progress_percent": 100.0,
  "download_url": "/api/v1/jobs/1a263b22-.../download",
  ...
}
```

Poll this until `status` is no longer `PENDING`/`PROCESSING`.

**Job statuses**

| Status | Meaning |
|---|---|
| `PENDING` | Accepted, waiting for a worker |
| `PROCESSING` | Certificates are being generated |
| `COMPLETED` | Every recipient got a certificate |
| `COMPLETED_WITH_ERRORS` | At least one succeeded, at least one failed/invalid |
| `FAILED` | No certificate could be generated (or the job crashed; see `error_message`) |

**Certificate statuses:** `PENDING`, `PROCESSING`, `SUCCESS`, `FAILED` (valid data, but generation raised an error), `INVALID` (rejected by validation, never generated).

## 5. Retrieving generated certificates

| Endpoint | Returns |
|---|---|
| `GET /api/v1/jobs/{job_id}/certificates?status=&limit=&offset=` | Results for each recipient: status, error, verification code, `download_url` |
| `GET /api/v1/certificates/{certificate_id}` | One certificate's details |
| `GET /api/v1/certificates/{certificate_id}/download` | The PDF |
| `GET /api/v1/jobs/{job_id}/download` | ZIP of all successful PDFs in the job |
| `POST /api/v1/jobs/{job_id}/retry` | Re-runs only the `FAILED` certificates |

```bash
# All results, or only the failures
curl "http://127.0.0.1:8000/api/v1/jobs/$JOB_ID/certificates"
curl "http://127.0.0.1:8000/api/v1/jobs/$JOB_ID/certificates?status=FAILED"

# One PDF
curl -o cert.pdf "http://127.0.0.1:8000/api/v1/certificates/$CERT_ID/download"

# Everything as a ZIP (files named 0001_Asha_Rao.pdf, ...)
curl -o certificates.zip "http://127.0.0.1:8000/api/v1/jobs/$JOB_ID/download"
```

Error responses: `404` for an unknown job/certificate, `409` when a certificate or job isn't ready (or has nothing to retry), and `410` when a PDF record exists but the file was removed from storage.

---

## 6. Design decisions

### Project layout

```
app/
  main.py               FastAPI app, startup (create tables, recover jobs), shutdown
  config.py             Settings (env-overridable)
  database.py           Engine, session factory, get_db dependency
  models.py             Job and Certificate tables + status enums
  schemas.py            Pydantic request/response models
  api/jobs.py           HTTP endpoints only (thin layer)
  api/docs.py           Swagger examples and response documentation
  services/
    validation.py       Per-recipient validation
    jobs.py             DB operations: create job, counts, final status, retry reset
    generator.py        The certificate template (ReportLab → PDF)
    processor.py        Background processing: process_job(job_id)
tests/                  pytest suite
```

The HTTP layer, the business logic and the PDF rendering are kept separate, so each part can be changed or tested on its own.

### Background processing instead of synchronous generation

A request can contain up to 1,000 recipients. Generating them inside the HTTP request would make the client wait a long time and risk timeouts. So:

1. `POST /jobs` validates the input, stores the job and **one row per recipient**, and returns `202` with a `job_id` straight away.
2. A worker generates the certificates in the background.
3. The client polls `GET /jobs/{id}` for progress and then downloads the results.

**Why a thread pool rather than Celery/RQ?** The assignment is a single service, and a thread pool needs no Redis or broker, so it runs with one command. The important part is that **the database is the source of truth**. `process_job(job_id)` only needs an id and reads everything else from the DB. In production you would wrap that function in a Celery task and call `.delay(job_id)` inside `submit_job`. Nothing else changes.

Trade-offs of the in-process pool, and how they are handled:
- *Work is lost if the process dies.* On startup, `recover_unfinished_jobs()` re-queues every job that was still `PENDING`/`PROCESSING`. Certificates left in `PROCESSING` are picked up again.
- *It only scales on one machine.* That's fine at this size. The next step is Celery workers plus Postgres.
- PDF generation is CPU-bound, so threads are limited by the GIL. Again, separate worker processes (Celery) solve this when it matters.

### Validation: two levels

- **Request-level problems** (missing/blank `course_name`, bad date, empty list, too many recipients) → `422`, and no job is created.
- **Recipient-level problems** (blank name, bad email, duplicate email, not an object) → the job **is still accepted**. Bad rows are saved with status `INVALID` and their error messages, returned in `invalid_recipients`, and listed in the job results. One bad row shouldn't block 999 good ones.
- If **no** recipient is valid, the request is rejected with `422`, because creating a job with nothing to do isn't useful.

To support this, `recipients` is typed loosely in the request model, and each item is validated separately with the `RecipientIn` model (`services/validation.py`).

### Failure isolation

Each certificate is generated inside its own `try/except` (`processor._generate_one`). An exception marks **that** certificate `FAILED` with `"<ExceptionType>: <message>"`, and the loop moves on to the next one. The state is committed after every certificate, so progress is visible live and a crash loses at most one certificate's work. If something outside the loop fails, `_run_safely` marks the job `FAILED` with an `error_message`, so a job never stays stuck in `PROCESSING`.

`POST /jobs/{id}/retry` resets only `FAILED` certificates to `PENDING` and processes them again. `INVALID` ones are not retried, because their data is wrong.

### Status is derived, not stored as counters

Counts (`success`, `failed`, ...) are calculated with a `GROUP BY` on the certificate rows instead of kept as separate counter columns. Counters can drift out of sync, and calculating them is cheap with the `job_id`/`status` indexes.

### Certificate generation

- **ReportLab**: pure Python, no system dependencies (unlike WeasyPrint/wkhtmltopdf), and fast. The template is a landscape A4 page with the recipient name, course, issue date, issuer and a verification code.
- Long names/course titles shrink to fit the page (`fit_font_size`).
- Each certificate gets a random, unique **verification code** printed on it, for future authenticity checks.
- PDFs are written to a `.tmp` file and then renamed, so a half-written file is never served.
- Files are stored on disk at `OUTPUT_DIR/<job_id>/<certificate_id>.pdf`, and the database stores the path. Swapping to S3 would only touch `render_certificate`'s output and the download endpoints.

### Other choices

- **UUIDs** for job/certificate ids, so URLs can't be enumerated.
- **Endpoints are plain `def`** (not `async def`) because SQLAlchemy is used synchronously. FastAPI runs them in its thread pool.
- **ZIP is built in memory.** Each PDF is a few KB, so 1,000 certificates is only a few MB. For much bigger jobs it should stream from a temp file.
- **Pagination** on the certificate list keeps responses small for big jobs.

### Known limitations / next steps

- Built-in PDF fonts (Helvetica) cover Latin characters only. Names in other scripts (e.g. Devanagari) need a TTF font such as Noto registered with ReportLab.
- No authentication. In production every job would belong to an API client/user.
- Moving to multiple machines: Celery + Redis workers, Postgres, and object storage for the PDFs.
- Possible additions: a webhook/callback URL when a job finishes, a public `GET /verify/{code}` endpoint, Alembic migrations, and a Dockerfile.
