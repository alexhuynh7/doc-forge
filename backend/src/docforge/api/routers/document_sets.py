"""Document-set listing/detail/delete router (T026/T044, FR-013/FR-007).

Team-scoped: a caller only sees READY sets owned by teams they belong to. Deletion
is blocked (423) before the 7-year retention window elapses.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Response
from pydantic import BaseModel

from docforge.api.deps import Container, get_container, get_current_user_id
from docforge.domain.errors import NotFoundError
from docforge.domain.models import DocumentSet

router = APIRouter(tags=["documents"])


def _today() -> date:
    return datetime.now(tz=timezone.utc).date()


class DocumentSetResponse(BaseModel):
    id: str
    team_id: str
    title: str
    status: str
    document_count: int
    uploaded_at: str
    ready_at: str | None
    retain_until: str


def _to_response(s: DocumentSet) -> DocumentSetResponse:
    return DocumentSetResponse(
        id=s.id,
        team_id=s.team_id,
        title=s.title,
        status=s.status.value,
        document_count=s.document_count,
        uploaded_at=s.uploaded_at.isoformat(),
        ready_at=s.ready_at.isoformat() if s.ready_at else None,
        retain_until=s.retain_until.isoformat(),
    )


@router.get("/document-sets", response_model=list[DocumentSetResponse])
def list_document_sets(
    user_id: Annotated[str, Depends(get_current_user_id)],
    container: Annotated[Container, Depends(get_container)],
) -> list[DocumentSetResponse]:
    team_ids = container.memberships.list_teams_for_user(user_id)
    sets = container.document_sets.list_for_teams(team_ids)
    return [_to_response(s) for s in sets]


@router.get("/document-sets/{set_id}", response_model=DocumentSetResponse)
def get_document_set(
    set_id: Annotated[str, Path()],
    user_id: Annotated[str, Depends(get_current_user_id)],
    container: Annotated[Container, Depends(get_container)],
) -> DocumentSetResponse:
    s = container.document_sets.get(set_id)
    if s is None or not s.is_viewable:
        raise NotFoundError(f"Document set {set_id} not found")
    container.access.assert_member(user_id, s.team_id)
    return _to_response(s)


@router.delete("/document-sets/{set_id}", status_code=204)
def delete_document_set(
    set_id: Annotated[str, Path()],
    user_id: Annotated[str, Depends(get_current_user_id)],
    container: Annotated[Container, Depends(get_container)],
) -> Response:
    """Attempt deletion. Returns 204 after retention expiry, or 423 (via the
    RetentionLockedError handler) while the 7-year window is active (FR-007/FR-008)."""
    container.retention.attempt_delete(set_id, user_id, now=_today())
    return Response(status_code=204)
