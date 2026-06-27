# Contract: Asynchronous Processing Pipeline (Worker)

This is the internal contract for the async ingest pipeline (research R6). It is not an HTTP
API; it defines the queue messages and the guarantees each stage must uphold. Workers are
Celery tasks fed from the broker on upload finalize.

## Trigger

`POST /uploads/{id}/finalize` (see [openapi.yaml](openapi.yaml)) verifies the uploaded
bytes' SHA-256, creates a `DocumentSet` in status `processing`, and enqueues:

```json
{ "task": "process_document_set", "set_id": "<uuid>" }
```

## Stages & guarantees

| Stage | Task | Input | Output | Guarantee |
|-------|------|-------|--------|-----------|
| 1. Validate | `validate_set` | set_id | per-document validity | Reject/quarantine invalid, password-protected, or corrupt PDFs → set `quarantined` (FR-012); never proceed for invalid input |
| 2. Split | `split_documents` | set_id | Document + Page rows (page_count) | Establishes page identity & ordering (FR-014); idempotent on retry |
| 3. Render | `render_page[doc_id,page_no]` (fan-out, one per page) | page ref | display image + thumbnail (WebP) | O(1) per page; parallelizable so large sets don't head-of-line block |
| 4. Tile | `tile_page[doc_id,page_no]` | rendered raster | DZI descriptor + tile pyramid | Enables sub-2s deep zoom (R1) |
| 5. Store | (within 3/4) | artifacts | object-store keys + SHA-256 | Write to WORM bucket; checksum recorded (FR-006); artifact keys immutable |
| 6. Finalize | `finalize_set` | set_id | set → `ready`, `ready_at` set | **Atomic visibility**: set flips to `ready` only after ALL pages `ready` (FR-003); writes `processing_completed` AuditEvent |

## Idempotency & retries

- Every task MUST be idempotent (safe to retry): re-rendering a page overwrites by a
  deterministic object key; DB upserts keyed on `(document_id, page_number)`.
- A failed page after max retries sets that page `failed`; `finalize_set` marks the set
  `failed` with a `failure_reason` (FR-011/FR-012) rather than leaving it half-visible.

## Backpressure (FR-009, Principle V)

- The queue absorbs the 2,000-sets/hour peak; workers autoscale on queue depth.
- No submission is dropped: finalize always persists the set + enqueues before returning
  `202`. If workers lag, sets simply remain `processing` longer — availability and read
  latency are unaffected.

## Retention application (FR-007, Principle IV)

- On first store of any object for a set, apply Object Lock (Compliance) with
  `retain_until = uploaded_at + 7 years`; mirror into `RetentionRecord`.
- Deletion requests before `retain_until` are rejected by the storage layer; the API returns
  `423 Locked` and writes a `deletion_attempt_blocked` AuditEvent (FR-008).
