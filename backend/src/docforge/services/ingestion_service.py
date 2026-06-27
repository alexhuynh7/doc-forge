"""Resumable upload ingestion (US2, FR-001/002/003/006).

Responsibilities:
- create an upload session (access-checked) and expose part URLs for resumable,
  direct-to-store transfer;
- track received bytes for resume;
- on finalize: verify the SHA-256 (integrity, FR-006), store the source PDF under
  7-year retention, create the DocumentSet as ``processing`` (atomic visibility,
  FR-003), and dispatch async processing (FR-009) — never blocking the request.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime

from docforge.domain.errors import IntegrityError, NotFoundError
from docforge.domain.models import (
    AuditEvent,
    AuditEventType,
    Document,
    DocumentSet,
    RetentionRecord,
    SetStatus,
    UploadSession,
    UploadStatus,
)
from docforge.observability import Metrics
from docforge.repositories.interfaces import (
    AuditRepository,
    DocumentRepository,
    DocumentSetRepository,
    ObjectStoreGateway,
    RetentionRepository,
    TaskDispatcher,
    UploadSessionRepository,
)
from docforge.services.access_service import AccessService


class IngestionService:
    def __init__(
        self,
        *,
        sessions: UploadSessionRepository,
        document_sets: DocumentSetRepository,
        documents: DocumentRepository,
        audit: AuditRepository,
        retention: RetentionRepository,
        object_store: ObjectStoreGateway,
        dispatcher: TaskDispatcher,
        access: AccessService,
        metrics: Metrics,
        now: datetime | None = None,
    ) -> None:
        self._sessions = sessions
        self._sets = document_sets
        self._documents = documents
        self._audit = audit
        self._retention = retention
        self._store = object_store
        self._dispatcher = dispatcher
        self._access = access
        self._metrics = metrics
        self._now = now or datetime(2026, 1, 2, 10, 0, 0)

    def create_session(
        self,
        *,
        user_id: str,
        team_id: str,
        title: str,
        filename: str,
        total_bytes: int,
        sha256: str,
    ) -> UploadSession:
        self._access.assert_member(user_id, team_id)  # FR-013
        session = UploadSession(
            id=str(uuid.uuid4()),
            team_id=team_id,
            created_by=user_id,
            title=title,
            filename=filename,
            declared_total_bytes=total_bytes,
            declared_sha256=sha256,
        )
        self._sessions.add(session)
        return session

    def get_session(self, session_id: str, user_id: str) -> UploadSession:
        """Load a session, enforcing team access (FR-013/FR-015).

        This is the single choke point for session retrieval — append/finalize go
        through it — so every session read/write is access-checked.
        """
        session = self._sessions.get(session_id)
        if session is None:
            raise NotFoundError(f"Upload session {session_id} not found")
        self._access.assert_member(user_id, session.team_id)
        return session

    def append_bytes(self, session_id: str, data: bytes, user_id: str) -> UploadSession:
        """Simulate a (resumable) part upload landing in the object store."""
        session = self.get_session(session_id, user_id)
        session.received.extend(data)
        return session

    def finalize(self, session_id: str, user_id: str) -> DocumentSet:
        session = self.get_session(session_id, user_id)

        # Reject re-finalize / concurrent finalize: only an ACTIVE session may be
        # finalized, so a retried 202 or a second caller cannot create a duplicate
        # DocumentSet, retention record, and dispatch.
        if session.status is not UploadStatus.ACTIVE:
            raise IntegrityError(
                f"Upload session {session_id} is not active (status={session.status.value})"
            )

        if not session.is_complete:
            raise IntegrityError(
                f"Upload incomplete: {session.received_bytes}/{session.declared_total_bytes} bytes"
            )
        actual_sha = hashlib.sha256(session.received).hexdigest()
        if actual_sha != session.declared_sha256:
            raise IntegrityError("Checksum mismatch on finalize")

        set_id = str(uuid.uuid4())
        document_set = DocumentSet(
            id=set_id,
            team_id=session.team_id,
            uploaded_by=session.created_by,
            title=session.title,
            uploaded_at=self._now,
            status=SetStatus.PROCESSING,  # atomic visibility: not viewable yet (FR-003)
            document_count=1,
        )
        self._sets.add(document_set)

        source_key = f"sets/{set_id}/source/{session.filename}"
        # Store source PDF under 7-year retention (Object Lock mirror, FR-007).
        sha = self._store.put_object(
            source_key, bytes(session.received), retain_until=document_set.retain_until
        )
        document = Document(
            id=str(uuid.uuid4()),
            set_id=set_id,
            filename=session.filename,
            size_bytes=session.declared_total_bytes,
            page_count=0,  # established during processing
            source_object_key=source_key,
            sha256=sha,
            order_index=0,
        )
        self._documents.add(document)

        # Apply the 7-year retention record on finalize (T045, FR-007).
        self._retention.add(
            RetentionRecord(set_id=set_id, retain_until=document_set.retain_until)
        )

        session.status = UploadStatus.FINALIZED
        self._audit.add(
            AuditEvent(
                id=str(uuid.uuid4()),
                set_id=set_id,
                event_type=AuditEventType.UPLOAD_ACCEPTED,
                occurred_at=self._now,
                actor_id=session.created_by,
                detail={"sha256": sha},
            )
        )
        self._metrics.inc("ingest_accepted_total")

        # Decouple from the request path: enqueue and return immediately (FR-009).
        self._dispatcher.dispatch_process_document_set(set_id)
        return document_set
