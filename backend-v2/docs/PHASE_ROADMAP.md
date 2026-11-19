# PPE Backend V2 — Phases & Dependency Gates

**Phase numbers are milestones, not calendar promises.** No dates, SLA, or hardware sizing are assumed. A phase is **complete only when its exit gate passes**; a documented planned test is not a passing test.

| Phase | Objective | Required deliverables | Verification | State |
|---|---|---|---|---|
| 1 | ERD, API, inference contract + base FastAPI | DB models, Alembic, auth, sites/cameras API subset, tests | pytest + migrations + contracts + security negative cases | **Starter present; PostgreSQL integration pending** |
| 2 | Model Registry / camera assignment | version APIs, authorization policy, audit + migration | tenant isolation, duplicate/checksum, assignment and rollback tests | Local checks passed. CI and review pending. |
| 3 | Incident ingestion / rules | internal auth, idempotent events, state machine, outbox | replay, race, cross-tenant, outage tests | Planned |
| 4 | Media gateway / camera lifecycle | secret refs, RTSP gateway, status, frame sampling | offline/reconnect, frame bounds, 50–100 camera bench | Planned |
| 5 | Evidence / delivery / reports | object storage, durable jobs, notifications | integrity, expiry, retry, authorization, restart tests | Planned |
| 6 | Frontend integration | React/TypeScript client generated from reviewed API | end-to-end RBAC, errors, stream view, a11y | Planned |
| 7 | Security, observability, performance | alerts, OTel/metrics, threat mitigation, load plans | security suite, load profile, failure injection, restore | Planned |
| 8 | V1→V2 staged migration / production gate | migration, shadow/canary, rollback playbooks | reconciliation, data parity, cutover drill | Planned |

## Mandatory dependencies

```
Phase 1 schema/API/inference contract
             ↓
Phase 2 model selection      (no GPU required)
             ↓
Phase 3 ingest/event state   (no RTSP required)
             ↓
Phase 4 media/AI worker      (contract integration)
             ↓
Phase 5 evidence and user-facing alert feeds
             ↓
Phase 6 frontend integration
             ↓
Phase 7 security/capacity hardening
             ↓
Phase 8 migration/canary/release
```

Overlap is permitted for independent design, but no integration of work lacking approved contracts. The target scale of 50–100 cameras is a **planning input**, not a proven capacity result. Set empirical acceptance targets (inference FPS, loss %, alert delivery, failover) from representative cameras, actual scene complexity, network bitrate, and GPU benchmarks.

## Each-phase handoff procedure

1. Review `docs/phases/NN-*.md` for scope, risks, exact test IDs and **open decisions**.
2. Create a feature branch; commit docs/contract design proposal before implementation.
3. Implement the smallest vertical slice, add automated tests and ensure CI is green.
4. Provide migration / rollback notes. Never overwrite original V1.
5. Attach test evidence using `docs/PR_TEMPLATE.md`; human reviews and approves merge.

See [test strategy](TEST_STRATEGY.md) and [production readiness](PRODUCTION_READINESS.md).
