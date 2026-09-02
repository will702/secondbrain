from app.services.ingestion.chunker import MAX_CHARS, MIN_CHARS, chunk_document, estimate_tokens
from app.services.parsing import ParsedDocument, Section


def test_small_sections_merge():
    parsed = ParsedDocument(
        sections=[Section(title=f"S{i}", text=f"Short section {i} content.") for i in range(5)]
    )
    chunks = chunk_document(parsed)
    assert 1 <= len(chunks) <= 2


def test_long_section_splits_within_bounds():
    text = "This is a sentence about machine learning concepts. " * 200
    parsed = ParsedDocument(sections=[Section(title="Big", text=text)])
    chunks = chunk_document(parsed)
    assert len(chunks) > 1
    assert all(len(c["text"]) <= MAX_CHARS for c in chunks)
    assert all(c["token_count"] == estimate_tokens(c["text"]) for c in chunks)


def test_sections_preserved_with_page_numbers():
    parsed = ParsedDocument(
        sections=[
            Section(title="Page 1", text="Content of page one. " * 40, page=1),
            Section(title="Page 2", text="Content of page two. " * 40, page=2),
        ]
    )
    chunks = chunk_document(parsed)
    assert {c["page"] for c in chunks} == {1, 2}
    assert chunks[0]["section"] == "Page 1"


def test_empty_document_yields_no_chunks():
    assert chunk_document(ParsedDocument(sections=[])) == []
    assert chunk_document(ParsedDocument(sections=[Section(title="x", text="  ")])) == []


def test_min_length_chunks_exist():
    # A single tiny section should still produce one chunk.
    parsed = ParsedDocument(sections=[Section(title="tiny", text="Due Friday.")])
    chunks = chunk_document(parsed)
    assert len(chunks) == 1
    assert len(chunks[0]["text"]) < MIN_CHARS  # tiny input stays tiny; no padding
