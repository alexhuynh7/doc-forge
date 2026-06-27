"""T029: contract tests for the upload endpoints (contracts/openapi.yaml)."""

from __future__ import annotations

import hashlib

from fastapi.testclient import TestClient

# Reuse the seeded member/team from conftest.
from tests.conftest import TEAM_ID


def _pdf(pages: int = 2) -> bytes:
    return b"%PDF-1.7 pages=" + str(pages).encode() + b" body"


def test_create_upload_returns_session_201(
    client: TestClient, member_headers: dict[str, str]
) -> None:
    data = _pdf()
    r = client.post(
        "/v1/uploads",
        headers=member_headers,
        json={
            "team_id": TEAM_ID,
            "title": "New Set",
            "filename": "plan.pdf",
            "total_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["received_bytes"] == 0
    assert body["total_bytes"] == len(data)
    assert body["part_urls"]


def test_create_upload_forbidden_for_non_member(
    client: TestClient, outsider_headers: dict[str, str]
) -> None:
    r = client.post(
        "/v1/uploads",
        headers=outsider_headers,
        json={"team_id": TEAM_ID, "title": "x", "filename": "f.pdf",
              "total_bytes": 1, "sha256": "0" * 64},
    )
    assert r.status_code == 403


def test_finalize_checksum_mismatch_409(
    client: TestClient, member_headers: dict[str, str]
) -> None:
    data = _pdf()
    create = client.post(
        "/v1/uploads",
        headers=member_headers,
        json={"team_id": TEAM_ID, "title": "x", "filename": "f.pdf",
              "total_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()},
    ).json()
    # Upload wrong bytes of the right length.
    client.put(
        f"/v1/uploads/{create['id']}/parts",
        headers=member_headers,
        content=b"Z" * len(data),
    )
    r = client.post(f"/v1/uploads/{create['id']}/finalize", headers=member_headers)
    assert r.status_code == 409  # IntegrityError -> 409
