# Test Strategy and Test-Case Catalogue

## Status and interpretation

- **Executable now:** `tests/test_api.py`, `tests/test_inference_contract.py`, `tests/test_phase1_safety.py`, `tests/test_contract_fixtures.py`, `tests/test_architecture_boundaries.py`.
- **Future acceptance cases:** `tests/specs/*.md`, and each `docs/phases/NN-*.md`; these are **specifications, not executed automated tests**. Convert to tests as the relevant phase is implemented.
- **Separate infra gate:** GitHub CI has an isolated Postgres migration job, distinct from SQLite unit tests. Local `pytest` alone never proves PostgreSQL-specific behavior.

## Test levels

| Level | Tool | Run where | Purpose |
| --- | --- | --- | --- |
| Contract/schema | pytest + Pydantic + snapshot verifier | Local and CI | Model/data interface backward compatibility |
| Unit/API | FastAPI TestClient / isolated SQLite | Local and CI | Business rules, negative input, role and tenant checks |
| Database integration | Alembic on throwaway PostgreSQL | CI + local Docker | DDL, migration head/check; add real DB app tests next |
| Service integration | Compose + test media/AI stubs | Planned | mTLS, outbox, failures, service retries |
| End-to-end | Browser/Cypress or Playwright + mock camera | Planned | User workflows, alerts, errors, roles |
| Load/soak | Camera simulators + real representative cameras | Planned | Measured throughput, drops, latency, leaks |
| Security/failover | Dedicated review harness | Planned | Cross-tenant, replay, SSRF, outage/restore |

## Phase gates — one-line quick matrix

| Phase | ID range | Key cases | Evidence |
|---|---|---|---|
| 1 | P1-01..P1-10 | health, auth, RBAC, tenant isolation, input schema, migrations | pytest, schema check, PG CI |
| 2 | P2-01..P2-08 | register/version conflict, ownership, assignment, rollback, audit | pytest + PG integration |
| 3 | P3-01..P3-10 | authenticated ingestion, replay, atomic outbox, state transition | integration/fault injection |
| 4 | P4-01..P4-10 | stream lifecycle, reconnection, bounded work, frame latency | media harness + load |
| 5 | P5-01..P5-09 | evidence auth, checksum, expiry, queues, notifications | integration + object store |
| 6 | P6-01..P6-08 | auth/roles, UI cross-tenant, streaming, errors, a11y | browser E2E |
| 7 | P7-01..P7-10 | security scan, observability, restore, scaling failure | release validation |
| 8 | P8-01..P8-10 | dry-run parity, migration, canary, rollback, approvals | migration/cutover rehearsal |

## Execution discipline

- Each case has `Given / When / Then`, negative cases, prerequisites, actual result and linked evidence before marking pass.
- Keep **test fixtures entirely synthetic**. Never use actual live construction CCTV frames or real secrets in repository tests.
- Mark an infra-dependent test **Not run** if its environment is unavailable; never mark pass on assumed behavior.
- Version and store contract examples and model sample outputs. Tests must validate schema compatibility and actual inference accuracy separately.
- No unmeasured guarantees like "supports 100 cameras". Define and benchmark acceptable camera FPS, alert latency percentiles, drop fraction, reconnect windows and GPU utilization before go-live.

## Commands

```powershell
python -m pytest -q
python scripts/check_architecture.py
python scripts/verify_contracts.py
python -m alembic check      # local dedicated DB with current migration
```

CI: `.github/workflows/backend-ci.yml`. Regression checklist: `docs/PRODUCTION_READINESS.md`.
