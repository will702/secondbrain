import io
import zipfile
from pathlib import Path

import pytest

from app.services.parsing import ParseError, parse_bytes

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_markdown_sections():
    parsed = parse_bytes((FIXTURES / "ml_syllabus.md").read_bytes(), "ml_syllabus.md", "text/markdown")
    titles = [s.title for s in parsed.sections]
    assert "Course Information" in titles
    assert "Assessment" in titles
    assessment = next(s for s in parsed.sections if s.title == "Assessment")
    assert "October 13" in assessment.text


def test_parse_txt_headings():
    parsed = parse_bytes((FIXTURES / "assignment4.txt").read_bytes(), "assignment4.txt", "text/plain")
    assert any("Assignment 4" in s.title for s in parsed.sections)
    assert "October 13" in parsed.full_text


def test_parse_csv_renders_rows():
    parsed = parse_bytes((FIXTURES / "schedule.csv").read_bytes(), "schedule.csv", "text/csv")
    assert len(parsed.sections) == 1
    assert "Assignment 4 deadline" in parsed.sections[0].text
    assert "date" in parsed.sections[0].title  # header shown in title


def _build_docx() -> bytes:
    from docx import Document

    doc = Document()
    doc.add_heading("Meeting Notes", level=1)
    doc.add_paragraph("Attendees: Willson, John, Professor Smith.")
    doc.add_heading("Decisions", level=2)
    doc.add_paragraph("Proposal deadline moved to October 16.")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def test_parse_docx():
    parsed = parse_bytes(_build_docx(), "meeting.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    titles = [s.title for s in parsed.sections]
    assert "Meeting Notes" in titles
    assert "October 16" in parsed.full_text


def _build_pptx() -> bytes:
    from pptx import Presentation

    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = "CNN Lecture"
    slide.placeholders[1].text = "Convolutional layers\nPooling\nResNet architecture"
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def test_parse_pptx():
    parsed = parse_bytes(_build_pptx(), "lecture.pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation")
    assert parsed.page_count == 1
    assert parsed.sections[0].title == "Slide 1"
    assert "CNN Lecture" in parsed.sections[0].text
    assert "ResNet" in parsed.sections[0].text


def _build_xlsx() -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Deadlines"
    ws.append(["item", "date"])
    ws.append(["Proposal", "2026-10-16"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_parse_xlsx():
    parsed = parse_bytes(_build_xlsx(), "grades.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    assert parsed.sections[0].title.startswith("Sheet: Deadlines")
    assert "Proposal" in parsed.sections[0].text


def test_parse_zip_flattens_entries():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("notes/a.md", "# Title\n\nSome text about deadlines.")
        zf.writestr("notes/b.txt", "Another document.")
    parsed = parse_bytes(buf.getvalue(), "bundle.zip", "application/zip")
    assert any(s.title.startswith("notes/a.md") for s in parsed.sections)


def test_parse_zip_rejects_unparsable():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("image.bin", "\x00\x01\x02")
    with pytest.raises(ParseError, match="no parsable"):
        parse_bytes(buf.getvalue(), "bin.zip", "application/zip")


def test_parse_unsupported_extension():
    with pytest.raises(ParseError, match="Unsupported"):
        parse_bytes(b"x", "file.exe", "application/octet-stream")
