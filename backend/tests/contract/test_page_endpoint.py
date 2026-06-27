"""T019: contract test for GET /v1/documents/{id}/pages/{n} (contracts/openapi.yaml)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_200_returns_pageview_shape(client: TestClient, member_headers: dict[str, str]) -> None:
    r = client.get("/v1/documents/doc-1/pages/312", headers=member_headers)
    assert r.status_code == 200
    body = r.json()
    for key in (
        "document_id",
        "page_number",
        "width_px",
        "height_px",
        "display_image_url",
        "url_expires_at",
    ):
        assert key in body
    assert body["page_number"] == 312


def test_202_when_page_still_processing(client: TestClient, member_headers: dict[str, str]) -> None:
    r = client.get("/v1/documents/doc-1/pages/999", headers=member_headers)
    assert r.status_code == 202
    assert r.json()["status"] == "pending"


def test_403_for_non_member(client: TestClient, outsider_headers: dict[str, str]) -> None:
    r = client.get("/v1/documents/doc-1/pages/312", headers=outsider_headers)
    assert r.status_code == 403


def test_404_for_unknown_page(client: TestClient, member_headers: dict[str, str]) -> None:
    r = client.get("/v1/documents/doc-1/pages/123456", headers=member_headers)
    assert r.status_code == 404


def test_401_without_token(client: TestClient) -> None:
    r = client.get("/v1/documents/doc-1/pages/312")
    assert r.status_code == 401
