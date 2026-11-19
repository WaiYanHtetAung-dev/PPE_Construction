# agent.md — Current Codex work item

> Project: PPE Construction V2 **business backend**, FastAPI + PostgreSQL + SQLAlchemy + Alembic.
> Status: Phase 1 starter exists; PostgreSQL integration evidence is pending. Phase 2 model registry is PLANNED.

Read `AGENTS.md` first. Then read `README.md`, `docs/CURRENT_STATUS.md`, `docs/TASK_BACKLOG.md`, `docs/PHASE_ROADMAP.md`, `docs/DECISIONS.md`, `docs/ERD.md`, `docs/API_CONTRACT.md`, `docs/INFERENCE_CONTRACT.md`, `docs/ARCHITECTURE.md`, `docs/SECURITY_AND_RISKS.md`, `docs/phases/02-model-registry.md`, and `tests/specs/P2_ACCEPTANCE.md`. Inspect actual code before describing implementation status.

## Current objective

Phase 2, **Model Registry + Camera Model Assignment**, *DESIGN ONLY* until ownership decision is explicitly approved.

1. Compare code/DB schema with existing contracts; identify implemented and missing pieces.
2. Explain ADR-004: `model_versions` currently has no `organization_id`.
3. Compare two safe designs: globally curated catalog with explicit per-tenant assignment authorization, or tenant-owned models with a migration.
4. Propose ERD/API/security/uniqueness/concurrency/audit implications, tests mapping P2-01 through P2-08, and rollback.
5. Show a narrow slice-by-slice implementation plan; **do not edit source code or migrations yet**.

After explicit approval, use `prompts/02-phase2-implement.md` to implement **one approved vertical slice**. Never import ultralytics/torch/cv2 into `app/`. No AI weights, RTSP decoding or production deployment. Report what you can and cannot test.

## Completion protocol

Use `docs/PR_TEMPLATE.md`. Update `docs/CURRENT_STATUS.md` and append evidence to `docs/DEV_LOG.md`. Do not mark Phase 2 complete until PostgreSQL migration, security negative cases and acceptance gate are verified and reviewed.

## Future phases

Phase sequence and exit gates are in `docs/PHASE_ROADMAP.md` and `docs/phases/`. Use `prompts/03-next-task-template.md` to continue only after handoff. Do not rewrite `AGENTS.md` for every feature; change `agent.md` and current-status/task files instead.
