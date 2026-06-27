"""Team-based access control (FR-013/FR-015).

Authorization is checked here, in the service layer, on every list and every page
retrieval. Possession of a (later, signed) artifact URL never bypasses this — the
URL is only minted after this check passes.
"""

from __future__ import annotations

from docforge.domain.errors import AccessDeniedError
from docforge.repositories.interfaces import MembershipRepository


class AccessService:
    def __init__(self, memberships: MembershipRepository) -> None:
        self._memberships = memberships

    def is_member(self, user_id: str, team_id: str) -> bool:
        return self._memberships.is_member(user_id, team_id)

    def assert_member(self, user_id: str, team_id: str) -> None:
        if not self._memberships.is_member(user_id, team_id):
            raise AccessDeniedError(
                f"User {user_id} is not a member of team {team_id}"
            )
