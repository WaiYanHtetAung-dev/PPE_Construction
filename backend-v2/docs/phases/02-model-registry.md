# Phase 2 — Model registry, versioning and camera assignment API

**Status:** PLANNED — do not assume implementation or test success.

## Scope and deliverables

Build admin-only catalog registration, listing and camera-level model assignment. Only metadata in backend. Resolve global-vs-tenant policy before coding.

## Design decisions and prerequisites

Decide global curated catalog vs per-org catalog; preserve uniqueness semantics, add audits and unassign/rollback behavior. No weight loading.

**Critical note:** Existing model_versions table lacks organization_id; org-scoped API cannot be built safely without an explicit policy.

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
| P2-01 | Register approved model | Admin and permitted artifact registry configured | Create model_key/version with valid sha256 and authorized artifact_ref | 201 or specified success, typed response and audit |
| P2-02 | Reject invalid artifact | Admin authorized | Submit malformed digest or arbitrary external URL | 422/4xx; no model loaded or fetched |
| P2-03 | Duplicate version conflict | Same model_key and version exist | Register duplicate model | 409 and unchanged existing record |
| P2-04 | Role denial | Operator/viewer logged in | Create or reassign model when admin-only | Denied with no changes or audit of mutation |
| P2-05 | Cross-tenant model denied | User Org A, camera Org B | Assign global/disallowed model to Org B camera | Denied, ownership checked via site and camera |
| P2-06 | Assign camera model | Admin controls camera and approved model | Assign, then retrieve model selection | Exact version persisted, GET returns matching metadata |
| P2-07 | Rollback model selection | Camera was changed V1→V2 | Reassign to known V1 | Assignment returns V1 and audit trail is complete |
| P2-08 | Atomic conflict handling | Two admins update same camera concurrently | Submit competing assignments with expected version/locking policy | Result matches documented concurrency rule; no torn state |

## Exit criteria

- [ ] All required cases for this phase run and their results are documented (not just specified).
- [ ] Negative auth/tenant/secret cases included for changed routes and workers.
- [ ] CI green, PostgreSQL migrations validated, contracts reviewed and exported if changed.
- [ ] A reviewer approves the security, privacy and migration impacts.
- [ ] Handoff and rollback notes recorded in `docs/PR_TEMPLATE.md`.

See also `tests/specs/P2_ACCEPTANCE.md` for scenario checkboxes and execution evidence template.
