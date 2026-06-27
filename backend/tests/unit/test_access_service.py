"""T017: team-based access control (FR-013/FR-015)."""

from __future__ import annotations

import pytest

from docforge.domain.errors import AccessDeniedError
from docforge.domain.models import Membership
from docforge.repositories.memory import InMemoryMembershipRepository
from docforge.services.access_service import AccessService


@pytest.fixture
def access() -> AccessService:
    repo = InMemoryMembershipRepository()
    repo.add(Membership(user_id="u1", team_id="t1"))
    return AccessService(repo)


def test_member_passes(access: AccessService) -> None:
    assert access.is_member("u1", "t1") is True
    access.assert_member("u1", "t1")  # no raise


def test_non_member_is_denied(access: AccessService) -> None:
    assert access.is_member("u2", "t1") is False
    with pytest.raises(AccessDeniedError):
        access.assert_member("u2", "t1")


def test_member_of_other_team_is_denied(access: AccessService) -> None:
    with pytest.raises(AccessDeniedError):
        access.assert_member("u1", "t2")
