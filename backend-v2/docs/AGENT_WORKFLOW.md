# Vibe Coding Workflow — Safe, Repeatable and Reviewable

1. Extract starter, create a **feature branch**; use `AGENTS.md` as agent instruction file.
2. Copy `agent.md` into your coding assistant. Point it at one `docs/phases/NN-*.md`.
3. **Plan before edit**: ask for changed ERD, endpoints, trust boundaries, tests, migration and backward-compatibility impact. Resolve open design decisions.
4. Implement the smallest vertical slice (one route + data layer + tests). Commit only when automated tests pass; do not auto-deploy.
5. Run PowerShell local checks from README, `git diff --check`, review contracts and migrations.
6. Run CI on the PR, then use `docs/PR_TEMPLATE.md` to hand off to a human reviewer. Move to next phase only after the gate passes.

## Recommended prompt pattern

> Read AGENTS.md and docs/phases/02-model-registry.md. Inspect actual source. First present a minimal design proposal and test plan; do not edit until the model ownership decision is approved. Then implement endpoints, role checks, migration (if necessary), contract updates, happy/negative/cross-tenant tests and documentation. Run tests; summarize exact results and remaining risks. Do not touch V1, inference weights or live site.

## Branch and commit conventions

- `feature/v2-p2-model-registry`, `feature/v2-p3-incident-ingest`, `fix/v2-tenant-guard`.
- One PR = one reviewed slice, not one giant phase.
- Keep approved API/schema snapshots in same PR as the change; do not blindly auto-update to hide drift.

## Stop and request human review if

A change drops/renames data, changes auth/session handling, introduces camera access credentials, changes incident semantics/model thresholds, alters service trust boundaries, adds a model artifact download, or involves V1 cutover/production deployment.
