"""Page-serving router — the hot path (T025, FR-004/FR-005/FR-015).

GET /documents/{documentId}/pages/{pageNumber}
  200 PageView          -> signed CDN URLs for the page
  202 ProcessingStatus  -> page exists but not yet rendered (via NotReadyError handler)
  403 / 404             -> via domain-error handlers
"""

from __future__ import annotations

import time
from typing import Annotated

from fastapi import APIRouter, Depends, Path
from pydantic import BaseModel

from docforge.api.deps import Container, get_container, get_current_user_id
from docforge.observability import METRICS

router = APIRouter(tags=["pages"])


class PageViewResponse(BaseModel):
    document_id: str
    page_number: int
    width_px: int
    height_px: int
    display_image_url: str
    thumbnail_url: str | None
    dzi_url: str | None
    url_expires_at: int


@router.get("/documents/{document_id}/pages/{page_number}", response_model=PageViewResponse)
def get_page(
    document_id: Annotated[str, Path()],
    page_number: Annotated[int, Path(ge=1)],
    user_id: Annotated[str, Depends(get_current_user_id)],
    container: Annotated[Container, Depends(get_container)],
) -> PageViewResponse:
    start = time.perf_counter()
    view = container.page_serving.get_page_view(document_id, page_number, user_id)
    METRICS.observe_page_open(time.perf_counter() - start)
    return PageViewResponse(
        document_id=view.document_id,
        page_number=view.page_number,
        width_px=view.width_px,
        height_px=view.height_px,
        display_image_url=view.display_image_url,
        thumbnail_url=view.thumbnail_url,
        dzi_url=view.dzi_url,
        url_expires_at=view.url_expires_at,
    )
