# Doc-Forge

**Large construction-plan document storage & sub-2-second page serving at scale.**

Doc-Forge stores, retrieves, and serves large construction-plan PDF document sets
(5 MB to 2 GB+) for 50,000 active users, sustaining ~2,000 document-set uploads per hour,
with a 7-year legal retention obligation — and renders **any individual page in the browser
in under 2 seconds**, regardless of how large the source document is.

This README is the complete system design. The companion design artifacts live in
[`specs/001-doc-storage-serving/`](specs/001-doc-storage-serving/): the
[spec](specs/001-doc-storage-serving/spec.md), [plan](specs/001-doc-storage-serving/plan.md),
[research / decision log](specs/001-doc-storage-serving/research.md),
[data model](specs/001-doc-storage-serving/data-model.md), and
[API contracts](specs/001-doc-storage-serving/contracts/). Binding engineering principles
are in [the constitution](.specify/memory/constitution.md). A runnable, tested reference
implementation of the core is in [`backend/`](backend/).

---

## Table of contents

1. [Requirements & constraints](#requirements--constraints)
2. [Design in one paragraph](#design-in-one-paragraph)
3. [Architecture](#architecture)
4. [The 2-second latency budget](#the-2-second-latency-budget)
5. [Capacity planning (back-of-the-envelope)](#capacity-planning-back-of-the-envelope)
6. [Key request flows](#key-request-flows)
7. [Data model](#data-model)
8. [Consistency & correctness model](#consistency--correctness-model)
9. [Failure modes & resilience](#failure-modes--resilience)
10. [Scaling strategy & bottlenecks](#scaling-strategy--bottlenecks)
11. [Security model](#security-model)
12. [Observability & SLOs](#observability--slos)
13. [Backend architecture](#backend-architecture)
14. [Technology choices & trade-offs](#technology-choices--trade-offs)
15. [Engineering principles & quality gates](#engineering-principles--quality-gates)
16. [Testing strategy](#testing-strategy)
17. [Engineering rigor: the review that found real bugs](#engineering-rigor-the-review-that-found-real-bugs)
18. [Development workflow & tooling](#development-workflow--tooling)
19. [Implementation status](#implementation-status)
20. [Running it](#running-it)
21. [Where to look (reviewer's map)](#where-to-look-reviewers-map)

---

## Requirements & constraints

| Dimension | Target | Source |
|-----------|--------|--------|
| **Page-render latency** | any page rendered in browser **< 2 s (p95)**, independent of document size | primary constraint |
| **Scale** | 50,000 active users | FR-010 / SC-004 |
| **Ingest throughput** | ~2,000 document sets / hour at peak, zero accepted-then-lost | FR-009 / SC-003 |
| **Retention** | every document retained **≥ 7 years**, deletion technically prevented before expiry | FR-007 / SC-005 |
| **File sizes** | individual PDFs from 5 MB to 2 GB+ | FR-001 |
| **Access** | document sets owned by **organization/project teams**; access enforced on every read | FR-013 / FR-015 |

**Non-goals (explicit scope boundaries):** full-text search inside PDFs, document editing/annotation,
real-time collaboration, and a polished end-user UI. The focus is the storage + serving system design.

---

## Design in one paragraph

Opening a 2 GB PDF and rendering page N on demand is unbounded in time — it can never reliably
meet a 2-second budget. So the central decision is to **move all PDF work off the read path**:

> **Precompute per-page artifacts at ingest; serve them as small static objects from a CDN.
> The source PDF is never touched when a user opens a page.**

At upload time each page is rasterized into a display image plus a **tiled image pyramid**
(Deep Zoom) for pan/zoom of large-format plans. Opening page N then costs a single CDN fetch
of a few hundred KB — **O(1) in document size**. A 2 GB document and a 5 MB document open in
the same time. Everything else in the architecture follows from protecting that read path:
async ingestion so spikes never touch it, a CDN + cache so fan-out never touches the origin,
and immutable artifacts so the edge can cache forever.

---

## Architecture

```text
                         ┌──────────────────────────────────────────┐
                         │                Browser (React)            │
                         │   OpenSeadragon tiled viewer + API client │
                         └───────────────┬──────────────┬───────────┘
              page tiles/images (signed) │              │ JSON API (uploads, listing, page resolve)
                         ┌───────────────▼──────┐       │
                         │         CDN / edge    │       │
                         │  (immutable page      │       │
                         │   artifacts, cached)  │       │
                         └───────────────▲──────┘       │
                                         │              │
        ┌────────────────────────────────┼──────────────▼─────────────────────────────┐
        │                                 │        Stateless API tier (FastAPI)         │
        │   resolve page → signed URL ────┘   API → Service → Repository layering        │
        │   • page_serving_service (hot read path, O(1))                                  │
        │   • ingestion_service (resumable uploads, checksum, atomic visibility)          │
        │   • retention_service (7-yr guard, integrity, audit)                            │
        │   • access_service (team-based authz on every read)                             │
        └───┬───────────────────────┬──────────────────────────┬─────────────────┬──────┘
            │                       │                          │                 │
   enqueue  │            metadata   │                    cache  │       blobs +   │ signed URLs
  (on upload)│           (Postgres) │                   (Redis) │      retention  │
            ▼                       ▼                          ▼                 ▼
   ┌─────────────────┐   ┌────────────────────┐   ┌──────────────┐   ┌────────────────────────┐
   │  Queue (Redis)  │   │   PostgreSQL        │   │   Redis      │   │  Object store (S3-comp.)│
   │  + Celery       │   │  teams, sets,       │   │ page→key map │   │  source PDFs + page     │
   │  worker pool    │   │  documents, pages,  │   │ readiness,   │   │  artifacts (WORM,       │
   │                 │   │  retention, audit   │   │ authz cache  │   │  Object Lock 7 yr)      │
   └────────┬────────┘   └────────────────────┘   └──────────────┘   └────────────▲───────────┘
            │  validate → split → rasterize → tile → checksum → store → finalize    │
            └──────────────────────────────────────────────────────────────────────┘
                              async processing pipeline (workers)
```

### Components

- **API tier (FastAPI, stateless)** — request/response, auth, and dependency wiring only.
  Horizontally scalable; all coordination state lives in Redis/Postgres.
- **Services** — use-case orchestration with no framework/HTTP/vendor types: page serving,
  ingestion, retention, access.
- **Repositories / gateways** — abstractions over PostgreSQL, the object store, and Redis.
  Adapters are swappable; the domain never imports a vendor SDK.
- **Async worker pipeline (Celery on Redis)** — does the heavy PDF work at ingest, decoupled
  from the request path so spikes queue rather than fail.
- **Object store (S3-compatible) with Object Lock** — source PDFs and derived artifacts,
  retained 7 years in Compliance mode (early deletion is technically impossible).
- **PostgreSQL** — queryable metadata (teams, sets, documents, pages, retention, audit).
- **Redis** — hot-metadata cache + Celery broker.
- **CDN** — edge-cached, page/tile-granular delivery of immutable artifacts.

---

## The 2-second latency budget

The budget is a contract, so it's worth showing where the 2 seconds actually goes for a cold
page open (warm/zoom paths are faster). The point: the critical path is **network + one small
artifact fetch**, and the artifact size is bounded and document-size-independent.

| Stage | Cold | Notes |
|-------|------|-------|
| TLS/connection (amortized via keep-alive/H2) | 0–150 ms | reused on subsequent pages |
| API: authz + `(doc, page)` → key resolve (Redis hit) + sign URL | 10–30 ms | DB only on cache miss |
| CDN fetch of display image (~150–300 KB) | 50–150 ms edge hit / 200–400 ms origin miss | immutable → high hit ratio |
| Browser decode + paint | 100–300 ms | WebP decode |
| **First readable paint (p95)** | **≈ 0.5–1.0 s** | comfortable margin under 2 s |
| Deep-zoom tiles (progressive, off critical path) | streamed | only the current viewport loads |

**Why it's size-independent:** the read path never opens the source PDF. It resolves a row
keyed on `(document_id, page_number)` and returns a signed URL to a precomputed artifact. A
2 GB document and a 5 MB document differ only in how much work happened *at ingest* — never at
read time. The reference implementation enforces this with a benchmark that asserts p95 < 2 s
and that 2 GB-vs-5 MB page-open times stay within 20%
([test_page_latency.py](backend/tests/perf/test_page_latency.py)).

---

## Capacity planning (back-of-the-envelope)

Assume an average set of **200 MB / ~200 pages** (construction plans skew large), with daily
volume averaging ~500 sets/hr (peaks at 2,000/hr) ⇒ **~12,000 sets/day**.

| Quantity | Estimate | Implication |
|----------|----------|-------------|
| Peak ingest bandwidth | 2,000 sets/hr × 200 MB ≈ **400 GB/hr** | direct-to-object-store upload keeps this off the API tier |
| Daily stored volume | 12k sets × 200 MB source + ~40% derived ≈ **~3.4 TB/day** | object-store lifecycle tiering controls cost |
| **7-year storage** | 3.4 TB/day × 365 × 7 ≈ **~8 PB** | rules out DB/filesystem blobs; object store + tiering required |
| Page metadata rows | 12k × 200 = 2.4M pages/day ⇒ **~6 B rows / 7 yr** | Postgres with time/set **partitioning** + read replicas; page index is a candidate to shard or move to a wide-column store as it grows |
| Worker CPU at peak | ~50 ms/page render+tile × 200 pages = ~10 s/set; 2,000/hr ≈ 0.56 sets/s ⇒ **~6 busy cores** | size to ~12–16 cores headroom; per-page fan-out stops big sets head-of-line-blocking |
| Read concurrency | 50k users, ~10% active, ~0.3 page-opens/s ⇒ **~1,500 page-opens/s** | CDN absorbs cache hits; origin sees only misses + URL minting, sharded across stateless API instances |

The two scale pressures that need a real answer, not hand-waving: **petabyte object storage**
(answered by S3 + lifecycle tiering, with early deletion still blocked by Object Lock) and
**billions of page-metadata rows** (answered by partitioning + replicas now, with a documented
path to sharding the page index if a single Postgres stops keeping up).

---

## Key request flows

### 1. Upload (resumable, large files)
1. `POST /uploads` opens a session and returns pre-signed part URLs (direct-to-store).
2. Client uploads parts directly to the object store; interrupted transfers **resume** from
   `received_bytes` — no re-sending received data.
3. `POST /uploads/{id}/finalize` verifies the SHA-256, stores the source under a 7-year
   retention lock, records the set as `processing`, writes an `upload_accepted` audit event,
   and **enqueues** processing — returning `202` immediately. No submission is ever dropped
   under load; a spike grows the queue, not the error rate.

### 2. Processing (async pipeline)
`validate → split → rasterize each page → tile (DZI) → checksum → store → finalize`.
The set flips to `ready` **only after every page of every document is rendered and committed
together** (atomic visibility) — a partial or invalid set is never viewable; invalid input is
`quarantined`. Stages are idempotent and safe to retry.

### 3. Page serving (the hot path, < 2 s)
`GET /documents/{id}/pages/{n}` → check team access → confirm the set is `ready` → resolve
`(document_id, page_number)` to its precomputed artifacts (Redis → Postgres) → mint
**short-lived signed CDN URLs** → return. The browser fetches the small image/tiles from the
edge. The source PDF is never read.

### 4. Deletion (retention-guarded)
`DELETE /document-sets/{id}` → if within the 7-year window, **blocked** (`423`) and the attempt
is audited; after expiry the set, blobs, and metadata are deleted and audited. The object
store's Object Lock enforces this as a backstop independent of application code.

---

## Data model

Nine entities (full detail in [data-model.md](specs/001-doc-storage-serving/data-model.md)):

```text
Team 1───* Membership *───1 User
Team 1───* DocumentSet 1───* Document 1───* Page 1───* PageArtifact
DocumentSet 1───1 RetentionRecord
DocumentSet 1───* AuditEvent
UploadSession  ──(finalize)──▶ DocumentSet
```

- **Team** — unit of ownership and access control.
- **DocumentSet** — the uploaded/retrieved unit; carries the status machine + retention clock.
- **Document / Page** — a PDF and its individually addressable pages; the hot lookup is the
  unique index on `(document_id, page_number)`.
- **PageArtifact** — the precomputed, immutable, CDN-served renderings of a page.
- **RetentionRecord / AuditEvent** — the 7-year guarantee and its tamper-evident trail.

---

## Consistency & correctness model

This is where the design earns its keep — the guarantees, and how they're enforced:

- **Atomic visibility (FR-003).** A set is viewable *only* in `READY`. The read path checks
  `is_viewable` before serving any page, and the pipeline **stages every page and commits the
  whole set at once** — so a mid-processing or failed set never exposes a half-rendered or
  orphaned page. (Both halves are tested; see the review story below.)
- **Idempotent ingestion.** Worker stages use deterministic object keys and upsert by
  `(document_id, page_number)`, so retries don't duplicate work. `finalize` rejects a
  non-`ACTIVE` session, so a retried `202` or a concurrent call can't create a duplicate set.
- **Integrity (FR-006).** SHA-256 is computed on write and re-verifiable on read; mismatches
  are detected and audited.
- **Durable retention (FR-007).** Object Lock (Compliance) makes early deletion *technically
  impossible*; a `RetentionRecord` mirrors it and the API + storage layer both refuse early
  deletion (defense in depth).
- **No lost uploads under load (FR-009).** `finalize` persists the set and enqueues before
  returning; back-pressure shows up as queue depth, never as dropped work.

---

## Failure modes & resilience

| Component fails | Read path | Write/ingest path | Mitigation |
|-----------------|-----------|-------------------|------------|
| Object store down | hot pages still served from CDN cache | uploads/finalize fail fast | CDN shields reads; clients retry; upload sessions persist for resume |
| PostgreSQL down | hot metadata served from Redis briefly; cold reads fail | finalize fails | read replicas; cache TTLs; sessions survive for resume |
| Redis down | cache miss → fall through to Postgres (slower, still correct) | broker down → processing pauses | degrade, don't break; **transactional outbox** so finalize never enqueues-then-loses |
| Worker crash mid-set | unaffected (set stays `processing`) | job redelivered | idempotent re-render; staged-commit means no partial state |
| Poison/corrupt PDF | unaffected | that set → `quarantined` | isolated; never blocks the queue |
| CDN miss storm (viral doc) | origin shielded | n/a | request coalescing + long TTLs on immutable artifacts |
| Ingest spike (2k/hr) | unaffected (separate path) | queue grows, drains | autoscale workers on queue depth; zero dropped submissions |

---

## Scaling strategy & bottlenecks

| Tier | Scales by | Bottleneck & answer |
|------|-----------|---------------------|
| API | add stateless instances behind LB | none structural — no in-process state |
| Workers | autoscale on queue depth | per-set latency × arrival rate; per-page fan-out prevents head-of-line blocking |
| Object store | managed, effectively unlimited | cost over 7 yr → lifecycle tiering (hot → cold) |
| CDN | managed; absorbs read fan-out | cache hit ratio → immutable artifacts maximize it |
| PostgreSQL | read replicas + partitioning | **page table at billions of rows** → partition by time/set; documented path to shard or move the page index to a wide-column store |
| Redis | cluster / shard | cache + broker can split into separate clusters |

---

## Security model

- **Team-based authorization on every read.** Enforced in the service layer (not just the
  router), on page serving, set listing, set detail, deletion, *and every upload-session
  operation*. Verified by tests, including negative cases.
- **Signed URLs, not public artifacts.** Page artifacts are delivered via short-lived signed
  URLs minted **only after** the access check, so possession of a CDN URL alone never bypasses
  authz. (Production adapters MUST HMAC the URL with a server-held secret and have the CDN
  reject expired/forged signatures — documented in the gateway contract.)
- **WORM retention.** Object Lock (Compliance, 7 yr) blocks early deletion even with admin
  credentials; the app refuses too, and every deletion attempt is audited.
- **Integrity.** Content hashes verified on write and re-verifiable on read.
- **Pluggable authentication, fail-closed.** The reference impl ships a dev token shortcut
  that is **disabled unless explicitly enabled** (`DOCFORGE_DEV_AUTH`), so the placeholder can
  never silently reach production; a real deployment wires a JWT verifier behind the same
  dependency.

---

## Observability & SLOs

- **SLO:** page-open p95 < 2 s; ingest sustains ≥ 2,000 sets/hr with zero accepted-then-lost.
- **Signals (Principle V):** page-open latency histogram, ingest/queue depth, throughput, and
  processing success rate — exposed at `/metrics`, sufficient to drive autoscaling and to
  detect a budget breach. `/healthz` for liveness.
- **Audit trail:** every retention-relevant event (`upload_accepted`, `processing_completed`,
  `deletion_attempt_blocked`, `deleted_after_expiry`, `integrity_check`) is recorded.

---

## Backend architecture

```text
backend/src/docforge/
├── domain/         # framework-free entities + rules (status machine, retention math)
├── repositories/   # Protocols + adapters (in-memory now; SQLAlchemy/S3/Redis in prod)
├── services/       # use cases: page_serving, ingestion, retention, access
├── api/            # FastAPI routers, DTOs, DI wiring, error→HTTP mapping
├── workers/        # async pipeline + task dispatcher (synchronous now; Celery in prod)
└── observability.py# metrics (Principle V)
```

Dependencies point **inward**: `api → services → repositories(interfaces) ← adapters`, and
nothing in `domain`/`services` imports a framework or vendor SDK. This is what makes the
sub-2s, retention, and access rules unit-testable in isolation and lets storage vendors be
swapped (in-memory ↔ SQLAlchemy/S3/Celery) by changing only the DI wiring in
[`api/deps.py`](backend/src/docforge/api/deps.py) — no service or domain code changes.

---

## Technology choices & trade-offs

Every choice has a rationale and a rejected alternative (full log:
[research.md](specs/001-doc-storage-serving/research.md)).

| Layer | Choice | Why | Rejected |
|-------|--------|-----|----------|
| Backend | Python 3.12 + FastAPI | async I/O-bound serving; explicit versioned API | — |
| Read path | precompute + tile + CDN | only way to make page-open O(1) in doc size | on-demand render (unbounded first-hit), client-side PDF.js (ships GBs) |
| Blob storage | S3-compatible + Object Lock | PB-scale; WORM retention; lifecycle tiering | Governance-mode lock (bypassable), DB/FS blobs (no scale/WORM) |
| Metadata | PostgreSQL | relational integrity over set→doc→page; fast indexed lookups | NoSQL (loses integrity + ad-hoc authz queries) |
| Rendering | PyMuPDF + libvips | fast per-page raster; low-memory tiled pyramids | Poppler/Ghostscript (slower/licensing) |
| Uploads | resumable (tus / S3 multipart) | multi-GB over flaky links must resume; offloads API bandwidth | single PUT (no resume), buffer-through-API (breaks statelessness) |
| Async | Celery on Redis | decouple ingest from read path; autoscale on depth | sync-in-request (spikes break it), cron-batch (latency to ready) |
| Frontend | React + OpenSeadragon | tiled deep-zoom viewer; thin API consumer | — |

---

## Engineering principles & quality gates

The project runs under a written [constitution](.specify/memory/constitution.md) (v1.0.0) with
two NON-NEGOTIABLE principles — **(I) the < 2 s page-latency budget** and **(II) test-first,
comprehensive coverage** — plus modular layering, durability/retention, and stateless
scalability. Every change passes lint + types + the full test suite, and read-path changes
must carry a latency measurement.

---

## Testing strategy

Four layers, all green (`pytest`, mypy strict, ruff):

- **Unit** — domain rules, each service against mocked repositories (the layering makes this
  trivial), worker pipeline, metrics.
- **Integration** — full upload → process → ready → page-view journey via the API; team-scoped
  access; retention deletion blocked + audited.
- **Contract** — endpoints validated against the OpenAPI spec (200/202/403/404/409/423 shapes).
- **Performance** — page-open p95 < 2 s and size-independence.

---

## Engineering rigor: the review that found real bugs

The codebase was put through an independent multi-agent adversarial review (security +
correctness + maintainability passes, fresh context). It surfaced — and the team then fixed,
each with a regression test — four genuine bugs in the *service logic* (not the test fakes):

1. **Upload-session paths missed the access check** — only session *creation* was gated; read/append/finalize were not. Now every session operation goes through one access-checked choke point.
2. **Page serving didn't check set visibility** — a `READY` page in a still-`processing`/`failed` set was directly servable, violating atomic visibility. Now gated on `is_viewable`.
3. **Partial processing failure left orphaned `READY` pages** — fixed by staging all renders and committing the whole set atomically.
4. **`finalize` wasn't idempotent** — a retried `202` could create a duplicate set; now rejected unless the session is `ACTIVE`.

Type-checking also caught a missing method on the storage Protocol, and the metrics histogram
had a double-counting bug the tests caught before it shipped. The point isn't that bugs
existed — it's that the layering made them cheap to find, the gates caught them, and each is
now locked down by a test. (Lower-severity items — production HMAC signing, page-index
sharding, structured failure logging — are tracked, not silently dropped.)

---

## Development workflow & tooling

This system was built with a disciplined, spec-driven, AI-assisted workflow. The *process* is
part of the deliverable — it's why the design is documented, the requirements are testable, and
the review caught real bugs before they shipped.

- **GitHub Spec Kit** (`.specify/`, `/speckit-*` skills) — spec-driven development. The flow
  *constitution → specify → plan → tasks → analyze → implement* produced everything under
  [`specs/001-doc-storage-serving/`](specs/001-doc-storage-serving/) and the
  [constitution](.specify/memory/constitution.md). Each phase is an artifact a reviewer can
  read: measurable success criteria, a decision log, a data model, API contracts, and a
  dependency-ordered task list. The `/speckit-analyze` cross-artifact check flagged coverage
  gaps (the SC-003 ingest load test, the Principle V observability task) *before* implementation
  started.
- **gstack** — a multi-agent engineering workflow (plan / review / QA / ship). Its `/review`
  ran an independent **adversarial + security + maintainability** pass over the backend with
  fresh context. That's the review behind
  [the four service-logic bugs](#engineering-rigor-the-review-that-found-real-bugs) above —
  each then fixed with a regression test.
- **code-review-graph (CRG)** — a local-first code-intelligence graph (Tree-sitter AST → a
  graph of functions/classes and their relationships) exposed to AI tools over **MCP**. It
  gives blast-radius / impact analysis and token-efficient review context — reading only what a
  change touches instead of whole files (benchmarked at large median token reductions). It
  auto-updates via Claude Code hooks + a git pre-commit hook; build/refresh with
  `code-review-graph build` / `update`.

> The CRG graph indexes git-tracked files, so it stays empty until this work is committed
> (everything is currently uncommitted on `main`). After the first commit,
> `code-review-graph build` populates it and the MCP tools become useful for impact analysis
> and review.

---

## Implementation status

The functional core is implemented and tested in [`backend/`](backend/) — **all three user
stories** (fast page serving, resumable uploads + processing, retention) work end-to-end with
**56 passing tests**, mypy-strict and ruff clean. Storage vendors are currently in-memory/fake
implementations behind the repository interfaces; the production adapters (SQLAlchemy, S3,
Celery, PyMuPDF) drop in without changing any service or domain code.

See [`specs/001-doc-storage-serving/tasks.md`](specs/001-doc-storage-serving/tasks.md) for the
full task breakdown (31 of 52 done) and what remains (production adapters, `docker-compose`,
frontend, load tests).

### Running it

```bash
cd backend
uv venv --python 3.12 .venv
uv pip install -e ".[dev]"
.venv/Scripts/python -m pytest    # 56 passed
.venv/Scripts/python -m mypy      # clean
.venv/Scripts/python -m ruff check src tests
```

Validation scenarios (V1–V7) mapping to the success criteria are in
[`quickstart.md`](specs/001-doc-storage-serving/quickstart.md).

---

## Where to look (reviewer's map)

| To evaluate… | Read |
|--------------|------|
| The core idea & trade-offs | this README + [research.md](specs/001-doc-storage-serving/research.md) |
| Requirements thinking | [spec.md](specs/001-doc-storage-serving/spec.md) (user stories, FRs, measurable SCs) |
| Architecture & layering | [plan.md](specs/001-doc-storage-serving/plan.md) + [backend/src/docforge/](backend/src/docforge/) |
| The hot path | [page_serving_service.py](backend/src/docforge/services/page_serving_service.py) |
| Atomicity & idempotency | [workers/processing.py](backend/src/docforge/workers/processing.py), [ingestion_service.py](backend/src/docforge/services/ingestion_service.py) |
| Retention guarantee | [retention_service.py](backend/src/docforge/services/retention_service.py) |
| API contract | [contracts/openapi.yaml](specs/001-doc-storage-serving/contracts/openapi.yaml) |
| Test rigor | [backend/tests/](backend/tests/) (unit / integration / contract / perf) |
