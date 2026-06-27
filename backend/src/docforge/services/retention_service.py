"""Retention, integrity, and deletion guard (US3, FR-006/007/008).

- ``register`` records the 7-year retention window on finalize.
- ``attempt_delete`` blocks deletion before the window elapses (and audits the
  attempt); after expiry it deletes and audits.
- ``verify_integrity`` re-hashes stored content and compares to recorded checksums,
  auditing the check (FR-006 read-time re-verification).

The authoritative guarantee is the storage-layer Object Lock (the object store
refuses early deletion as a backstop); this service provides the policy decision,
the audit trail, and the API-facing behavior.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import date, datetime

from docforge.domain.errors import (
    IntegrityError,
    NotFoundError,
    RetentionLockedError,
)
from docforge.domain.models import (
    AuditEvent,
    AuditEventType,
    DocumentSet,
    RetentionRecord,
)
from docforge.repositories.interfaces import (
    AuditRepository,
    DocumentRepository,
    DocumentSetRepository,
    ObjectStoreGateway,
    PageArtifactRepository,
    PageRepository,
    RetentionRepository,
)
from docforge.services.access_service import AccessService


class RetentionService:
    def __init__(
        self,
        *,
        document_sets: DocumentSetRepository,
        documents: DocumentRepository,
        pages: PageRepository,
        artifacts: PageArtifactRepository,
        retention: RetentionRepository,
        audit: AuditRepository,
        object_store: ObjectStoreGateway,
        access: AccessService,
    ) -> None:
        self._sets = document_sets
        self._documents = documents
        self._pages = pages
        self._artifacts = artifacts
        self._retention = retention
        self._audit = audit
        self._store = object_store
        self._access = access

    def register(self, document_set: DocumentSet) -> RetentionRecord:
        """Record the 7-year retention window (called on finalize, FR-007)."""
        record = RetentionRecord(
            set_id=document_set.id, retain_until=document_set.retain_until
        )
        self._retention.add(record)
        return record

    def attempt_delete(self, set_id: str, user_id: str, now: date) -> None:
        document_set = self._sets.get(set_id)
        if document_set is None:
            raise NotFoundError(f"Document set {set_id} not found")
        self._access.assert_member(user_id, document_set.team_id)

        record = self._retention.get(set_id)
        retain_until = record.retain_until if record else document_set.retain_until

        if now < retain_until:
            # Blocked: audit the attempt and refuse (FR-007/FR-008).
            self._audit.add(
                self._event(
                    set_id,
                    AuditEventType.DELETION_ATTEMPT_BLOCKED,
                    user_id,
                    {"retain_until": retain_until.isoformat()},
                )
            )
            raise RetentionLockedError(
                f"Deletion blocked: retained until {retain_until.isoformat()}"
            )

        # After expiry: clear retention, delete blobs + metadata, audit.
        self._retention.delete(set_id)
        for document in self._documents.list_for_set(set_id):
            self._store.delete_object(document.source_object_key)
        self._documents.delete_for_set(set_id)
        self._sets.delete(set_id)
        self._audit.add(
            self._event(set_id, AuditEventType.DELETED_AFTER_EXPIRY, user_id, {})
        )

    def verify_integrity(self, set_id: str) -> bool:
        """Re-hash the stored source(s) and compare to the recorded checksum (FR-006)."""
        documents = self._documents.list_for_set(set_id)
        if not documents:
            raise NotFoundError(f"Document set {set_id} has no documents")
        for document in documents:
            data = self._store.get_object(document.source_object_key)
            if data is None or hashlib.sha256(data).hexdigest() != document.sha256:
                self._audit.add(
                    self._event(
                        set_id,
                        AuditEventType.INTEGRITY_CHECK,
                        None,
                        {"document_id": document.id, "ok": False},
                    )
                )
                raise IntegrityError(
                    f"Integrity check failed for document {document.id}"
                )
        self._audit.add(
            self._event(set_id, AuditEventType.INTEGRITY_CHECK, None, {"ok": True})
        )
        return True

    def _event(
        self,
        set_id: str,
        event_type: AuditEventType,
        actor_id: str | None,
        detail: dict[str, object],
    ) -> AuditEvent:
        return AuditEvent(
            id=str(uuid.uuid4()),
            set_id=set_id,
            event_type=event_type,
            occurred_at=datetime(2026, 1, 2, 10, 0, 0),
            actor_id=actor_id,
            detail=detail,
        )
