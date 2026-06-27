"""Framework-free domain errors.

These carry no HTTP/framework concepts; the API layer maps them to responses
(see docforge.api.errors). Keeping them here preserves the layering mandated by
the constitution (Principle III).
"""

from __future__ import annotations


class DomainError(Exception):
    """Base class for all domain-level errors."""


class NotFoundError(DomainError):
    """A requested entity does not exist (or is not visible to the caller)."""


class AccessDeniedError(DomainError):
    """Caller is not a member of the team that owns the resource (FR-013/FR-015)."""


class NotReadyError(DomainError):
    """The requested artifact is not yet available (still processing).

    Carries the per-page processing status so the API can communicate it (FR-011).
    """

    def __init__(self, status: str, message: str = "Resource is still processing") -> None:
        super().__init__(message)
        self.status = status


class IntegrityError(DomainError):
    """Stored content failed checksum verification (FR-006)."""


class RetentionLockedError(DomainError):
    """Deletion attempted before the 7-year retention window elapsed (FR-007)."""


class InvalidDocumentError(DomainError):
    """Uploaded content is not a valid, processable document (FR-012)."""
