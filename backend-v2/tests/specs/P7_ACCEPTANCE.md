# Phase 7 Acceptance Checklist — Security, observability, reliability and capacity qualification

> STATUS: PLANNED — do not assume implementation or test success.
> These case descriptions are **not proof** of executed tests. Update status/evidence after automation or manual validation.

| Case | Status | Evidence / link |
| --- | --- | --- |
| P7-01 — Brute-force control | Not run | — |
| P7-02 — Dependency vulnerability scan | Not run | — |
| P7-03 — Secret-safe logs | Not run | — |
| P7-04 — Tenant fuzz testing | Not run | — |
| P7-05 — Monitoring coverage | Not run | — |
| P7-06 — Database restore | Not run | — |
| P7-07 — Sustained load | Not run | — |
| P7-08 — Recovery/circuit breaker | Not run | — |
| P7-09 — Expired evidence retention | Not run | — |
| P7-10 — TLS/network exposure | Not run | — |

## Given / When / Then scenarios

### P7-01 — Brute-force control
- **Given:** Login API reachable in staging
- **When:** Sustain failed auth attempts
- **Then:** Rate limit/alert thresholds according to policy
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD

### P7-02 — Dependency vulnerability scan
- **Given:** Pinned runtime/lock available
- **When:** Run SCA/security checks
- **Then:** No unresolved release-blocking findings
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD

### P7-03 — Secret-safe logs
- **Given:** Service paths have injected fake canary credentials
- **When:** Exercise errors, streaming and auth
- **Then:** Tokens/RTSP secrets absent in logs/traces
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD

### P7-04 — Tenant fuzz testing
- **Given:** Mixed organizations and resource IDs
- **When:** Try cross-org endpoints and payload refs
- **Then:** No unauthorized read/write including evidence
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD

### P7-05 — Monitoring coverage
- **Given:** All services deployed in test topology
- **When:** Kill DB / inference worker / camera source
- **Then:** Alerting and health metrics reflect outage
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD

### P7-06 — Database restore
- **Given:** Backups enabled on disposable DB
- **When:** Restore to target point
- **Then:** Verified row consistency and measured RPO/RTO
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD

### P7-07 — Sustained load
- **Given:** Representative recordings and camera samples
- **When:** Run soak test with measured FPS
- **Then:** Document throughput/latency/drop curves, agreed thresholds
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD

### P7-08 — Recovery/circuit breaker
- **Given:** Inference service becomes unavailable
- **When:** Send requests and restore service
- **Then:** Bounded retries, queued or dropped work per policy, quick recovery
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD

### P7-09 — Expired evidence retention
- **Given:** Hold/expiry fixtures exist
- **When:** Run purge and access deleted evidence
- **Then:** Policy enforcement and deletion audit
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD

### P7-10 — TLS/network exposure
- **Given:** Staging environment deployed
- **When:** Inspect ports/auth and attempt prohibited access
- **Then:** Only approved public routes, TLS and service identities
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD
