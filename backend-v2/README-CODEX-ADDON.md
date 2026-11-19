# PPE Construction V2 — Codex Workflow Add-on

This is an **add-on**, not a replacement for your working FastAPI backend. It contains persistent handoff files and paste-ready prompts for Codex.

## Install

1. Back up your existing `AGENTS.md` and `agent.md` if you made local edits.
2. Copy the `docs/` and `prompts/` folders into the **Backend V2 project root**, alongside `AGENTS.md`, `app/`, `tests/` and `alembic/`.
3. **Do not overwrite** your existing `AGENTS.md`. Review `AGENTS_APPEND.md` and append its contents at the end of your existing `AGENTS.md` if compatible.
4. `agent.next.md` is a suggested replacement for the task-focused `agent.md`: review first, then copy into `agent.md` if appropriate.
5. Paste `prompts/01-phase2-design.md` into Codex. Do **not** yet paste the implementation prompt; resolve the Phase 2 ownership design decision first.

## Source of truth

Existing repository source files and original `docs/PHASE_ROADMAP.md`, `docs/ERD.md`, `docs/API_CONTRACT.md`, `docs/INFERENCE_CONTRACT.md` and `tests/specs/` remain authoritative. These new files are task coordination support, not proof of completed code/tests.

## Progress policy

Codex updates `docs/CURRENT_STATUS.md` and `docs/DEV_LOG.md` after **every executed work slice**. It records exact commands and outcomes, including failures / unverified infrastructure. Planned test descriptions cannot be marked passed. Advancing a phase requires exit criteria, CI, PostgreSQL integration evidence and human review.

## Safe use of Git

Work on feature branches, review diffs, and do not auto-merge or deploy. No live camera credentials, real video evidence, GPU models or production secrets in the backend repo.
