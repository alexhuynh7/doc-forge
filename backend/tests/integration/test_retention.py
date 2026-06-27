"""T040: retention via the API — deletion blocked (423) and audited (US3, FR-007/008).

The seeded set (conftest) was uploaded 2026-01-02, so its 7-year window is active for
"today" — the API delete must be blocked. The post-expiry success path is exercised at
the service level in test_retention_service.py (it requires a future clock).
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_delete_within_retention_window_returns_423(
    client: TestClient, member_headers: dict[str, str]
) -> None:
    r = client.delete("/v1/document-sets/set-1", headers=member_headers)
    assert r.status_code == 423
    assert r.json()["code"] == "retention_locked"
    # The set is still present and viewable.
    listing = client.get("/v1/document-sets", headers=member_headers).json()
    assert any(s["id"] == "set-1" for s in listing)


def test_delete_audits_the_blocked_attempt(
    client: TestClient, member_headers: dict[str, str]
) -> None:
    client.delete("/v1/document-sets/set-1", headers=member_headers)
    audit = client.app.state.container.audit.list_for_set("set-1")
    assert any(e.event_type.value == "deletion_attempt_blocked" for e in audit)


def test_outsider_delete_is_forbidden(
    client: TestClient, outsider_headers: dict[str, str]
) -> None:
    r = client.delete("/v1/document-sets/set-1", headers=outsider_headers)
    assert r.status_code == 403
