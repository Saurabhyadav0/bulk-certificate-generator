"""The certificate template / PDF generation."""

from datetime import date
from pathlib import Path

from pypdf import PdfReader

from app.models import Certificate
from app.services.generator import CertificateContent, fit_font_size, render_certificate
from tests.conftest import make_payload


def _content(**overrides) -> CertificateContent:
    data = {
        "recipient_name": "Asha Rao",
        "course_name": "Python Bootcamp",
        "issue_date": date(2026, 10, 1),
        "issuer": "Acme Academy",
        "verification_code": "ABC123DEF456",
    }
    data.update(overrides)
    return CertificateContent(**data)


def test_render_certificate_creates_pdf_with_recipient_details(tmp_path):
    path = render_certificate(_content(), tmp_path / "nested" / "cert.pdf")

    assert path.exists()
    assert path.read_bytes().startswith(b"%PDF")
    assert not list(tmp_path.rglob("*.tmp"))  # temp file was renamed

    text = PdfReader(path).pages[0].extract_text()
    for expected in ["Asha Rao", "Python Bootcamp", "Acme Academy", "01 October 2026", "ABC123DEF456"]:
        assert expected in text


def test_long_names_shrink_to_fit():
    long_name = "Maximilian Alexander Bartholomew Fitzgerald-Montgomery the Third"
    size = fit_font_size(long_name, "Helvetica-Bold", 40, 18, 600)
    assert 18 <= size < 40
    assert fit_font_size("Asha", "Helvetica-Bold", 40, 18, 600) == 40


def test_job_generates_one_pdf_per_valid_recipient(client, db):
    job_id = client.post("/api/v1/jobs", json=make_payload(3)).json()["job_id"]

    certs = db.query(Certificate).filter_by(job_id=job_id).order_by(Certificate.row_index).all()
    assert len(certs) == 3
    for cert in certs:
        assert cert.file_path and Path(cert.file_path).exists()
        assert cert.verification_code
        assert cert.generated_at is not None
        assert cert.recipient_name in PdfReader(cert.file_path).pages[0].extract_text()

    # Verification codes are unique per certificate.
    assert len({c.verification_code for c in certs}) == 3
