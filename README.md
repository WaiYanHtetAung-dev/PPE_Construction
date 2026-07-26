# PPE Detect — Construction Site Safety Monitor

A self-hosted web platform that runs `models/finalboss.pt` (an Ultralytics
YOLO model trained on 8 classes) to detect **person / helmet (6 colours) /
vest** and classify each person as **SECURE** (helmet + vest) or
**UNSECURE** (missing one or both) — from an uploaded image/video, your
browser's webcam, or one or more **RTSP cameras** (IP cameras, phone
"IP Webcam" apps, NVR camera feeds, etc.).

It ships with a Frigate-NVR-style dashboard: sidebar navigation, dark/light
theme, login, a SQLite-backed settings page, camera management, and an
events history log with CSV export.

---

## 1. What's included

```
ppe-platform/
├── backend/
│   ├── main.py            FastAPI app: auth, settings, events, detection routes
│   ├── auth.py             Session-cookie auth dependency
│   ├── database.py         SQLite (stdlib sqlite3 — no extra DB server needed)
│   ├── detector.py         Model wrapper + person↔PPE matching logic
│   ├── camera_worker.py    Background thread per RTSP camera (connect, detect, stream)
│   ├── annotate.py         Drawing/annotation of boxes onto frames
│   └── requirements.txt
├── frontend/
│   ├── index.html           App shell: login screen + sidebar + all views
│   └── static/
│       ├── style.css         Dark/light theme, responsive sidebar layout
│       ├── api.js             fetch wrapper (session cookies, 401 handling)
│       ├── theme.js           Dark/light/auto theme toggle
│       └── app.js             Navigation + all view logic
├── models/
│   └── finalboss.pt         Model weights used by the app
├── data/
│   └── ppe_platform.db      Created on first run (users, settings, events)
├── scripts/
│   ├── reset_admin_password.py   Recover access if you lock yourself out
│   └── setup_conda_and_run.ps1   Alternative Windows setup using conda instead of venv
├── .gitignore
├── setup.sh / setup.ps1 / setup.bat   One-command install + prepare
├── run.sh / run.ps1 / run.bat         One-command launch
├── stop.sh / stop.ps1 / stop.bat      Stop the running app
├── logs.sh / logs.ps1 / logs.bat      Tail backend logs
├── errors.sh / errors.ps1 / errors.bat  Tail backend error output only
├── Dockerfile
└── README.md
```

No extra database server, message queue, or account system is needed —
auth and storage are handled with Python's built-in `sqlite3`, `hashlib`,
and `secrets` on purpose, since installing heavy compiled packages has
historically been the main source of setup pain.

---

## 2. Requirements

- **Python 3.10 or newer** — check with `python3 --version` (Ubuntu/macOS)
  or `python --version` (Windows).
- **~2 GB free disk** for the Python virtual environment (PyTorch +
  Ultralytics are large downloads on first `setup`).
- No separate FFmpeg install is needed — `opencv-python-headless` ships
  with its own bundled FFmpeg build, which is what talks to RTSP cameras
  and reads/writes video files.
- A GPU is optional. The app runs on CPU by default; see
  [Configuration](#6-configuration) to force a CUDA device.

---

## 3. Quick start

### Ubuntu / macOS (bash)

```bash
cd ppe-platform
chmod +x *.sh          # first time only, if the executable bit was lost by the zip
./setup.sh             # creates .venv/, installs backend/requirements.txt
./run.sh                # starts the server in the background on port 8000
```

`run.sh` prints the URL to open once it's up:

```
PPE Detect Platform is running (PID 12345)
  On this machine: http://localhost:8000
  On your LAN:     http://192.168.x.x:8000
  Logs:  ./logs.sh
  Stop:  ./stop.sh
```

Open that URL in a browser. Other commands:

```bash
./logs.sh     # tail live backend logs (Ctrl+C to stop watching, server keeps running)
./errors.sh   # tail logs filtered to lines containing "error"
./stop.sh     # stop the background server
```

Run on a different port with `PPE_PORT=9000 ./run.sh`.

### Windows — PowerShell

```powershell
cd ppe-platform
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass   # first time only, if scripts are blocked
.\setup.ps1
.\run.ps1
```

`run.ps1` also starts the server in the background on port 8000 (override
with `$env:PPE_PORT = "9000"` before running) and prints the same kind of
URL summary as the Ubuntu script. Use:

```powershell
.\logs.ps1     # tail live backend logs
.\errors.ps1   # tail logs filtered to errors
.\stop.ps1     # stop the background server
```

### Windows — CMD

```bat
cd ppe-platform
setup.bat
run.bat
```

then `logs.bat`, `errors.bat`, `stop.bat` the same way.

### What `setup` and `run` actually do

1. **`setup`** creates a Python virtual environment at `.venv/` (if it
   doesn't already exist) and installs everything in
   `backend/requirements.txt` into it (FastAPI, Uvicorn, Ultralytics/YOLO,
   OpenCV, NumPy). This step downloads several hundred MB the first time —
   subsequent runs are fast since the packages are cached in `.venv/`.
2. **`run`** re-checks the venv/dependencies (so it's safe to run without
   calling `setup` first), then starts the FastAPI app with Uvicorn,
   listening on `0.0.0.0` so it's reachable both from `localhost` and from
   other devices on your LAN. It writes its process ID to
   `.ppe_platform.pid` and streams output to `backend/logs.log` (and
   `backend/logs.err.log` on Windows) so it can be stopped/tailed later.
3. On first startup ever, the server also creates the SQLite database at
   `data/ppe_platform.db` and a default admin account (see below).

---

## 4. First run — logging in

The first time the server starts, it prints a confirmation to
`logs.log`/the console:

```
============================================================
 First run — a default admin account was created:
   username: admin
   password: admin123
============================================================
```

Log in at the app URL with:

- **username:** `admin`
- **password:** `admin123`

Then go to **Settings → Account** and change the password immediately —
this default is meant to be changed on first login, not left in place.
This message only appears once; the account persists across every run
after that (it lives in `data/ppe_platform.db`).

**Locked out?** Run `python scripts/reset_admin_password.py` (from inside
the activated virtual environment) to reset the admin password without
needing to log in first.

To add more accounts (e.g. a read-only viewer for a site supervisor), call
the API as an already-logged-in admin:

```bash
curl -X POST http://localhost:8000/api/auth/users \
  -H "Content-Type: application/json" \
  --cookie "ppe_session=<your session cookie>" \
  -d '{"username": "supervisor", "password": "changeme123", "role": "viewer"}'
```

(There's no "add user" screen in the UI yet — this is the one piece still
API-only.)

---

## 5. The UI

- **Dashboard** — 7-day secure/unsecure totals, an "Active alerts" panel
  (unsecure incidents), and a feed of recent events. The Dashboard sidebar
  item shows an unread-alert badge; visiting the page clears it.
- **Live Camera** — your browser's webcam streamed through the model over a
  WebSocket, plus a grid of any RTSP cameras you've added (see §7). The
  webcam idle state is a quiet placeholder tile with a small "Start camera"
  button.
- **Image Analysis** / **Video Analysis** — drag-and-drop, annotated
  result, downloadable video.
- **Events** — a filterable report: date range (today/week/month/custom),
  status (secure/unsecure), and source (image/video/live/RTSP), with a
  **CSV export** button that respects the current filters. Click any row
  to open a detail view with the full annotated frame and a close-up
  capture of each unsecure person.
- **Settings** — theme (dark/light/match system), site name, confidence
  threshold, video frame-skip, event retention, in-app alert toggle
  (site-wide) + alert sound (per-device), **camera management** (add/edit/
  enable/disable/delete RTSP cameras), and password change.

Sidebar collapses into a slide-in drawer under ~880px width; stat rows and
grids reflow to a single column on phones. This pass also tightened up the
visual polish across the board — consistent card shadows and hover states,
a clearer accent on the active nav item, a hazard-stripe accent on the
login card, and a smoother transition between views — so it should feel
noticeably less flat than before.

---

## 6. Configuration

Most settings are editable from the **Settings** page and persisted in the
database. A few things need to be set before the server starts, via
environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `PPE_MODEL_PATH` | `models/finalboss.pt` | Path to the weights file |
| `PPE_DEVICE` | auto | Force a device, e.g. `cpu`, `cuda:0` |
| `PPE_DB_PATH` | `data/ppe_platform.db` | SQLite database location |
| `PPE_PORT` | `8000` | Port used by `run.sh` / `run.ps1` / `run.bat` |

The confidence threshold set in Settings takes effect immediately (no
restart needed) — it updates the running detector in memory as well as
the database.

---

## 7. RTSP cameras — setup and troubleshooting

### Adding a camera

Go to **Settings → Cameras**, give it a name, and paste the RTSP URL,
for example:

```
rtsp://username:password@192.168.1.50:554/stream1
```

Once added and enabled:

- A background thread opens the stream, samples ~1 frame/second for
  detection (PPE status doesn't change frame-to-frame, so ~1fps keeps CPU
  usage sane with multiple cameras), and **reconnects automatically** if
  the connection drops.
- The camera appears as a tile on the **Live Camera** page, streamed to
  the browser as MJPEG — no plugins needed.
- Disabling or deleting a camera stops its worker thread immediately.
- If a camera can't connect, its status dot on **Settings → Cameras**
  turns red and shows a `last_error` message explaining why — check that
  first any time a feed doesn't come up.

### Diagnosing a connection that won't open

Using your camera as a worked example —
`rtsp://SaiMg:GGWP9124@192.168.89.61:8080/h264_ulaw.sdp` — this URL shape
(port `8080`, path `h264_ulaw.sdp`) is the pattern used by the Android
**"IP Webcam"** app, so the steps below are written with that app in mind,
but the same checks apply to any RTSP source.

1. **Confirm the phone/camera app is actually running and serving.**
   In IP Webcam, you must open the app and tap **Start server** — the app
   needs to stay open (screen can be off on some Android versions, but
   test with the screen on first) and shows the RTSP/HTTP URL once the
   server is live. If the app isn't running, nothing downstream will work.

2. **Confirm both devices are on the same network.** The server running
   this platform and the camera (`192.168.89.61` here) must be able to
   reach each other directly — same Wi-Fi network/subnet, not a guest
   network or a phone's separate mobile-data connection, and not across a
   VPN that doesn't route LAN traffic. If this backend runs inside Docker,
   WSL2, or a VM, its network namespace may **not** have direct access to
   your LAN by default — you'd need bridged/host networking (Docker
   `--network host` on Linux, or WSL2 mirrored networking mode) for it to
   reach `192.168.89.61` at all.

3. **Test the URL outside this app first**, to prove it's a network/camera
   issue and not something in this codebase. From the same machine that
   runs the backend:
   ```bash
   ffplay "rtsp://SaiMg:GGWP9124@192.168.89.61:8080/h264_ulaw.sdp"
   ```
   or open it in **VLC → Media → Open Network Stream**. If VLC/ffplay
   can't connect either, the problem is the network path or the camera
   app — fix that first, then retry in this platform.

4. **Check the port is reachable.** From the backend machine:
   ```bash
   # Linux/macOS
   nc -vz 192.168.89.61 8080
   # Windows PowerShell
   Test-NetConnection -ComputerName 192.168.89.61 -Port 8080
   ```
   If this fails, it's almost always a firewall (on the phone, the router,
   or the server machine) or the devices genuinely being on different
   subnets/VLANs — not something fixable in application code.

5. **RTSP transport (already fixed in this build).** Many phone/IP-camera
   RTSP servers default to UDP transport, which frequently can't traverse
   normal Wi-Fi/NAT setups and shows up as OpenCV/FFmpeg silently failing
   to open the stream even though the camera is reachable. `camera_worker.py`
   now forces **TCP transport** and sets explicit open/read timeouts before
   every connection attempt, which resolves the large majority of "won't
   connect" cases. If you're running an older copy of this project without
   that fix, pull the updated `backend/camera_worker.py`.

6. **Credentials with special characters.** If your username or password
   contains `@ : / ? # &` or similar, URL-encode those characters in the
   RTSP URL (e.g. `@` becomes `%40`) — an un-encoded `@` in the password
   will be misread as the start of the host portion of the URL.

7. **Still failing?** Check `last_error` on **Settings → Cameras** (also
   returned by `GET /api/cameras`) for the specific reason, and check
   `backend/logs.log` / `./errors.sh` (`.\errors.ps1` on Windows) around
   the time you added the camera.

### How detection load is shared across cameras

Detection across the webcam feed and all RTSP cameras is serialized
through a single lock around the model, since the underlying YOLO
predictor isn't guaranteed safe for concurrent calls from multiple
threads — this trades a little throughput for correctness. If you're
running several cameras and CPU-bound inference becomes the bottleneck,
that lock is the place to look first (e.g. running multiple model
instances, or moving to GPU via `PPE_DEVICE=cuda:0`).

---

## 8. Live alerts and incident logging

Rather than logging a new event every time a frame shows a violation
(which would flood the log with near-duplicates for one ongoing issue),
both the webcam feed and RTSP cameras track violations as **incidents**:

- An event is logged the moment someone goes from secure → unsecure.
- While the violation continues, a reminder is logged (and a Dashboard
  alert fires) every **2 minutes** — not every frame.
- The incident is considered resolved after **5 consecutive seconds** of
  everyone being secure again (this hysteresis avoids flickering on/off
  from single missed detections).

RTSP cameras track this independently per camera, so one camera's ongoing
violation doesn't suppress or interfere with another's.

---

## 9. Manual setup (without the scripts)

```bash
python3 -m venv .venv
source .venv/bin/activate        # .venv\Scripts\activate on Windows
pip install -r backend/requirements.txt
cd backend
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

---

## 10. API reference

All routes below (except `/api/auth/login` and `/api/health`) require a
valid session cookie — log in first, or the browser handles this
automatically once you're signed in.

- `POST /api/auth/login` / `POST /api/auth/logout` / `GET /api/auth/me`
- `POST /api/auth/change-password` — `{old_password, new_password}`
- `POST /api/auth/users` — admin only, creates a new account
- `GET /api/settings` / `POST /api/settings` — admin only for POST
- `GET /api/events?limit=&offset=&unsecure_only=` — simple event list (used by the Dashboard feed)
- `GET /api/events/report?status=&source=&start_date=&end_date=&limit=&offset=` — filtered/paginated report (used by the Events page); returns `{events, total}`
- `GET /api/events/export?status=&source=&start_date=&end_date=` — same filters, streams a CSV download
- `GET /api/events/stats?days=7` — aggregate counts
- `GET /api/events/{id}` — full detail (annotated image + per-person captures) for the event modal
- `GET /api/alerts/poll?since_id=` — new unsecure events since `since_id`, used by the Dashboard's toast/badge poller
- `GET /api/cameras` — list cameras with live `status`/`last_error`
- `POST /api/cameras` — admin only, `{name, rtsp_url, enabled}`
- `PUT /api/cameras/{id}` — admin only, partial update; restarts the camera's worker thread
- `DELETE /api/cameras/{id}` — admin only, stops the worker and removes the camera
- `GET /api/cameras/{id}/stream` — MJPEG stream (point an `<img>` tag at this)
- `POST /api/detect/image` — multipart `file`; annotated JPEG + JSON
- `POST /api/detect/video` — multipart `file`, optional `process_every_n`; `{job_id}`
- `GET /api/jobs/{job_id}` — poll status/progress
- `GET /api/download/{job_id}` — annotated `.mp4`
- `WS /ws/live` — base64 JPEG frames in, `{annotated_b64, persons, summary, inference_ms}` out
- `GET /api/health` — `{status, model_loaded}`

---

## 11. Known limitations

- In-app alerts (toasts + Dashboard badge) are the only notification
  channel — there's no email/SMS delivery. This was a deliberate scope
  decision, not an oversight.
- Video codec: OpenCV's default Python wheel often lacks an H.264 encoder,
  so inline browser preview of processed videos may not always work even
  though the download plays fine in VLC/most players.
- RTSP camera streams rely on OpenCV's bundled FFmpeg support for the
  `rtsp://` protocol — this is the same mechanism already used for video
  file uploads, so no extra dependency is needed, but very unusual camera
  codecs could still be a problem; check `camera.status`/`last_error` from
  `GET /api/cameras` if a camera won't connect (see §7 for a full
  troubleshooting walkthrough).
- Detection across the webcam feed and all RTSP cameras is serialized
  through one lock (see §7) — with several cameras and a CPU-only model,
  per-camera detection latency will rise proportionally.
- Test on a real RTSP camera and a few days of Events data before relying
  on the report/export/alerts for anything important.

---

## 12. Git ready

To share this repo, initialize git and commit the source files:

```bash
git init
git add .
git commit -m "Initial PPE Platform startup-ready project"
```

The repository keeps source code and configuration, while ignoring local
build artifacts, virtual environments, logs, and the runtime `data/`
folder.
