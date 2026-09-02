import io
import logging
import zipfile
from collections.abc import Callable

from app.services.parsing import ParsedDocument, ParseError, Section

logger = logging.getLogger("secondbrain.parsing")

PARSERS: dict[str, Callable[[bytes, str], ParsedDocument]] = {}
EXTENSIONS: set[str] = set()

# Zip archives: how many entries and total bytes we will extract (zip-bomb guard).
MAX_ZIP_ENTRIES = 100
MAX_ZIP_TOTAL_BYTES = 200 * 1024 * 1024


def register_parser(*extensions: str):
    def deco(fn):
        for ext in extensions:
            PARSERS[ext] = fn
            EXTENSIONS.add(ext)
        return fn

    return deco


def parse(data: bytes, filename: str, mime_type: str) -> ParsedDocument:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    parser = PARSERS.get(ext)
    if parser is None:
        raise ParseError(f"Unsupported file type: .{ext or filename!r}")
    try:
        return parser(data, filename)
    except ParseError:
        raise
    except Exception as exc:
        raise ParseError(f"Failed to parse {filename}: {type(exc).__name__}: {exc}") from exc


def _sections_from_text(text: str, page: int | None = None) -> list[Section]:
    """Markdown-style sectioning used by txt/md/csv exports: split on headings."""
    if not text.strip():
        return []
    sections: list[Section] = []
    current_title = ""
    buffer: list[str] = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            if buffer:
                sections.append(
                    Section(title=current_title, text="\n".join(buffer).strip(), page=page)
                )
                buffer = []
            current_title = line.lstrip("# ").strip()
        else:
            buffer.append(line)
    if buffer:
        sections.append(Section(title=current_title, text="\n".join(buffer).strip(), page=page))
    return [s for s in sections if s.text]


@register_parser("txt", "md", "markdown")
def parse_plain(data: bytes, filename: str) -> ParsedDocument:
    text = data.decode("utf-8", errors="replace")
    return ParsedDocument(sections=_sections_from_text(text), page_count=1)


@register_parser("csv")
def parse_csv(data: bytes, filename: str) -> ParsedDocument:
    import csv

    text = data.decode("utf-8", errors="replace")
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return ParsedDocument(sections=[])
    header = ", ".join(rows[0])
    rendered = "\n".join(" | ".join(row) for row in rows)
    return ParsedDocument(
        sections=[Section(title=f"CSV: {filename} (columns: {header})", text=rendered, page=1)],
        page_count=1,
    )


@register_parser("pdf")
def parse_pdf(data: bytes, filename: str) -> ParsedDocument:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    sections: list[Section] = []
    for index, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if text:
            sections.append(Section(title=f"Page {index}", text=text, page=index))
    return ParsedDocument(sections=sections, page_count=len(reader.pages))


@register_parser("docx")
def parse_docx(data: bytes, filename: str) -> ParsedDocument:
    from docx import Document as DocxDocument

    doc = DocxDocument(io.BytesIO(data))
    sections: list[Section] = []
    current_title = ""
    buffer: list[str] = []
    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        if para.style.name.startswith("Heading"):
            if buffer:
                sections.append(Section(title=current_title, text="\n".join(buffer)))
            current_title = text
            buffer = []
        else:
            buffer.append(text)
    if buffer:
        sections.append(Section(title=current_title, text="\n".join(buffer)))
    return ParsedDocument(sections=[s for s in sections if s.text], page_count=1)


@register_parser("pptx")
def parse_pptx(data: bytes, filename: str) -> ParsedDocument:
    from pptx import Presentation

    prs = Presentation(io.BytesIO(data))
    sections: list[Section] = []
    for index, slide in enumerate(prs.slides, start=1):
        lines: list[str] = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    text = "".join(run.text for run in para.runs).strip()
                    if text:
                        lines.append(text)
            if getattr(shape, "has_table", False) and shape.has_table:
                for row in shape.table.rows:
                    cells = [c.text.strip() for c in row.cells]
                    lines.append(" | ".join(cells))
        if lines:
            sections.append(Section(title=f"Slide {index}", text="\n".join(lines), page=index))
    return ParsedDocument(sections=sections, page_count=len(prs.slides._sldIdLst))


@register_parser("xlsx")
def parse_xlsx(data: bytes, filename: str) -> ParsedDocument:
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    sections: list[Section] = []
    for sheet in wb.worksheets:
        lines: list[str] = []
        for row in sheet.iter_rows(values_only=True):
            cells = [str(c) if c is not None else "" for c in row]
            if any(cells):
                lines.append(" | ".join(cells))
        if lines:
            sections.append(Section(title=f"Sheet: {sheet.title}", text="\n".join(lines)))
    wb.close()
    return ParsedDocument(sections=sections, page_count=1)


@register_parser("zip")
def parse_zip(data: bytes, filename: str) -> ParsedDocument:
    """Flatten a zip archive: parse each supported entry and concatenate sections."""
    sections: list[Section] = []
    total = 0
    count = 0
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            count += 1
            if count > MAX_ZIP_ENTRIES:
                raise ParseError("Zip archive has too many entries (limit 100)")
            total += info.file_size
            if total > MAX_ZIP_TOTAL_BYTES:
                raise ParseError("Zip archive too large when extracted (limit 200MB)")
            ext = info.filename.rsplit(".", 1)[-1].lower()
            if ext not in EXTENSIONS:
                continue
            entry_data = zf.read(info)
            inner = parse(entry_data, info.filename, "application/octet-stream")
            for section in inner.sections:
                sections.append(
                    Section(
                        title=f"{info.filename} — {section.title}"[:300],
                        text=section.text,
                        page=section.page,
                    )
                )
    if not sections:
        raise ParseError("Zip archive contains no parsable documents")
    return ParsedDocument(sections=sections, page_count=1, warning="zip archive flattened")
