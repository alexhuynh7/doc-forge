# Phase 1 Data Model: Large Construction-Plan Document Storage & Page Serving

Derived from the spec's Key Entities and Functional Requirements. Field types are logical
(implementation maps these to Postgres columns / object-store keys). Blob bytes live in the
object store; everything below is metadata in PostgreSQL unless noted.

## Entity overview & relationships

```text
Team 1───* Membership *───1 User
Team 1───* DocumentSet 1───* Document 1───* Page 1───* PageArtifact
DocumentSet 1───1 RetentionRecord
DocumentSet 1───* AuditEvent
UploadSession *───1 DocumentSet (becomes, on finalize)
```

## Team
The unit of ownership and access control.

| Field | Type | Notes |
|-------|------|-------|
| id | UUID (PK) | |
| name | string | |
| created_at | timestamp | |

## User
| Field | Type | Notes |
|-------|------|-------|
| id | UUID (PK) | |
| email | string (unique) | |
| created_at | timestamp | |

## Membership
Join entity granting a user access to a team's document sets (FR-013/FR-015).

| Field | Type | Notes |
|-------|------|-------|
| user_id | UUID (FK→User) | PK part |
| team_id | UUID (FK→Team) | PK part |
| role | enum(`member`,`admin`) | admin may manage membership |
| created_at | timestamp | |

## DocumentSet
The top-level uploaded/retrieved unit (FR-001, FR-003).

| Field | Type | Notes |
|-------|------|-------|
| id | UUID (PK) | |
| team_id | UUID (FK→Team) | owner; access checks key on this |
| uploaded_by | UUID (FK→User) | |
| title | string | |
| status | enum(`uploading`,`processing`,`ready`,`failed`,`quarantined`) | FR-011; viewable only when `ready` |
| document_count | int | |
| uploaded_at | timestamp | retention clock start (FR-007) |
| ready_at | timestamp \| null | when processing completed |
| failure_reason | string \| null | FR-012 |

**Validation / rules**: A set is only listable/viewable when `status = ready` (FR-003 atomic
visibility). `status` transitions are one-directional except `processing→failed`/`ready`.

## Document
An individual PDF within a set (FR-001).

| Field | Type | Notes |
|-------|------|-------|
| id | UUID (PK) | |
| set_id | UUID (FK→DocumentSet) | |
| filename | string | |
| size_bytes | bigint | 5 MB–2 GB+ |
| page_count | int | |
| source_object_key | string | object-store key of original PDF (WORM-locked) |
| sha256 | char(64) | integrity (FR-006), verified on write & re-verifiable on read |
| order_index | int | position within set |

## Page
An individually addressable, individually viewable unit (FR-004, FR-014). This is the entity
the read path resolves.

| Field | Type | Notes |
|-------|------|-------|
| id | UUID (PK) | |
| document_id | UUID (FK→Document) | |
| page_number | int | 1-based; `(document_id, page_number)` UNIQUE + indexed |
| width_px | int | rendered display dimensions |
| height_px | int | |
| status | enum(`pending`,`ready`,`failed`) | per-page processing state |

**Rules**: `(document_id, page_number)` is unique and indexed — the hot lookup for page
serving. Page ordering is immutable once `ready` (FR-014).

## PageArtifact
The precomputed, CDN-served renderings of a page (research R1). Bytes live in object store.

| Field | Type | Notes |
|-------|------|-------|
| id | UUID (PK) | |
| page_id | UUID (FK→Page) | |
| kind | enum(`display_image`,`thumbnail`,`dzi_descriptor`,`tile`) | |
| object_key | string | immutable, content-addressed object-store key |
| level | int \| null | pyramid level for `tile`/`dzi` |
| sha256 | char(64) | integrity |
| bytes | int | |

**Rules**: artifacts are immutable once written → safe for long-lived CDN caching (R7).

## RetentionRecord
Durability/compliance state for a set (FR-007, FR-008).

| Field | Type | Notes |
|-------|------|-------|
| set_id | UUID (PK, FK→DocumentSet) | |
| retain_until | date | = uploaded_at + 7 years; enforced by Object Lock at storage layer |
| object_lock_mode | enum(`compliance`) | WORM mode applied to objects |
| legal_hold | bool | optional extension beyond 7 yr |

**Rules**: deletion before `retain_until` MUST be rejected (FR-007) and the attempt logged
as an `AuditEvent` (FR-008). The authoritative guarantee is the storage-layer Object Lock;
this record mirrors it for query/audit.

## AuditEvent
Auditable history of retention-relevant actions (FR-008).

| Field | Type | Notes |
|-------|------|-------|
| id | UUID (PK) | |
| set_id | UUID (FK→DocumentSet) | |
| event_type | enum(`upload_accepted`,`processing_completed`,`deletion_attempt_blocked`,`deleted_after_expiry`,`integrity_check`) | |
| actor_id | UUID \| null | user/system that triggered it |
| detail | json | e.g. checksum result |
| occurred_at | timestamp | |

## UploadSession
Tracks a resumable upload in progress (FR-002, research R5).

| Field | Type | Notes |
|-------|------|-------|
| id | UUID (PK) | |
| team_id | UUID (FK→Team) | |
| created_by | UUID (FK→User) | |
| storage_upload_id | string | object-store multipart/tus id |
| received_bytes | bigint | progress for resume |
| total_bytes | bigint \| null | |
| status | enum(`active`,`finalized`,`aborted`) | finalize → creates DocumentSet |
| expires_at | timestamp | abandoned sessions cleaned up |

## State transitions (DocumentSet)

```text
uploading ──finalize──▶ processing ──all pages rendered & checksummed──▶ ready
   │                        │
   └──abort──▶ (no set)     ├──invalid/corrupt PDF──▶ quarantined   (FR-012)
                            └──processing error──────▶ failed       (FR-011/FR-012)
```

Only `ready` sets are listable/viewable (FR-003). Pages within a `processing` set report
`pending` until their artifacts exist; requesting such a page returns "still processing"
rather than an error (spec edge case).
