# Architecture Decision Log (ADRs)

| ID | Decision | State | Rationale / risk |
|---|---|---|---|
| ADR-001 | FastAPI modular business backend separate from media/AI | Adopted for V2 | Can change/restart APIs without loading GPU models |
| ADR-002 | PostgreSQL + SQLAlchemy + Alembic | Adopted for V2 | Transactional records/migrations; test on real PG |
| ADR-003 | Versioned JSON inference request/response | Adopted at contract level | Adapter can swap models while preserving canonical classes |
| ADR-004 | Globally curated registry with tenant-scoped camera assignments | **Approved (2026-11-18)** | Global version identity and separate publishing and assignment permissions |
| ADR-005 | Incident state, dedup window, idempotency and outbox | OPEN (Phase 3) | Prevent double alerts and data loss |
| ADR-006 | Media topology VPN pull vs edge outbound push | OPEN (Phase 4) | Router-only cloud pull requires site connectivity |
| ADR-007 | Evidence retention and privacy controls | OPEN (Phase 5) | Significant storage/security/legal implications |
| ADR-008 | Actual FPS/latency/availability SLOs | OPEN (Phase 7) | Needs representative 50–100 camera benchmark |

## ADR-004 — Globally curated model registry

The project owner approved Option A on 2026-11-18. The stack is FastAPI, PostgreSQL, SQLAlchemy 2.x, Alembic, Pydantic v2 and Pytest, with a separate AI inference service.

- Keep `(model_key, version)` globally unique. Only authorized platform publishers may register versions. Provision grants through a restricted administrative CLI. Organization admin membership confers no platform publishing authority.
- Organization admins may view and assign eligible versions. Validate the caller's membership and the camera → site → organization relationship server-side. Scope current selection, history and audit records to the camera's organization.
- Artifact references, digests and class maps are immutable after publishing. Register a new version to change any of these fields. Accept approved opaque artifact references and validate digest format. Artifact retrieval, byte-level checksum verification and model loading belong to the independent inference service.
- Support assignment, switching and rollback to an eligible version with optimistic concurrency via `expected_revision`. Persist selection, revision, append-only history and audit in one transaction. Rollback adds a history entry.
- Use new Alembic revisions for publisher grants, registry eligibility and platform audit, then assignment revision and history. Review existing artifact provenance before enabling eligibility. Preserve the inference contract and keep YOLO, OpenCV and PyTorch outside FastAPI.

Organization-owned catalogs would require ownership backfill, tenant-aware uniqueness and downstream tenant-aware version resolution. Revisit ownership if private catalogs or tenant-specific model licensing become requirements. Application rollback should preserve committed audit and history data.

Phase 2 acceptance evidence is pending. See [P2-01 through P2-08](../tests/specs/P2_ACCEPTANCE.md).

## ADR record template

- **Context:**
- **Alternatives considered:**
- **Decision and reviewers:**
- **Consequences:**
- **Test evidence:**
- **Rollback / revisit trigger:**
