# Phase 5 Acceptance Checklist — Evidence storage, durable jobs, notifications and reporting

> STATUS: PLANNED — do not assume implementation or test success.
> These case descriptions are **not proof** of executed tests. Update status/evidence after automation or manual validation.

| Case | Status | Evidence / link |
| --- | --- | --- |
| P5-01 — Evidence upload validity | Not run | — |
| P5-02 — Unauthorized evidence access | Not run | — |
| P5-03 — Expired link | Not run | — |
| P5-04 — Corrupt evidence detection | Not run | — |
| P5-05 — Job restart durability | Not run | — |
| P5-06 — Notification idempotency | Not run | — |
| P5-07 — Notification retry | Not run | — |
| P5-08 — Report org scope | Not run | — |
| P5-09 — Retention expiry | Not run | — |

## Given / When / Then scenarios

### P5-01 — Evidence upload validity
- **Given:** Authorized internal worker
- **When:** Upload valid image/video object with checksum
- **Then:** Private object stored; DB only records key and digest
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD

### P5-02 — Unauthorized evidence access
- **Given:** Evidence exists for Org B
- **When:** Org A user requests signed URL
- **Then:** Denied; no object exposure
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD

### P5-03 — Expired link
- **Given:** Short-lived signed link issued
- **When:** Attempt download after expiry
- **Then:** Rejected
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD

### P5-04 — Corrupt evidence detection
- **Given:** Known artifact with checksum
- **When:** Tamper with object or upload mismatch
- **Then:** Detected and incident marked for review; not trusted
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD

### P5-05 — Job restart durability
- **Given:** Processing job persisted
- **When:** Kill and restart job worker
- **Then:** Job recovers from durable state without losing work
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD

### P5-06 — Notification idempotency
- **Given:** One incident generates an outbox event
- **When:** Duplicate delivery attempt
- **Then:** At-most-one user-visible notification per documented key/window
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD

### P5-07 — Notification retry
- **Given:** Transport is temporarily unavailable
- **When:** Publish and recover transport
- **Then:** Bounded retry and dead-letter/reconciliation behavior
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD

### P5-08 — Report org scope
- **Given:** Mixed-org incidents exist
- **When:** Export Org A report
- **Then:** Only permitted Org A records and columns
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD

### P5-09 — Retention expiry
- **Given:** Object retention limit reached
- **When:** Run retention job
- **Then:** Data deletion/hold rules and audit conform to policy
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD
