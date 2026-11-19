# Phase 2 Acceptance Checklist — Model registry, versioning and camera assignment API

> STATUS: P2-01 through P2-08 passed in [hosted run #2](https://github.com/WaiYanHtetAung-dev/PPE_Construction/actions/runs/44460576958) on `71b6fb5`. Approval is blocked by artifact eligibility enforcement; human review is pending.

| Case | Status | Evidence / link |
| --- | --- | --- |
| P2-01 — Register approved model | Passed (SQLite) | tests/test_platform_models.py |
| P2-02 — Reject invalid artifact | Passed (SQLite) | tests/test_platform_models.py |
| P2-03 — Duplicate version conflict | Passed (SQLite and PostgreSQL 17) | tests/test_platform_models.py |
| P2-04 — Role denial | Passed (SQLite) | tests/test_platform_models.py |
| P2-05 — Cross-tenant model denied | Passed (SQLite) | tests/test_camera_models.py |
| P2-06 — Assign camera model | Passed (SQLite) | tests/test_camera_models.py |
| P2-07 — Rollback model selection | Passed (SQLite) | tests/test_camera_models.py |
| P2-08 — Atomic conflict handling | Passed (PostgreSQL 17) | tests/test_camera_models.py |

## Given / When / Then scenarios

### P2-01 — Register approved model
- **Given:** Authorized platform publisher and approved artifact namespace configured
- **When:** Create model_key/version with valid sha256 and authorized artifact_ref
- **Then:** 201 or specified success, typed response and audit
- **Automation / test path:** tests/test_platform_models.py
- **Result:** Passed (SQLite)
- **Evidence date:** 2026-11-19

### P2-02 — Reject invalid artifact
- **Given:** Authorized platform publisher
- **When:** Submit malformed digest or arbitrary external URL
- **Then:** 422/4xx; no model loaded or fetched
- **Automation / test path:** tests/test_platform_models.py
- **Result:** Passed (SQLite)
- **Evidence date:** 2026-11-19

### P2-03 — Duplicate version conflict
- **Given:** Same model_key and version exist
- **When:** Register duplicate model
- **Then:** 409 and unchanged existing record
- **Automation / test path:** tests/test_platform_models.py
- **Result:** Passed (SQLite and PostgreSQL 17)
- **Evidence date:** 2026-11-19

### P2-04 — Role denial
- **Given:** Operator/viewer logged in
- **When:** Create or reassign model when admin-only
- **Then:** Denied with no changes or audit of mutation
- **Automation / test path:** tests/test_platform_models.py
- **Result:** Passed (SQLite)
- **Evidence date:** 2026-11-19

### P2-05 — Cross-tenant model denied
- **Given:** User Org A, camera Org B
- **When:** Assign global/disallowed model to Org B camera
- **Then:** Denied, ownership checked via site and camera
- **Automation / test path:** tests/test_camera_models.py
- **Result:** Passed (SQLite)
- **Evidence date:** 2026-11-19

### P2-06 — Assign camera model
- **Given:** Admin controls camera and approved model
- **When:** Assign, then retrieve model selection
- **Then:** Exact version persisted, GET returns matching metadata
- **Automation / test path:** tests/test_camera_models.py
- **Result:** Passed (SQLite)
- **Evidence date:** 2026-11-19

### P2-07 — Rollback model selection
- **Given:** Camera was changed V1→V2
- **When:** Reassign to known V1
- **Then:** Assignment returns V1 and audit trail is complete
- **Automation / test path:** tests/test_camera_models.py
- **Result:** Passed (SQLite)
- **Evidence date:** 2026-11-19

### P2-08 — Atomic conflict handling
- **Given:** Two admins update same camera concurrently
- **When:** Submit competing assignments with expected version/locking policy
- **Then:** Result matches documented concurrency rule; no torn state
- **Automation / test path:** tests/test_camera_models.py
- **Result:** Passed (PostgreSQL 17)
- **Evidence date:** 2026-11-19

## Catalog-read regression evidence

The SQLite tests in `tests/test_model_catalog.py` passed. They cover eligibility, pagination, invalid input, missing sessions, publisher and lower-role denial, and foreign organization denial. This supplements P2-04 and P2-05. Camera assignment evidence is listed below.

## 2026-11-19 camera assignment evidence

| Case | Local result | Evidence |
| --- | --- | --- |
| P2-05 | Passed (SQLite) | `test_assignment_access_and_validation` rejects foreign cameras, ineligible models and invalid or unauthorized requests. |
| P2-06 | Passed (SQLite) | `test_assignment_switch_rollback_unassign_and_history` confirms current selection and revision via GET. |
| P2-07 | Passed (SQLite) | Switching back appends history. `test_assignment_rolls_back_on_audit_failure` verifies transaction rollback. |
| P2-08 | Passed (PostgreSQL 17) | `test_postgres_concurrent_assignments_and_append_only_history` checks first and existing assignment races and direct history mutation rejection. |

All tests above are in `tests/test_camera_models.py`. Phase closure requires resolution of the eligibility blocker and human sign-off.

## Hosted CI evidence

| Criteria | Hosted job and scope |
| --- | --- |
| P2-01 to P2-07 | unit-contract-security, SQLite API/contract suite, 45 passed and 2 PostgreSQL-only skips |
| P2-03 and P2-08 | postgres-migration, PostgreSQL 17 duplicate and camera update races, 2 passed. Also checks immutable model fields and append-only history. |

P2-01 tests metadata registration and audit. It does not test artifact retrieval, verification or eligibility promotion. P2-04 covers application authorization and grant logic. PostgreSQL role provisioning was not exercised end to end. P2-06 retrieval and the P2-07 rollback flow were tested over HTTP with SQLite.

## Human-review checklist

- [ ] Enforce eligibility only after verified artifact evidence is recorded. Prove an ordinary writer cannot enable an unverified version or make it available to assignment.
- [ ] Confirm production publisher, verifier, runtime and migration privileges are separate, and exercise CLI grant/revoke with the deployed role grants.
- [ ] Review same-tenant checks for camera selection/history, atomic audit writes, PostgreSQL conflict results and immutable metadata tests.
- [ ] Verify the migration against a populated pre-Phase-2 database and rehearse application rollback with history and audit retained. Agree on backup and retention before schema downgrade or hard deletion.
- [ ] Confirm secret scan and API/inference compatibility on the reviewed PR head, then record named human sign-off.
