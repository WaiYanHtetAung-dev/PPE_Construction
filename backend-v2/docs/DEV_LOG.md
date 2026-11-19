# Development Log — append-only human-readable handoff

Record an entry after every Codex work slice; never erase past test failures or claim planned tests are passing.

## Entry template

### YYYY-MM-DD — Task ID / title

- **Branch / commit / PR:**
- **Phase / status:**
- **Scope:**
- **Files changed:**
- **ERD/API/Inference contract impact:**
- **Migration / rollback:**
- **Security / tenant implications:**
- **Commands executed and exact results:**
- **Acceptance cases actually executed (ID and evidence):**
- **Not run / reason:**
- **Remaining blockers / open decisions:**
- **Next single actionable task:**
- **Human reviewer and approval state:**

> Start real entries only after actual work is performed. Do not fill evidence retroactively from assumptions.

### 2026-11-18 — V2-P2-DESIGN / ADR-004 approval and baseline

- **Branch / commit / PR** V2 source copy has no usable Git worktree. The sibling legacy checkout is on main and was inspected read-only.
- **Phase / status** Project owner approved Option A. Phase 2 implementation remains planned.
- **Files changed** docs/DECISIONS.md, docs/CURRENT_STATUS.md, docs/DEV_LOG.md and docs/TASK_BACKLOG.md.
- **Design and compatibility** Documented restricted publisher CLI, immutable metadata, tenant ownership and atomic assignment history. Application code, Alembic and contract snapshots received zero changes.
- **Verification** With Python 3.14.7 in .venv, pip install -r requirements-dev.txt and pip check exited 0. Pytest exited 0 with 24 passed and two warnings. Exit cleanup reported WinError 32 for the temporary SQLite database. Compile, architecture and contract verification exited 0.
- **Pending evidence** PostgreSQL migration checks require a verified disposable database. CI and P2-01 through P2-08 have no new execution evidence.
- **Next task** V2-P2-API1 publisher registration and transactional platform audit.

### V2-P2-API1 — Platform publisher registration

- Added the restricted publisher CLI and publisher-only registration with transactional platform audit.
- Alembic revision `a6c37b0e4f21` follows `9db36ad49c74`. It adds publisher and audit tables, default-ineligible metadata and a PostgreSQL immutability trigger.
- SQLite testing returned 39 passes and one PostgreSQL-only skip. Session teardown disposes the engine before deleting the temporary file. Architecture, contract and compilation checks passed.
- Disposable PostgreSQL 17 passed upgrade, current and schema drift checks. One PostgreSQL concurrency and direct metadata immutability test passed. CI execution evidence is pending.
- The API change is additive and the inference schema remains compatible. Application rollback can retain the migration and audit. Downgrade removes publisher grants and audit records.
- Next slice is V2-P2-API2, starting with the admin-only eligible catalog list and detail.

### V2-P2-API2 - Eligible organization catalog reads

- Added eligible-only paginated list and version detail with organization admin checks.
- SQLite suite returned 42 passed and one PostgreSQL-only skip. Compile, architecture and contract checks passed. Existing OpenAPI operations and schemas matched.
- No database change. Git diff checks do not cover the untracked V2 directory. PostgreSQL was not rerun for catalog reads.
- Next task is tenant-safe camera assignment GET/PUT.

### 2026-11-19 - V2-P2-API2 camera assignment

- Added tenant-safe camera selection GET/PUT and history GET. PUT atomically commits selection, revision, history and org audit.
- Added Alembic revision d2f4a193b0c7. Existing assignments remain at baseline revision 0. The PostgreSQL trigger enforces append-only history. Schema downgrade drops revision and history data. Application rollback can retain the migration.
- SQLite suite returned 45 passed and 2 PostgreSQL-only skips. Disposable PostgreSQL 17 passed upgrade, drift check and 2 integration tests. Compile, architecture and contract checks passed. OpenAPI additions preserve existing operations and schemas.
- V2 files remain untracked on feature/backend-v2-foundation. Git diff --check cannot cover untracked files. CI evidence and human review are pending.
- Next task is the V2-P2-GATE review.

### 2026-11-19 - V2-P2-GATE final review for Draft PR #1

- Application commit `71b6fb5` passed [hosted run #2](https://github.com/WaiYanHtetAung-dev/PPE_Construction/actions/runs/44460576958). Unit/contract/security: 45 passed, 2 skipped. PostgreSQL 17: upgrade/current at `d2f4a193b0c7`, drift check and 2 integration tests passed.
- Blocking. Registration defaults to ineligible, while a database writer can set the flag without persisted verification. Reproduced on a disposable PostgreSQL 17 database after upgrading through head. The synthetic write was rolled back. Catalog and assignment trust this flag. Require an authenticated verifier, durable evidence bound to the immutable artifact reference and digest, restricted database roles, and a negative integration test for unverified promotion.
- Important. Validate least-privilege publisher grant/revoke and runtime permissions using actual database roles. Rehearse application rollback with the schema retained and check migration over a representative pre-existing assignment. The CI migration job runs from an empty database.
- Rollback. Roll back application code while retaining schema and audit/history. Schema downgrades remove assignment history/revisions and potentially publisher/audit records. Backup and rehearsal are required before considering a downgrade.
- Scope. Documentation review only. PR stays Draft and human sign-off is pending. Phase 3 remains gated.

### 2026-11-19 - Final Phase 2 gate rehearsal

- [Hosted run #4](https://github.com/WaiYanHtetAung-dev/PPE_Construction/actions/runs/44461554789) is attached to PR head `544b3f50dc718c4c394e7632a831bf56de105ced`. Both jobs passed. Unit suite 45 passed, 2 skipped. PostgreSQL suite 2 passed. Alembic head and schema drift checks passed.
- Populated disposable PostgreSQL 17 at `9db36ad49c74` with an organization, admin, site, camera, model version and current assignment. Upgrade to `d2f4a193b0c7` preserved the selection at revision 0 and left the legacy model ineligible. Alembic check reported no drift.
- A synthetic database writer enabled a new version without verified evidence. The current API accepted it for assignment, confirming the blocking eligibility gap. Testing used only the disposable database.
- Rehearsed application rollback to the local V2 API1-only snapshot while retaining the migrated schema. Health, login, camera read and camera creation worked. Roll-forward returned the same assignment at revision 1 with the history and audit records intact. This did not exercise a packaged release or a schema downgrade.
- Privileges reviewed in code. Publisher access is separate from org admin. Runtime and migration permissions are operational configuration. There is no verified promotion mechanism or verifier role to test, and actual production role grants were not tested.
- Recommendation remains hold for approval. PR remains Draft. No V1, deployment or Phase 3 changes.
