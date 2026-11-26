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
| ADR-009 | Workload-scoped camera assignment snapshots | **PENDING APPROVAL** | Define camera authorization, assignment freshness, and revocation ordering before gateway sync |

## ADR-004 — Globally curated model registry

The project owner approved Option A on 2026-11-18. The stack is FastAPI, PostgreSQL, SQLAlchemy 2.x, Alembic, Pydantic v2 and Pytest, with a separate AI inference service.

- Keep `(model_key, version)` globally unique. Only authorized platform publishers may register versions. Provision grants through a restricted administrative CLI. Organization admin membership confers no platform publishing authority.
- Organization admins may view and assign eligible versions. Validate the caller's membership and the camera → site → organization relationship server-side. Scope current selection, history and audit records to the camera's organization.
- Artifact references, digests and class maps are immutable after publishing. Register a new version to change any of these fields. Accept approved opaque artifact references and validate digest format. Artifact retrieval, byte-level checksum verification and model loading belong to the independent inference service.
- Support assignment, switching and rollback to an eligible version with optimistic concurrency via `expected_revision`. Persist selection, revision, append-only history and audit in one transaction. Rollback adds a history entry.
- Use new Alembic revisions for publisher grants, registry eligibility and platform audit, then assignment revision and history. Review existing artifact provenance before enabling eligibility. Preserve the inference contract and keep YOLO, OpenCV and PyTorch outside FastAPI.

Organization-owned catalogs would require ownership backfill, tenant-aware uniqueness and downstream tenant-aware version resolution. Revisit ownership if private catalogs or tenant-specific model licensing become requirements. Application rollback should preserve committed audit and history data.

Phase 2 acceptance evidence is pending. See [P2-01 through P2-08](../tests/specs/P2_ACCEPTANCE.md).

## ADR-009 proposal — Workload-scoped camera assignment snapshots

**Status:** PENDING APPROVAL. This proposal introduces no endpoint, permission,
credential, or runtime behavior. Review it with the project owner and the
control-plane and model-security owners before implementing the resolver.

### Current boundaries

- The existing camera assignment GET, PUT and history APIs require a human
  organization-admin session and validate camera ownership through the site's
  organization. GET returns the chosen model and revision even when that model
  later loses eligibility. The model catalog filters for current eligibility,
  but does not return a camera binding or class map. Combining these reads with
  an admin token would grant excess authority and allow a race between reads.
- The worker eligibility authority issues a short-lived lease for model
  key/version and signed evidence. It has a dedicated service credential and
  restricted PostgreSQL grants. It cannot attest to a camera, site, tenant, or
  assignment revision.
- Verification revocation does not advance the camera's selection revision.
  A fresh verification can make the same model UUID eligible again under the
  existing evidence rules. Assignment revision alone is insufficient to order
  eligibility changes.

### Proposed control-plane read and credential

Add a private read-only snapshot operation owned by the control plane. Give the
gateway a dedicated, audience-scoped workload identity bound server-side to an
explicit organization, site and camera scope. Review credential provisioning,
rotation, revocation, error disclosure and production role grants before use.
Only the existing human API performs registration and assignment writes. Keep
gateway access over a configured HTTPS origin with certificate verification,
redirects disabled, bounded response size, and explicit request deadlines.
Keep database credentials, model artifact paths, and worker-authority credentials
out of the gateway.

Validate the provisioned camera → site → organization chain and read the
assignment, immutable class map and current verification evidence at one
authoritative database snapshot. Reuse the existing registry and eligibility
view. Proposed response fields are an explicit eligible or denied state, org,
site and camera IDs, assignment revision, model UUID/key/version, class map,
verification generation, issued and expiry timestamps, and a request nonce for
binding. The exact schema and negative status mapping need review. Responses
should be `no-store`. Do not change inference v1 or the worker's independent
artifact checks. The gateway must reject incompatible class maps before sending.

### Proposed consistency policy

- Serialize refresh per camera. Reject lower revisions and conflicting model
  identities at the same revision. Track the latest verification generation
  separately and prevent a delayed pre-revocation response from restoring a
  denied generation. Cross-camera notifications for shared models, denial
  ordering and same-version re-verification require an accepted policy.
- Use an explicit lease cap `T`, maximum healthy polling period `P`, and
  request deadline `D`. Bound lease use with a monotonic deadline measured
  from request start. An observed denial or failed refresh invalidates the
  local binding. An expired snapshot cannot be used even if a poll stops.
  Under healthy authoritative reads, the proposed observation window is at
  most `P + D`. `T`, `P`, `D`, clock tolerance and overload behavior are review
  inputs. No numerical revocation propagation bound is accepted or measured yet.
- Bind queued frames to the active assignment generation and drop affected
  pending frames on change or denial. Recheck generation before send and before
  emitting results. The worker currently revalidates eligibility before ONNX
  execution. Work already executing may finish. The proposed gateway discards
  a late result after local invalidation and does not promise global cancellation.

### Evidence required after approval

Test scoped service auth, malformed or expired snapshots, stale and overlapping
refreshes, an outage with recovery, three-camera switching and tenant isolation,
class-map compatibility, pre-send and in-flight revocation, and the documented
propagation bound. Test temporary models independently of Finalboss. Until then,
existing admin API and worker tests show independent boundaries only.

## ADR record template

- **Context:**
- **Alternatives considered:**
- **Decision and reviewers:**
- **Consequences:**
- **Test evidence:**
- **Rollback / revisit trigger:**
