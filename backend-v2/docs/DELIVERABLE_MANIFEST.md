# Deliverable Manifest and Phase Status

This pack is an **overlay/update** for the downloaded Backend V2 starter (not a deployed application). It includes original source plus additional planning files, safety regression tests and CI templates.

## User-requested authoring artifacts

- `README.md`: comprehensive setup, architecture status, implementation matrix and next step.
- `AGENTS.md`: authoritative coding-agent guardrails, workflow, testing and handoff.
- `agent.md`: short ready-to-paste coding prompt for Phase 2.
- `docs/PHASE_ROADMAP.md`: all 8 phases, gates and dependencies.
- `docs/phases/01-*.md` ... `08-*.md`: individual objectives, design decisions, detailed acceptance test matrix and exits.
- `tests/specs/P1_ACCEPTANCE.md` ... `P8_ACCEPTANCE.md`: **75 scenario specifications** to progressively automate, all initially Not run.
- `docs/ARCHITECTURE.md`, `docs/DECISIONS.md`, `docs/SECURITY_AND_RISKS.md`: architecture, ADR log and risk register.
- `docs/V1_MIGRATION_NOTES.md`: cautious legacy schema mapping and migration plan.
- `docs/TEST_STRATEGY.md`, `docs/TEST_EXECUTION_REPORT.md`, `docs/PRODUCTION_READINESS.md`, `docs/LOCAL_RUNBOOK.md`, `docs/PR_TEMPLATE.md`, `docs/AGENT_WORKFLOW.md`, `docs/GITHUB_INTEGRATION.md`.
- `scripts/check_architecture.py`, `scripts/verify_contracts.py`, `scripts/verify_docs.py`.
- `tests/test_phase1_safety.py`, `tests/test_contract_fixtures.py`, `tests/test_architecture_boundaries.py`, `tests/fixtures/`.
- `.github/workflows/backend-ci.yml`: standalone starter CI.
- `infra/github-workflows/backend-v2-monorepo-ci.yml`: copy to the root GitHub repo workflow directory after integrating under `backend-v2/`.

## Explicit test-status boundary

Executed locally (after generation): see response/update logs for exact results. **SQLite** tests and offline contract checks do not constitute a complete production certification. PostgreSQL migration integration, inference, RTSP/network and scale benchmarking remain unvalidated in this environment. Future-phase `tests/specs` are non-executable acceptance definitions, not passing test counts.
