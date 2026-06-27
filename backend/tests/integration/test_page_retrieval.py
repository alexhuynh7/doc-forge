"""T020: page retrieval is access-gated and lists are team-scoped (FR-013/FR-015)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_member_sees_only_their_teams_sets(
    client: TestClient, member_headers: dict[str, str]
) -> None:
    r = client.get("/v1/document-sets", headers=member_headers)
    assert r.status_code == 200
    sets = r.json()
    assert len(sets) == 1
    assert sets[0]["id"] == "set-1"
    assert sets[0]["retain_until"] == "2033-01-02"  # 7-year retention surfaced


def test_outsider_sees_no_sets(client: TestClient, outsider_headers: dict[str, str]) -> None:
    r = client.get("/v1/document-sets", headers=outsider_headers)
    assert r.status_code == 200
    assert r.json() == []


def test_outsider_cannot_open_set_detail(
    client: TestClient, outsider_headers: dict[str, str]
) -> None:
    r = client.get("/v1/document-sets/set-1", headers=outsider_headers)
    assert r.status_code == 403


def test_member_page_round_trip_returns_signed_url(
    client: TestClient, member_headers: dict[str, str]
) -> None:
    r = client.get("/v1/documents/doc-1/pages/312", headers=member_headers)
    assert r.status_code == 200
    # Read path never exposes the 2.1GB source; only a signed page artifact URL.
    assert "source.pdf" not in r.json()["display_image_url"]
    assert "display.webp" in r.json()["display_image_url"]


def test_metrics_record_page_opens(client: TestClient, member_headers: dict[str, str]) -> None:
    client.get("/v1/documents/doc-1/pages/312", headers=member_headers)
    snap = client.get("/metrics").json()
    assert snap["page_open_total"] >= 1
    assert snap["page_open_p_within_2s"] == 1.0  # in-memory resolve is well under 2s
