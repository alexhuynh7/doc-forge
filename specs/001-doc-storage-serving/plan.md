# Implementation Plan: Large Construction-Plan Document Storage & Page Serving

**Branch**: `001-doc-storage-serving` | **Date**: 2026-06-27 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/001-doc-storage-serving/spec.md`

## Summary

Serve any individual page of any construction-plan PDF (5 MB–2 GB+) to the browser in
under 2 seconds (p95), for 50,000 active users, sustaining ~2,000 document-set uploads/hour,
with 7-year immutable retention.

**Core technical approach**: decouple the *read path* from document size by precomputing
**per-page artifacts** (rasterized page images + a tiled image pyramid for deep zoom) at
ingest time and serving them as small static objects through a CDN. The source PDFs are
never touched on the read path. Uploads are resumable and processed asynchronously by a
worker pool fed from a queue, so ingest spikes degrade throughput (lag) rather than
availability. Blobs live in an S3-compatible object store with Object Lock (WORM) for the
7-year retention guarantee; metadata lives in PostgreSQL. The Python backend (FastAPI) is
organized into **API → Service → Repository** layers with a framework-independent domain
core; both backend and frontend ship with unit tests.

## Technical Context

**Language/Version**: Python 3.12 (backend), TypeScript 5.x / React 18 (frontend)

**Primary Dependencies**:
- Backend: FastAPI + Uvicorn/Gunicorn (API), Pydantic v2 (DTO/validation), SQLAlchemy 2.x +
  Alembic (metadata persistence), `boto3` (S3-compatible object store), Celery (async
  workers) on Redis broker, PyMuPDF (PDF page rasterization + tiling), `tus`-style resumable
  upload handling.
- Frontend: React 18 + TypeScript, OpenSeadragon (tiled deep-zoom page viewer), a typed API
  client.

**Storage**:
- Object store (S3-compatible, e.g. AWS S3) with Object Lock in Compliance mode — source
  PDFs + derived page artifacts; lifecycle/retention enforced at the bucket/object level.
- PostgreSQL — metadata (teams, users, document sets, documents, pages, processing/retention
  state).
- Redis — metadata/response cache + Celery broker.
- CDN (e.g. CloudFront) — edge caching of page artifacts.

**Testing**:
- Backend: `pytest` (unit), `pytest` + Testcontainers/localstack + ephemeral Postgres
  (integration), `schemathesis`/contract tests against the OpenAPI contract.
- Frontend: Vitest + React Testing Library (unit/component), Playwright (optional E2E).

**Target Platform**: Linux containers (backend API + workers) behind a load balancer;
object store + CDN as managed services; modern evergreen browsers for the viewer.

**Project Type**: Web application (separate `backend/` and `frontend/`).

**Performance Goals**: Page-open p95 < 2 s end-to-end, independent of document size and page
index; ingest throughput ≥ 2,000 document sets/hour sustained at peak.

**Constraints**: Page-open cost MUST be O(1) in document size (no source-PDF access on read);
7-year retention enforced technically (Object Lock), not by policy; services stateless and
horizontally scalable; resumable uploads for multi-GB files.

**Scale/Scope**: 50,000 active users; ~2,000 document sets/hour peak ingest; multi-year
accumulating storage (estimated low-PB scale over 7 years — see research.md).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Evaluated against [constitution.md](../../.specify/memory/constitution.md) v1.0.0:

| Principle | Plan compliance | Status |
|-----------|-----------------|--------|
| **I. Page-Latency Budget (NON-NEGOTIABLE)** | Per-page artifacts precomputed at ingest; read path is a CDN/object-store GET of a small image/tile; source PDF never read on the request path; latency benchmark is a required task. | ✅ PASS |
| **II. Test-First & Comprehensive Coverage (NON-NEGOTIABLE)** | Unit tests for both BE (pytest) and FE (Vitest/RTL); service & repository layers unit-testable via mocked dependencies; integration tests against ephemeral Postgres + localstack; contract tests from OpenAPI. | ✅ PASS |
| **III. Modular, Layered Architecture** | API → Service → Repository layering; domain core has no framework/vendor imports; object store, DB, cache behind repository/gateway interfaces (swappable, mockable). | ✅ PASS |
| **IV. Durability, Integrity & Legal Retention** | Object Lock (Compliance, 7 yr) prevents early deletion; SHA-256 checksums verified on write and re-verifiable on read; atomic visibility (set ready only after full processing); audit log of retention events. | ✅ PASS |
| **V. Horizontal Scalability & Stateless Services** | Stateless FastAPI instances; upload/processing decoupled via Celery queue; autoscaling on queue depth + latency metrics; all coordination state in Redis/Postgres. | ✅ PASS |

**Result**: PASS — no violations. Complexity Tracking omitted (nothing to justify; the
repository/service layering is mandated by Principle III, not extra complexity).

## Project Structure

### Documentation (this feature)

```text
specs/001-doc-storage-serving/
├── plan.md              # This file (/speckit-plan output)
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output (OpenAPI + worker pipeline contract)
│   ├── openapi.yaml
│   └── processing-pipeline.md
├── checklists/
│   └── requirements.md  # From /speckit-specify
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

```text
backend/
├── src/
│   └── docforge/
│       ├── domain/              # Framework-free core: entities, value objects, domain rules
│       │   ├── models.py        # DocumentSet, Document, Page, Team, RetentionRecord
│       │   └── errors.py
│       ├── repositories/        # Persistence interfaces + implementations
│       │   ├── interfaces.py    # Abstract repos (DocumentSetRepository, PageRepository, ...)
│       │   ├── sqlalchemy/      # Postgres implementations
│       │   └── object_store/    # S3-compatible blob gateway (PDFs + page artifacts)
│       ├── services/            # Use-case orchestration (no framework/HTTP types)
│       │   ├── ingestion_service.py
│       │   ├── page_serving_service.py
│       │   ├── retention_service.py
│       │   └── access_service.py        # team-based authorization
│       ├── api/                 # FastAPI routers, request/response DTOs, dependency wiring
│       │   ├── routers/
│       │   └── deps.py
│       ├── workers/             # Celery tasks: PDF split, rasterize, tile, checksum, store
│       │   └── processing.py
│       └── config.py
└── tests/
    ├── unit/                    # domain, services (mocked repos), workers
    ├── integration/             # repos vs ephemeral Postgres + localstack object store
    └── contract/                # OpenAPI conformance

frontend/
├── src/
│   ├── components/
│   │   └── PageViewer/          # OpenSeadragon tiled viewer
│   ├── pages/
│   ├── services/                # typed API client
│   └── hooks/
└── tests/
    └── unit/                    # Vitest + React Testing Library
```

**Structure Decision**: Web-application layout with separate `backend/` and `frontend/`.
The backend interior follows the constitution's mandated **API → Service → Repository**
layering with a framework-free `domain/` core; storage vendors sit behind
`repositories/` interfaces so they are swappable and mockable in unit tests. The frontend
is a thin consumer of the documented API (per the constitution) and may be deferred since
the focus is system design — the contracts in `contracts/` are the source of truth either
way.

## Complexity Tracking

> No constitutional violations to justify. Section intentionally left empty.
