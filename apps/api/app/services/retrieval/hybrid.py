"""Hybrid retrieval: lexical (tsvector) + semantic (pgvector) with reciprocal
rank fusion, then Qwen3-Reranker reordering and per-result explanations of
which signals matched (ARCHITECTURE.md §5). Deterministic — no generative LLM
in the retrieval path; the reranker is a pure scoring model and degrades to
fused order when unavailable.
"""

import sqlalchemy as sa
from sqlalchemy.orm import Session as OrmSession

from app.agents import reranker
from app.agents.embeddings import get_embedder
from app.core.config import get_settings
from app.models import Document, DocumentChunk

K = 20
RRF_K = 60


def _lexical_scores(db: OrmSession, user_id, query: str, doc_ids=None) -> dict[str, float]:
    ts_query = sa.func.websearch_to_tsquery("english", query)
    statement = (
        sa.select(
            DocumentChunk.id,
            sa.func.ts_rank(DocumentChunk.tsv, ts_query).label("rank"),
        )
        .where(DocumentChunk.user_id == user_id, DocumentChunk.tsv.op("@@")(ts_query))
        .order_by(sa.desc("rank"))
        .limit(K)
    )
    if doc_ids is not None:
        statement = statement.where(DocumentChunk.document_id.in_(doc_ids))
    return {str(row[0]): float(row[1]) for row in db.execute(statement)}


def _semantic_scores(db: OrmSession, user_id, query: str, doc_ids=None) -> dict[str, float]:
    vector = get_embedder().embed_query(query)
    distance = DocumentChunk.embedding.cosine_distance(vector)
    statement = (
        sa.select(DocumentChunk.id, distance.label("distance"))
        .where(DocumentChunk.user_id == user_id, DocumentChunk.embedding.isnot(None))
        .order_by(distance.asc())
        .limit(K)
    )
    if doc_ids is not None:
        statement = statement.where(DocumentChunk.document_id.in_(doc_ids))
    return {str(row[0]): 1.0 - float(row[1]) for row in db.execute(statement)}


def search_chunks(
    db: OrmSession,
    user_id,
    query: str,
    limit: int = 10,
    document_ids: list | None = None,
) -> list[dict]:
    """Fused, reranked, explained results: [{chunk_id, document_id, text,
    section, page, score, rerank_score, matched_signals}]."""
    lexical = _lexical_scores(db, user_id, query, document_ids)
    semantic = _semantic_scores(db, user_id, query, document_ids)
    if not lexical and not semantic:
        return []

    fused: dict[str, float] = {}
    signals: dict[str, list[str]] = {}
    for name, scores in (("lexical", lexical), ("semantic", semantic)):
        for rank, chunk_id in enumerate(sorted(scores, key=scores.get, reverse=True)):
            fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank + 1)
            signals.setdefault(chunk_id, []).append(name)

    import uuid as _uuid

    chunk_rows = db.execute(
        sa.select(DocumentChunk, Document.original_filename, Document.title)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(DocumentChunk.id.in_([_uuid.UUID(c) for c in fused.keys()]))
    ).all()

    results = []
    for chunk, filename, doc_title in chunk_rows:
        results.append(
            {
                "chunk_id": str(chunk.id),
                "document_id": str(chunk.document_id),
                "document_title": doc_title or filename,
                "section": chunk.section,
                "page": chunk.page,
                "text": chunk.text,
                "matched_signals": signals.get(str(chunk.id), []),
                "score": round(fused.get(str(chunk.id), 0.0), 4),
            }
        )
    results.sort(key=lambda r: r["score"], reverse=True)

    # Rerank the fused candidates; only the top slice reaches the LLM.
    candidates = results[: max(limit, 0) * 2] or results
    rerank_slice = candidates[: get_settings().rerank_candidates]
    scores = reranker.rerank_with_breaker(query, [r["text"] for r in rerank_slice])
    if scores is not None:
        for result, score in zip(rerank_slice, scores, strict=False):
            result["rerank_score"] = round(score, 4)
            result["matched_signals"].append("rerank")
        rerank_slice.sort(key=lambda r: r["rerank_score"], reverse=True)
        results = rerank_slice + [r for r in results if "rerank_score" not in r]
    return results[:limit]
