"""T032: processing pipeline — split/render, idempotency, quarantine (US2)."""

from __future__ import annotations

from datetime import datetime


from docforge.domain.models import (
    ArtifactKind,
    Document,
    DocumentSet,
    PageStatus,
    SetStatus,
)
from docforge.observability import Metrics
from docforge.repositories.memory import (
    FakeObjectStore,
    FakePageRenderer,
    InMemoryAuditRepository,
    InMemoryDocumentRepository,
    InMemoryDocumentSetRepository,
    InMemoryPageArtifactRepository,
    InMemoryPageRepository,
)
from docforge.workers.processing import ProcessingPipeline

SET_ID = "set-1"
DOC_ID = "doc-1"


def _build(source: bytes):
    sets = InMemoryDocumentSetRepository()
    docs = InMemoryDocumentRepository()
    pages = InMemoryPageRepository()
    artifacts = InMemoryPageArtifactRepository()
    audit = InMemoryAuditRepository()
    store = FakeObjectStore()
    key = f"sets/{SET_ID}/source/plan.pdf"
    store.put_object(key, source)
    sets.add(
        DocumentSet(
            id=SET_ID, team_id="t", uploaded_by="u", title="x",
            uploaded_at=datetime(2026, 1, 2), status=SetStatus.PROCESSING, document_count=1,
        )
    )
    docs.add(
        Document(
            id=DOC_ID, set_id=SET_ID, filename="plan.pdf", size_bytes=len(source),
            page_count=0, source_object_key=key, sha256="0" * 64,
        )
    )
    pipeline = ProcessingPipeline(
        document_sets=sets, documents=docs, pages=pages, artifacts=artifacts,
        audit=audit, object_store=store, renderer=FakePageRenderer(), metrics=Metrics(),
    )
    return pipeline, sets, pages, artifacts, audit


def test_valid_pdf_processes_to_ready_with_all_pages() -> None:
    pipeline, sets, pages, artifacts, audit = _build(b"%PDF pages=4 x")
    pipeline.process_document_set(SET_ID)

    assert sets.get(SET_ID).status is SetStatus.READY
    for n in range(1, 5):
        page = pages.get_by_number(DOC_ID, n)
        assert page is not None and page.status is PageStatus.READY
        kinds = {a.kind for a in artifacts.list_for_page(page.id)}
        assert ArtifactKind.DISPLAY_IMAGE in kinds and ArtifactKind.DZI_DESCRIPTOR in kinds
    assert len(audit.list_for_set(SET_ID)) == 1  # processing_completed


def test_invalid_pdf_is_quarantined_not_ready() -> None:
    pipeline, sets, pages, _, _ = _build(b"NOT-A-PDF pages=2")
    pipeline.process_document_set(SET_ID)

    s = sets.get(SET_ID)
    assert s.status is SetStatus.QUARANTINED
    assert s.failure_reason is not None
    assert pages.get_by_number(DOC_ID, 1) is None  # nothing made viewable


def test_render_failure_marks_set_failed_with_no_orphan_pages() -> None:
    # C3 regression: a render that throws on a later page must commit NO pages,
    # leaving no orphaned READY pages behind a FAILED set (atomic visibility).
    pipeline, sets, pages, artifacts, _ = _build(b"%PDF pages=3 x")

    class _FailOnPage2(FakePageRenderer):
        def render_page(self, data: bytes, page_number: int):  # type: ignore[no-untyped-def]
            if page_number == 2:
                raise RuntimeError("render boom")
            return super().render_page(data, page_number)

    pipeline._renderer = _FailOnPage2()  # noqa: SLF001 - test injection
    pipeline.process_document_set(SET_ID)

    s = sets.get(SET_ID)
    assert s.status is SetStatus.FAILED
    assert s.failure_reason is not None
    # Page 1 rendered fine but must NOT be committed, since the set failed.
    assert pages.get_by_number(DOC_ID, 1) is None
    assert pages.get_by_number(DOC_ID, 2) is None


def test_processing_is_idempotent_on_retry() -> None:
    pipeline, sets, pages, artifacts, _ = _build(b"%PDF pages=2 x")
    pipeline.process_document_set(SET_ID)
    pipeline.process_document_set(SET_ID)  # re-run

    # Page identity is keyed on (document_id, page_number) -> no duplicate pages,
    # and artifacts overwrite by deterministic key (2 kinds re-added per page).
    page = pages.get_by_number(DOC_ID, 1)
    assert page is not None and page.status is PageStatus.READY
    assert sets.get(SET_ID).status is SetStatus.READY
