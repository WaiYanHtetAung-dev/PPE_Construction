# CI Integration Notes

## GitLab compatibility

The root `.gitlab-ci.yml` provides backend, PostgreSQL 17 and browser jobs for a Linux
Docker executor with job-scoped service networking. From `backend-v2`, both
providers use `python scripts/ci_checks.py backend` and
`python scripts/ci_checks.py postgres` after installing the requirements specified
in their workflows. `sh frontend-v2/scripts/ci-build.sh` performs the shared
frontend build and typecheck. `python backend-v2/scripts/ci_checks.py browser`
runs the shared browser suite with Chromium. The GitLab browser job uses
Debian Bookworm's Python and a workspace virtual environment, while GitHub
uses Python 3.12. PostgreSQL must be a fresh CI service with `APP_ENV=ci`, user
and database `ppe_ci`, and `DATABASE_URL` targeting `postgres:5432` in GitLab or
`127.0.0.1:5432` in GitHub. The checked-in password is for that disposable service.

GitLab runner execution is **NOT TESTED**. Before migration, validate the config
with GitLab CI Lint and execute it on an authorized runner. Compose validation,
image builds, image security gates and provenance remain
outside the GitLab config. Keep GitHub checks required until equivalent GitLab
checks pass. These jobs require no deployment credentials, registry push,
checkpoint, or production variables. Reserve protected variables and protected
environments for separately authorized release jobs.

- `.github/workflows/backend-ci.yml` is ready for a **standalone backend repository** and uses disposable PostgreSQL 17 in GitHub-hosted CI.
- If V2 is placed in `PPE_Construction/backend-v2`, GitHub only recognizes workflows in **repository-root** `.github/workflows`; **move** the workflow there and set `working-directory: backend-v2` / path-aware commands.
- CI unit suite runs on temporary SQLite (by `tests/conftest.py`); migration suite uses actual PostgreSQL and checks Alembic head. This separation is explicit.
- For a fully production-quality gate, add PostgreSQL application-level integration tests, migrations against a sanitized prior-version snapshot, pinned dependencies, dependency scanning, formatting, and load/security job suites.
- Do not place live RTSP credentials/model weights or production DB URLs in GitHub Actions secrets/CI until a security and deployment design is approved.
- If updating dependencies changes generated JSON schema snapshots, inspect why; do not auto-accept blindly.
