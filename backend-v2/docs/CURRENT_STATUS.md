# CURRENT_STATUS — PPE Construction V2

**Updated** 2026-11-19

**Active phase** Phase 2.6-C readiness checks implemented. Real exporter preflight, export and parity are blocked by unavailable approved inputs.

[Draft PR #1](https://github.com/WaiYanHtetAung-dev/PPE_Construction/pull/1) targets `main` from `feature/backend-v2-review`. Human approval is pending.

Phase 2 includes restricted CLI publisher grants, publisher-only registration, default-ineligible model metadata and transactional platform audit. Admin-only catalog reads return eligible versions. Camera assignment, rollback and history are implemented. [Approved ADR-004](DECISIONS.md#adr-004--globally-curated-model-registry)

## Local verification

Use the project environment from the V2 root. The baseline used the locally available Python 3.14.7. CI specifies Python 3.12. The requirements files specify version ranges.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

| Check | Result |
|---|---|
| pip check | Passed, exit 0 |
| pytest -q | 45 passed on SQLite, 2 PostgreSQL-only tests skipped. Windows SQLite file cleanup succeeded after disposing the test engine. |
| compileall -q app tests scripts | Passed, exit 0 |
| scripts/check_architecture.py | Passed, exit 0 |
| scripts/verify_contracts.py | Passed, exit 0. Checked-in OpenAPI and inference v1 snapshots match. |
| PostgreSQL 17 migration upgrade/check | Passed on a disposable Docker database. Head is `d2f4a193b0c7`. |
| PostgreSQL integration | 2 passed. Concurrent duplicate registration and camera assignment races, plus direct metadata/history mutation rejection. |
| Hosted CI | [Run #4](https://github.com/WaiYanHtetAung-dev/PPE_Construction/actions/runs/44461554789) passed on `544b3f5`. Unit job: 45 passed, 2 skipped. PostgreSQL 17 job: upgrade/current/drift passed and 2 integration tests passed. |

| Disposable PostgreSQL 17 rehearsal | Populated upgrade from `9db36ad49c74` to `d2f4a193b0c7` and schema drift check passed. Local V2 API1-only snapshot rollback and current-app roll-forward retained model revision, assignment, history and audit. |
| Deployment privileges | Review only. Actual PostgreSQL role grants, verifier credentials and production rollback artifact were not tested. |

| Eligibility fix | Linux Python 3.12: 52 passed, 3 PostgreSQL-only skips. Disposable PostgreSQL 17: 3 integration tests passed. Alembic head `e5c19a74d620` and drift check passed. See [PR checks](https://github.com/WaiYanHtetAung-dev/PPE_Construction/pull/1/checks) for hosted CI on the fix. |

| Phase 2.5 local | Linux: 68 passed, 4 PostgreSQL-only skips. Disposable PostgreSQL 17: 4 integration tests passed. Compose smoke: verified inference 200, revoked inference 503, schema and evidence retained after stopping services. |

| Phase 2.6 local | Actual CPUExecutionProvider ran synthetic ONNX: 10 adapter/security tests passed. Full Linux suite 78 passed, 4 skipped. Disposable PostgreSQL 17 integration: 4 passed. CPU worker image and Compose configuration passed. |

## Phase 2.6-B release status

| Gate | Status |
|---|---|
| Implementation | Complete. Dual-profile offline runner, corpus verification, two-mode V1 reference and signed-worker parity capture. |
| Export compatibility | NOT TESTED for 8.4.102 or 8.4.96. Approved digests, wheel locks and execution clearance unavailable. |
| Real-model parity | NOT TESTED. No approved candidate or de-identified corpus. |
| Licensing | Written clearance pending. |
| Human review | Pending. Draft PR #1 remains open. |
| Production deployment | No approval or deployment. |

## Phase 2.6-C readiness evidence

- The Finalboss checkpoint matches the recorded SHA-256. No deserialization was performed.
- A checkpoint-free Linux Docker probe confirmed non-root, loopback-only and read-only controls, without a checkpoint mount or database configuration.
- Targeted synthetic preflight/workflow suite returned 8 passed, 2 optional ONNX skips on the local Windows venv. The full suite is tracked in hosted PR checks.
- Approved 8.4.102 and 8.4.96 exporter images and wheel locks, checkpoint rights, corpus and per-image fixture records are missing. Neither profile was run or selected.

## Next single task

Provision the independent approved image/lock/rights bundles and approved corpus on the disposable offline host. Run checkpoint-free preflight for each profile and the reference corpus using [the readiness runbook](PHASE_2_6_READINESS.md).
