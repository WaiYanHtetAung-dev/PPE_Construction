# Local Validation Evidence — 2026-11-18

These checks ran in the assistant's isolated working environment against the packaged Backend V2 starter; **not** against a deployed PPE Construction server.

| Check | Observed outcome | Scope / important limitation |
| --- | --- | --- |
| `python -m pytest -q` | **24 passed** | SQLite test database; no real PostgreSQL application integration |
| `python scripts/verify_contracts.py` | **PASS** | Checked-in OpenAPI + inference v1 snapshots match models locally |
| `python scripts/check_architecture.py` | **PASS** | AST import and model artifact boundary guard on `app/` only |
| `python scripts/verify_docs.py` | **PASS** | 29 Markdown documents with local link targets checked |
| `python -m compileall -q app tests scripts` | **PASS** | Python syntax compilation for selected directories |
| PostgreSQL Docker migration upgrade / `alembic check` | **NOT RUN** | Docker not available in this environment; CI job supplied but not executed |
| GitHub Actions workflows | **NOT RUN** | Template only; must commit/push via PR to execute |
| Actual YOLO model, GPU, RTSP/camera, browser and 50–100 camera benchmark | **NOT RUN** | These services are planned, not provided in this starter |

### Important clarification

The 75 test cases in `tests/specs` are **future phase acceptance definitions** and are not included in the 24 passing automated tests. The final release gate remains **blocked** pending real Postgres integration, authorization reviews and media/inference load tests.

### Known defects / design gaps

- `FrameRef.object_key` currently validates length, not path/URL security. A trusted inference/media resolver **must** allowlist permitted object namespace and reject traversal/URLs before fetching frames.
- `model_versions` lacks organization ownership; Phase 2 registry policy must be decided before writing an organization-scoped API.
- Existing org/site/camera endpoints do not yet provide full create/update/delete/soft-delete lifecycle and write audit service.
