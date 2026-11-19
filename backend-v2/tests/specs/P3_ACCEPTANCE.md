# Phase 3 Acceptance Checklist — Secure inference result ingestion and incident lifecycle

> STATUS: PLANNED — do not assume implementation or test success.
> These case descriptions are **not proof** of executed tests. Update status/evidence after automation or manual validation.

| Case | Status | Evidence / link |
| --- | --- | --- |
| P3-01 — Service authentication | Not run | — |
| P3-02 — Ingest valid event | Not run | — |
| P3-03 — Idempotency replay | Not run | — |
| P3-04 — Cross-tenant mismatch | Not run | — |
| P3-05 — State transition | Not run | — |
| P3-06 — Invalid transition | Not run | — |
| P3-07 — Unknown/low-confidence inference | Not run | — |
| P3-08 — Transaction failure | Not run | — |
| P3-09 — Concurrent duplicate deliveries | Not run | — |
| P3-10 — Service identity rotation | Not run | — |

## Given / When / Then scenarios

### P3-01 — Service authentication
- **Given:** Internal endpoint deployed
- **When:** Call without trusted service identity
- **Then:** 401/403; no event persisted
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD

### P3-02 — Ingest valid event
- **Given:** Authorized service and matching camera/site/org
- **When:** Send valid versioned event with event_id
- **Then:** One incident/event and one outbox message committed
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD

### P3-03 — Idempotency replay
- **Given:** Same signed event_id previously ingested
- **When:** Send it twice or retry after timeout
- **Then:** One business event; stable response; no double alert
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD

### P3-04 — Cross-tenant mismatch
- **Given:** Camera belongs Org B and request claims Org A
- **When:** POST ingest payload
- **Then:** Rejected and no side effects
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD

### P3-05 — State transition
- **Given:** Existing open incident
- **When:** Ack then resolve with authorized actors
- **Then:** Valid transitions; audit and timestamps created
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD

### P3-06 — Invalid transition
- **Given:** Resolved incident exists
- **When:** Attempt invalid transition
- **Then:** 409/4xx; original state remains
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD

### P3-07 — Unknown/low-confidence inference
- **Given:** Incomplete PPE objects or low confidence
- **When:** Evaluate rules against frame
- **Then:** No fabricated definite violation; explicit unknown policy
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD

### P3-08 — Transaction failure
- **Given:** DB fault happens before outbox insert
- **When:** Attempt ingest and restore DB
- **Then:** No partial incident/outbox commit; retry safe
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD

### P3-09 — Concurrent duplicate deliveries
- **Given:** Two workers replay identical event
- **When:** Deliver concurrently
- **Then:** At most one persisted canonical event
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD

### P3-10 — Service identity rotation
- **Given:** Old workload credential has been revoked
- **When:** Submit authenticated request using revoked identity
- **Then:** Rejected; new credential accepted
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD
