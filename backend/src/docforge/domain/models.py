"""Framework-free domain entities and rules (data-model.md).

Pure Python: no FastAPI, SQLAlchemy, or boto3 imports. The DocumentSet status
machine encodes the atomic-visibility rule (FR-003): a set is viewable only when
``READY``.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import date, datetime

RETENTION_YEARS = 7


class SetStatus(str, enum.Enum):
    UPLOADING = "uploading"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    QUARANTINED = "quarantined"


class PageStatus(str, enum.Enum):
    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"


class ArtifactKind(str, enum.Enum):
    DISPLAY_IMAGE = "display_image"
    THUMBNAIL = "thumbnail"
    DZI_DESCRIPTOR = "dzi_descriptor"
    TILE = "tile"


class Role(str, enum.Enum):
    MEMBER = "member"
    ADMIN = "admin"


class UploadStatus(str, enum.Enum):
    ACTIVE = "active"
    FINALIZED = "finalized"
    ABORTED = "aborted"


class AuditEventType(str, enum.Enum):
    UPLOAD_ACCEPTED = "upload_accepted"
    PROCESSING_COMPLETED = "processing_completed"
    DELETION_ATTEMPT_BLOCKED = "deletion_attempt_blocked"
    DELETED_AFTER_EXPIRY = "deleted_after_expiry"
    INTEGRITY_CHECK = "integrity_check"


@dataclass(frozen=True)
class Team:
    id: str
    name: str


@dataclass(frozen=True)
class User:
    id: str
    email: str


@dataclass(frozen=True)
class Membership:
    user_id: str
    team_id: str
    role: Role = Role.MEMBER


@dataclass
class DocumentSet:
    id: str
    team_id: str
    uploaded_by: str
    title: str
    uploaded_at: datetime
    status: SetStatus = SetStatus.UPLOADING
    document_count: int = 0
    ready_at: datetime | None = None
    failure_reason: str | None = None

    @property
    def is_viewable(self) -> bool:
        """Atomic visibility: only READY sets are listable/viewable (FR-003)."""
        return self.status is SetStatus.READY

    @property
    def retain_until(self) -> date:
        """Earliest permissible deletion date (FR-007)."""
        u = self.uploaded_at.date()
        try:
            return u.replace(year=u.year + RETENTION_YEARS)
        except ValueError:  # Feb 29 -> Feb 28
            return u.replace(year=u.year + RETENTION_YEARS, day=28)


@dataclass
class Document:
    id: str
    set_id: str
    filename: str
    size_bytes: int
    page_count: int
    source_object_key: str
    sha256: str
    order_index: int = 0


@dataclass
class Page:
    id: str
    document_id: str
    page_number: int
    width_px: int = 0
    height_px: int = 0
    status: PageStatus = PageStatus.PENDING


@dataclass
class PageArtifact:
    id: str
    page_id: str
    kind: ArtifactKind
    object_key: str
    sha256: str
    bytes: int = 0
    level: int | None = None


@dataclass
class UploadSession:
    """A resumable upload in progress (FR-002). ``received`` simulates the bytes
    accumulated by direct-to-object-store part uploads; ``received_bytes`` drives
    resume."""

    id: str
    team_id: str
    created_by: str
    title: str
    filename: str
    declared_total_bytes: int
    declared_sha256: str
    status: UploadStatus = UploadStatus.ACTIVE
    received: bytearray = field(default_factory=bytearray)

    @property
    def received_bytes(self) -> int:
        return len(self.received)

    @property
    def is_complete(self) -> bool:
        return self.received_bytes == self.declared_total_bytes


@dataclass
class RetentionRecord:
    """Durability/compliance mirror of the storage-layer Object Lock (FR-007/008)."""

    set_id: str
    retain_until: date
    object_lock_mode: str = "compliance"
    legal_hold: bool = False


@dataclass
class AuditEvent:
    id: str
    set_id: str
    event_type: AuditEventType
    occurred_at: datetime
    actor_id: str | None = None
    detail: dict[str, object] = field(default_factory=dict)
