"""The hot read path: resolve a page to viewable, signed artifact URLs (US1).

Cost is O(1) in document size — we resolve ``(document_id, page_number)`` directly
to precomputed artifacts and mint signed CDN URLs. The source PDF is never opened
(Constitution Principle I, FR-004/FR-005).
"""

from __future__ import annotations

from dataclasses import dataclass

from docforge.domain.errors import NotFoundError, NotReadyError
from docforge.domain.models import ArtifactKind, PageStatus
from docforge.repositories.interfaces import (
    DocumentRepository,
    DocumentSetRepository,
    ObjectStoreGateway,
    PageArtifactRepository,
    PageRepository,
)
from docforge.services.access_service import AccessService

SIGNED_URL_TTL_SECONDS = 300


@dataclass(frozen=True)
class PageView:
    document_id: str
    page_number: int
    width_px: int
    height_px: int
    display_image_url: str
    thumbnail_url: str | None
    dzi_url: str | None
    url_expires_at: int


class PageServingService:
    def __init__(
        self,
        *,
        documents: DocumentRepository,
        document_sets: DocumentSetRepository,
        pages: PageRepository,
        artifacts: PageArtifactRepository,
        object_store: ObjectStoreGateway,
        access: AccessService,
    ) -> None:
        self._documents = documents
        self._sets = document_sets
        self._pages = pages
        self._artifacts = artifacts
        self._store = object_store
        self._access = access

    def get_page_view(self, document_id: str, page_number: int, user_id: str) -> PageView:
        """Resolve a page for a user, enforcing team access (FR-015).

        Raises NotFoundError (404), AccessDeniedError (403), or NotReadyError (202).
        """
        document = self._documents.get(document_id)
        if document is None:
            raise NotFoundError(f"Document {document_id} not found")

        document_set = self._sets.get(document.set_id)
        if document_set is None:
            raise NotFoundError(f"Document set {document.set_id} not found")

        # Access check BEFORE any artifact/URL work (FR-013/FR-015).
        self._access.assert_member(user_id, document_set.team_id)

        # Atomic visibility (FR-003): a page is only servable when its set is READY.
        # Without this, a READY page in a still-processing or failed set would leak.
        if not document_set.is_viewable:
            raise NotReadyError(status=document_set.status.value)

        page = self._pages.get_by_number(document_id, page_number)
        if page is None:
            raise NotFoundError(
                f"Page {page_number} of document {document_id} not found"
            )

        if page.status is not PageStatus.READY:
            # Still processing / failed -> 202 with status (spec edge case, FR-011).
            raise NotReadyError(status=page.status.value)

        artifacts = {a.kind: a for a in self._artifacts.list_for_page(page.id)}
        display = artifacts.get(ArtifactKind.DISPLAY_IMAGE)
        if display is None:
            raise NotReadyError(status=PageStatus.PENDING.value)

        display_url, expires_at = self._store.signed_url(
            display.object_key, SIGNED_URL_TTL_SECONDS
        )
        thumb = artifacts.get(ArtifactKind.THUMBNAIL)
        dzi = artifacts.get(ArtifactKind.DZI_DESCRIPTOR)

        return PageView(
            document_id=document_id,
            page_number=page_number,
            width_px=page.width_px,
            height_px=page.height_px,
            display_image_url=display_url,
            thumbnail_url=self._store.signed_url(thumb.object_key, SIGNED_URL_TTL_SECONDS)[0]
            if thumb
            else None,
            dzi_url=self._store.signed_url(dzi.object_key, SIGNED_URL_TTL_SECONDS)[0]
            if dzi
            else None,
            url_expires_at=expires_at,
        )
