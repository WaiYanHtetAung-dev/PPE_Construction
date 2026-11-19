# Adding Backend V2 to the existing PPE_Construction GitHub repository

Target repository from earlier work: `WaiYanHtetAung-dev/PPE_Construction`. **Do not alter the legacy `main` implementation in place**. The scripts and docs in this package do **not** push changes to GitHub automatically.

## Safe manual branch flow — Windows PowerShell

```powershell
# Run in a directory where you want a separate working copy
# Git must be installed and authenticated.
git clone https://github.com/WaiYanHtetAung-dev/PPE_Construction.git
cd PPE_Construction
git switch -c feature/backend-v2-foundation

# Extract the new Developer Kit ZIP separately, then copy its project contents
# INTO this repo as the backend-v2 directory. This should include app/, docs/,
# tests/, contracts/, alembic/, AGENTS.md, agent.md and README.md.
# Avoid copying another whole legacy V1 folder or generated caches.

# GitHub workflows are only discovered at repo-root .github/workflows.
# Copy infra/github-workflows/backend-v2-monorepo-ci.yml to:
#   .github/workflows/backend-v2-ci.yml

git status --short
git add backend-v2 .github/workflows/backend-v2-ci.yml
git commit -m "chore(v2): bootstrap backend docs, contracts, tests and CI"
git push -u origin feature/backend-v2-foundation
```

Open a **draft pull request** against `main`. Keep deployment off; use pull-request CI to inspect effects. Review before merge. This flow intentionally leaves V1 implementation unaffected until a separate cutover is approved.

## Repo layout after integration

```text
PPE_Construction/
  backend/                 # Existing V1 — unchanged
  frontend/                # Existing V1 — unchanged
  models/                  # Existing V1 — unchanged
  backend-v2/              # This starter / developer kit content
    AGENTS.md
    agent.md
    README.md
    app/ alembic/ contracts/ docs/ tests/ scripts/
  .github/workflows/
    backend-v2-ci.yml      # COPY from backend-v2/infra/github-workflows/
```

## What still needs manual verification

- `backend-v2/` project paths used in the workflow match the actual structure.
- Python dependencies install, SQLite suite passes, disposable PostgreSQL migrations/check pass on GitHub-hosted runner.
- Verify `.env`, DB backups, credentials, RTSP URLs and model weights were not staged accidentally.
- Branch protection/required checks, reviewers, CODEOWNERS (if team agreed), release permissions and artifact storage policy need deliberate repository setup.

See `docs/CI_NOTES.md`, `docs/PR_TEMPLATE.md` and `AGENTS.md`.
