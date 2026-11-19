# Phase 8 Acceptance Checklist — Controlled V1 data migration, shadow trial, canary production cutover

> STATUS: PLANNED — do not assume implementation or test success.
> These case descriptions are **not proof** of executed tests. Update status/evidence after automation or manual validation.

| Case | Status | Evidence / link |
| --- | --- | --- |
| P8-01 — Source backup | Not run | — |
| P8-02 — Dry-run mapping | Not run | — |
| P8-03 — Idempotent import | Not run | — |
| P8-04 — Credential handling | Not run | — |
| P8-05 — Evidence parity | Not run | — |
| P8-06 — Reconciliation | Not run | — |
| P8-07 — Shadow mode | Not run | — |
| P8-08 — Canary camera/site | Not run | — |
| P8-09 — Rollback rehearsal | Not run | — |
| P8-10 — Release approval | Not run | — |

## Given / When / Then scenarios

### P8-01 — Source backup
- **Given:** V1 DB/image data available offline
- **When:** Create backup and restore it
- **Then:** Successful restoration and verified hashes/counts
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD

### P8-02 — Dry-run mapping
- **Given:** Sanitized V1 source snapshot
- **When:** Run importer dry-run
- **Then:** Deterministic report, ambiguous rows flagged
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD

### P8-03 — Idempotent import
- **Given:** Same V1 snapshot already imported in test target
- **When:** Run import twice
- **Then:** No duplicate users/cameras/incidents/evidence
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD

### P8-04 — Credential handling
- **Given:** Legacy usernames/sessions present
- **When:** Migrate identities
- **Then:** No raw V1 session token reused; reset or approved process
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD

### P8-05 — Evidence parity
- **Given:** Historical thumbnails available
- **When:** Migrate object and verify digest
- **Then:** Evidence backed by object key, checksums match
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD

### P8-06 — Reconciliation
- **Given:** Source/target snapshots prepared
- **When:** Compare counts, samples, exceptions
- **Then:** Approved mismatch ledger; no silent loss
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD

### P8-07 — Shadow mode
- **Given:** V1 serving production while V2 monitors shadow
- **When:** Enable V2 without notification sends
- **Then:** No double-notify; compare model incidents
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD

### P8-08 — Canary camera/site
- **Given:** Approved trial subset
- **When:** Route limited site to V2
- **Then:** Acceptable measured incident/latency behavior
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD

### P8-09 — Rollback rehearsal
- **Given:** Canary active and rollback trigger simulated
- **When:** Switch site back to V1
- **Then:** Documented rollback completes with data integrity
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD

### P8-10 — Release approval
- **Given:** All previous gates pass
- **When:** Request final deployment authorization
- **Then:** Human sign-off recorded, deployment only then permitted
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD
