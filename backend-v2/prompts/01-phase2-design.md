You are the senior backend engineer for PPE Construction V2. I am continuing an existing FastAPI/PostgreSQL backend. The repository's AGENTS.md is binding.

TASK ID: V2-P2-DESIGN — Phase 2 Model Registry ownership and API design. DESIGN ONLY: do not edit source code, run destructive migrations, merge, or deploy.

1) Re-read AGENTS.md, agent.md, README.md, docs/CURRENT_STATUS.md, docs/TASK_BACKLOG.md, docs/PHASE_ROADMAP.md, docs/DECISIONS.md, docs/ERD.md, docs/API_CONTRACT.md, docs/INFERENCE_CONTRACT.md, docs/ARCHITECTURE.md, docs/SECURITY_AND_RISKS.md, docs/phases/02-model-registry.md, and tests/specs/P2_ACCEPTANCE.md. Inspect actual application modules, Alembic migrations and tests. Report which endpoints/tables exist versus planned. Check git status and do not overwrite local edits.
2) Resolve the OPEN ADR-004 design question: `model_versions` currently lacks `organization_id`. Compare (A) globally curated, admin-approved model registry with organization-level assignment checks and (B) tenant-owned model registry plus migration. For each, explain privacy, authorization, uniqueness, safe artifact refs/checksums, migration, audit, concurrency and operating cost. Make a recommendation and explain tradeoffs; DO NOT assume a selection is approved.
3) Propose the smallest reviewable vertical slices: Model metadata registration/list/detail, then per-camera GET/PUT assignment and rollback. Specify HTTP method/path, Pydantic request/response, role/tenant checks, DB constraints, and 401/403/404/409/422 behaviors.
4) Map every P2-01...P2-08 acceptance scenario to planned pytest cases and disposable PostgreSQL verification. Preserve independent inference; do not load weights or import ultralytics/torch/cv2 into app/.
5) Present an ADR proposal, API/ERD/contract diff plan, security risks, and the single next task. Ask for explicit approval of the ownership policy before implementation. No code edits yet.

Report in Burmese if possible while preserving technical symbols in English.
