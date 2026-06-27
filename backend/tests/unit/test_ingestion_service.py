"""T031: ingestion_service — session, resume, checksum, atomic finalize (US2)."""

from __future__ import annotations

import hashlib

import pytest

from docforge.api.deps import Container
from docforge.domain.errors import AccessDeniedError, IntegrityError
from docforge.domain.models import Membership, SetStatus

TEAM = "team-1"
USER = "user-1"


@pytest.fixture
def container() -> Container:
    c = Container.create()
    c.memberships.add(Membership(user_id=USER, team_id=TEAM))
    return c


def _pdf(pages: int = 2) -> bytes:
    return b"%PDF-1.7 pages=" + str(pages).encode() + b" body"


def _start(container: Container, data: bytes):
    return container.ingestion.create_session(
        user_id=USER,
        team_id=TEAM,
        title="Set",
        filename="plan.pdf",
        total_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )


def test_non_member_cannot_create_session(container: Container) -> None:
    with pytest.raises(AccessDeniedError):
        container.ingestion.create_session(
            user_id="outsider", team_id=TEAM, title="x", filename="f.pdf",
            total_bytes=1, sha256="0" * 64,
        )


def test_resume_reports_received_bytes(container: Container) -> None:
    data = _pdf()
    session = _start(container, data)
    container.ingestion.append_bytes(session.id, data[:3], USER)
    resumed = container.ingestion.get_session(session.id, USER)
    assert resumed.received_bytes == 3
    assert not resumed.is_complete


def test_finalize_incomplete_upload_raises(container: Container) -> None:
    data = _pdf()
    session = _start(container, data)
    container.ingestion.append_bytes(session.id, data[:2], USER)
    with pytest.raises(IntegrityError):
        container.ingestion.finalize(session.id, USER)


def test_finalize_checksum_mismatch_raises(container: Container) -> None:
    data = _pdf()
    session = _start(container, data)
    container.ingestion.append_bytes(session.id, b"X" * len(data), USER)  # right len, wrong bytes
    with pytest.raises(IntegrityError):
        container.ingestion.finalize(session.id, USER)


def test_non_member_cannot_read_or_write_session(container: Container) -> None:
    # C1 regression: session access is membership-gated on every path.
    data = _pdf()
    session = _start(container, data)
    with pytest.raises(AccessDeniedError):
        container.ingestion.get_session(session.id, "outsider")
    with pytest.raises(AccessDeniedError):
        container.ingestion.append_bytes(session.id, data, "outsider")
    with pytest.raises(AccessDeniedError):
        container.ingestion.finalize(session.id, "outsider")


def test_double_finalize_is_rejected(container: Container) -> None:
    # C4 regression: a second finalize must not create a duplicate set.
    data = _pdf(pages=2)
    session = _start(container, data)
    container.ingestion.append_bytes(session.id, data, USER)
    container.ingestion.finalize(session.id, USER)
    with pytest.raises(IntegrityError):
        container.ingestion.finalize(session.id, USER)


def test_finalize_creates_processing_set_then_pipeline_makes_it_ready(
    container: Container,
) -> None:
    data = _pdf(pages=3)
    session = _start(container, data)
    container.ingestion.append_bytes(session.id, data, USER)
    document_set = container.ingestion.finalize(session.id, USER)

    # Synchronous dispatcher ran the pipeline -> READY with 3 pages.
    stored = container.document_sets.get(document_set.id)
    assert stored.status is SetStatus.READY
    docs = container.documents.list_for_set(document_set.id)
    assert docs[0].page_count == 3
    assert container.metrics.counters["ingest_accepted_total"] >= 1
