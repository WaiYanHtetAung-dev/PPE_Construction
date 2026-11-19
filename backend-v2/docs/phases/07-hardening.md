# Phase 7 — Security, observability, reliability and capacity qualification

**Status:** PLANNED — do not assume implementation or test success.

## Scope and deliverables

OpenTelemetry metrics/traces/logging, auth/tenancy review, rate limits, secure runtime, backup/restore and load/failover.

## Design decisions and prerequisites

Use explicitly agreed SLO and RTO/RPO. No pre-made FPS guarantees; performance results reported per hardware/network.

**Critical note:** At-scale readiness not proven by unit tests.

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
| P7-01 | Brute-force control | Login API reachable in staging | Sustain failed auth attempts | Rate limit/alert thresholds according to policy |
| P7-02 | Dependency vulnerability scan | Pinned runtime/lock available | Run SCA/security checks | No unresolved release-blocking findings |
| P7-03 | Secret-safe logs | Service paths have injected fake canary credentials | Exercise errors, streaming and auth | Tokens/RTSP secrets absent in logs/traces |
| P7-04 | Tenant fuzz testing | Mixed organizations and resource IDs | Try cross-org endpoints and payload refs | No unauthorized read/write including evidence |
| P7-05 | Monitoring coverage | All services deployed in test topology | Kill DB / inference worker / camera source | Alerting and health metrics reflect outage |
| P7-06 | Database restore | Backups enabled on disposable DB | Restore to target point | Verified row consistency and measured RPO/RTO |
| P7-07 | Sustained load | Representative recordings and camera samples | Run soak test with measured FPS | Document throughput/latency/drop curves, agreed thresholds |
| P7-08 | Recovery/circuit breaker | Inference service becomes unavailable | Send requests and restore service | Bounded retries, queued or dropped work per policy, quick recovery |
| P7-09 | Expired evidence retention | Hold/expiry fixtures exist | Run purge and access deleted evidence | Policy enforcement and deletion audit |
| P7-10 | TLS/network exposure | Staging environment deployed | Inspect ports/auth and attempt prohibited access | Only approved public routes, TLS and service identities |

## Exit criteria

- [ ] All required cases for this phase run and their results are documented (not just specified).
- [ ] Negative auth/tenant/secret cases included for changed routes and workers.
- [ ] CI green, PostgreSQL migrations validated, contracts reviewed and exported if changed.
- [ ] A reviewer approves the security, privacy and migration impacts.
- [ ] Handoff and rollback notes recorded in `docs/PR_TEMPLATE.md`.

See also `tests/specs/P7_ACCEPTANCE.md` for scenario checkboxes and execution evidence template.
