# Phase 3 — Secure inference result ingestion and incident lifecycle

**Status:** Private ingestion and transactional outbox slice implemented. Lifecycle transitions, PPE association rules, workload rotation verification, and delivery remain open.

## Scope and deliverables

Authenticated internal ingest, provenance, replay-safe idempotency, person/PPE association, temporal confirmation, event outbox and audit.

## Design decisions and prerequisites

Design class association, unknown status, tracking IDs, event key, state machine open/ack/resolved and retry behavior.

**Critical note:** Inference service only detects objects; business event worker decides incidents. Cross-tenant FKs must be validated.

### ADR-005 first ingestion slice, pending review

- Run ingestion as a private FastAPI entry point. Authenticate a dedicated rules workload with a secret mounted at runtime. Keep browser sessions and inference-worker credentials outside this trust boundary.
- Accept an already-confirmed violation with an event UUID, observation timestamp, organization/site/camera IDs, and violation type. Validate the resource chain in one database query before writing. Treat the rules worker as the source of confirmed events; keep frame-level classification and unknown-state decisions in that worker.
- Store a canonical payload fingerprint with the event UUID. Identical retries return the existing incident ID. Reusing the UUID with a different payload returns a conflict. Enforce the UUID with a unique database constraint to cover concurrent delivery.
- Commit the incident and its pending outbox message in one transaction. Retain the idempotency record through the agreed retry horizon, including after downstream delivery. Keep notification delivery and incident lifecycle transitions as separately tested slices.
- Test the duplicate race and rollback on disposable PostgreSQL. Keep the existing public `/api/v1` OpenAPI surface unchanged and document the private contract separately.

### Private endpoint contract

The separate ASGI factory is `app.incident_ingestion:from_environment`. Configure
`INCIDENT_INGESTION_TOKEN_FILE` with the path of a mounted credential containing
32–256 printable ASCII characters. Expose this listener only on the trusted
workload network with TLS termination. The authorized rules workload is trusted
to submit events across the organizations it serves. Keep this credential
separate from user and inference credentials.

`POST /internal/v1/incidents` takes `event_id`, `organization_id`, `site_id`, and
`camera_id` UUIDs, a timezone-aware `detected_at`, and a lowercase snake-case
`violation_type`. It returns `201` on initial acceptance, `200` for an identical
replay (both with `incident_id`), `409` for conflicting reuse, `404` for a resource
binding mismatch, `401` for missing or invalid credentials, and `422` for an
invalid body. The event UUID must be generated once per confirmed violation and
reused on retry. Pending outbox entries have a null `published_at`.

Migration `81c540a1d2f6` adds the outbox table. Stop the private listener to
roll back application traffic while retaining incidents and outbox records.
Downgrading the schema deletes unsent entries and their idempotency records.

From `backend-v2`, run `python -m pytest -q tests/test_incident_ingestion.py`.
The PostgreSQL race test uses `PPE_DISPOSABLE_POSTGRES_URL` after Alembic upgrade
on the ephemeral CI database.

## Execution plan

1. Read architecture, ERD and relevant current API + inference contracts. Compare real code to planned endpoints.
2. Write an ADR/design proposal for any missing ownership, security, consistency or networking decision.
3. Define typed contracts + migration plan before implementation.
4. Implement smallest vertical slice on feature branch and add tests with mocked external services.
5. Run local tests and CI, inspect PostgreSQL migration and contract diffs.
6. Complete documented acceptance cases, attach evidence, list blockers and obtain review before next phase.

## Acceptance test cases

| ID | Test | Given | When | Expected result |
|---|---|---|---|---|
| P3-01 | Service authentication | Internal endpoint deployed | Call without trusted service identity | 401/403; no event persisted |
| P3-02 | Ingest valid event | Authorized service and matching camera/site/org | Send valid versioned event with event_id | One incident/event and one outbox message committed |
| P3-03 | Idempotency replay | Same signed event_id previously ingested | Send it twice or retry after timeout | One business event; stable response; no double alert |
| P3-04 | Cross-tenant mismatch | Camera belongs Org B and request claims Org A | POST ingest payload | Rejected and no side effects |
| P3-05 | State transition | Existing open incident | Ack then resolve with authorized actors | Valid transitions; audit and timestamps created |
| P3-06 | Invalid transition | Resolved incident exists | Attempt invalid transition | 409/4xx; original state remains |
| P3-07 | Unknown/low-confidence inference | Incomplete PPE objects or low confidence | Evaluate rules against frame | No fabricated definite violation; explicit unknown policy |
| P3-08 | Transaction failure | DB fault happens before outbox insert | Attempt ingest and restore DB | No partial incident/outbox commit; retry safe |
| P3-09 | Concurrent duplicate deliveries | Two workers replay identical event | Deliver concurrently | At most one persisted canonical event |
| P3-10 | Service identity rotation | Old workload credential has been revoked | Submit authenticated request using revoked identity | Rejected; new credential accepted |

## Exit criteria

- [ ] All required cases for this phase run and their results are documented (not just specified).
- [ ] Negative auth/tenant/secret cases included for changed routes and workers.
- [ ] CI green, PostgreSQL migrations validated, contracts reviewed and exported if changed.
- [ ] A reviewer approves the security, privacy and migration impacts.
- [ ] Handoff and rollback notes recorded in `docs/PR_TEMPLATE.md`.

See also `tests/specs/P3_ACCEPTANCE.md` for scenario checkboxes and execution evidence template.
