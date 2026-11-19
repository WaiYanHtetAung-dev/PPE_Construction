# Codex Workflow — How to integrate future work

## Before each task

1. Confirm actual repo root, branch and uncommitted files (`git status --short`). Never overwrite unrelated edits.
2. Read `AGENTS.md`, `agent.md`, `docs/CURRENT_STATUS.md`, `docs/TASK_BACKLOG.md`, current phase plan, matching acceptance spec, source modules and contracts.
3. State implemented vs planned vs blocked. Flag ADRs requiring human approval. A prior conversation is **not** evidence code exists.
4. Propose a design and the smallest vertical slice, including SQL migration and API contract implications, negative tenant tests and rollback.

## During the task

5. After explicit approval for any blocking decision, implement one narrowly scoped slice on a feature branch.
6. Add automated tests for the relevant Given/When/Then cases; keep an exact mapping to `P2-01` etc.
7. Run `python -m pytest -q`, `python -m compileall -q app tests scripts`, `python scripts/check_architecture.py`, `python scripts/verify_contracts.py`, and `git diff --check`.
8. For schema changes, run Alembic migration/check on a **disposable PostgreSQL instance**. Never mutate production data or quietly rewrite applied migrations.
9. Inspect OpenAPI/JSON schema snapshots; review intentional changes (export only if contracts changed).

## After the task

10. Append actual evidence to `docs/DEV_LOG.md`, update `docs/CURRENT_STATUS.md`, `docs/TASK_BACKLOG.md`, and `tests/specs/` cases actually executed.
11. Use `docs/PR_TEMPLATE.md` for handoff. Show test output, commit/PR, migration and rollback, security implications, unverified work and the **next single task**.
12. Mark `docs/PHASE_ROADMAP.md` complete only when exit gate + review passed. Keep `AGENTS.md` stable; update `agent.md` when switching the current objective.

## Starting each later Codex session

Paste `prompts/04-resume-session.md`, then specify exactly one task from `docs/TASK_BACKLOG.md`.

## Never

No YOLO/PyTorch/OpenCV imports in business API, public exposure of internal ingestion, arbitrary media URL fetching, secrets in Git/logs, auto merge/deploy, fabricated tests or unreviewed API breaking changes.
