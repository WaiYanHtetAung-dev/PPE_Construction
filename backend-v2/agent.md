# AI Agent Kickoff — paste into Cursor / VS Code Copilot / Claude Code

Read `AGENTS.md` as binding repository rules, then `README.md`, `docs/ERD.md`, `docs/API_CONTRACT.md`, `docs/INFERENCE_CONTRACT.md`, `docs/PHASE_ROADMAP.md`, `docs/SECURITY_AND_RISKS.md` and the actual implementation/tests. Explain the **current implementation status** before proposing changes. Never claim a planned feature already exists.

We are working **only on the V2 business backend**, not the legacy V1, frontend, or YOLO model. Python FastAPI / SQLAlchemy / PostgreSQL / Alembic. Maintain independent AI inference by using a versioned contract; never import YOLO/OpenCV/PyTorch into `app/`. Preserve authentication, organization isolation and API backward compatibility.

**Today's task:** Phase 2, *Model Registry API + per-camera model assignments*, in a small reviewed vertical slice. **Before code**, explain the open architecture decision: `model_versions` currently lacks `organization_id`. Propose either (A) globally curated registry + explicit tenant authorization for assignments or (B) tenant-owned registry + migration. Make no cross-tenant write possible. Show proposed endpoints, schema changes, and negative tests for approval, then implement only the approved decision. Handle duplicates, unknown model/camera, camera site ownership, role permissions, artifact checksum validation and audit logs. Do not load model weights.

After implementation run `pytest -q`, `scripts/check_architecture.py`, `scripts/verify_contracts.py`, and PostgreSQL Alembic checks in a disposable DB. Export contract snapshots only when approved changes warrant it. Report files changed, tests run/passed/failed, untested assumptions, security risks and next PR.

Use `docs/PR_TEMPLATE.md` for the handoff. **Never deploy or merge without human review.**
