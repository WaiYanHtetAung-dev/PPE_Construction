# CI Integration Notes

- `.github/workflows/backend-ci.yml` is ready for a **standalone backend repository** and uses disposable PostgreSQL 17 in GitHub-hosted CI.
- If V2 is placed in `PPE_Construction/backend-v2`, GitHub only recognizes workflows in **repository-root** `.github/workflows`; **move** the workflow there and set `working-directory: backend-v2` / path-aware commands.
- CI unit suite runs on temporary SQLite (by `tests/conftest.py`); migration suite uses actual PostgreSQL and checks Alembic head. This separation is explicit.
- For a fully production-quality gate, add PostgreSQL application-level integration tests, migrations against a sanitized prior-version snapshot, pinned dependencies, dependency scanning, formatting, and load/security job suites.
- Do not place live RTSP credentials/model weights or production DB URLs in GitHub Actions secrets/CI until a security and deployment design is approved.
- If updating dependencies changes generated JSON schema snapshots, inspect why; do not auto-accept blindly.
