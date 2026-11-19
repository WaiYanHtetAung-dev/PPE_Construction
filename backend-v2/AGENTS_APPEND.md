## Persistent Codex task continuity (add-on rules)

- At the start of each new task or resumed Codex session, read `docs/CURRENT_STATUS.md`, `docs/TASK_BACKLOG.md`, the current `docs/phases/NN-*.md`, and `tests/specs/PN_ACCEPTANCE.md` in addition to all existing mandatory `AGENTS.md` references.
- Use `agent.md` as the **current-task kickoff document**, never as a substitute for `AGENTS.md` or accepted contracts.
- Only one narrow slice per PR/task; first DISCOVER and DESIGN. If an ADR is unresolved or a risky decision would change security, tenancy, authentication, schema or API compatibility, stop after proposal until explicit user approval.
- After implementation, update `docs/CURRENT_STATUS.md`, append a dated entry to `docs/DEV_LOG.md`, and adjust `docs/TASK_BACKLOG.md` and relevant acceptance evidence. Never claim unexecuted tests passed; record environment and exact commands.
- Update `docs/PHASE_ROADMAP.md` to COMPLETED only when the documented phase exit gate and human review are satisfied; partial implementation stays IN PROGRESS.
- An agent may propose updates to `AGENTS.md`, ADRs and foundational contracts, but must not silently override standing rules or rewrite applied Alembic migrations.
- Every task handoff must say what changed, tests actually executed, remaining risks, rollback, and the **next single actionable task**.
