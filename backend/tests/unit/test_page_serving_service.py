"""T021: page_serving_service — resolve, access denial, and processing states."""

from __future__ import annotations

import pytest

from docforge.api.deps import Container
from docforge.domain.errors import AccessDeniedError, NotFoundError, NotReadyError
from tests.conftest import DOC_ID, MEMBER_ID, OUTSIDER_ID, _seed


@pytest.fixture
def container() -> Container:
    c = Container.create()
    _seed(c)
    return c


def test_resolves_ready_page_to_signed_urls(container: Container) -> None:
    view = container.page_serving.get_page_view(DOC_ID, 312, MEMBER_ID)
    assert view.page_number == 312
    assert view.width_px == 4000
    assert view.display_image_url.startswith("https://cdn.local/")
    assert "sig=" in view.display_image_url and "expires=" in view.display_image_url
    assert view.dzi_url is not None
    assert view.url_expires_at > 0


def test_outsider_is_denied_before_url_minting(container: Container) -> None:
    with pytest.raises(AccessDeniedError):
        container.page_serving.get_page_view(DOC_ID, 312, OUTSIDER_ID)


def test_pending_page_raises_not_ready(container: Container) -> None:
    with pytest.raises(NotReadyError) as exc:
        container.page_serving.get_page_view(DOC_ID, 999, MEMBER_ID)
    assert exc.value.status == "pending"


def test_missing_page_raises_not_found(container: Container) -> None:
    with pytest.raises(NotFoundError):
        container.page_serving.get_page_view(DOC_ID, 100000, MEMBER_ID)


def test_missing_document_raises_not_found(container: Container) -> None:
    with pytest.raises(NotFoundError):
        container.page_serving.get_page_view("no-such-doc", 1, MEMBER_ID)


def test_ready_page_in_non_viewable_set_is_not_served(container: Container) -> None:
    # C2 regression: a READY page must not be servable while its set isn't READY
    # (atomic visibility, FR-003). Flip the seeded set to PROCESSING.
    from docforge.domain.models import SetStatus

    document = container.documents.get(DOC_ID)
    document_set = container.document_sets.get(document.set_id)
    document_set.status = SetStatus.PROCESSING

    with pytest.raises(NotReadyError) as exc:
        container.page_serving.get_page_view(DOC_ID, 312, MEMBER_ID)
    assert exc.value.status == "processing"
