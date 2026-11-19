# Backend V2 Work Backlog

**Not proof of completion** — update only from actual code/test evidence and reviewed decisions. A phase may span multiple PRs.

| ID | Phase | Task | Current state | Dependency / gate |
|---|---|---|---|---|
| V2-P1-GATE | 1 | Verify PostgreSQL migrations and base CI | Unverified | Disposable PostgreSQL; CI evidence |
| V2-P2-DESIGN | 2 | Resolve ADR-004 global vs tenant model registry | Done | Option A approved and recorded |
| V2-P2-API1 | 2 | Add publisher grant, immutable registration and transactional platform audit | Implemented; local and hosted checks passed | Human review pending |
| V2-P2-API2 | 2 | Eligible catalog list/detail, then per-camera assignment GET/PUT, audit, rollback and concurrency tests | Implemented; local and hosted checks passed | Human review pending |
| V2-P2-GATE | 2 | P2-01 to P2-08 acceptance, PostgreSQL migration, CI and review | Eligibility fix locally verified; human review pending | Hosted fix CI and reviewer approval. Production key/mount/role and inference rollout controls stay gated. |
| V2-P2.5-INFERENCE | 2.5 | Independent inference worker, fail-closed eligibility leases and compatible rollback | Implemented and locally verified | Hosted PR checks and named human review. Production adapter and workload controls remain gated. |
| V2-P2.6-API1 | 2.6 | CPU ONNX adapter, offline export and Finalboss detection parity | Adapter and synthetic tests complete; real parity blocked | Approved exporter image/wheel lock, rights clearance and approved real fixture corpus |
| V2-P3 | 3 | Authenticated idempotent incident ingestion, state machine and outbox | Planned | Approved Phase 3 ADR, Phase 2 contract gate |
| V2-P4 | 4 | Media gateway / stream lifecycle / bounded inference bridge | Planned | Approved trust boundary + topology |
| V2-P5 | 5 | Evidence, durable jobs, realtime notifications, reports | Planned | Storage privacy/retention decisions |
| V2-P6 | 6 | React frontend consumption of versioned API | Planned | Reviewed API and evidence contracts |
| V2-P7 | 7 | Security, telemetry, failure injection and performance validation | Planned | Representative infrastructure |
| V2-P8 | 8 | V1 migration/canary/release/rollback | Planned | Human release approval |

## Working agreement

Codex should pick **one** task ID at a time, map it to `docs/phases/` and `tests/specs/`, and update this table only after actual evidence. Tasks do not advance to Done just because code is generated.

## V2-P2-API1 implementation

1. Add an Alembic revision for explicit platform publisher grants, version eligibility and platform registration audit. Existing and new versions start ineligible. Eligibility transition requires standalone artifact provenance and checksum verification.
2. Add restricted CLI grant and revocation operations. Check the grant server-side and keep organization roles independent.
3. Add a typed publisher-only registration endpoint. Validate opaque approved references, digest format and class map. Insert immutable metadata and its audit event in a single transaction. Return a conflict for duplicate global version identities.
4. Automate P2-01 through P2-04 for registration, including a PostgreSQL duplicate race and audit-write failure rollback. Run Alembic upgrade and drift checks on disposable PostgreSQL and review the additive OpenAPI diff.

Follow with an independent organization catalog list/detail slice, then camera assignment, rollback and history with P2-05 through P2-08.
