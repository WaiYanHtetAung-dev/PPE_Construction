# Phase 6 — React/TypeScript UI connected to reviewed API

**Status:** PLANNED — do not assume implementation or test success.

## Scope and deliverables

Build UI as separate app using generated typed client, auth guard, multi-site camera dashboard, incident workflows and live stream view.

## Design decisions and prerequisites

Do not break API contracts; browser cannot access database, RTSP credentials or internal service APIs.

**Critical note:** Frontend is a new project, not included in this backend-only starter.

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
| P6-01 | Login flow | Valid account in test environment | Login using browser client | Session handled without leaking credentials |
| P6-02 | Role-based navigation | Admin and viewer accounts | Login as viewer | Read-only views; create/admin actions disabled and server enforces role |
| P6-03 | Tenant isolation | User belongs only to Org A | Navigate manually to Org B resource URL | No unauthorized data or cached content |
| P6-04 | Camera live view | Authorized test stream exists | Open live camera tile | Approved media protocol plays; errors surfaced |
| P6-05 | Disconnected camera UI | Camera offline | Open camera details | Clear offline state, no frozen misleading live indicator |
| P6-06 | Incident acknowledgement | Authorized operator and open incident | Acknowledge in UI | Backend state updates and audit, UI refreshes |
| P6-07 | Transient auth/network error | Token expires or API times out | Perform UI action | Safe error/reauth and no blind retry mutation |
| P6-08 | Accessibility/responsive | Desktop and mobile viewport | Keyboard navigate and inspect screenreader semantics | Agreed accessibility checks pass |

## Exit criteria

- [ ] All required cases for this phase run and their results are documented (not just specified).
- [ ] Negative auth/tenant/secret cases included for changed routes and workers.
- [ ] CI green, PostgreSQL migrations validated, contracts reviewed and exported if changed.
- [ ] A reviewer approves the security, privacy and migration impacts.
- [ ] Handoff and rollback notes recorded in `docs/PR_TEMPLATE.md`.

See also `tests/specs/P6_ACCEPTANCE.md` for scenario checkboxes and execution evidence template.
