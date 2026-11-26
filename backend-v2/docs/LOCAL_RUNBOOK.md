# Backend V2 Local Runbook (Windows PowerShell)

## Same-origin browser smoke (Task 1)

Run from the workspace root on D: with Node 22.12+ (or Node 24), pnpm 9.15.9
and Python 3.12 available. The smoke runner starts a loopback-only Vite preview
of `dist` and a separate loopback-only FastAPI server, both on OS-assigned ports.
Vite forwards `/api` to `PPE_API_ORIGIN`, preserving `/api/v1` paths. The runner
sets this variable itself and reuses the existing pytest SQLite fixture and
synthetic account. Docker, PostgreSQL, `.env` setup and model files are unnecessary.

```powershell
New-Item -ItemType Directory -Force .venv\smoke-tmp | Out-Null
$env:TEMP = (Resolve-Path .venv\smoke-tmp).Path
$env:TMP = $env:TEMP
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path (Resolve-Path .venv).Path 'smoke-browsers'
$env:PIP_CACHE_DIR = Join-Path (Resolve-Path .venv).Path 'pip-cache'
python -m venv .venv\browser-smoke
$smokePython = (Resolve-Path .venv\browser-smoke\Scripts\python.exe).Path
& $smokePython -m pip install -r backend-v2\requirements-browser-smoke.txt
& $smokePython -m playwright install chromium
Push-Location frontend-v2
pnpm install --frozen-lockfile --ignore-scripts --store-dir ..\.venv\pnpm-store
pnpm exec tsc --noEmit --project tsconfig.json
pnpm run build
Pop-Location
Push-Location backend-v2
& $smokePython -m pytest -q tests/browser_smoke.py
Pop-Location
```

To see the dashboard in a real browser after the setup above, run the same
smoke test with the Playwright Inspector:

```powershell
$env:PWDEBUG = '1'
Push-Location backend-v2
try {
    & $smokePython -m pytest -s tests/browser_smoke.py -k same_origin_session_and_data
} finally {
    Pop-Location
    Remove-Item Env:\PWDEBUG
}
```

Use **Step over** in the Inspector to watch the test sign in, render synthetic
site, camera and incident data, and sign out. The browser and local servers
close when the test ends. The dashboard does not display the synthetic media
pipeline or a live stream. Decoder/ONNX timing and sampling comparisons are
reported by the separate Linux stack command, along with a real ONNX worker
stop and restart while three synthetic cameras keep sampling. See the
[disposable stack prerequisites](phases/04-media-gateway.md#disposable-https-stack-acceptance)
for Linux runner setup.

## Synthetic pilot diagnostics in a browser

Open a successful **Backend V2 CI (monorepo)** run and download
**synthetic-pilot-diagnostics** from the run's Artifacts section. Extract the
ZIP into the workspace (for example under `.venv`) and open
`synthetic-pilot.html` in a browser. The report shows per-camera decoded FPS,
sampling and result rates, frame drops, and time to the first fresh result
after restarting the synthetic worker. The source reconnect soak section shows
six EOF or stalled-read cycles, peer inference results, and per-camera frame
counts. The report opens directly from disk.

On a disposable Linux runner with the stack prerequisites, generate the same
report from `backend-v2`:

```bash
mkdir -p ../.venv
python scripts/ci_checks.py postgres
python scripts/ci_checks.py stack --report ../.venv/synthetic-pilot.html
```

GitHub retains the HTML artifact for 14 days.

## Browser CI

In GitHub Actions, `.github/workflows/frontend-v2-ci.yml` runs the existing
frontend checks first. The browser steps run from `backend-v2` on Ubuntu:

```sh
python -m pip install -r requirements-browser-smoke.txt
python -m playwright install --with-deps chromium
python -m pytest -q tests/browser_smoke.py
```

For manual local integration with a separate disposable backend, start Vite dev
or preview with `PPE_API_ORIGIN` set to the backend origin (for example,
`http://127.0.0.1:8000`). Bind the frontend to loopback with `--host 127.0.0.1`.
The Vite preview proxy is for integration tests. Any deployment proxy must
serve the UI and forward `/api/v1` on the same HTTPS origin. The static Nginx
CI image remains a build artifact.

## Start development

```powershell
cd D:\ppe-backend-v2-starter
.\.venv\Scripts\Activate.ps1
# .env must point at isolated local development DB; never a shared/production DB.
docker compose up -d postgres
python -m alembic upgrade head
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/docs` if `ENABLE_API_DOCS=true`. This is for local development only.

## Stop development

```powershell
# Press Ctrl+C in Uvicorn terminal
# Then stop only the local Postgres service:
docker compose stop postgres
```

**Never run `docker compose down -v` on a database you want to keep.** It destroys local named volumes. Rehearse backup + restore separately before production.

## Diagnose common issues

- `py -3.12` not found → install compatible Python or use `py -m venv .venv` and check `python --version`.
- `Docker daemon is not running` → start Docker Desktop, verify `docker version`.
- `Connection refused on 5432` → verify `docker compose ps`, `.env` host/port and local port conflicts.
- `psycopg` import missing → re-install `requirements-dev.txt` in the activated venv.
- `alembic check` reports pending operations → review ORM models and migration; **do not auto-delete DB**.
- `/docs` returns 404 → ensure `.env` has `ENABLE_API_DOCS=true` and restart Uvicorn.
- `401` on org route → login, use bearer token and a real organization ID from bootstrap account.
- `404` on someone else's organization is intentional privacy protection; never 'fix' by bypassing authorization.
- `pytest` passes but PG fails → unit tests use SQLite; inspect migration error in disposable PostgreSQL.

## API smoke sequence

1. `/health/live` → `{"status":"ok"}`.
2. `/health/ready` → `{"status":"ready"}` with running Postgres.
3. `POST /api/v1/auth/login` → short-lived opaque access token.
4. Set Swagger **Authorize**, `GET /api/v1/auth/me` → memberships.
5. `POST /api/v1/organizations/{organization_id}/sites` with `{"name":"Demo Site"}`.
6. `POST /api/v1/organizations/{organization_id}/sites/{site_id}/cameras` with `{"name":"Test Cam", "stream_ref":"stream:demo/test-cam", "enabled":true}`.
7. `GET /api/v1/organizations/{organization_id}/incidents` → empty list in new database.
8. Logout, confirm token no longer accesses `/auth/me`.

No stream, frame, model or incident processing will occur; these are later phases.
