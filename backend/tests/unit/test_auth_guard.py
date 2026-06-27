"""C5 regression: dev auth is fail-closed — disabling it blocks all requests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def test_disabling_dev_auth_blocks_requests(
    client: TestClient, member_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Settings reads env per-construction, and get_current_user_id reads settings
    # per-request, so flipping the env mid-test takes effect immediately.
    monkeypatch.setenv("DOCFORGE_DEV_AUTH", "false")
    r = client.get("/v1/documents/doc-1/pages/312", headers=member_headers)
    assert r.status_code == 503
    assert "dev auth disabled" in r.json()["detail"].lower()


def test_dev_auth_enabled_by_default(
    client: TestClient, member_headers: dict[str, str]
) -> None:
    r = client.get("/v1/documents/doc-1/pages/312", headers=member_headers)
    assert r.status_code == 200
