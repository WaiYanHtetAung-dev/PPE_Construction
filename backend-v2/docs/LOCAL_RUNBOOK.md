# Backend V2 Local Runbook (Windows PowerShell)

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
