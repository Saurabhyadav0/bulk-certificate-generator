"""The single, predefined certificate template, drawn with ReportLab."""

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

PAGE_WIDTH, PAGE_HEIGHT = landscape(A4)
CENTER_X = PAGE_WIDTH / 2
MAX_TEXT_WIDTH = PAGE_WIDTH - 160

PRIMARY = colors.HexColor("#1F3A5F")
ACCENT = colors.HexColor("#C9A227")
MUTED = colors.HexColor("#555555")


@dataclass(frozen=True)
class CertificateContent:
    recipient_name: str
    course_name: str
    issue_date: date
    issuer: str
    verification_code: str


def fit_font_size(text: str, font: str, preferred: float, minimum: float, max_width: float) -> float:
    """Shrink the font until the text fits on one line (long names/courses)."""
    size = preferred
    while size > minimum and stringWidth(text, font, size) > max_width:
        size -= 1
    return size


def _draw_centered(c: canvas.Canvas, y: float, text: str, font: str, size: float, color) -> None:
    c.setFont(font, size)
    c.setFillColor(color)
    c.drawCentredString(CENTER_X, y, text)


def render_certificate(content: CertificateContent, output_path: Path) -> Path:
    """Render one certificate PDF to `output_path`.

    The file is written to a temporary name first and then renamed, so a
    crash mid-write never leaves a half-written PDF that could be served.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_name(output_path.name + ".tmp")

    c = canvas.Canvas(str(tmp_path), pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    c.setTitle(f"Certificate - {content.recipient_name}")
    c.setAuthor(content.issuer)

    # Border
    c.setStrokeColor(PRIMARY)
    c.setLineWidth(6)
    c.rect(24, 24, PAGE_WIDTH - 48, PAGE_HEIGHT - 48)
    c.setStrokeColor(ACCENT)
    c.setLineWidth(1.5)
    c.rect(36, 36, PAGE_WIDTH - 72, PAGE_HEIGHT - 72)

    # Heading
    _draw_centered(c, PAGE_HEIGHT - 130, "CERTIFICATE OF COMPLETION", "Helvetica-Bold", 34, PRIMARY)
    c.setStrokeColor(ACCENT)
    c.setLineWidth(2)
    c.line(CENTER_X - 120, PAGE_HEIGHT - 148, CENTER_X + 120, PAGE_HEIGHT - 148)

    _draw_centered(c, PAGE_HEIGHT - 200, "This is to certify that", "Helvetica", 16, MUTED)

    # Recipient name (font shrinks for very long names)
    name_size = fit_font_size(content.recipient_name, "Helvetica-Bold", 40, 18, MAX_TEXT_WIDTH)
    _draw_centered(c, PAGE_HEIGHT - 260, content.recipient_name, "Helvetica-Bold", name_size, PRIMARY)

    _draw_centered(c, PAGE_HEIGHT - 310, "has successfully completed", "Helvetica", 16, MUTED)

    course_size = fit_font_size(content.course_name, "Helvetica-Bold", 24, 12, MAX_TEXT_WIDTH)
    _draw_centered(c, PAGE_HEIGHT - 350, content.course_name, "Helvetica-Bold", course_size, PRIMARY)

    # Footer: date on the left, issuer signature on the right
    footer_y = 120
    c.setStrokeColor(MUTED)
    c.setLineWidth(1)
    c.line(110, footer_y, 310, footer_y)
    c.line(PAGE_WIDTH - 310, footer_y, PAGE_WIDTH - 110, footer_y)

    c.setFont("Helvetica", 13)
    c.setFillColor(colors.black)
    c.drawCentredString(210, footer_y + 8, content.issue_date.strftime("%d %B %Y"))
    c.drawCentredString(PAGE_WIDTH - 210, footer_y + 8, content.issuer)
    c.setFont("Helvetica", 10)
    c.setFillColor(MUTED)
    c.drawCentredString(210, footer_y - 16, "Date of issue")
    c.drawCentredString(PAGE_WIDTH - 210, footer_y - 16, "Issued by")

    _draw_centered(
        c, 56, f"Verification code: {content.verification_code}", "Helvetica", 9, MUTED
    )

    c.showPage()
    c.save()
    tmp_path.replace(output_path)
    return output_path
