# Phase 3 — Secure inference result ingestion and incident lifecycle

**Status:** PLANNED — do not assume implementation or test success.

## Scope and deliverables

Authenticated internal ingest, provenance, replay-safe idempotency, person/PPE association, temporal confirmation, event outbox and audit.

## Design decisions and prerequisites

Design class association, unknown status, tracking IDs, event key, state machine open/ack/resolved and retry behavior.

**Critical note:** Inference service only detects objects; business event worker decides incidents. Cross-tenant FKs must be validated.

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
