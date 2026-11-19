# Phase 8 — Controlled V1 data migration, shadow trial, canary production cutover

**Status:** PLANNED — do not assume implementation or test success.

## Scope and deliverables

Offline V1 mapping, idempotent importer, source/target validation, shadow traffic, phased release and rollback drills.

## Design decisions and prerequisites

Back up V1, never merge changes into V1 blindly, document network/migration cutover and approval.

**Critical note:** This phase requires separate explicit human release authorization.

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
| P8-01 | Source backup | V1 DB/image data available offline | Create backup and restore it | Successful restoration and verified hashes/counts |
| P8-02 | Dry-run mapping | Sanitized V1 source snapshot | Run importer dry-run | Deterministic report, ambiguous rows flagged |
| P8-03 | Idempotent import | Same V1 snapshot already imported in test target | Run import twice | No duplicate users/cameras/incidents/evidence |
| P8-04 | Credential handling | Legacy usernames/sessions present | Migrate identities | No raw V1 session token reused; reset or approved process |
| P8-05 | Evidence parity | Historical thumbnails available | Migrate object and verify digest | Evidence backed by object key, checksums match |
| P8-06 | Reconciliation | Source/target snapshots prepared | Compare counts, samples, exceptions | Approved mismatch ledger; no silent loss |
| P8-07 | Shadow mode | V1 serving production while V2 monitors shadow | Enable V2 without notification sends | No double-notify; compare model incidents |
| P8-08 | Canary camera/site | Approved trial subset | Route limited site to V2 | Acceptable measured incident/latency behavior |
| P8-09 | Rollback rehearsal | Canary active and rollback trigger simulated | Switch site back to V1 | Documented rollback completes with data integrity |
| P8-10 | Release approval | All previous gates pass | Request final deployment authorization | Human sign-off recorded, deployment only then permitted |

## Exit criteria

- [ ] All required cases for this phase run and their results are documented (not just specified).
- [ ] Negative auth/tenant/secret cases included for changed routes and workers.
- [ ] CI green, PostgreSQL migrations validated, contracts reviewed and exported if changed.
- [ ] A reviewer approves the security, privacy and migration impacts.
- [ ] Handoff and rollback notes recorded in `docs/PR_TEMPLATE.md`.

See also `tests/specs/P8_ACCEPTANCE.md` for scenario checkboxes and execution evidence template.
