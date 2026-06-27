---
description: "Task list for Large Construction-Plan Document Storage & Page Serving"
---

# Tasks: Large Construction-Plan Document Storage & Page Serving

**Input**: Design documents from `/specs/001-doc-storage-serving/`

**Prerequisites**: [plan.md](plan.md) (required), [spec.md](spec.md) (user stories),
[research.md](research.md), [data-model.md](data-model.md), [contracts/](contracts/),
[quickstart.md](quickstart.md)

**Tests**: INCLUDED. The Constitution (Principle II, NON-NEGOTIABLE) and the user request
mandate unit tests for both backend and frontend; tests are written before/with implementation.

**Organization**: Tasks are grouped by user story (US1 = P1, US2 = P2, US3 = P3) so each
story can be implemented, tested, and delivered as an independent increment.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: US1 / US2 / US3 (only on user-story phase tasks)
- Exact file paths are included in each task.

## Path Conventions

Web app layout from plan.md: backend at `backend/src/docforge/`, tests at `backend/tests/`;
frontend at `frontend/src/`, `frontend/tests/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and tooling.

- [ ] T001 Create the repository structure per plan.md (`backend/src/docforge/{domain,repositories,services,api,workers}`, `backend/tests/{unit,integration,contract,perf}`, `frontend/src/{components,pages,services,hooks}`, `frontend/tests/unit`)
- [X] T002 Initialize the Python backend project in `backend/pyproject.toml` with FastAPI, Uvicorn/Gunicorn, Pydantic v2, SQLAlchemy 2.x, Alembic, boto3, Celery, redis, PyMuPDF, pyvips
- [X] T003 [P] Configure backend lint/format/type tooling (ruff, black, mypy) in `backend/pyproject.toml` and `backend/.pre-commit-config.yaml`
- [ ] T004 [P] Initialize the React + TypeScript frontend in `frontend/package.json` with React 18, OpenSeadragon, Vitest, React Testing Library, ESLint/Prettier
- [ ] T005 [P] Add `docker-compose.yml` at repo root with PostgreSQL, Redis, and MinIO (Object Lock enabled) for local dev/integration
- [ ] T006 [P] Configure pytest (`backend/pytest.ini`, fixtures in `backend/tests/conftest.py`) and Vitest (`frontend/vitest.config.ts`); wire both into a CI workflow that blocks merge on failure

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure all user stories depend on. Includes team-based access
control, since every read/list path is access-checked (FR-013/FR-015).

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T007 [P] Define framework-free domain entities (Team, User, Membership, DocumentSet, Document, Page, PageArtifact, RetentionRecord, AuditEvent, UploadSession) and value objects in `backend/src/docforge/domain/models.py` per data-model.md
- [X] T008 [P] Define domain errors (AccessDenied, NotReady, IntegrityError, RetentionLocked, InvalidDocument) in `backend/src/docforge/domain/errors.py`
- [X] T009 [P] Unit test domain entities and state-transition rules (DocumentSet status machine, atomic visibility) in `backend/tests/unit/test_domain_models.py`
- [X] T010 Define repository + gateway interfaces (DocumentSetRepository, DocumentRepository, PageRepository, PageArtifactRepository, TeamRepository, MembershipRepository, UploadSessionRepository, RetentionRepository, AuditRepository, ObjectStoreGateway) in `backend/src/docforge/repositories/interfaces.py`
- [ ] T011 Create the SQLAlchemy schema + initial Alembic migration for all metadata tables (with `(document_id, page_number)` unique index) in `backend/src/docforge/repositories/sqlalchemy/` and `backend/alembic/versions/`
- [ ] T012 [P] Implement the S3-compatible ObjectStoreGateway (put/get/signed-URL, SHA-256 on write, Object Lock params) in `backend/src/docforge/repositories/object_store/s3_gateway.py`
- [ ] T013 [P] Implement the Redis cache adapter (page→object-key map, set readiness, access decisions) in `backend/src/docforge/repositories/cache/redis_cache.py`
- [X] T014 Implement configuration management (settings for DB/Redis/object-store/CDN/signing keys) in `backend/src/docforge/config.py`
- [ ] T015 [P] Configure structured logging + error-to-HTTP mapping in `backend/src/docforge/api/errors.py` and `backend/src/docforge/observability.py`
- [X] T016 Create the FastAPI app skeleton, JWT auth dependency, and DI wiring (inject repos/services) in `backend/src/docforge/api/main.py` and `backend/src/docforge/api/deps.py`
- [X] T017 [US-shared] Implement `access_service` (team-membership authorization) in `backend/src/docforge/services/access_service.py` with unit tests in `backend/tests/unit/test_access_service.py`
- [ ] T018 [P] Implement SQLAlchemy Team/User/Membership repositories in `backend/src/docforge/repositories/sqlalchemy/membership_repo.py` with integration tests in `backend/tests/integration/test_membership_repo.py`
- [X] T051 [P] **(Constitution Principle V — observability)** Implement metrics + health endpoint exposing page-open latency, ingest/queue depth, throughput, and processing success rate (sufficient to drive autoscaling) in `backend/src/docforge/observability.py` and `backend/src/docforge/api/routers/health.py`; unit test metric emission in `backend/tests/unit/test_observability.py` *(execute alongside T015–T018)*

**Checkpoint**: Foundation ready — domain, persistence, object store, auth, and access
control exist. User stories can now begin.

---

## Phase 3: User Story 1 — Open any page in < 2 s (Priority: P1) 🎯 MVP

**Goal**: Resolve any page of any document to precomputed artifacts and serve it via signed
CDN URLs in under 2 s, independent of document size (FR-004/005, SC-001/002).

**Independent Test**: Seed a `ready` document set with page artifacts, then call
`GET /documents/{id}/pages/{n}` for varied pages/sizes and confirm signed URLs return and
p95 render < 2 s with size-independence (V1/V2).

### Tests for User Story 1 (write first, must fail) ⚠️

- [X] T019 [P] [US1] Contract test for `GET /documents/{documentId}/pages/{pageNumber}` (200 PageView, 202 processing, 403, 404) against contracts/openapi.yaml in `backend/tests/contract/test_page_endpoint.py`
- [X] T020 [P] [US1] Integration test: seeded ready page returns signed URLs and is access-gated by team in `backend/tests/integration/test_page_retrieval.py`
- [X] T021 [P] [US1] Unit test `page_serving_service` (resolve page→artifacts, "still processing" path, access denial) in `backend/tests/unit/test_page_serving_service.py`
- [X] T022 [P] [US1] Latency benchmark proving p95 < 2 s and 2 GB-vs-5 MB within 20%, **under representative concurrent load (toward the 50k-active-user target, SC-004)** in `backend/tests/perf/test_page_latency.py`

### Implementation for User Story 1

- [ ] T023 [P] [US1] Implement Page/PageArtifact/Document/DocumentSet SQLAlchemy repositories in `backend/src/docforge/repositories/sqlalchemy/document_repo.py`
- [X] T024 [US1] Implement `page_serving_service` (resolve `(document_id, page_number)`→artifacts via cache→DB, mint short-lived signed URLs, enforce access via access_service, return processing status) in `backend/src/docforge/services/page_serving_service.py`
- [X] T025 [US1] Implement the `GET /documents/{documentId}/pages/{pageNumber}` router + PageView/ProcessingStatus DTOs in `backend/src/docforge/api/routers/pages.py`
- [X] T026 [US1] Implement `GET /document-sets` and `GET /document-sets/{setId}` (team-scoped listing/detail) in `backend/src/docforge/api/routers/document_sets.py`
- [ ] T027 [P] [US1] **[OPTIONAL — FE deferred per spec]** Implement the React PageViewer with OpenSeadragon (DZI tiles) in `frontend/src/components/PageViewer/PageViewer.tsx` and typed API client in `frontend/src/services/api.ts`
- [ ] T028 [P] [US1] **[OPTIONAL — FE deferred per spec]** Frontend unit/component tests for PageViewer (renders page, handles processing/error states) in `frontend/tests/unit/PageViewer.test.tsx`

**Checkpoint**: A user can open any page of a pre-processed set in < 2 s, access-gated. MVP
is demonstrable (seed data + viewer).

---

## Phase 4: User Story 2 — Reliable resumable large uploads (Priority: P2)

**Goal**: Accept resumable multi-GB uploads, verify integrity, and asynchronously process
sets into per-page artifacts with atomic visibility (FR-001/002/003/006/009/011/012).

**Independent Test**: Start an upload, interrupt and resume it, finalize, and confirm the set
moves processing→ready with viewable pages; confirm partial/invalid uploads never become
viewable (V3/V4/V7).

### Tests for User Story 2 (write first, must fail) ⚠️

- [X] T029 [P] [US2] Contract tests for `POST /uploads`, `GET /uploads/{id}`, `POST /uploads/{id}/finalize` against contracts/openapi.yaml in `backend/tests/contract/test_upload_endpoints.py`
- [X] T030 [P] [US2] Integration test: resumable upload (interrupt + resume) then finalize → set becomes ready in `backend/tests/integration/test_upload_resume.py`
- [X] T031 [P] [US2] Unit test `ingestion_service` (session create, checksum verify, atomic finalize) in `backend/tests/unit/test_ingestion_service.py`
- [X] T032 [P] [US2] Unit tests for worker pipeline stages (validate/split/render/tile/finalize, idempotency, quarantine on invalid PDF) in `backend/tests/unit/test_processing_pipeline.py`

### Implementation for User Story 2

- [ ] T033 [P] [US2] Implement UploadSession SQLAlchemy repository in `backend/src/docforge/repositories/sqlalchemy/upload_repo.py`
- [X] T034 [US2] Implement `ingestion_service` (create session + presigned part URLs, track received_bytes for resume, verify SHA-256 on finalize, create DocumentSet as `processing`, enqueue job) in `backend/src/docforge/services/ingestion_service.py`
- [X] T035 [US2] Implement upload routers (`POST /uploads`, `GET /uploads/{id}`, `POST /uploads/{id}/finalize`) in `backend/src/docforge/api/routers/uploads.py`
- [ ] T036 [US2] Configure the Celery app + Redis broker in `backend/src/docforge/workers/app.py`
- [X] T037 [US2] Implement the processing pipeline tasks (validate→split→render_page→tile_page→finalize_set) per contracts/processing-pipeline.md, with PyMuPDF rasterization + pyvips tiling, checksums, and Object-Lock writes, in `backend/src/docforge/workers/processing.py`
- [X] T038 [US2] Implement atomic visibility + failure/quarantine transitions (set flips to `ready` only when all pages ready; invalid→`quarantined`, error→`failed`) in `backend/src/docforge/services/ingestion_service.py`
- [ ] T039 [P] [US2] **[OPTIONAL — FE deferred per spec]** Frontend resumable upload UI + progress in `frontend/src/components/Uploader/Uploader.tsx` with unit tests in `frontend/tests/unit/Uploader.test.tsx`
- [ ] T052 [P] [US2] **(SC-003 verification)** Ingest throughput/spike load test asserting ≥ 2,000 finalized document sets in a peak hour (scaled burst) with zero accepted-then-lost sets and unaffected read latency, in `backend/tests/perf/test_ingest_throughput.py`

**Checkpoint**: Users can reliably upload large sets that become viewable via US1; spikes
queue without loss.

---

## Phase 5: User Story 3 — 7-year retention & retrieval (Priority: P3)

**Goal**: Guarantee documents are retained, integrity-verifiable, and undeletable before
7 years, with an auditable trail (FR-006/007/008, SC-005).

**Independent Test**: Attempt to delete a recent set (blocked, 423, audited); re-verify
integrity of an old set; confirm retain_until = upload + 7 years (V5).

### Tests for User Story 3 (write first, must fail) ⚠️

- [X] T040 [P] [US3] Integration test: deletion before retain_until is blocked (423) and audit-logged; deletion after expiry succeeds in `backend/tests/integration/test_retention.py`
- [X] T041 [P] [US3] Unit test `retention_service` (retain_until computation, deletion guard, integrity re-verification) in `backend/tests/unit/test_retention_service.py`

### Implementation for User Story 3

- [X] T042 [P] [US3] Implement RetentionRecord + AuditEvent SQLAlchemy repositories in `backend/src/docforge/repositories/sqlalchemy/retention_repo.py`
- [X] T043 [US3] Implement `retention_service` (set retain_until = uploaded_at + 7y, apply Object Lock Compliance, block early deletion, re-verify SHA-256 on read, write AuditEvents) in `backend/src/docforge/services/retention_service.py`
- [X] T044 [US3] Implement `POST /document-sets/{setId}:delete` returning 204 (after expiry) or 423 (locked) in `backend/src/docforge/api/routers/document_sets.py`
- [X] T045 [US3] Wire retention application into the finalize stage (apply lock on first object store write) in `backend/src/docforge/workers/processing.py`

**Checkpoint**: All three stories independently functional; retention is technically enforced.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Improvements spanning stories.

- [ ] T046 [P] Document API + architecture (link contracts, data-model) in `docs/architecture.md` and update root `README.md`
- [ ] T047 [P] Add CI coverage gate enforcing meaningful branch coverage on `domain/` and `services/` (Constitution Principle II)
- [ ] T048 Security hardening: signed-URL TTL tuning, authz checks on every page/list path, rate limiting on uploads in `backend/src/docforge/api/`
- [ ] T049 [P] Performance optimization pass (cache warming for hot pages, worker concurrency tuning) informed by T022 benchmark
- [ ] T050 Execute the full quickstart.md validation (V1–V7) and record results

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies — start immediately.
- **Foundational (Phase 2)**: depends on Setup — **BLOCKS all user stories**.
- **User Stories (Phase 3–5)**: all depend on Foundational. US1 is the MVP; US2 produces the
  data US1 serves, but US1 is independently testable via seeded data. US3 layers on the
  storage writes done in US2 but is independently testable via seeded sets.
- **Polish (Phase 6)**: depends on the targeted user stories being complete.

### User Story Dependencies

- **US1 (P1)**: after Foundational. Independently testable with seeded `ready` artifacts.
- **US2 (P2)**: after Foundational. Independently testable end-to-end (upload→ready).
- **US3 (P3)**: after Foundational. Independently testable via seeded sets + delete attempts.

### Within Each Story

- Tests first (must fail) → repositories → services → endpoints → frontend/integration.
- Models/repos before services; services before endpoints.

### Parallel Opportunities

- Setup: T003, T004, T005, T006 in parallel.
- Foundational: T007/T008/T009 together; T012/T013/T015/T018 in parallel after interfaces (T010).
- Within a story, all `[P]` test tasks run together, and `[P]` repos/frontend run alongside.
- With staffing, US1/US2/US3 can proceed in parallel once Foundational completes.

---

## Parallel Example: User Story 1

```bash
# Tests for US1 together (write first):
Task: "Contract test page endpoint in backend/tests/contract/test_page_endpoint.py"   # T019
Task: "Integration test page retrieval in backend/tests/integration/test_page_retrieval.py"  # T020
Task: "Unit test page_serving_service in backend/tests/unit/test_page_serving_service.py"  # T021
Task: "Latency benchmark in backend/tests/perf/test_page_latency.py"                  # T022

# Parallel implementation:
Task: "Document repositories in backend/src/docforge/repositories/sqlalchemy/document_repo.py"  # T023
Task: "React PageViewer in frontend/src/components/PageViewer/PageViewer.tsx"          # T027
```

---

## Implementation Strategy

### MVP First (User Story 1 only)

1. Phase 1 Setup → 2. Phase 2 Foundational (blocks everything) → 3. Phase 3 US1.
4. **STOP & VALIDATE**: seed a ready set, run V1/V2 — prove sub-2s, size-independent page
   serving. This is the demonstrable MVP and the product's core promise.

### Incremental Delivery

1. Setup + Foundational → foundation ready.
2. US1 → validate (MVP: fast page serving).
3. US2 → validate (real uploads feed US1).
4. US3 → validate (retention guarantees).
5. Polish.

### Parallel Team Strategy

After Foundational: Dev A → US1, Dev B → US2, Dev C → US3; integrate independently.

---

## Notes

- `[P]` = different files, no incomplete-task dependency.
- `[Story]` label traces each task to its user story (US-shared = needed by all, kept in
  Foundational).
- Tests are written to fail before implementation (Constitution Principle II).
- Commit after each task or logical group; stop at checkpoints to validate stories.
- **Remediation tasks (added post-`/speckit-analyze`)**: T051 (observability/metrics, Phase 2
  Foundational — resolves the Principle V gap), T052 (ingest throughput test, US2 — resolves
  the SC-003 verification gap). T022 was broadened for SC-004 concurrency; frontend tasks
  T027/T028/T039 are marked OPTIONAL to match the spec's deferred-FE assumption. New total:
  **53 tasks** (T051/T052 appended to preserve existing IDs; execute T051 within Phase 2 and
  T052 within US2 per their notes).
