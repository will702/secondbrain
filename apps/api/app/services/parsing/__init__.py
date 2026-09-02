"""Document parsing: bytes → ParsedDocument (sections with page spans).

Every parser returns a uniform structure so downstream chunking/extraction
never cares about the source format. Parsers are pure functions — no DB, no LLM.
"""

from dataclasses import dataclass, field


@dataclass
class Section:
    title: str
    text: str
    page: int | None = None


@dataclass
class ParsedDocument:
    sections: list[Section] = field(default_factory=list)
    page_count: int | None = None
    warning: str | None = None

    @property
    def full_text(self) -> str:
        parts: list[str] = []
        for section in self.sections:
            parts.append(f"## {section.title}\n{section.text}" if section.title else section.text)
        return "\n\n".join(parts)

    @property
    def char_count(self) -> int:
        return sum(len(s.text) for s in self.sections)


class ParseError(Exception):
    pass


def parse_bytes(data: bytes, filename: str, mime_type: str) -> ParsedDocument:
    """Dispatch on file extension (upload validation already allowlisted it)."""
    from app.services.parsing.dispatcher import parse

    return parse(data, filename, mime_type)
