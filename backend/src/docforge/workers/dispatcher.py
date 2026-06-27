"""Task dispatchers (TaskDispatcher implementations).

``SynchronousDispatcher`` runs the pipeline inline — ideal for tests and local dev
and lets the upload→ready flow be verified end-to-end without a broker. In
production a ``CeleryDispatcher`` would enqueue ``process_document_set`` onto Redis
(deferred); the ingestion service depends only on the TaskDispatcher Protocol, so
swapping is a one-line wiring change (Constitution Principle III/V).
"""

from __future__ import annotations

from docforge.workers.processing import ProcessingPipeline


class SynchronousDispatcher:
    def __init__(self, pipeline: ProcessingPipeline) -> None:
        self._pipeline = pipeline

    def dispatch_process_document_set(self, set_id: str) -> None:
        self._pipeline.process_document_set(set_id)
