"""Map framework-free domain errors to HTTP responses (T015).

Keeps HTTP concerns out of the service/domain layers (Constitution Principle III).
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from docforge.domain.errors import (
    AccessDeniedError,
    IntegrityError,
    InvalidDocumentError,
    NotFoundError,
    NotReadyError,
    RetentionLockedError,
)


def _error(code: str, message: str, status: int) -> JSONResponse:
    return JSONResponse(status_code=status, content={"code": code, "message": message})


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(NotFoundError)
    async def _not_found(_: Request, exc: NotFoundError) -> JSONResponse:
        return _error("not_found", str(exc), 404)

    @app.exception_handler(AccessDeniedError)
    async def _forbidden(_: Request, exc: AccessDeniedError) -> JSONResponse:
        return _error("forbidden", str(exc), 403)

    @app.exception_handler(NotReadyError)
    async def _processing(_: Request, exc: NotReadyError) -> JSONResponse:
        # 202: the page exists but is still being prepared (FR-011, spec edge case).
        return JSONResponse(
            status_code=202,
            content={"status": exc.status, "message": str(exc)},
        )

    @app.exception_handler(RetentionLockedError)
    async def _locked(_: Request, exc: RetentionLockedError) -> JSONResponse:
        return _error("retention_locked", str(exc), 423)

    @app.exception_handler(IntegrityError)
    async def _integrity(_: Request, exc: IntegrityError) -> JSONResponse:
        return _error("integrity_error", str(exc), 409)

    @app.exception_handler(InvalidDocumentError)
    async def _invalid(_: Request, exc: InvalidDocumentError) -> JSONResponse:
        return _error("invalid_document", str(exc), 422)
