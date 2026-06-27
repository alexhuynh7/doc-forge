<!--
SYNC IMPACT REPORT
==================
Version change: TEMPLATE (unversioned) → 1.0.0
Rationale: Initial ratification of the Doc-Forge constitution (MAJOR baseline).

Modified principles: N/A (initial adoption)
Added principles:
  - I. Page-Latency Performance Budget (NON-NEGOTIABLE)
  - II. Test-First & Comprehensive Coverage (NON-NEGOTIABLE)
  - III. Modular, Layered Architecture
  - IV. Durability, Integrity & Legal Retention
  - V. Horizontal Scalability & Stateless Services
Added sections:
  - Technology & Performance Standards
  - Development Workflow & Quality Gates
  - Governance

Templates requiring updates:
  - .specify/templates/plan-template.md ............ ✅ reviewed (Constitution Check gate aligns; no edit needed)
  - .specify/templates/spec-template.md ............ ✅ reviewed (mandatory sections compatible; no edit needed)
  - .specify/templates/tasks-template.md ........... ✅ reviewed (test-task categories already present; no edit needed)
  - .specify/templates/checklist-template.md ....... ✅ reviewed (no principle references; no edit needed)
  - README.md ...................................... ⚠ pending (placeholder content; update when project scope is documented)

Deferred TODOs: none. RATIFICATION_DATE set to initial adoption date 2026-06-27.
-->

# Doc-Forge Constitution

Doc-Forge stores, retrieves, and serves large construction-plan PDF document sets
(5 MB to 2 GB+) for 50,000 active users at a peak of ~2,000 document-set uploads per
hour, with a 7-year legal retention obligation. These principles are binding on every
design decision, code change, and review.

## Core Principles

### I. Page-Latency Performance Budget (NON-NEGOTIABLE)

Any individual page of any document MUST be retrievable and renderable in the user's
browser in under 2 seconds (p95), independent of the source document's total size.

- Documents MUST NOT be served whole for page-level viewing; serving paths MUST operate
  on per-page (or per-tile) artifacts so that a 2 GB document and a 5 MB document have
  the same page-open cost.
- Page artifacts MUST be precomputed asynchronously at ingest time, not on the request
  path. The read path MUST be a cache/CDN/object-store lookup, never a synchronous
  render of the source PDF.
- Every change touching the read path MUST be accompanied by a latency measurement
  (benchmark or load-test result) demonstrating the p95 < 2s budget still holds.
- Rationale: Sub-2s page render is the product's primary contract with users; it is the
  constraint that shapes storage layout, ingestion, and serving, so it is enforced as a
  hard gate rather than a goal.

### II. Test-First & Comprehensive Coverage (NON-NEGOTIABLE)

Behavior MUST be specified by automated tests before or alongside the code that
implements it; untested logic is treated as broken.

- Every public function, service boundary, and module MUST have unit tests. Business
  logic and data-transformation code MUST achieve meaningful branch coverage, not just
  line coverage.
- Tests MUST be written so they fail before the implementation exists (Red-Green-Refactor);
  a passing test that never failed is not evidence of correctness.
- Ingestion, storage, retrieval, and retention logic MUST additionally have integration
  tests against realistic fixtures (including large and multi-page documents).
- CI MUST run the full test suite on every change; merges are blocked on a green suite.
- Rationale: The user demands strong architecture with unit tests; at this scale and with
  a 7-year retention liability, regressions are expensive and must be caught mechanically.

### III. Modular, Layered Architecture

The system MUST be decomposed into independently testable modules with explicit
boundaries and unidirectional dependencies.

- Core domain logic (document modeling, page indexing, retention rules) MUST NOT depend
  on framework, transport, or storage-vendor details; those MUST sit behind interfaces.
- Storage backends (object store, cache, metadata DB) MUST be accessed through
  abstractions so they can be swapped or mocked in tests without touching domain code.
- Each module MUST have a single, clearly stated responsibility; "utility" or
  "organizational-only" modules with no cohesive purpose are prohibited.
- Rationale: Clean layering is what makes the test-first principle achievable and lets the
  performance- and scale-critical components evolve independently.

### IV. Durability, Integrity & Legal Retention

No document or page artifact may be lost, silently corrupted, or deleted before its legal
retention window expires.

- All documents MUST be retained for a minimum of 7 years from upload; deletion or
  overwrite before expiry MUST be technically prevented (e.g. immutability/object-lock),
  not merely policy.
- Stored artifacts MUST carry integrity verification (checksums/content hashes) verified
  on write and on read; integrity failures MUST be detectable and reported.
- Ingestion MUST be idempotent and atomic: a partially uploaded or partially processed
  document set MUST NOT become visible as if complete.
- Retention, deletion-eligibility, and integrity behaviors MUST be covered by automated
  tests.
- Rationale: Retention is a legal requirement, and at 2 TB-scale daily ingest, integrity
  and durability cannot rely on manual vigilance.

### V. Horizontal Scalability & Stateless Services

Services MUST scale out to absorb 50,000 active users and ~2,000 document-set uploads per
hour without architectural rework.

- Application/service tiers MUST be stateless; session, progress, and coordination state
  MUST live in shared stores (cache, queue, DB), never in process memory.
- Upload and page-generation work MUST be decoupled from the request path via queues so
  that ingest spikes degrade throughput gracefully, never availability.
- The system MUST expose health, throughput, and latency metrics sufficient to drive
  autoscaling and to detect breaches of Principle I.
- Rationale: The stated load is the design point, not the limit; statelessness and
  async decoupling are what let capacity be added by adding instances.

## Technology & Performance Standards

- Backend MUST be implemented in Python; the public API surface MUST be explicitly
  versioned and documented.
- Frontend, where built, MUST be implemented in React; the frontend is a consumer of the
  documented API and MUST NOT embed business rules that belong in the backend.
- Large object storage MUST use an object store (e.g. S3-compatible) with lifecycle and
  immutability/retention controls; metadata MUST live in a queryable datastore separate
  from blob storage.
- Page-level serving MUST be fronted by a CDN/edge cache; cache keys MUST be page- (or
  tile-) granular.
- Performance budgets are explicit and testable: page-open p95 < 2s; ingestion MUST
  sustain ≥ 2,000 document sets/hour peak without backlog growth that breaches Principle I.

## Development Workflow & Quality Gates

- Every change MUST pass: linting/formatting, the full automated test suite, and a
  Constitution Check confirming no principle is violated.
- Any change to a read-path component MUST include or update a latency check (Principle I).
- Any change to ingestion, storage, or retention MUST include or update durability and
  retention tests (Principle IV).
- Code review MUST explicitly verify compliance with these principles; a reviewer MUST
  reject changes that trade away the performance budget, test coverage, or retention
  guarantees without an approved, documented exception.
- Deviations from a principle MUST be justified in writing in the change description and
  approved before merge; undocumented complexity is grounds for rejection.

## Governance

This constitution supersedes other practices and conventions where they conflict.

- Amendments MUST be proposed via a change that updates this file, states the rationale,
  and is reviewed and approved before merge.
- Versioning of this constitution follows semantic versioning: MAJOR for
  backward-incompatible principle removals/redefinitions, MINOR for new principles or
  materially expanded guidance, PATCH for clarifications and wording fixes.
- All pull requests and reviews MUST verify compliance with the principles above; the
  NON-NEGOTIABLE principles (I and II) admit no exception.
- Compliance is re-validated at every Constitution Check gate defined in the planning and
  task templates under `.specify/templates/`.

**Version**: 1.0.0 | **Ratified**: 2026-06-27 | **Last Amended**: 2026-06-27
