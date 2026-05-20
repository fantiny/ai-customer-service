"""DocumentSyncer — pulls documents from an external API and upserts them
into the local faq_documents table so BM25 / pgvector can index them.

Expected external API contract:

    GET {base_url}/documents?category={category}&page={page}&page_size={page_size}
    → {
        "data": [
            {
                "id": "doc-001",               # required
                "title": "退换货政策",           # used as metadata.title
                "content": "...",              # required
                "category": "wedding_dress_faq",
                "metadata": { ... }            # optional extra fields
            }
        ],
        "next_page": 2    # null / absent when last page reached
      }

If the upstream system doesn't paginate, set "next_page" to null.
Override `_parse_document` to adapt any non-standard response format.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

import asyncpg

from ....domain.entities import Document
from ..auth.providers import IAuthProvider
from ..http_client import AuthedHTTPClient

logger = logging.getLogger(__name__)


class DocumentSyncer:
    """Fetches documents from an external source and writes them to local DB.

    Designed to run once at startup (or on a scheduled basis) so that the
    BM25 and pgvector retrieval stack always works against a local copy of
    the catalogue — avoiding latency and availability coupling during live
    conversations.
    """

    DEFAULT_PAGE_SIZE = 100

    def __init__(
        self,
        base_url: str,
        auth_provider: IAuthProvider,
        db_pool: asyncpg.Pool,
        category: str,
        timeout: float = 60.0,
    ) -> None:
        self._client = AuthedHTTPClient(
            base_url=base_url,
            auth_provider=auth_provider,
            timeout=timeout,
        )
        self._pool = db_pool
        self._category = category
        logger.info(
            "DocumentSyncer configured (category=%s, base_url=%s, auth=%s)",
            category,
            base_url,
            auth_provider.describe(),
        )

    async def sync(self) -> int:
        """Pull all documents from the external source and upsert locally.

        Returns the number of documents successfully upserted.
        """
        docs = await self._fetch_all()
        if not docs:
            logger.warning(
                "DocumentSyncer[%s]: no documents returned from external source",
                self._category,
            )
            return 0

        upserted = await self._upsert_all(docs)
        logger.info(
            "DocumentSyncer[%s]: synced %d documents from external source",
            self._category,
            upserted,
        )
        return upserted

    # ── Fetching ──────────────────────────────────────────────────────────────

    async def _fetch_all(self) -> list[Document]:
        """Paginate through all pages and return combined document list."""
        documents: list[Document] = []
        page = 1

        while True:
            raw = await self._client.get(
                "/documents",
                params={
                    "category": self._category,
                    "page": page,
                    "page_size": self.DEFAULT_PAGE_SIZE,
                },
            )
            if raw is None:
                break

            # Support bare list or { "data": [...], "next_page": ... } envelope
            rows: list[dict] = raw.get("data", raw) if isinstance(raw, dict) else raw
            for item in rows:
                doc = self._parse_document(item)
                if doc:
                    documents.append(doc)

            # Pagination: continue only if "next_page" is present and non-null
            if isinstance(raw, dict) and raw.get("next_page"):
                page = int(raw["next_page"])
            else:
                break

        return documents

    def _parse_document(self, raw: dict[str, Any]) -> Document | None:
        """Map a raw API response item to a Document.

        Override this to adapt non-standard schemas without touching the syncer
        infrastructure.
        """
        content = raw.get("content", "")
        if not content:
            return None  # skip empty docs

        doc_id_raw = raw.get("id", raw.get("doc_id", ""))
        # Stable deterministic UUID based on external id + category
        doc_id = str(uuid.uuid5(
            uuid.NAMESPACE_DNS,
            f"{self._category}:{doc_id_raw}",
        ))

        extra_meta: dict = raw.get("metadata", {}) or {}
        metadata = {
            "title": raw.get("title", ""),
            "category": self._category,
            "external_id": str(doc_id_raw),
            **extra_meta,
        }

        return Document(doc_id=doc_id, content=content, metadata=metadata)

    # ── Persistence ───────────────────────────────────────────────────────────

    async def _upsert_all(self, docs: list[Document]) -> int:
        """Batch-upsert documents into faq_documents. Returns count upserted."""
        count = 0
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                for doc in docs:
                    await conn.execute(
                        """
                        INSERT INTO faq_documents (doc_id, content, metadata)
                        VALUES ($1, $2, $3::jsonb)
                        ON CONFLICT (doc_id) DO UPDATE
                          SET content    = EXCLUDED.content,
                              metadata   = EXCLUDED.metadata,
                              updated_at = now()
                        """,
                        doc.doc_id,
                        doc.content,
                        json.dumps(doc.metadata, ensure_ascii=False),
                    )
                    count += 1
        return count
