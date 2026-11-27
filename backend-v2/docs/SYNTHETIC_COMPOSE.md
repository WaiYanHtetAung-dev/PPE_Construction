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
         '-f', 'compose.synthetic.media.yaml', '-f', 'compose.synthetic.ai.yaml')
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

The AI overlay runs a separate CPU ONNX service. It generates and signs a
synthetic model per lab startup, verifies it under a restricted verifier role,
and assigns it to the North camera. The worker reads model and frame volumes
read-only. Internal HTTPS is pinned to a disposable CA. The snapshot and
eligibility listeners use separate read-only PostgreSQL roles. The fixture's
signing key exists only in the bootstrap process.

As a North organization admin, select **View model assignment** on the camera
row to see the configured model key, version and assignment revision. The
dashboard requests these details only when opened or refreshed. The assignment
display describes the saved selection. The ONNX probe separately verifies
current eligibility and inference. South's viewer role has no assignment
control.

## Verify

Against a fresh lab, from the same directory:

```powershell
python -m pip install -r requirements-browser-smoke.txt
python -m playwright install chromium
python -m tests.synthetic_compose_browser --origin "http://$binding" --env-file .env.synthetic-stack
python -m tests.synthetic_compose_browser --origin "http://$binding" --env-file .env.synthetic-stack --media-state online
docker compose @lab exec -T ai-control python -m tests.synthetic_compose_ai probe
docker compose @lab stop --timeout 10 synthetic-site
python -m tests.synthetic_compose_browser --origin "http://$binding" --env-file .env.synthetic-stack --media-state offline
docker compose @lab start synthetic-site
python -m tests.synthetic_compose_browser --origin "http://$binding" --env-file .env.synthetic-stack --media-state online
docker compose @lab exec -T ai-control python -m tests.synthetic_compose_ai probe --record-synthetic-incident
python -m tests.synthetic_compose_browser --origin "http://$binding" --env-file .env.synthetic-stack --expect-probe-incident
```

The test registers a camera and advances the seeded incident. The
[GitHub workflow](../../.github/workflows/synthetic-compose-ci.yml) starts a
fresh stack for each run. It also verifies the two audit records in PostgreSQL
and checks that the API role cannot insert incidents or alter audit entries.
The ONNX probe checks worker authentication and verifies that the network frame's
detections, camera, organization, site and model match the scoped assignment.
The explicit incident probe then submits a test-confirmed event through the
existing ingestion app in-process, retries that event once and verifies one
incident and outbox row. The browser checks that North shows one probe incident
and South cannot see it. Use a fresh lab for this count-based acceptance run.

## Stop and recover

```powershell
docker compose @lab ps -a
docker compose @lab logs --tail 60 bootstrap api frontend central-media gateway-preview synthetic-site
docker compose @lab logs --tail 60 ai-fixtures ai-bind ai-control inference-worker
docker compose @lab down
```

`down` retains the lab database. Run the startup command again with the same
file to resume. For another clean acceptance run, generate a new environment
file and use it in `$lab`. When you are finished with a specific disposable
lab and want to erase its database, confirm its project in `docker compose
@lab ps -a` and run `docker compose @lab down --volumes` with that file.

The test CA, certificate and model verification are valid for one hour. Run
`down` followed by startup with the same file to renew them and keep the lab
database. The independent revocation and worker restart suite can be run using
the [outbound media runbook](ADR-006-OUTBOUND-MEDIA.md#reproduce-the-synthetic-stack).

The published UI uses the real incident read and status routes. The probe
exercises delivery idempotency for a single event in the disposable lab.
Automatic detection-to-incident rules, deduplication windows, outbox publishing,
evidence access and notifications require ADR-005 and ADR-007.
