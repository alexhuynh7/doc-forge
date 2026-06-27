"""Shared fixtures: a seeded in-memory container + FastAPI TestClient."""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from docforge.api.deps import Container
from docforge.api.main import create_app
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

TEAM_ID = "team-1"
MEMBER_ID = "user-member"
OUTSIDER_ID = "user-outsider"
DOC_ID = "doc-1"
SET_ID = "set-1"


def _seed(container: Container) -> None:
    container.memberships.add(Membership(user_id=MEMBER_ID, team_id=TEAM_ID))

    container.document_sets.add(
        DocumentSet(
            id=SET_ID,
            team_id=TEAM_ID,
            uploaded_by=MEMBER_ID,
            title="Tower B — Structural Plans",
            uploaded_at=datetime(2026, 1, 2, 10, 0, 0),
            status=SetStatus.READY,
            document_count=1,
            ready_at=datetime(2026, 1, 2, 10, 5, 0),
        )
    )
    container.documents.add(
        Document(
            id=DOC_ID,
            set_id=SET_ID,
            filename="tower-b.pdf",
            size_bytes=2_100_000_000,  # 2.1 GB — exercises the size-independence claim
            page_count=1400,
            source_object_key=f"sets/{SET_ID}/docs/{DOC_ID}/source.pdf",
            sha256="0" * 64,
        )
    )
    # A READY page with artifacts, and a still-PENDING page.
    ready_page = Page(
        id="page-ready",
        document_id=DOC_ID,
        page_number=312,
        width_px=4000,
        height_px=3000,
        status=PageStatus.READY,
    )
    container.pages.add(ready_page)
    container.artifacts.add(
        PageArtifact(
            id="art-1",
            page_id=ready_page.id,
            kind=ArtifactKind.DISPLAY_IMAGE,
            object_key=f"sets/{SET_ID}/docs/{DOC_ID}/pages/312/display.webp",
            sha256="a" * 64,
            bytes=180_000,
        )
    )
    container.artifacts.add(
        PageArtifact(
            id="art-2",
            page_id=ready_page.id,
            kind=ArtifactKind.DZI_DESCRIPTOR,
            object_key=f"sets/{SET_ID}/docs/{DOC_ID}/pages/312/tiles.dzi",
            sha256="b" * 64,
            bytes=2_000,
        )
    )
    container.pages.add(
        Page(
            id="page-pending",
            document_id=DOC_ID,
            page_number=999,
            status=PageStatus.PENDING,
        )
    )


@pytest.fixture
def container() -> Container:
    c = Container.create()
    _seed(c)
    return c


@pytest.fixture
def client(container: Container) -> TestClient:
    return TestClient(create_app(container))


@pytest.fixture
def member_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {MEMBER_ID}"}


@pytest.fixture
def outsider_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {OUTSIDER_ID}"}
