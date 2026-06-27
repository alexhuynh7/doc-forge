"""In-memory repository + object-store implementations.

Used for unit/integration tests and local runs of the MVP slice. They satisfy the
same Protocols as the production SQLAlchemy/S3 adapters, so services are identical
regardless of backend (Constitution Principle III).
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone

from docforge.domain.errors import RetentionLockedError
from docforge.domain.models import (
    AuditEvent,
    Document,
    DocumentSet,
    Membership,
    Page,
    PageArtifact,
    RetentionRecord,
    UploadSession,
)
from docforge.repositories.interfaces import RenderedPage


class InMemoryMembershipRepository:
    def __init__(self) -> None:
        self._memberships: set[tuple[str, str]] = set()

    def is_member(self, user_id: str, team_id: str) -> bool:
        return (user_id, team_id) in self._memberships

    def list_teams_for_user(self, user_id: str) -> list[str]:
        return [team_id for (uid, team_id) in self._memberships if uid == user_id]

    def add(self, membership: Membership) -> None:
        self._memberships.add((membership.user_id, membership.team_id))


class InMemoryDocumentSetRepository:
    def __init__(self) -> None:
        self._sets: dict[str, DocumentSet] = {}

    def get(self, set_id: str) -> DocumentSet | None:
        return self._sets.get(set_id)

    def list_for_teams(self, team_ids: list[str]) -> list[DocumentSet]:
        teams = set(team_ids)
        # Only READY sets are listable (atomic visibility, FR-003).
        return [s for s in self._sets.values() if s.team_id in teams and s.is_viewable]

    def add(self, document_set: DocumentSet) -> None:
        self._sets[document_set.id] = document_set

    def delete(self, set_id: str) -> None:
        self._sets.pop(set_id, None)


class InMemoryDocumentRepository:
    def __init__(self) -> None:
        self._docs: dict[str, Document] = {}

    def get(self, document_id: str) -> Document | None:
        return self._docs.get(document_id)

    def list_for_set(self, set_id: str) -> list[Document]:
        return [d for d in self._docs.values() if d.set_id == set_id]

    def add(self, document: Document) -> None:
        self._docs[document.id] = document

    def delete_for_set(self, set_id: str) -> None:
        for doc_id in [d.id for d in self._docs.values() if d.set_id == set_id]:
            del self._docs[doc_id]


class InMemoryPageRepository:
    def __init__(self) -> None:
        # keyed by (document_id, page_number) — the hot lookup (data-model.md)
        self._pages: dict[tuple[str, int], Page] = {}

    def get_by_number(self, document_id: str, page_number: int) -> Page | None:
        return self._pages.get((document_id, page_number))

    def add(self, page: Page) -> None:
        self._pages[(page.document_id, page.page_number)] = page


class InMemoryPageArtifactRepository:
    def __init__(self) -> None:
        self._artifacts: dict[str, list[PageArtifact]] = {}

    def list_for_page(self, page_id: str) -> list[PageArtifact]:
        return list(self._artifacts.get(page_id, []))

    def add(self, artifact: PageArtifact) -> None:
        self._artifacts.setdefault(artifact.page_id, []).append(artifact)


class InMemoryUploadSessionRepository:
    def __init__(self) -> None:
        self._sessions: dict[str, UploadSession] = {}

    def get(self, session_id: str) -> UploadSession | None:
        return self._sessions.get(session_id)

    def add(self, session: UploadSession) -> None:
        self._sessions[session.id] = session


class InMemoryAuditRepository:
    def __init__(self) -> None:
        self._events: list[AuditEvent] = []

    def add(self, event: AuditEvent) -> None:
        self._events.append(event)

    def list_for_set(self, set_id: str) -> list[AuditEvent]:
        return [e for e in self._events if e.set_id == set_id]


class InMemoryRetentionRepository:
    def __init__(self) -> None:
        self._records: dict[str, RetentionRecord] = {}

    def get(self, set_id: str) -> RetentionRecord | None:
        return self._records.get(set_id)

    def add(self, record: RetentionRecord) -> None:
        self._records[record.set_id] = record

    def delete(self, set_id: str) -> None:
        self._records.pop(set_id, None)


class FakeObjectStore:
    """Deterministic signed-URL generator + byte store standing in for an
    S3-compatible store with Object Lock.

    Mirrors the production contract: page reads resolve to a short-lived signed URL
    and never touch the source PDF (Constitution Principle I); writes record a
    retain_until to mirror Object Lock (Constitution Principle IV).
    """

    def __init__(self, base_url: str = "https://cdn.local", clock_epoch: int = 1_750_000_000):
        self._base = base_url.rstrip("/")
        self._now = clock_epoch  # injectable clock keeps tests deterministic
        self._objects: dict[str, bytes] = {}
        self.retention: dict[str, date] = {}

    def set_now(self, clock_epoch: int) -> None:
        """Advance the fake's wall clock (simulates time passing for retention)."""
        self._now = clock_epoch

    def signed_url(self, object_key: str, ttl_seconds: int = 300) -> tuple[str, int]:
        expires_at = self._now + ttl_seconds
        sig = hashlib.sha256(f"{object_key}:{expires_at}".encode()).hexdigest()[:16]
        url = f"{self._base}/{object_key}?expires={expires_at}&sig={sig}"
        return url, expires_at

    def put_object(
        self, object_key: str, data: bytes, retain_until: date | None = None
    ) -> str:
        self._objects[object_key] = bytes(data)
        if retain_until is not None:
            self.retention[object_key] = retain_until
        return hashlib.sha256(data).hexdigest()

    def get_object(self, object_key: str) -> bytes | None:
        return self._objects.get(object_key)

    def delete_object(self, object_key: str) -> None:
        # Object Lock (Compliance) backstop: refuse deletion while retained (FR-007).
        retain_until = self.retention.get(object_key)
        if retain_until is not None:
            today = datetime.fromtimestamp(self._now, tz=timezone.utc).date()
            if today < retain_until:
                raise RetentionLockedError(
                    f"{object_key} is under retention until {retain_until.isoformat()}"
                )
        self._objects.pop(object_key, None)
        self.retention.pop(object_key, None)


class FakePageRenderer:
    """Stand-in for PyMuPDF/libvips. Valid PDFs start with ``%PDF``; page count is
    read from a ``pages=N`` marker in the bytes (default 1) so tests can control it."""

    def is_valid_pdf(self, data: bytes) -> bool:
        return data.startswith(b"%PDF")

    def page_count(self, data: bytes) -> int:
        marker = b"pages="
        idx = data.find(marker)
        if idx == -1:
            return 1
        digits = bytearray()
        for b in data[idx + len(marker) :]:
            if 48 <= b <= 57:
                digits.append(b)
            else:
                break
        return int(digits) if digits else 1

    def render_page(self, data: bytes, page_number: int) -> RenderedPage:
        return RenderedPage(
            width_px=4000,
            height_px=3000,
            display_image=f"display:{page_number}".encode(),
            dzi_descriptor=f"dzi:{page_number}".encode(),
        )
