Continue PPE Construction V2 with Codex. The code repository is the source of truth, not prior chat history.

TASK ID: <choose exactly one row in docs/TASK_BACKLOG.md>
PHASE: <phase number + phase markdown path>
GOAL: <one concrete vertical slice>

Read AGENTS.md, agent.md, docs/CURRENT_STATUS.md, docs/TASK_BACKLOG.md, docs/PHASE_ROADMAP.md, docs/DECISIONS.md, docs/ERD.md, docs/API_CONTRACT.md, docs/INFERENCE_CONTRACT.md, docs/ARCHITECTURE.md, docs/SECURITY_AND_RISKS.md, the specific docs/phases/NN-*.md, matching tests/specs/PN_ACCEPTANCE.md, and actual implementation/tests. Inspect git status and the last handoff; describe current state and blocking decisions first. Treat all unapproved decisions as blocking; propose instead of silently selecting.

Step 1 — DISCOVER: implemented, planned, blocked, security and compatibility risks.
Step 2 — DESIGN: precise DB/API/contracts delta, permissions, tests/acceptance IDs and rollback; request approval when a design gate is unresolved.
Step 3 — IMPLEMENT: only one approved slice; preserve model/media/business service boundaries.
Step 4 — VERIFY: run pytest, compileall, architecture checks, contract checks, git diff --check, PostgreSQL disposable DB migration when applicable; report exact results, never invent passing tests.
Step 5 — HANDOFF: update docs/CURRENT_STATUS.md, append docs/DEV_LOG.md, update backlog and tested acceptance case evidence; create PR-ready notes with remaining risks and next single task. Never auto-merge/deploy.

Use Burmese for the explanation, English for code and identifiers.
