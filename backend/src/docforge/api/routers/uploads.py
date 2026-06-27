"""Resumable upload router (US2, contracts/openapi.yaml).

POST /uploads               -> create session + (fake) part URLs
GET  /uploads/{id}          -> progress, for resume
PUT  /uploads/{id}/parts    -> upload bytes (stand-in for direct-to-store part PUT)
POST /uploads/{id}/finalize -> verify checksum, create set (processing), enqueue
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Depends, Path, Request
from pydantic import BaseModel

from docforge.api.deps import Container, get_container, get_current_user_id
from docforge.domain.models import UploadSession

router = APIRouter(tags=["uploads"])


class CreateUploadRequest(BaseModel):
    team_id: str
    title: str
    filename: str
    total_bytes: int
    sha256: str


class UploadSessionResponse(BaseModel):
    id: str
    status: str
    received_bytes: int
    total_bytes: int
    part_urls: list[str]


class DocumentSetResponse(BaseModel):
    id: str
    team_id: str
    title: str
    status: str
    document_count: int


def _session_response(session: UploadSession, request: Request) -> UploadSessionResponse:
    part_url = str(request.url_for("upload_parts", upload_id=session.id))
    return UploadSessionResponse(
        id=session.id,
        status=session.status.value,
        received_bytes=session.received_bytes,
        total_bytes=session.declared_total_bytes,
        part_urls=[part_url],
    )


@router.post("/uploads", response_model=UploadSessionResponse, status_code=201)
def create_upload(
    request: Request,
    body: CreateUploadRequest,
    user_id: Annotated[str, Depends(get_current_user_id)],
    container: Annotated[Container, Depends(get_container)],
) -> UploadSessionResponse:
    session = container.ingestion.create_session(
        user_id=user_id,
        team_id=body.team_id,
        title=body.title,
        filename=body.filename,
        total_bytes=body.total_bytes,
        sha256=body.sha256,
    )
    return _session_response(session, request)


@router.get("/uploads/{upload_id}", response_model=UploadSessionResponse)
def get_upload(
    request: Request,
    upload_id: Annotated[str, Path()],
    user_id: Annotated[str, Depends(get_current_user_id)],
    container: Annotated[Container, Depends(get_container)],
) -> UploadSessionResponse:
    session = container.ingestion.get_session(upload_id, user_id)
    return _session_response(session, request)


@router.put("/uploads/{upload_id}/parts", name="upload_parts", response_model=UploadSessionResponse)
def upload_parts(
    request: Request,
    upload_id: Annotated[str, Path()],
    user_id: Annotated[str, Depends(get_current_user_id)],
    container: Annotated[Container, Depends(get_container)],
    data: Annotated[bytes, Body(media_type="application/octet-stream")],
) -> UploadSessionResponse:
    session = container.ingestion.append_bytes(upload_id, data, user_id)
    return _session_response(session, request)


@router.post("/uploads/{upload_id}/finalize", response_model=DocumentSetResponse, status_code=202)
def finalize_upload(
    upload_id: Annotated[str, Path()],
    user_id: Annotated[str, Depends(get_current_user_id)],
    container: Annotated[Container, Depends(get_container)],
) -> DocumentSetResponse:
    document_set = container.ingestion.finalize(upload_id, user_id)
    return DocumentSetResponse(
        id=document_set.id,
        team_id=document_set.team_id,
        title=document_set.title,
        status=document_set.status.value,
        document_count=document_set.document_count,
    )
