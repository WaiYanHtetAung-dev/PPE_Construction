# Phase 1 — API/ERD/inference contracts and minimum secure CRUD foundation

**Status:** Starter implemented subset; Postgres integration not validated here.

## Scope and deliverables

Present starter: authentication and memberships, site/camera list and create, incident read, initial migration, model schema definitions. No live inference or media.

## Design decisions and prerequisites

Check all baseline routes, migration on Postgres, and contracts. OpenAPI snapshot is reviewed before new endpoints.

**Critical note:** SQLite tests are not sufficient for PostgreSQL signoff.

## Execution plan

1. Read architecture, ERD and relevant current API + inference contracts. Compare real code to planned endpoints.
2. Write an ADR/design proposal for any missing ownership, security, consistency or networking decision.
3. Define typed contracts + migration plan before implementation.
4. Implement smallest vertical slice on feature branch and add tests with mocked external services.
5. Run local tests and CI, inspect PostgreSQL migration and contract diffs.
6. Complete documented acceptance cases, attach evidence, list blockers and obtain review before next phase.

## Acceptance test cases

| ID | Test | Given | When | Expected result |
|---|---|---|---|---|
| P1-01 | Health probes | API and a valid isolated DB are available | GET /health/live and /health/ready | 200 with status ok/ready |
| P1-02 | Missing auth | An organization endpoint exists | Request it without bearer token | 401; no resource data |
| P1-03 | Invalid login | A valid test account exists | POST /auth/login with wrong password | 401; no token returned |
| P1-04 | Valid login and logout | A test admin exists | Login, GET /auth/me, then logout and reuse token | Identity is correct; old token returns 401 |
| P1-05 | Cross-tenant read denied | User belongs only to Org A | GET Org B site/camera/incident data | 404 or approved policy error; no data leakage |
| P1-06 | Role-based site/camera writes | Viewer and admin accounts exist | Viewer creates site/camera; admin creates them | Viewer denied; admin succeeds |
| P1-07 | RTSP/SSRF input blocked | An admin and site exist | Submit rtsp:// credential URL or traversal as stream_ref | 422; no secret URL persisted |
| P1-08 | Inference invalid schema rejected | Pydantic inference models installed | Parse invalid class, score, bbox and unknown fields | ValidationError; strict contract |
| P1-09 | Postgres from scratch | A disposable PostgreSQL DB exists | Run alembic upgrade head and alembic check | Migration applies cleanly and has no drift |
| P1-10 | Architectural boundary | Current app tree exists | Scan imports and model artifacts | No YOLO, Torch, OpenCV, .pt in business app |

## Exit criteria

- [ ] All required cases for this phase run and their results are documented (not just specified).
- [ ] Negative auth/tenant/secret cases included for changed routes and workers.
- [ ] CI green, PostgreSQL migrations validated, contracts reviewed and exported if changed.
- [ ] A reviewer approves the security, privacy and migration impacts.
- [ ] Handoff and rollback notes recorded in `docs/PR_TEMPLATE.md`.

See also `tests/specs/P1_ACCEPTANCE.md` for scenario checkboxes and execution evidence template.
