# Quickstart & Validation Guide

This guide proves the feature works end-to-end and that its constitutional guarantees hold.
It references [data-model.md](data-model.md) and [contracts/](contracts/) instead of
duplicating them. Implementation code lives in `tasks.md` (next phase) and the source tree.

## Prerequisites

- Python 3.12, Node 20+
- Local infra (via `docker compose`): PostgreSQL, Redis, an S3-compatible store with Object
  Lock support (e.g. MinIO with object-lock enabled), and a local CDN/proxy stand-in.
- Backend deps installed (`uv pip install -e backend[dev]`), frontend deps (`npm ci` in
  `frontend/`).

## Setup

```bash
docker compose up -d            # postgres, redis, minio
alembic -c backend/alembic.ini upgrade head   # metadata schema
celery -A docforge.workers worker -l info &    # processing pipeline
uvicorn docforge.api.main:app --reload         # API
```

## Validation scenarios

Each scenario maps to a spec acceptance criterion / success criterion.

### V1 — Page opens in < 2 s, size-independent (SC-001, SC-002, US1)
1. Upload a 5 MB set and a 2 GB+ set (see V3 for upload mechanics); wait for `ready`.
2. Request `GET /documents/{id}/pages/{n}` for assorted page numbers in each.
3. Measure time from request to the display image being fully fetched + rendered.
- **Expected**: p95 < 2 s for both; the 2 GB document's page-open time is within 20% of the
  5 MB document's (proves the source PDF is not on the read path).

### V2 — Latency benchmark gate (Principle I)
- Run the load/latency benchmark (`backend/tests/perf/`) against a corpus spanning sizes and
  page indices at target concurrency.
- **Expected**: page-open p95 < 2 s holds under concurrent load; benchmark output is
  attached to any read-path change (required by the constitution).

### V3 — Reliable resumable large upload (SC-007, US2)
1. `POST /uploads` → receive session + part URLs.
2. Upload parts directly to the object store; kill the client mid-transfer.
3. `GET /uploads/{id}` → resume from `received_bytes`; complete remaining parts.
4. `POST /uploads/{id}/finalize`.
- **Expected**: upload resumes without re-sending received data; finalize verifies SHA-256;
  set enters `processing` then `ready` (atomic visibility — never viewable while partial).

### V4 — Spike absorption (SC-003, FR-009)
- Drive ~2,000 finalizes within an hour (or a scaled burst) at the queue.
- **Expected**: zero accepted-then-lost sets; read latency (V1) unaffected while the worker
  queue drains; sets remain `processing` longer if workers lag, then reach `ready`.

### V5 — 7-year retention is technically enforced (SC-005, FR-007/008)
1. Attempt `POST /document-sets/{id}:delete` on a recently uploaded set.
- **Expected**: `423 Locked`; object remains; a `deletion_attempt_blocked` AuditEvent is
  written. (Object Lock Compliance mode rejects deletion even with admin credentials.)

### V6 — Team-based access control (FR-013/FR-015, US — access)
1. As a user NOT in the owning team, call list and page-retrieval endpoints.
- **Expected**: `403` on both; a signed page URL is never minted for a non-member.

### V7 — Invalid input handling (FR-012, edge cases)
- Finalize an upload of a corrupt / password-protected / non-PDF file.
- **Expected**: set becomes `quarantined`/`failed` with a clear `failure_reason`; never
  `ready`.

## Test commands

```bash
# Backend unit (domain + services with mocked repos) and integration (real PG + MinIO)
pytest backend/tests/unit -q
pytest backend/tests/integration -q
pytest backend/tests/contract -q          # OpenAPI conformance

# Frontend unit/component
cd frontend && npm run test               # Vitest + React Testing Library
```

- **Expected**: all suites green; unit coverage meaningful on `domain/` and `services/`
  (Constitution Principle II). CI blocks merge on any failure.

## Done / acceptance

The feature is validated when V1–V7 pass and the test suites are green — demonstrating the
sub-2s page budget, size-independence, reliable ingest at peak, immutable 7-year retention,
team access enforcement, and graceful handling of bad input.
