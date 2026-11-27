# Disposable PPE Compose lab

The lab serves the built React dashboard and the real FastAPI API through one
loopback origin. It runs PostgreSQL in a private Compose network, waits for a
one-shot Alembic migration and fixture bootstrap, and gives the API a separate
database role. The fixture creates three synthetic organizations. The demo
operator can update North incidents, can view South and has no access to the
third organization. The seeded incident is available for trying the existing
`open → acknowledged → resolved` workflow.

## Start

Use a development Docker context with Linux containers, Docker Compose v2 and
Python 3.12+. The context must be isolated from shared or production Docker
projects. In PowerShell from `backend-v2`:

```powershell
python scripts/create_synthetic_environment.py .env.synthetic-stack
$lab = @('--env-file', '.env.synthetic-stack', '-f', 'compose.synthetic.yaml',
         '-f', 'compose.synthetic.media.yaml')
docker compose @lab config --quiet
docker compose @lab up --build --wait --wait-timeout 90
$binding = docker compose @lab port frontend 8080
Start-Process "http://$binding"
```

Sign in as `operator@ppe-lab.example.com` with the value of
`PPE_LAB_LOGIN_PASSWORD` from your generated file. Keep that file private.
Compose assigns a free port on `127.0.0.1`. Only the frontend proxy is
published. Keep the file to reopen the same project and its data. Each
generated environment selects a new project name and credentials. Avoid
exporting variables named `PPE_LAB_*` or `COMPOSE_PROJECT_NAME` in the shell
that runs the lab so Compose uses the generated values.

Select **Check camera status** for **North Synthetic Camera** and wait for
**Online**. Use **Load video preview** to open a short H.264 clip. The lab
creates video in the synthetic site container. Its RTSP server listens only on
that container's loopback. The publisher initiates authenticated, encrypted
SRT to central MediaMTX, and the gateway reads only the fixed central ingress
through a local RTSP relay. PostgreSQL, ingress and preview have no host ports.
If you ran an earlier database-only lab, create a fresh environment file for
this media run so the seeded camera has the matching gateway identity.

## Verify

Against a fresh lab, from the same directory:

```powershell
python -m pip install -r requirements-browser-smoke.txt
python -m playwright install chromium
python -m tests.synthetic_compose_browser --origin "http://$binding" --env-file .env.synthetic-stack
python -m tests.synthetic_compose_browser --origin "http://$binding" --env-file .env.synthetic-stack --media-state online
docker compose @lab stop --timeout 10 synthetic-site
python -m tests.synthetic_compose_browser --origin "http://$binding" --env-file .env.synthetic-stack --media-state offline
docker compose @lab start synthetic-site
python -m tests.synthetic_compose_browser --origin "http://$binding" --env-file .env.synthetic-stack --media-state online
```

The test registers a camera and advances the seeded incident. The
[GitHub workflow](../../.github/workflows/synthetic-compose-ci.yml) starts a
fresh stack for each run. It also verifies the two audit records in PostgreSQL
and checks that the API role cannot insert incidents or alter audit entries.

## Stop and recover

```powershell
docker compose @lab ps -a
docker compose @lab logs --tail 60 bootstrap api frontend central-media gateway-preview synthetic-site
docker compose @lab down
```

`down` retains the lab database. Run the startup command again with the same
file to resume. For another clean acceptance run, generate a new environment
file and use it in `$lab`. When you are finished with a specific disposable
lab and want to erase its database, confirm its project in `docker compose
@lab ps -a` and run `docker compose @lab down --volumes` with that file.

The signed synthetic ONNX suite can be run separately using the
[outbound media runbook](ADR-006-OUTBOUND-MEDIA.md#reproduce-the-synthetic-stack).
The published UI uses the real incident read and status routes. Detection
ingestion policy, evidence access and notifications are tracked under ADR-005
and ADR-007.
