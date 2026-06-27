"""T009: domain entities and the atomic-visibility rule (FR-003) + retention (FR-007)."""

from __future__ import annotations

from datetime import datetime

import pytest

from docforge.domain.models import DocumentSet, SetStatus


def _set(status: SetStatus, uploaded: datetime) -> DocumentSet:
    return DocumentSet(
        id="s", team_id="t", uploaded_by="u", title="x", uploaded_at=uploaded, status=status
    )


@pytest.mark.parametrize(
    ("status", "viewable"),
    [
        (SetStatus.UPLOADING, False),
        (SetStatus.PROCESSING, False),
        (SetStatus.READY, True),
        (SetStatus.FAILED, False),
        (SetStatus.QUARANTINED, False),
    ],
)
def test_only_ready_sets_are_viewable(status: SetStatus, viewable: bool) -> None:
    assert _set(status, datetime(2026, 1, 1)).is_viewable is viewable


def test_retain_until_is_seven_years_after_upload() -> None:
    s = _set(SetStatus.READY, datetime(2026, 1, 2, 10, 0))
    assert s.retain_until.isoformat() == "2033-01-02"


def test_retain_until_handles_leap_day() -> None:
    s = _set(SetStatus.READY, datetime(2024, 2, 29, 10, 0))
    # 2031 is not a leap year -> clamps to Feb 28
    assert s.retain_until.isoformat() == "2031-02-28"
