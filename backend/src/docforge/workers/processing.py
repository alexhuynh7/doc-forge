"""Async processing pipeline (US2, contracts/processing-pipeline.md).

Stages: validate -> split -> render+tile each page -> finalize. The set flips to
READY only after every page is rendered (atomic visibility, FR-003); invalid input
is quarantined (FR-012). Every stage is idempotent: re-running overwrites artifacts
by deterministic object keys and upserts pages by ``(document_id, page_number)``.

In production this runs as Celery tasks; here it is a plain callable invoked by the
synchronous dispatcher, so the orchestration is fully unit-testable without a broker.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from docforge.domain.errors import InvalidDocumentError
from docforge.domain.models import (
    ArtifactKind,
    AuditEvent,
    AuditEventType,
    Document,
    DocumentSet,
    Page,
    PageArtifact,
    PageStatus,
    SetStatus,
)
from docforge.observability import Metrics
from docforge.repositories.interfaces import (
    AuditRepository,
    DocumentRepository,
    DocumentSetRepository,
    ObjectStoreGateway,
    PageArtifactRepository,
    PageRenderer,
    PageRepository,
)


class ProcessingPipeline:
    def __init__(
        self,
        *,
        document_sets: DocumentSetRepository,
        documents: DocumentRepository,
        pages: PageRepository,
        artifacts: PageArtifactRepository,
        audit: AuditRepository,
        object_store: ObjectStoreGateway,
        renderer: PageRenderer,
        metrics: Metrics,
        now: datetime | None = None,
    ) -> None:
        self._sets = document_sets
        self._documents = documents
        self._pages = pages
        self._artifacts = artifacts
        self._audit = audit
        self._store = object_store
        self._renderer = renderer
        self._metrics = metrics
        self._now = now or datetime(2026, 1, 2, 10, 5, 0)

    def process_document_set(self, set_id: str, document_id: str | None = None) -> None:
        document_set = self._sets.get(set_id)
        if document_set is None:
            return  # nothing to do (idempotent on missing/cleaned-up set)

        documents = self._documents_for_set(set_id, document_id)
        try:
            # Stage every page of every document BEFORE committing any. A failure
            # mid-set commits nothing, so a FAILED/QUARANTINED set never leaves
            # orphaned READY pages behind (atomic visibility, FR-003).
            staged: list[tuple[Page, list[PageArtifact]]] = []
            for document in documents:
                source = self._store.get_object(document.source_object_key) or b""
                self._validate(source)
                count = self._renderer.page_count(source)
                document.page_count = count
                for n in range(1, count + 1):
                    staged.append(self._render_page(document, source, n))
            for page, artifacts in staged:
                self._pages.add(page)
                for artifact in artifacts:
                    self._artifacts.add(artifact)
            self._finalize_ready(document_set)
        except InvalidDocumentError as exc:
            document_set.status = SetStatus.QUARANTINED
            document_set.failure_reason = str(exc)
            self._metrics.inc("sets_failed_total")
        except Exception as exc:  # noqa: BLE001 - convert to a recorded failure
            document_set.status = SetStatus.FAILED
            document_set.failure_reason = str(exc)
            self._metrics.inc("sets_failed_total")

    # --- stages -------------------------------------------------------------

    def _validate(self, source: bytes) -> None:
        if not self._renderer.is_valid_pdf(source):
            raise InvalidDocumentError("Uploaded file is not a valid PDF")

    def _render_page(
        self, document: Document, source: bytes, n: int
    ) -> tuple[Page, list[PageArtifact]]:
        """Render one page and return its (page, artifacts) WITHOUT committing —
        the caller commits the whole set only after all pages render."""
        rendered = self._renderer.render_page(source, n)
        # Deterministic keys make re-processing idempotent.
        page = self._pages.get_by_number(document.id, n) or Page(
            id=str(uuid.uuid4()), document_id=document.id, page_number=n
        )
        page.width_px = rendered.width_px
        page.height_px = rendered.height_px

        display_key = f"sets/{document.set_id}/docs/{document.id}/pages/{n}/display.webp"
        dzi_key = f"sets/{document.set_id}/docs/{document.id}/pages/{n}/tiles.dzi"
        display_sha = self._store.put_object(display_key, rendered.display_image)
        dzi_sha = self._store.put_object(dzi_key, rendered.dzi_descriptor)

        artifacts = [
            PageArtifact(
                id=str(uuid.uuid4()),
                page_id=page.id,
                kind=ArtifactKind.DISPLAY_IMAGE,
                object_key=display_key,
                sha256=display_sha,
                bytes=len(rendered.display_image),
            ),
            PageArtifact(
                id=str(uuid.uuid4()),
                page_id=page.id,
                kind=ArtifactKind.DZI_DESCRIPTOR,
                object_key=dzi_key,
                sha256=dzi_sha,
                bytes=len(rendered.dzi_descriptor),
            ),
        ]
        page.status = PageStatus.READY
        return page, artifacts

    def _finalize_ready(self, document_set: DocumentSet) -> None:
        document_set.status = SetStatus.READY
        document_set.ready_at = self._now
        self._audit.add(
            AuditEvent(
                id=str(uuid.uuid4()),
                set_id=document_set.id,
                event_type=AuditEventType.PROCESSING_COMPLETED,
                occurred_at=self._now,
            )
        )
        self._metrics.inc("sets_processed_total")

    # --- helpers ------------------------------------------------------------

    def _documents_for_set(self, set_id: str, document_id: str | None) -> list[Document]:
        if document_id is not None:
            doc = self._documents.get(document_id)
            return [doc] if doc else []
        return self._documents.list_for_set(set_id)
