# CURRENT_STATUS — PPE Construction V2

**Updated** 2026-11-19

**Active phase** Phase 2 — V2-P2-API1 and V2-P2-API2 implemented and locally verified.

The V2 feature worktree is `D:/wyha/PPE_Construction/PPE_Construction-git/backend-v2` on `feature/backend-v2-foundation`. The V2 directory is untracked in that worktree. The parent index contains pre-existing staged V1 deletions. Review the index separately before committing.

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
| CI and remaining Phase 2 acceptance | CI and human review pending. P2-01 through P2-08 have local coverage. |

## Next single task

Prepare a V2-only review diff and obtain hosted CI evidence and human approval before Phase 3.
