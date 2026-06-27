# Phase 0 Research: Large Construction-Plan Document Storage & Page Serving

This document resolves the technical unknowns behind the plan. Each decision records what
was chosen, why, and the alternatives rejected.

## R1. How to serve any page in < 2 s independent of document size

**Decision**: Precompute **per-page artifacts** at ingest and serve them as small static
objects via CDN. For each page generate (a) a rasterized full-page image (WebP, ~150–200 DPI
display resolution) and (b) a **tiled image pyramid** (Deep Zoom / DZI) for zoom/pan of
large-format plans. The read path resolves `set/document/page → object key` and returns a
CDN URL; the source PDF is never opened on a read.

**Rationale**: The latency of opening a 2 GB PDF and rendering page N is unbounded and grows
with size and page index — it cannot meet a 2 s budget on the request path. Moving all
PDF work to ingest makes page-open an O(1) cache/object-store fetch of a few hundred KB,
satisfying Constitution Principle I (size-independent page cost). Tiling means the browser
only ever fetches the tiles for the current viewport/zoom, keeping even very large plans
fast.

**Alternatives considered**:
- *On-demand render per request* (render page N when requested, then cache): first-hit
  latency for a cold 2 GB document blows the budget and creates thundering-herd risk.
  Rejected as the primary path; an on-demand fallback is allowed only for not-yet-processed
  pages, behind a "still processing" state.
- *Client-side PDF.js rendering*: requires shipping the whole (multi-GB) PDF to the browser
  — impossible within 2 s. Rejected.
- *Single static image per page, no tiling*: fine for small pages but a large-format
  construction sheet at readable zoom is huge; tiling is needed for zoom without a big
  initial download.

## R2. PDF page rasterization / tiling library

**Decision**: **PyMuPDF (fitz)** in Celery workers to render pages to pixmaps and emit
tiles + a display image; assemble DZI descriptors. Optionally `libvips` (`pyvips`) for fast
pyramid/tile generation from the rendered raster.

**Rationale**: PyMuPDF is fast, handles large/complex PDFs, gives per-page rendering at
arbitrary DPI without loading rendering of other pages, and is pip-installable. `libvips`
produces tiled pyramids with very low memory overhead, important for large pages.

**Alternatives considered**: `pdf2image`/Poppler (slower, heavier process spawn);
Ghostscript (licensing + speed); commercial SDKs (cost, lock-in). Rejected for the default.

## R3. Object storage + 7-year retention enforcement

**Decision**: S3-compatible object store with **Object Lock in Compliance mode**, retention
set to 7 years on every stored object (source PDFs and derived artifacts). Storage-class
lifecycle transitions move cold data to cheaper tiers but **never** delete before expiry.

**Rationale**: Compliance-mode Object Lock makes early deletion *technically impossible*
(even by root), satisfying Constitution Principle IV ("technically prevented, not merely
policy"). Lifecycle tiering controls cost as data accumulates over years.

**Alternatives considered**:
- *Governance mode* Object Lock: bypassable by privileged users — does not meet "technically
  prevented". Rejected for the legal requirement.
- *Application-level deletion guards only*: a bug or admin can delete data. Rejected.
- *Store blobs in Postgres/Filesystem*: doesn't scale to PB, no native WORM. Rejected.

## R4. Metadata store

**Decision**: **PostgreSQL** for teams, users, document sets, documents, pages, processing
status, and retention/audit records. Page lookup keyed by `(document_id, page_number)`.

**Rationale**: Strong consistency for "is this set ready / who can access it", relational
integrity across the set→document→page hierarchy, and fast indexed page lookups. The
metadata is small relative to blobs and fits a single well-indexed RDBMS at this scale
(read-replicas + caching for fan-out).

**Alternatives considered**: DynamoDB/NoSQL (loses relational integrity and ad-hoc query
flexibility for access checks); storing metadata in object store (no query/indexing).
Rejected.

## R5. Resumable, reliable large uploads (5 MB–2 GB+)

**Decision**: **Resumable uploads** via the tus protocol *or* S3 multipart upload with
pre-signed part URLs (client uploads parts directly to the object store; backend tracks an
upload session and finalizes). Each completed upload is checksummed (SHA-256) and recorded
as a pending document set.

**Rationale**: Multi-GB transfers over unreliable links must resume without restarting
(FR-002, SC-007). Direct-to-object-store multipart offloads bandwidth from the API tier
(supports Principle V scalability) and is the natural fit for S3-compatible storage.

**Alternatives considered**: single PUT (no resume, fails on 2 GB over flaky links);
buffering the whole file through the API tier (memory + bandwidth bottleneck, breaks
statelessness). Rejected.

## R6. Asynchronous processing pipeline + spike absorption

**Decision**: **Celery** workers on a **Redis** broker (or a managed queue). On upload
finalize, enqueue a `process_document_set` job; workers split the PDF, rasterize/tile each
page, compute checksums, upload artifacts, and only then flip the set to `ready` (atomic
visibility, FR-003). Autoscale workers on queue depth.

**Rationale**: Decoupling ingest from serving lets a 2,000-sets/hour spike queue up and
drain (throughput lag) without dropping submissions or harming read latency (Principle V,
FR-009). Per-page subtasks parallelize processing of a single large set.

**Alternatives considered**: synchronous processing in the request (ties up API workers,
breaks under spikes); cron-batch (latency to "ready" too high). Rejected.

## R7. Caching / CDN layering

**Decision**: **CDN** (e.g. CloudFront) in front of page artifacts with long-lived,
content-addressed (immutable) cache keys at page/tile granularity; **Redis** caches hot
metadata (set readiness, page→object-key maps, access decisions) to keep the read path off
the DB for popular documents.

**Rationale**: Page artifacts are immutable once generated → ideal for aggressive edge
caching; concurrent access to a popular plan is absorbed at the edge (edge cases:
concurrent spikes). Metadata cache removes DB round-trips from the 2 s budget.

**Alternatives considered**: serve artifacts straight from object store (works but higher
latency + egress cost, no edge locality); no metadata cache (DB becomes the read-path
bottleneck under fan-out). Rejected.

## R8. Backend architecture (repository + service layers)

**Decision**: **API → Service → Repository** with a framework-free `domain/` core.
Controllers (FastAPI routers) translate HTTP ↔ DTOs and call services; services orchestrate
use cases and enforce domain rules (access, retention, atomic visibility); repositories
abstract Postgres and the object store behind interfaces. Dependency injection wires
concrete implementations; tests inject fakes/mocks.

**Rationale**: Directly satisfies Constitution Principle III (modular, layered, swappable,
testable) and the user's explicit request for repository + service layers. Domain isolation
keeps the 2 s/retention/access rules unit-testable without HTTP, DB, or S3.

**Alternatives considered**: fat controllers / active-record models with DB access in
routes (untestable, violates Principle III). Rejected.

## R9. Access control (team-based)

**Decision**: Document sets are owned by a **Team**; an `access_service` checks team
membership on every list and every page-retrieval request (FR-013, FR-015). Page artifact
URLs are delivered as **short-lived signed URLs** (or via an authorizing edge function) so
that possession of a CDN URL alone does not bypass access checks.

**Rationale**: Meets the resolved org/team access model from the spec while keeping the fast
CDN read path: access is checked when minting the signed URL; the artifact fetch itself
stays edge-cached. Short TTLs bound exposure.

**Alternatives considered**: fully public artifact URLs (violates confidentiality);
proxying every tile through the API with an auth check (defeats CDN benefit, hurts latency).
Rejected — signed URLs balance both.

## R10. Capacity & cost sanity check (informs Scale/Scope)

**Decision**: Plan for **low-petabyte** total storage over 7 years and size workers to the
2,000-sets/hour peak.

**Rationale (order-of-magnitude)**: At 2,000 sets/hour ≈ 48k sets/day. If an average set is
~100 MB of source plus ~30–50% in derived artifacts, daily ingest ≈ several TB; over 7 years
this accumulates to the low-PB range — confirming object-store + lifecycle tiering (R3) and
ruling out DB/filesystem blob storage. Worker count is driven by per-set processing time ×
peak arrival rate; per-page parallelism keeps large sets from head-of-line blocking.

**Alternatives considered**: precise capacity modeling deferred to load testing; these
figures only validate the storage/processing architecture class, not exact provisioning.

---

## Resolved unknowns

All Technical Context items are resolved; **no `NEEDS CLARIFICATION` markers remain**. The
spec's single open question (access model) was resolved upstream to **org/project teams**
and is reflected in R9.
