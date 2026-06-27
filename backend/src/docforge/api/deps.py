"""Dependency injection wiring (T016).

A single ``Container`` holds the repositories, object store, and services. The MVP
wires in-memory implementations; swapping to SQLAlchemy/S3 means changing only this
wiring, not the services or routers (Constitution Principle III).

Auth: a minimal bearer-token dependency resolves the caller's user id. In production
this validates a JWT; here it trusts an ``Authorization: Bearer <user_id>`` header so
the read path and access checks are exercisable end-to-end in tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Header, HTTPException

from docforge.config import Settings, get_settings
from docforge.observability import METRICS, Metrics
from docforge.repositories.memory import (
    FakeObjectStore,
    FakePageRenderer,
    InMemoryAuditRepository,
    InMemoryDocumentRepository,
    InMemoryDocumentSetRepository,
    InMemoryMembershipRepository,
    InMemoryPageArtifactRepository,
    InMemoryPageRepository,
    InMemoryRetentionRepository,
    InMemoryUploadSessionRepository,
)
from docforge.services.access_service import AccessService
from docforge.services.ingestion_service import IngestionService
from docforge.services.page_serving_service import PageServingService
from docforge.services.retention_service import RetentionService
from docforge.workers.dispatcher import SynchronousDispatcher
from docforge.workers.processing import ProcessingPipeline


@dataclass
class Container:
    settings: Settings
    metrics: Metrics
    memberships: InMemoryMembershipRepository
    document_sets: InMemoryDocumentSetRepository
    documents: InMemoryDocumentRepository
    pages: InMemoryPageRepository
    artifacts: InMemoryPageArtifactRepository
    sessions: InMemoryUploadSessionRepository
    audit: InMemoryAuditRepository
    retention_repo: InMemoryRetentionRepository
    object_store: FakeObjectStore
    renderer: FakePageRenderer
    access: AccessService
    page_serving: PageServingService
    pipeline: ProcessingPipeline
    ingestion: IngestionService
    retention: RetentionService

    @classmethod
    def create(cls, settings: Settings | None = None) -> "Container":
        settings = settings or get_settings()
        metrics = METRICS
        memberships = InMemoryMembershipRepository()
        document_sets = InMemoryDocumentSetRepository()
        documents = InMemoryDocumentRepository()
        pages = InMemoryPageRepository()
        artifacts = InMemoryPageArtifactRepository()
        sessions = InMemoryUploadSessionRepository()
        audit = InMemoryAuditRepository()
        retention_repo = InMemoryRetentionRepository()
        object_store = FakeObjectStore(base_url=settings.cdn_base_url)
        renderer = FakePageRenderer()
        access = AccessService(memberships)
        page_serving = PageServingService(
            documents=documents,
            document_sets=document_sets,
            pages=pages,
            artifacts=artifacts,
            object_store=object_store,
            access=access,
        )
        pipeline = ProcessingPipeline(
            document_sets=document_sets,
            documents=documents,
            pages=pages,
            artifacts=artifacts,
            audit=audit,
            object_store=object_store,
            renderer=renderer,
            metrics=metrics,
        )
        ingestion = IngestionService(
            sessions=sessions,
            document_sets=document_sets,
            documents=documents,
            audit=audit,
            retention=retention_repo,
            object_store=object_store,
            dispatcher=SynchronousDispatcher(pipeline),
            access=access,
            metrics=metrics,
        )
        retention = RetentionService(
            document_sets=document_sets,
            documents=documents,
            pages=pages,
            artifacts=artifacts,
            retention=retention_repo,
            audit=audit,
            object_store=object_store,
            access=access,
        )
        return cls(
            settings=settings,
            metrics=metrics,
            memberships=memberships,
            document_sets=document_sets,
            documents=documents,
            pages=pages,
            artifacts=artifacts,
            sessions=sessions,
            audit=audit,
            retention_repo=retention_repo,
            object_store=object_store,
            renderer=renderer,
            access=access,
            page_serving=page_serving,
            pipeline=pipeline,
            ingestion=ingestion,
            retention=retention,
        )


def get_container() -> Container:
    """Overridden in tests and at app startup via ``app.dependency_overrides``."""
    raise RuntimeError("Container not configured; set dependency_overrides[get_container]")


def get_current_user_id(
    authorization: Annotated[str | None, Header()] = None,
) -> str:
    # Fail closed: the dev token shortcut must be explicitly enabled (C5). In
    # production (DOCFORGE_DEV_AUTH=false) this raises until a real JWT verifier
    # is wired, so `Bearer <user_id>` impersonation can never silently ship.
    if not get_settings().dev_auth_enabled:
        raise HTTPException(
            status_code=503,
            detail="Authentication not configured (dev auth disabled)",
        )
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    return authorization.split(" ", 1)[1].strip()
