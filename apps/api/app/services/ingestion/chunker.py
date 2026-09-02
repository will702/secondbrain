"""Section-aware chunking: ParsedDocument → chunk dicts ready for embedding.

Deterministic, no LLM. Bounds: target ~1200 chars (≈300 tokens), hard max 1600,
soft min 200 — small sections merge with neighbors, big sections split on
sentence boundaries.
"""

import re

from app.services.parsing import ParsedDocument

TARGET_CHARS = 1200
MAX_CHARS = 1600
MIN_CHARS = 200

_SENTENCE_END = re.compile(r"(?<=[.!?;:])\s+")


def _split_long(text: str, max_chars: int) -> list[str]:
    sentences = _SENTENCE_END.split(text)
    parts: list[str] = []
    buffer = ""
    for sentence in sentences:
        if not sentence:
            continue
        # A single monster "sentence" longer than the cap gets hard-split.
        while len(sentence) > max_chars:
            if buffer:
                parts.append(buffer.strip())
                buffer = ""
            parts.append(sentence[:max_chars].strip())
            sentence = sentence[max_chars:]
        if len(buffer) + len(sentence) + 1 > max_chars and buffer:
            parts.append(buffer.strip())
            buffer = sentence
        else:
            buffer = f"{buffer} {sentence}".strip()
    if buffer.strip():
        parts.append(buffer.strip())
    return parts


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def chunk_document(parsed: ParsedDocument) -> list[dict]:
    """Returns [{chunk_index, section, page, text, token_count}], never empty for non-empty input."""
    chunks: list[dict] = []

    def emit(section_title: str, page: int | None, text: str) -> None:
        for part in _split_long(text, MAX_CHARS) if len(text) > MAX_CHARS else [text]:
            if part.strip():
                chunks.append(
                    {
                        "chunk_index": len(chunks),
                        "section": section_title or None,
                        "page": page,
                        "text": part.strip(),
                        "token_count": estimate_tokens(part),
                    }
                )

    merge_text = ""
    merge_title = ""
    merge_page: int | None = None

    def flush_merge() -> None:
        nonlocal merge_text, merge_title, merge_page
        if merge_text.strip():
            emit(merge_title, merge_page, merge_text)
        merge_text, merge_title, merge_page = "", "", None

    for section in parsed.sections:
        if not section.text.strip():
            continue
        # Small sections accumulate together so tiny paragraphs don't become noisy vectors.
        if len(section.text) < MIN_CHARS:
            if not merge_text:
                merge_title, merge_page = section.title, section.page
            merge_text = f"{merge_text}\n{section.text}".strip()
            if len(merge_text) >= TARGET_CHARS:
                flush_merge()
            continue
        flush_merge()
        emit(section.title, section.page, section.text)

    flush_merge()
    return chunks
