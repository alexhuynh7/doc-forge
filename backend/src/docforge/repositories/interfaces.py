"""Persistence and storage abstractions (data-model.md, plan.md R8).

Services depend only on these Protocols, never on SQLAlchemy/boto3. This is what
makes the domain/services unit-testable and the storage vendors swappable
(Constitution Principle III). Concrete implementations live under
``repositories/memory.py`` (MVP/tests) and would live under
``repositories/sqlalchemy/`` and ``repositories/object_store/`` in production.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from dataclasses import dataclass
from datetime import date

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


@runtime_checkable
class MembershipRepository(Protocol):
    def is_member(self, user_id: str, team_id: str) -> bool: ...
    def list_teams_for_user(self, user_id: str) -> list[str]: ...
    def add(self, membership: Membership) -> None: ...


@runtime_checkable
class DocumentSetRepository(Protocol):
    def get(self, set_id: str) -> DocumentSet | None: ...
    def list_for_teams(self, team_ids: list[str]) -> list[DocumentSet]: ...
    def add(self, document_set: DocumentSet) -> None: ...
    def delete(self, set_id: str) -> None: ...


@runtime_checkable
class DocumentRepository(Protocol):
    def get(self, document_id: str) -> Document | None: ...
    def list_for_set(self, set_id: str) -> list[Document]: ...
    def add(self, document: Document) -> None: ...
    def delete_for_set(self, set_id: str) -> None: ...


@runtime_checkable
class PageRepository(Protocol):
    def get_by_number(self, document_id: str, page_number: int) -> Page | None: ...
    def add(self, page: Page) -> None: ...


@runtime_checkable
class PageArtifactRepository(Protocol):
    def list_for_page(self, page_id: str) -> list[PageArtifact]: ...
    def add(self, artifact: PageArtifact) -> None: ...


@runtime_checkable
class UploadSessionRepository(Protocol):
    def get(self, session_id: str) -> UploadSession | None: ...
    def add(self, session: UploadSession) -> None: ...


@runtime_checkable
class AuditRepository(Protocol):
    def add(self, event: AuditEvent) -> None: ...
    def list_for_set(self, set_id: str) -> list[AuditEvent]: ...


@runtime_checkable
class RetentionRepository(Protocol):
    def get(self, set_id: str) -> RetentionRecord | None: ...
    def add(self, record: RetentionRecord) -> None: ...
    def delete(self, set_id: str) -> None: ...


@runtime_checkable
class ObjectStoreGateway(Protocol):
    """Blob storage abstraction. Page reads only ever call ``signed_url`` —
    the source PDF is never fetched on the read path (Constitution Principle I)."""

    def signed_url(self, object_key: str, ttl_seconds: int = 300) -> tuple[str, int]:
        """Return (url, expires_at_epoch) for a short-lived, access-checked fetch."""
        ...

    def put_object(
        self, object_key: str, data: bytes, retain_until: date | None = None
    ) -> str:
        """Store bytes (optionally under retention/Object Lock) and return SHA-256."""
        ...

    def get_object(self, object_key: str) -> bytes | None:
        """Fetch stored bytes (used by workers to read the source PDF — never on
        the page read path)."""
        ...

    def delete_object(self, object_key: str) -> None:
        """Delete an object. MUST raise if the object is still within its Object
        Lock retention window (Constitution Principle IV backstop)."""
        ...


@dataclass(frozen=True)
class RenderedPage:
    width_px: int
    height_px: int
    display_image: bytes
    dzi_descriptor: bytes


@runtime_checkable
class PageRenderer(Protocol):
    """Abstraction over PDF rasterization/tiling (production: PyMuPDF + libvips)."""

    def is_valid_pdf(self, data: bytes) -> bool: ...
    def page_count(self, data: bytes) -> int: ...
    def render_page(self, data: bytes, page_number: int) -> RenderedPage: ...


@runtime_checkable
class TaskDispatcher(Protocol):
    """Abstraction over the async queue (production: Celery on Redis)."""

    def dispatch_process_document_set(self, set_id: str) -> None: ...
