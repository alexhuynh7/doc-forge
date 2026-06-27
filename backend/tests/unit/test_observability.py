"""T051: metrics registry behavior (Constitution Principle V)."""

from __future__ import annotations

from docforge.observability import Metrics


def test_page_open_latency_within_2s_ratio() -> None:
    m = Metrics()
    for s in [0.1, 0.5, 1.2, 1.9, 3.0]:  # 4 of 5 within 2s
        m.observe_page_open(s)
    snap = m.snapshot()
    assert snap["page_open_total"] == 5
    assert snap["page_open_p_within_2s"] == 4 / 5


def test_processing_success_rate() -> None:
    m = Metrics()
    assert m.processing_success_rate() == 1.0  # no data -> 100%
    m.inc("sets_processed_total", 9)
    m.inc("sets_failed_total", 1)
    assert m.processing_success_rate() == 0.9


def test_queue_depth_tracked() -> None:
    m = Metrics()
    m.set_queue_depth(42)
    assert m.snapshot()["queue_depth"] == 42
