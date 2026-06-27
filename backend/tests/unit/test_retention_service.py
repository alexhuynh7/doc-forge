"""T041: retention_service — deletion guard, expiry deletion, integrity (US3)."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from docforge.domain.errors import (
    AccessDeniedError,
    IntegrityError,
    RetentionLockedError,
)
from docforge.domain.models import (
    Document,
    DocumentSet,
    Membership,
    SetStatus,
)
from docforge.api.deps import Container

TEAM = "team-1"
USER = "user-1"
SET_ID = "set-1"


def _container_with_set() -> Container:
    c = Container.create()
    c.memberships.add(Membership(user_id=USER, team_id=TEAM))
    s = DocumentSet(
        id=SET_ID, team_id=TEAM, uploaded_by=USER, title="x",
        uploaded_at=datetime(2026, 1, 2, 10, 0), status=SetStatus.READY,
    )
    c.document_sets.add(s)
    source_key = f"sets/{SET_ID}/source/plan.pdf"
    data = b"%PDF plan bytes"
    sha = c.object_store.put_object(source_key, data, retain_until=s.retain_until)
    c.documents.add(
        Document(
            id="doc-1", set_id=SET_ID, filename="plan.pdf", size_bytes=len(data),
            page_count=1, source_object_key=source_key, sha256=sha,
        )
    )
    c.retention.register(s)
    return c


def test_delete_before_expiry_is_blocked_and_audited() -> None:
    c = _container_with_set()
    with pytest.raises(RetentionLockedError):
        c.retention.attempt_delete(SET_ID, USER, now=date(2026, 6, 1))
    events = [e.event_type.value for e in c.audit.list_for_set(SET_ID)]
    assert "deletion_attempt_blocked" in events
    assert c.document_sets.get(SET_ID) is not None  # still there


def test_non_member_cannot_delete() -> None:
    c = _container_with_set()
    with pytest.raises(AccessDeniedError):
        c.retention.attempt_delete(SET_ID, "outsider", now=date(2099, 1, 1))


def test_delete_after_expiry_succeeds_and_removes_blobs() -> None:
    c = _container_with_set()
    # Time has passed beyond the 7-year window: advance the store's Object Lock clock.
    c.object_store.set_now(int(datetime(2033, 2, 1, tzinfo=timezone.utc).timestamp()))
    c.retention.attempt_delete(SET_ID, USER, now=date(2033, 2, 1))  # > retain_until
    assert c.document_sets.get(SET_ID) is None
    assert c.documents.list_for_set(SET_ID) == []
    assert c.object_store.get_object(f"sets/{SET_ID}/source/plan.pdf") is None
    events = [e.event_type.value for e in c.audit.list_for_set(SET_ID)]
    assert "deleted_after_expiry" in events


def test_verify_integrity_passes_for_intact_content() -> None:
    c = _container_with_set()
    assert c.retention.verify_integrity(SET_ID) is True


def test_verify_integrity_fails_on_corruption() -> None:
    c = _container_with_set()
    # Corrupt the stored bytes behind the recorded checksum.
    c.object_store.put_object(f"sets/{SET_ID}/source/plan.pdf", b"tampered")
    with pytest.raises(IntegrityError):
        c.retention.verify_integrity(SET_ID)
