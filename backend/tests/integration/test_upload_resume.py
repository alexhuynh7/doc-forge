"""T030: full US2 journey — resumable upload -> processing -> READY -> page viewable.

This is the end-to-end proof that US2 feeds US1: after a (resumed) upload finalizes,
the synchronous pipeline renders pages and the same page-serving endpoint from US1
returns a signed URL.
"""

from __future__ import annotations

import hashlib

from fastapi.testclient import TestClient

from tests.conftest import TEAM_ID


def _pdf(pages: int = 3) -> bytes:
    return b"%PDF-1.7 pages=" + str(pages).encode() + b" structural-drawings"


def test_resumable_upload_then_finalize_then_view_page(
    client: TestClient, member_headers: dict[str, str]
) -> None:
    data = _pdf(pages=3)

    # 1. Begin upload.
    create = client.post(
        "/v1/uploads",
        headers=member_headers,
        json={"team_id": TEAM_ID, "title": "Tower C", "filename": "tower-c.pdf",
              "total_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()},
    ).json()
    upload_id = create["id"]

    # 2. Upload first chunk, then "drop" and resume.
    half = len(data) // 2
    client.put(f"/v1/uploads/{upload_id}/parts", headers=member_headers, content=data[:half])
    progress = client.get(f"/v1/uploads/{upload_id}", headers=member_headers).json()
    assert progress["received_bytes"] == half  # resume point

    # 3. Resume with the remainder (no re-send of received bytes).
    client.put(f"/v1/uploads/{upload_id}/parts", headers=member_headers, content=data[half:])

    # 4. Finalize -> 202 processing (synchronously completed by the dispatcher).
    fin = client.post(f"/v1/uploads/{upload_id}/finalize", headers=member_headers)
    assert fin.status_code == 202
    set_id = fin.json()["id"]

    # 5. The set is now viewable in the team-scoped listing (atomic visibility).
    listing = client.get("/v1/document-sets", headers=member_headers).json()
    assert any(s["id"] == set_id for s in listing)

    # 6. Find the document and open a page via the US1 read path.
    detail = client.get(f"/v1/document-sets/{set_id}", headers=member_headers)
    assert detail.status_code == 200
    container = client.app.state.container
    doc = container.documents.list_for_set(set_id)[0]

    page = client.get(f"/v1/documents/{doc.id}/pages/2", headers=member_headers)
    assert page.status_code == 200
    assert "pages/2/display.webp" in page.json()["display_image_url"]
    # The 7-year retention was applied to the stored source on finalize.
    assert any(k.endswith("tower-c.pdf") for k in container.object_store.retention)
