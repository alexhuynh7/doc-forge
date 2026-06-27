"""FastAPI application assembly (T016).

Wires the DI container, registers domain-error handlers, and mounts routers. The
container is created once and injected via ``dependency_overrides`` so tests can
substitute their own seeded container.
"""

from __future__ import annotations

from fastapi import FastAPI

from docforge.api.deps import Container, get_container
from docforge.api.errors import register_error_handlers
from docforge.api.routers import document_sets, health, pages, uploads


def create_app(container: Container | None = None) -> FastAPI:
    app = FastAPI(title="Doc-Forge API", version="0.1.0")
    register_error_handlers(app)
    app.include_router(health.router)
    app.include_router(pages.router, prefix="/v1")
    app.include_router(document_sets.router, prefix="/v1")
    app.include_router(uploads.router, prefix="/v1")

    resolved = container or Container.create()
    app.dependency_overrides[get_container] = lambda: resolved
    app.state.container = resolved
    return app


app = create_app()
