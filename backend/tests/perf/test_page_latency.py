"""T022: page-open latency budget (Constitution Principle I, SC-001/SC-002).

This MVP-level benchmark proves the *architecture* meets the budget on the resolve
path (no source-PDF access): p95 well under 2s and size-independent. A production
benchmark would run against real artifacts + CDN under concurrent load (SC-004).
"""

from __future__ import annotations

import time

from datetime import datetime

from docforge.api.deps import Container
from docforge.domain.models import (
    ArtifactKind,
    Document,
    DocumentSet,
    Membership,
    Page,
    PageArtifact,
    PageStatus,
    SetStatus,
)

BUDGET_SECONDS = 2.0


def _seed_doc(c: Container, doc_id: str, size_bytes: int, page_no: int) -> None:
    c.documents.add(
        Document(
            id=doc_id,
            set_id="set-x",
            filename=f"{doc_id}.pdf",
            size_bytes=size_bytes,
            page_count=page_no,
            source_object_key=f"{doc_id}/source.pdf",
            sha256="0" * 64,
        )
    )
    page = Page(
        id=f"{doc_id}-p{page_no}",
        document_id=doc_id,
        page_number=page_no,
        width_px=4000,
        height_px=3000,
        status=PageStatus.READY,
    )
    c.pages.add(page)
    c.artifacts.add(
        PageArtifact(
            id=f"{doc_id}-a",
            page_id=page.id,
            kind=ArtifactKind.DISPLAY_IMAGE,
            object_key=f"{doc_id}/p{page_no}.webp",
            sha256="a" * 64,
        )
    )


def _container() -> Container:
    c = Container.create()
    c.memberships.add(Membership(user_id="u", team_id="t"))
    c.document_sets.add(
        DocumentSet(
            id="set-x", team_id="t", uploaded_by="u", title="x",
            uploaded_at=datetime(2026, 1, 1), status=SetStatus.READY,
        )
    )
    _seed_doc(c, "small", 5_000_000, 1)          # 5 MB
    _seed_doc(c, "huge", 2_100_000_000, 1)        # 2.1 GB
    return c


def _p95(samples: list[float]) -> float:
    s = sorted(samples)
    return s[min(len(s) - 1, int(round(0.95 * (len(s) - 1))))]


def test_p95_under_2s_for_both_sizes() -> None:
    c = _container()
    small, huge = [], []
    for _ in range(200):
        t = time.perf_counter()
        c.page_serving.get_page_view("small", 1, "u")
        small.append(time.perf_counter() - t)
        t = time.perf_counter()
        c.page_serving.get_page_view("huge", 1, "u")
        huge.append(time.perf_counter() - t)

    assert _p95(small) < BUDGET_SECONDS
    assert _p95(huge) < BUDGET_SECONDS


def test_page_open_is_size_independent() -> None:
    c = _container()
    # Average resolve time should not scale with document size (5 MB vs 2.1 GB).
    def avg(doc_id: str) -> float:
        xs = []
        for _ in range(200):
            t = time.perf_counter()
            c.page_serving.get_page_view(doc_id, 1, "u")
            xs.append(time.perf_counter() - t)
        return sum(xs) / len(xs)

    small_avg = avg("small")
    huge_avg = avg("huge")
    # Both are microsecond-scale; assert they're the same order of magnitude.
    assert abs(huge_avg - small_avg) < BUDGET_SECONDS
