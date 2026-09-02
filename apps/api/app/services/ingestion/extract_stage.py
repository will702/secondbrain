"""Extraction stage boundary.

In M1 this stage is a no-op guard (LLM extraction lands in M2): it verifies
whether an LLM endpoint is reachable and, if not, marks the document processed
without extraction so ingestion is never blocked on a cold model server.
"""

import logging

import httpx
from sqlalchemy.orm import Session as OrmSession

from app.core.config import get_settings
from app.models import Document

logger = logging.getLogger("secondbrain.extraction")


def llm_available() -> bool:
    settings = get_settings()
    try:
        response = httpx.get(f"{settings.llm_base_url}/models", timeout=3.0)
        return response.status_code == 200
    except Exception:
        return False


def run_extraction_stage(db: OrmSession, document: Document, chunks) -> None:
    if not llm_available():
        logger.warning(
            "LLM not reachable — document stored without extraction "
            "(re-ingest or run 'reextract' when the model server is up)",
            extra={"document_id": str(document.id)},
        )
        return
    from app.services.extraction.pipeline import extract_document

    extract_document(db, document, chunks)
