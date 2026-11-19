# Phase 1 Acceptance Checklist — API/ERD/inference contracts and minimum secure CRUD foundation

> STATUS: Starter implemented subset; Postgres integration not validated here.
> These case descriptions are **not proof** of executed tests. Update status/evidence after automation or manual validation.

| Case | Status | Evidence / link |
| --- | --- | --- |
| P1-01 — Health probes | Not run | — |
| P1-02 — Missing auth | Not run | — |
| P1-03 — Invalid login | Not run | — |
| P1-04 — Valid login and logout | Not run | — |
| P1-05 — Cross-tenant read denied | Not run | — |
| P1-06 — Role-based site/camera writes | Not run | — |
| P1-07 — RTSP/SSRF input blocked | Not run | — |
| P1-08 — Inference invalid schema rejected | Not run | — |
| P1-09 — Postgres from scratch | Not run | — |
| P1-10 — Architectural boundary | Not run | — |

## Given / When / Then scenarios

### P1-01 — Health probes
- **Given:** API and a valid isolated DB are available
- **When:** GET /health/live and /health/ready
- **Then:** 200 with status ok/ready
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD

### P1-02 — Missing auth
- **Given:** An organization endpoint exists
- **When:** Request it without bearer token
- **Then:** 401; no resource data
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD

### P1-03 — Invalid login
- **Given:** A valid test account exists
- **When:** POST /auth/login with wrong password
- **Then:** 401; no token returned
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD

### P1-04 — Valid login and logout
- **Given:** A test admin exists
- **When:** Login, GET /auth/me, then logout and reuse token
- **Then:** Identity is correct; old token returns 401
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD

### P1-05 — Cross-tenant read denied
- **Given:** User belongs only to Org A
- **When:** GET Org B site/camera/incident data
- **Then:** 404 or approved policy error; no data leakage
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD

### P1-06 — Role-based site/camera writes
- **Given:** Viewer and admin accounts exist
- **When:** Viewer creates site/camera; admin creates them
- **Then:** Viewer denied; admin succeeds
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD

### P1-07 — RTSP/SSRF input blocked
- **Given:** An admin and site exist
- **When:** Submit rtsp:// credential URL or traversal as stream_ref
- **Then:** 422; no secret URL persisted
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD

### P1-08 — Inference invalid schema rejected
- **Given:** Pydantic inference models installed
- **When:** Parse invalid class, score, bbox and unknown fields
- **Then:** ValidationError; strict contract
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD

### P1-09 — Postgres from scratch
- **Given:** A disposable PostgreSQL DB exists
- **When:** Run alembic upgrade head and alembic check
- **Then:** Migration applies cleanly and has no drift
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD

### P1-10 — Architectural boundary
- **Given:** Current app tree exists
- **When:** Scan imports and model artifacts
- **Then:** No YOLO, Torch, OpenCV, .pt in business app
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD
