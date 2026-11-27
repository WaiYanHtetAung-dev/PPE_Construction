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
| ADR-009 | Workload-scoped camera assignment snapshots | **Approved for implementation and synthetic testing** | Production workload provisioning and live connectivity require separate authorization |

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

**Status:** **APPROVED** by the project owner for implementation and synthetic
testing. Production credential provisioning, live CCTV and deployment require
separate authorization.

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

### Approved decision

Use one private, read-only control-plane snapshot operation per camera.
Keep registration and writes on the existing ADR-004 admin APIs. A separate
internal listener owns the snapshot route. The gateway polls it directly over
configured HTTPS with certificate and hostname verification, no redirects or
environment proxies, a bounded body, and a total request deadline. Keep the
publisher, verifier, revoker, worker eligibility authority, registry and
inference v1 boundaries intact.

The alternatives are a human admin session, a worker-authority credential,
and a dedicated workload identity. Only the last option can supply camera
scope with a read-only grant. Defer push-based invalidation and batched reads
until the pilot shows that polling needs replacement.

### Workload identity and authorization

- Provision a stable gateway principal for one organization and an explicit
  allowlist of site/camera pairs. A gateway serving another organization uses a
  separate principal. The server binds the principal to its allowlist and the
  snapshot audience. Request IDs identify the desired resource only.
- Use a dedicated opaque bearer credential composed of a random key ID and a
  256-bit random secret. Store only a secret digest and metadata. Compare the
  digest in constant time. Resolve the credential on the trusted service side
  and recheck its active grant, audience, scope and time validity in the same
  authoritative statement as the snapshot. Keep plaintext credentials in a
  protected runtime secret. Gateway, worker ingress, worker authority and
  human session credentials have separate audiences and lifecycles.
- Use a restricted operator path to provision, rotate and revoke credentials
  with audit records containing principal/key ID, action and time. Proposed
  keys are valid for at most 24 hours, with at most two active keys per
  principal during up to 5 minutes of
  intentional overlap. Install and verify the replacement, then revoke the
  old key. On credential reload, clear the old binding epochs and poll with
  the replacement. Disabling a compromised key or principal denies new reads
  after the change commits. On `401`, clear bindings for the affected credential
  and require fresh authorization. Previously issued snapshots are bounded by
  their lease and also by the key's expiry.
- Use a read-only DB role for the snapshot listener with the minimum projection
  of credential state, authorized scope, current assignment and eligibility
  evidence. Provisioning and revocation writes use separate roles. Keep model
  artifact location, digest, database credentials and worker-authority
  credentials out of the gateway. Suppress request bodies, credential headers,
  exception bodies, SQL parameter values and detailed auth failures in logs.

### Snapshot API v1

`POST /internal/v1/camera-assignment-snapshots` is read-only in effect. POST
keeps the request nonce and resource tuple in a typed JSON body. Require explicit
`schema_version` (`"1.0"`), `organization_id`, `site_id`, `camera_id` and a fresh
UUID `nonce`. Scope is always validated server-side. Limit request bodies to
2 KiB and responses to 512 KiB. Every response includes `Cache-Control: no-store`.

| Response field | Type and invariant |
| --- | --- |
| `schema_version` | Literal `"1.0"`, required |
| `organization_id`, `site_id`, `camera_id`, `nonce` | UUIDs, exact request binding |
| `assignment_revision` | Integer `0..2^63-1`, committed camera revision |
| `decision` | `eligible`, `unassigned`, `camera_disabled`, `revoked`, `expired`, or `unverified` |
| `model` | `{model_version_id: UUID, model_key: string, version: string}` matching the current selection, or `null` when no model is selected |
| `class_map` | Eligible snapshots only. Immutable registry original-label to canonical `person`, `helmet`, or `vest` map using existing registry limits. `null` on denials. |
| `verification_generation` | Positive verification row ID for the selected model, or `null` when no evidence exists. Required for eligible, revoked and expired evidence. |
| `revoked_through_generation` | Largest revoked verification row ID for the selected model, or `null`. Include it even when a later generation is eligible. |
| `issued_at`, `expires_at` | Aware UTC timestamps from the database. Eligible expiry is the earliest of issuance + `T`, evidence expiry and credential expiry. Denials have `expires_at == issued_at`. |

Reject duplicate or unknown fields, unsupported versions, inconsistent
decision/nullability, invalid TTL and incompatible class maps. Apply a timely,
nonce-bound zero-lifetime denial even though it cannot authorize dispatch. A
map must match the gateway's trusted supported class profile before dispatch.
The worker independently verifies its eligible model and artifact. The
inference v1 response does not
echo a model UUID or the evidence generation, so the gateway's generation fence
tracks its own snapshot, not the generation used inside an already-started RPC.

| HTTP status | Meaning and gateway action |
| --- | --- |
| `200` | Scoped camera read. Only `eligible` can activate a binding. Any denial clears the camera binding. A definitive revocation also fences affected local bindings of the same model. |
| `401` | Missing, malformed, expired, revoked or wrong-audience credential. Uniform response. Clear bindings authenticated with that credential. |
| `404` | Camera absent, wrong tuple or outside scope. Uniform response. Clear the requested binding. |
| `422` | Structurally invalid body or unsupported version after authentication. Clear the requested binding. Requests over the body limit receive `413`. |
| `429`, `503` | Overload or unavailable authoritative state. Clear the requested binding. Retry at the next scheduled poll. |

Other unexpected statuses, timeouts and malformed responses fail closed. Error
bodies provide generic details and exclude scope, credentials and evidence.

### Atomic read and ordering

Use one fresh `READ COMMITTED` statement on the PostgreSQL primary per poll.
Join current credential and scope, camera → site → organization, assignment,
immutable model metadata, latest verification and revocation rows. Reuse the
existing eligibility view with explicit checks for camera enablement and
positive remaining evidence lifetime. Use the statement's issuance timestamp and
cap expiry as above. Serve the decision and its ordering fields from that
same MVCC snapshot. A revoked latest generation takes precedence over expiry.
Once a change commits, later primary statements observe it. An earlier
statement can still return a prior view of state. No replica or intermediary
cache is in the admission path.

- Maintain one refresh in flight per camera, a local refresh ticket and a new
  nonce. Ignore responses for superseded tickets before mutating state. A
  current response with a lower assignment revision or conflicting model
  identity at the same revision fails closed. Preserve the last known
  revision and identity across transient failures. A restored response at the
  same revision may renew otherwise unchanged, still eligible evidence.
- Maintain a separate newest-observed verification generation and revoked
  floor per model across the gateway's scoped cameras. Apply the floor before
  accepting an eligible response. A current response with a lower verification
  generation for the same model fails closed for that camera. An observed floor
  invalidates affected local bindings at or below that generation and fences
  replies still in flight. Observing newer evidence also invalidates bindings of older
  generations. Each camera must refresh under its own scope. New positive
  state is never copied between cameras.
- The existing promoter and revoker serialize per model and require evidence
  issued after revocation for re-verification. A newer authoritative eligible
  generation strictly above the floor may reactivate the same model UUID
  without advancing the camera revision. A current snapshot returns the floor
  even if revoke and re-verification both happened between polls. Thus a
  delayed response for the pre-revocation generation cannot reactivate it.
  Keep ordering state while matching provisioned bindings, pending frames or
  requests exist. Retire it only when these references are gone and future
  use requires a fresh primary read. Gateways restart with no positive
  snapshots and reacquire from the primary.

### Pilot timing and revocation bounds

| Setting | Proposed pilot value | Rationale |
| --- | --- | --- |
| `P` | 5 s maximum healthy start-to-start poll interval per camera | Stagger 2–3 cameras at 0.4–0.6 requests/s total and cap concurrency at one refresh per camera. |
| `D` | 2 s total request deadline | Includes connect, TLS, read and validation. A missed or failed slot has no inline retry. Resume at the next slot without a catch-up burst. |
| `T` | 10 s maximum positive snapshot lifetime | Gives 3 s over `P + D` while bounding use if polling stalls. Evidence or credential expiry can shorten it. |

Use a suspend-inclusive monotonic clock where supported. Fail closed on resume
and reacquire if the clock cannot account for suspension. The local deadline
is `request_start_monotonic + min(T, expires_at - issued_at)`, never response
receipt plus lifetime. Reject expired responses and check the deadline at
send and result emission. UTC is used for validating the server's lifetime,
with no client wall-clock subtraction in the admission deadline.

For a revocation that remains in effect, a healthy gateway with primary reads
and enforced `P` and `D` observes denial or fails closed within **7 s** of
commit. With missed polling or scheduling stalls, the last pre-commit grant
cannot authorize a new send or result emission after **10 s** from commit
under the expiry rule. Observed revocation blocks affected local dispatch
immediately before any next send decision. These are proposed local bounds,
not measured production SLOs. They exclude already-emitted responses and do
not promise instantaneous cross-gateway observation or cancellation of worker
compute. For re-verification between polls, apply the returned revoked floor
to older work and allow the newer generation only after a valid fresh poll.

Record committed-change to observed-denial time, last old-generation
send/emission, timeout count, and missed polling slots during acceptance.
Evaluate the worker authority's separate lease separately from gateway timing.
At 100 cameras, this polling policy implies 20 requests/s before overhead.
Benchmark query latency, pools, scheduling jitter and revocation bounds before
considering batched snapshots or invalidation notifications. Keep a single
primary read path and the same authorization and ordering semantics if scaling.

### Queue and in-flight policy

Admit a frame only with a usable snapshot and tag it with the camera's
current binding epoch.
An authorization loss, expiry, switch or verification generation change
increments the epoch and drops affected pending frames. Fresh frames after
reactivation may enter with the new epoch. An identical eligible refresh can
extend expiry within its new lease without changing the epoch. Preserve the
bounded queue and independent camera handling. Check epoch, model identity,
known revocation and expiry immediately before sending and again at the
downstream handoff. If handoff yields or queues asynchronously, carry the
epoch and recheck at actual emission. Discard late results across an invalidation
boundary and clean staged files on every path. A request already executing may
finish at the worker. Never retry it under a different assignment.

### Acceptance matrix and proposed file plan

| Layer | Deterministic acceptance cases |
| --- | --- |
| Unit, fake clocks and transport | Strict shape, nonce and scope echo; incompatible class map; `401` scope-wide invalidation; `404`/`422`/`429`/`503`, timeout and expiry fail closed; reject stale revision/generation and reordered responses; allow newer re-verification only with a fresh scoped poll; fail closed on suspend/resume; bounded queue, cleanup and redacted logs. |
| Disposable PostgreSQL | Read-only grants; human and worker tokens denied; scoped key rotation/expiry/revocation; wrong org/site/camera indistinguishable from absent; two connections with explicit barriers around assignment/revocation commits; no torn result; latest evidence and revoked floor present after revoke/reverify, with original publisher/verifier restrictions intact. |
| Synthetic gateway | Three cameras `A/A/B → B/A/B`; sibling independence, distinct frame/model attribution and pytest barriers for queued/in-flight invalidation; shared-model revoke before send and during a delayed response; outage and validated recovery; observe `P+D` and `T` with deterministic time and measure them on the isolated pilot; independent ONNX worker rejects ineligible model. Use generated fixtures only. |
| Regression and CI | Existing API and inference v1 snapshots, application tests, media suite and disposable PostgreSQL checks. Use the existing shared GitHub/GitLab commands. Actual GitLab Runner result remains separate. |

Use a fake-clock boundary test with the first poll at `t=0`, a revocation
just after that statement observes an eligible model, and the next poll
starting by `t=5`. Test denial or a deadline by `t=7`. In a separate case stop
polling and assert that the original lease denies sends and emissions at
`t=10`. Also test evidence with less than 2 s left at issue so a response may
arrive before the request deadline and still be too late to use.

Implementation files:

- `backend-v2/app/assignment_snapshot.py` and
  `backend-v2/app/contracts/assignment_snapshot.py` for the private listener
  and typed schema, with migration `4e29c61bd0fa` for gateway credentials,
  camera scope and the read projections.
- `backend-v2/media_gateway/assignment_resolver.py`, `frame_queue.py`, and
  `inference_dispatch.py` for refresh, epoch binding and result fencing.
- `backend-v2/tests/test_assignment_snapshot.py` and
  `tests/media_assignment_integration.py` for deterministic tests. Wire them
  through `backend-v2/scripts/ci_checks.py` and record results in the media
  phase documentation.

### Approval and rollback

The owner approved the private listener, PostgreSQL projection and role
boundaries, scoped identity and credential lifecycle, v1 schema and negative
statuses, pilot timing assumptions and queue/revocation policy for implementation
and synthetic tests. If rolled back, disable the
new listener and revoke its keys. Keep existing assignments and history, and
require fresh authorization before resuming gateway dispatch.

## ADR record template

- **Context:**
- **Alternatives considered:**
- **Decision and reviewers:**
- **Consequences:**
- **Test evidence:**
- **Rollback / revisit trigger:**
