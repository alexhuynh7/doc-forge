"""Metrics + observability (T051, Constitution Principle V).

Exposes the signals needed to drive autoscaling and to detect breaches of the
sub-2s budget: page-open latency, ingest/queue depth, throughput, and processing
success rate. This is a dependency-free in-process registry for the MVP; in
production it would export to Prometheus/OpenTelemetry.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field


@dataclass
class _Histogram:
    count: int = 0
    total: float = 0.0
    buckets: dict[float, int] = field(
        default_factory=lambda: {0.5: 0, 1.0: 0, 2.0: 0, 5.0: 0}
    )

    def observe(self, value: float) -> None:
        self.count += 1
        self.total += value
        for upper in sorted(self.buckets):
            if value <= upper:
                self.buckets[upper] += 1

    def within(self, threshold: float) -> int:
        # Buckets are cumulative (observe() bumps every bound >= value), so the
        # count within `threshold` is the single bucket for the smallest bound
        # >= threshold — not a sum across buckets.
        for upper in sorted(self.buckets):
            if upper >= threshold:
                return self.buckets[upper]
        return self.count


class Metrics:
    """Thread-safe in-process metrics registry."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.page_open_latency = _Histogram()
        self.counters: dict[str, int] = {
            "page_open_total": 0,
            "ingest_accepted_total": 0,
            "ingest_lost_total": 0,
            "sets_processed_total": 0,
            "sets_failed_total": 0,
        }
        self.queue_depth = 0

    def observe_page_open(self, seconds: float) -> None:
        with self._lock:
            self.page_open_latency.observe(seconds)
            self.counters["page_open_total"] += 1

    def inc(self, name: str, amount: int = 1) -> None:
        with self._lock:
            self.counters[name] = self.counters.get(name, 0) + amount

    def set_queue_depth(self, depth: int) -> None:
        with self._lock:
            self.queue_depth = depth

    def processing_success_rate(self) -> float:
        ok = self.counters["sets_processed_total"]
        bad = self.counters["sets_failed_total"]
        total = ok + bad
        return 1.0 if total == 0 else ok / total

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "page_open_total": self.counters["page_open_total"],
                "page_open_p_within_2s": (
                    self.page_open_latency.within(2.0) / self.page_open_latency.count
                    if self.page_open_latency.count
                    else None
                ),
                "queue_depth": self.queue_depth,
                "ingest_accepted_total": self.counters["ingest_accepted_total"],
                "ingest_lost_total": self.counters["ingest_lost_total"],
                "processing_success_rate": self.processing_success_rate(),
            }


# Module-level singleton used by the app + routers.
METRICS = Metrics()
