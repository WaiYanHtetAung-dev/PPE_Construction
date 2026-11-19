# Phase 5 — Evidence storage, durable jobs, notifications and reporting

**Status:** PLANNED — do not assume implementation or test success.

## Scope and deliverables

Private object-store evidence, checksums, incident event fanout, retry/dead-letter, export/report API and retention.

## Design decisions and prerequisites

Set media type/size limits, signed downloads, RBAC, retention, delivery status and retry policy.

**Critical note:** Do not store image/video Base64 in PostgreSQL or emit raw sensitive URLs in logs.

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
| P5-01 | Evidence upload validity | Authorized internal worker | Upload valid image/video object with checksum | Private object stored; DB only records key and digest |
| P5-02 | Unauthorized evidence access | Evidence exists for Org B | Org A user requests signed URL | Denied; no object exposure |
| P5-03 | Expired link | Short-lived signed link issued | Attempt download after expiry | Rejected |
| P5-04 | Corrupt evidence detection | Known artifact with checksum | Tamper with object or upload mismatch | Detected and incident marked for review; not trusted |
| P5-05 | Job restart durability | Processing job persisted | Kill and restart job worker | Job recovers from durable state without losing work |
| P5-06 | Notification idempotency | One incident generates an outbox event | Duplicate delivery attempt | At-most-one user-visible notification per documented key/window |
| P5-07 | Notification retry | Transport is temporarily unavailable | Publish and recover transport | Bounded retry and dead-letter/reconciliation behavior |
| P5-08 | Report org scope | Mixed-org incidents exist | Export Org A report | Only permitted Org A records and columns |
| P5-09 | Retention expiry | Object retention limit reached | Run retention job | Data deletion/hold rules and audit conform to policy |

## Exit criteria

- [ ] All required cases for this phase run and their results are documented (not just specified).
- [ ] Negative auth/tenant/secret cases included for changed routes and workers.
- [ ] CI green, PostgreSQL migrations validated, contracts reviewed and exported if changed.
- [ ] A reviewer approves the security, privacy and migration impacts.
- [ ] Handoff and rollback notes recorded in `docs/PR_TEMPLATE.md`.

See also `tests/specs/P5_ACCEPTANCE.md` for scenario checkboxes and execution evidence template.
