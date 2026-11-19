# Phase 6 Acceptance Checklist — React/TypeScript UI connected to reviewed API

> STATUS: PLANNED — do not assume implementation or test success.
> These case descriptions are **not proof** of executed tests. Update status/evidence after automation or manual validation.

| Case | Status | Evidence / link |
| --- | --- | --- |
| P6-01 — Login flow | Not run | — |
| P6-02 — Role-based navigation | Not run | — |
| P6-03 — Tenant isolation | Not run | — |
| P6-04 — Camera live view | Not run | — |
| P6-05 — Disconnected camera UI | Not run | — |
| P6-06 — Incident acknowledgement | Not run | — |
| P6-07 — Transient auth/network error | Not run | — |
| P6-08 — Accessibility/responsive | Not run | — |

## Given / When / Then scenarios

### P6-01 — Login flow
- **Given:** Valid account in test environment
- **When:** Login using browser client
- **Then:** Session handled without leaking credentials
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD

### P6-02 — Role-based navigation
- **Given:** Admin and viewer accounts
- **When:** Login as viewer
- **Then:** Read-only views; create/admin actions disabled and server enforces role
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD

### P6-03 — Tenant isolation
- **Given:** User belongs only to Org A
- **When:** Navigate manually to Org B resource URL
- **Then:** No unauthorized data or cached content
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD

### P6-04 — Camera live view
- **Given:** Authorized test stream exists
- **When:** Open live camera tile
- **Then:** Approved media protocol plays; errors surfaced
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD

### P6-05 — Disconnected camera UI
- **Given:** Camera offline
- **When:** Open camera details
- **Then:** Clear offline state, no frozen misleading live indicator
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD

### P6-06 — Incident acknowledgement
- **Given:** Authorized operator and open incident
- **When:** Acknowledge in UI
- **Then:** Backend state updates and audit, UI refreshes
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD

### P6-07 — Transient auth/network error
- **Given:** Token expires or API times out
- **When:** Perform UI action
- **Then:** Safe error/reauth and no blind retry mutation
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD

### P6-08 — Accessibility/responsive
- **Given:** Desktop and mobile viewport
- **When:** Keyboard navigate and inspect screenreader semantics
- **Then:** Agreed accessibility checks pass
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD
