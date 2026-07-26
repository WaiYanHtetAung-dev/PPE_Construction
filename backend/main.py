from __future__ import annotations

import asyncio
import base64
import csv
import io
import json
import os
import shutil
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from fastapi import (
    Cookie,
    Depends,
    FastAPI,
    File,
    HTTPException,
    Response,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
    BackgroundTasks,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import auth
import database
from annotate import annotate_frame
from camera_worker import CameraWorker
from detector import PPEDetector, HELMET_CLASS_IDS, VEST_CLASS_ID

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
MODEL_PATH = os.environ.get("PPE_MODEL_PATH", str(PROJECT_ROOT / "models" / "finalboss.pt"))
DEVICE = os.environ.get("PPE_DEVICE")  # e.g. "cuda:0", "cpu", or leave unset for auto
JOBS_DIR = Path(tempfile.gettempdir()) / "ppe_platform_jobs"
JOBS_DIR.mkdir(parents=True, exist_ok=True)

detector: Optional[PPEDetector] = None
jobs: dict[str, dict] = {}
camera_workers: dict[int, CameraWorker] = {}


def _start_camera_worker(camera: dict) -> None:
    """Start (or restart) the background thread for one camera row."""
    existing = camera_workers.pop(camera["id"], None)
    if existing is not None:
        existing.stop()
    if not camera["enabled"]:
        return
    worker = CameraWorker(
        camera_id=camera["id"],
        name=camera["name"],
        rtsp_url=camera["rtsp_url"],
        detect_and_annotate=_detect_and_annotate,
        log_event=_log_detection_event,
    )
    camera_workers[camera["id"]] = worker
    worker.start()


def _stop_camera_worker(camera_id: int) -> None:
    worker = camera_workers.pop(camera_id, None)
    if worker is not None:
        worker.stop()

# --- Live-camera incident tracking ---------------------------------------
# Instead of logging an event on a flat timer (which turns one ongoing
# violation into dozens of near-duplicate events), we track it as a single
# "incident": one event when it starts, periodic reminders while it
# continues, and nothing else until it's resolved and happens again.
_live_incident_active = False
_live_incident_last_alert_ts = 0.0
_live_secure_streak_start: float | None = None

LIVE_INCIDENT_REMINDER_SECONDS = 120  # re-log/re-alert every 2 min if still ongoing
LIVE_SECURE_HYSTERESIS_SECONDS = 5    # need this many seconds of "all secure" before calling it resolved


@asynccontextmanager
async def lifespan(app: FastAPI):
    global detector
    created = database.init_db()
    if created:
        username, password = created
        print("=" * 60)
        print(" First run — a default admin account was created:")
        print(f"   username: {username}")
        print(f"   password: {password}")
        print(" Log in and change this password from Settings.")
        print("=" * 60)

    if not Path(MODEL_PATH).exists():
        raise RuntimeError(f"Model weights not found at {MODEL_PATH}")
    settings = database.get_settings()
    conf = float(settings.get("confidence_threshold", "0.35"))
    detector = PPEDetector(MODEL_PATH, device=DEVICE, conf=conf)

    for camera in database.list_cameras(enabled_only=True):
        _start_camera_worker(camera)

    yield

    for camera_id in list(camera_workers.keys()):
        _stop_camera_worker(camera_id)
    detector = None


app = FastAPI(title="PPE Detect Platform", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)


@app.middleware("http")
async def no_cache_for_static(request, call_next):
    """Static JS/CSS get an ETag from StaticFiles, but browsers can still
    serve them straight from disk cache without even checking that ETag.
    Forcing revalidation means every reload picks up a new deploy of
    app.js/style.css immediately — no more stale-cache confusion after
    updating the code."""
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str = "viewer"


@app.post("/api/auth/login")
async def login(body: LoginRequest, response: Response):
    user = database.verify_user(body.username, body.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = database.create_session(user["id"])
    response.set_cookie(
        auth.SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        max_age=database.SESSION_TTL_SECONDS,
        path="/",
    )
    return {"username": user["username"], "role": user["role"]}


@app.post("/api/auth/logout")
async def logout(response: Response, ppe_session: str | None = Cookie(default=None)):
    if ppe_session:
        database.delete_session(ppe_session)
    response.delete_cookie(auth.SESSION_COOKIE, path="/")
    return {"status": "ok"}


@app.get("/api/auth/me")
async def me(user=Depends(auth.get_current_user)):
    return {"username": user["username"], "role": user["role"]}


@app.post("/api/auth/change-password")
async def change_password(body: ChangePasswordRequest, user=Depends(auth.get_current_user)):
    check = database.verify_user(user["username"], body.old_password)
    if check is None:
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    if len(body.new_password) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters")
    database.change_password(user["id"], body.new_password)
    return {"status": "ok"}


@app.post("/api/auth/users")
async def create_user(body: CreateUserRequest, user=Depends(auth.get_current_user)):
    auth.require_admin(user)
    try:
        database.create_user(body.username, body.password, body.role)
    except Exception:
        raise HTTPException(status_code=400, detail="Username already exists")
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
@app.get("/api/settings")
async def get_settings(user=Depends(auth.get_current_user)):
    return database.get_settings()


@app.post("/api/settings")
async def update_settings(payload: dict, user=Depends(auth.get_current_user)):
    auth.require_admin(user)
    updated = database.update_settings(payload)
    if "confidence_threshold" in payload and detector is not None:
        try:
            detector.conf = float(payload["confidence_threshold"])
        except ValueError:
            pass
    return updated


# ---------------------------------------------------------------------------
# Cameras (RTSP)
# ---------------------------------------------------------------------------
class CameraRequest(BaseModel):
    name: str
    rtsp_url: str
    enabled: bool = True


class CameraUpdateRequest(BaseModel):
    name: str | None = None
    rtsp_url: str | None = None
    enabled: bool | None = None


def _camera_with_status(camera: dict) -> dict:
    worker = camera_workers.get(camera["id"])
    camera["status"] = worker.status if worker else ("disabled" if not camera["enabled"] else "stopped")
    camera["last_error"] = worker.last_error if worker else None
    return camera


@app.get("/api/cameras")
async def list_cameras_route(user=Depends(auth.get_current_user)):
    return {"cameras": [_camera_with_status(c) for c in database.list_cameras()]}


@app.post("/api/cameras")
async def create_camera_route(body: CameraRequest, user=Depends(auth.get_current_user)):
    auth.require_admin(user)
    camera_id = database.create_camera(body.name, body.rtsp_url, body.enabled)
    camera = database.get_camera(camera_id)
    _start_camera_worker(camera)
    return _camera_with_status(camera)


@app.put("/api/cameras/{camera_id}")
async def update_camera_route(camera_id: int, body: CameraUpdateRequest, user=Depends(auth.get_current_user)):
    auth.require_admin(user)
    if database.get_camera(camera_id) is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    database.update_camera(camera_id, name=body.name, rtsp_url=body.rtsp_url, enabled=body.enabled)
    camera = database.get_camera(camera_id)
    _start_camera_worker(camera)  # restarts with new settings; stops the thread if now disabled
    return _camera_with_status(camera)


@app.delete("/api/cameras/{camera_id}")
async def delete_camera_route(camera_id: int, user=Depends(auth.get_current_user)):
    auth.require_admin(user)
    _stop_camera_worker(camera_id)
    database.delete_camera(camera_id)
    return {"status": "ok"}


async def _mjpeg_generator(camera_id: int):
    boundary = b"--frame\r\n"
    try:
        while True:
            worker = camera_workers.get(camera_id)
            if worker is None:
                break
            if worker.latest_jpeg is not None:
                yield (
                    boundary
                    + b"Content-Type: image/jpeg\r\n"
                    + f"Content-Length: {len(worker.latest_jpeg)}\r\n\r\n".encode()
                    + worker.latest_jpeg
                    + b"\r\n"
                )
            # ~3fps to the browser is plenty smooth for an MJPEG preview
            # and keeps bandwidth reasonable with several camera tiles open.
            await asyncio.sleep(0.3)
    except asyncio.CancelledError:
        pass  # client disconnected / navigated away — just stop generating


@app.get("/api/cameras/{camera_id}/stream")
async def stream_camera(camera_id: int, user=Depends(auth.get_current_user)):
    if camera_id not in camera_workers:
        raise HTTPException(status_code=404, detail="Camera is not running")
    return StreamingResponse(
        _mjpeg_generator(camera_id),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


# ---------------------------------------------------------------------------
# Events (history log)
# ---------------------------------------------------------------------------
@app.get("/api/events")
async def get_events(
    limit: int = 50, offset: int = 0, unsecure_only: bool = False, user=Depends(auth.get_current_user)
):
    return {"events": database.list_events(limit=limit, offset=offset, unsecure_only=unsecure_only)}


@app.get("/api/alerts/poll")
async def poll_alerts(since_id: int = 0, user=Depends(auth.get_current_user)):
    return {"events": database.list_unsecure_events_after(since_id, limit=20)}


@app.get("/api/events/stats")
async def get_event_stats(days: int = 7, user=Depends(auth.get_current_user)):
    return database.event_stats_last_n_days(days)


@app.get("/api/events/report")
async def get_events_report(
    status: str = "all",
    source: str = "all",
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 50,
    offset: int = 0,
    user=Depends(auth.get_current_user),
):
    rows, total = database.query_events_report(
        status=status, source=source, start_date=start_date, end_date=end_date, limit=limit, offset=offset
    )
    return {"events": rows, "total": total}


@app.get("/api/events/export")
async def export_events_csv(
    status: str = "all",
    source: str = "all",
    start_date: str | None = None,
    end_date: str | None = None,
    user=Depends(auth.get_current_user),
):
    rows = database.query_events_for_export(status=status, source=source, start_date=start_date, end_date=end_date)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "created_at_utc", "source", "camera_name", "total_persons", "secure_count", "unsecure_count"])
    for r in rows:
        writer.writerow([
            r["id"], r["created_at"], r["source"], r["camera_name"] or "",
            r["total_persons"], r["secure_count"], r["unsecure_count"],
        ])
    buf.seek(0)

    filename = f"ppe_events_{time.strftime('%Y%m%d_%H%M%S', time.gmtime())}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/events/{event_id}")
async def get_event_detail(event_id: int, user=Depends(auth.get_current_user)):
    event = database.get_event(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    if event.get("persons_json"):
        event["persons"] = json.loads(event["persons_json"])
    else:
        event["persons"] = []
    del event["persons_json"]
    return event


# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------
def _decode_upload_to_bgr(data: bytes) -> np.ndarray:
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(status_code=400, detail="Could not decode image file")
    return img


def _encode_bgr_to_jpeg_b64(img: np.ndarray, quality: int = 90) -> str:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise RuntimeError("JPEG encode failed")
    return base64.b64encode(buf.tobytes()).decode("ascii")


def _make_thumbnail_b64(img: np.ndarray, max_w: int = 160) -> str:
    h, w = img.shape[:2]
    scale = min(1.0, max_w / w)
    small = cv2.resize(img, (int(w * scale), int(h * scale)))
    return _encode_bgr_to_jpeg_b64(small, quality=60)


def _build_person_captures(annotated_img: np.ndarray, persons) -> list[dict]:
    """One entry per detected person; unsecure persons also get a cropped
    close-up image so the Events detail view can show exactly who/what was
    missing without displaying the full scene."""
    h, w = annotated_img.shape[:2]
    entries = []
    for p in persons:
        entry = {
            "status": p.status,
            "missing": p.missing,
            "confidence": round(p.conf, 3),
        }
        if not p.is_secure:
            x1, y1, x2, y2 = p.box
            pad_x = (x2 - x1) * 0.15
            pad_y = (y2 - y1) * 0.15
            cx1 = max(0, int(x1 - pad_x))
            cy1 = max(0, int(y1 - pad_y))
            cx2 = min(w, int(x2 + pad_x))
            cy2 = min(h, int(y2 + pad_y))
            crop = annotated_img[cy1:cy2, cx1:cx2]
            if crop.size > 0:
                entry["crop_b64"] = _encode_bgr_to_jpeg_b64(crop, quality=82)
        entries.append(entry)
    return entries


def _detect_and_annotate(img_bgr: np.ndarray):
    """Pure compute: run the model, annotate, and summarize. No side effects
    (no DB writes) — callers decide separately whether/when to log."""
    detections, persons, ms = detector.infer(img_bgr)
    annotated = annotate_frame(img_bgr, persons, detections=detections)

    matched_ids = set()
    for p in persons:
        if p.helmet is not None:
            matched_ids.add(id(p.helmet))
        if p.vest is not None:
            matched_ids.add(id(p.vest))
    unmatched_items = [
        {"label": d.label, "confidence": round(d.conf, 3)}
        for d in detections
        if (d.cls in HELMET_CLASS_IDS or d.cls == VEST_CLASS_ID) and id(d) not in matched_ids
    ]
    summary = detector.summarize(persons)
    return detections, persons, annotated, ms, unmatched_items, summary


def _log_detection_event(source: str, annotated: np.ndarray, persons, summary: dict, camera_name: str | None = None) -> None:
    thumb = _make_thumbnail_b64(annotated) if persons else None
    full_img = _encode_bgr_to_jpeg_b64(annotated, quality=85) if persons else None
    persons_json = json.dumps(_build_person_captures(annotated, persons)) if persons else None
    database.log_event(
        source, summary["total_persons"], summary["secure"], summary["unsecure"],
        thumb, full_img, persons_json, camera_name,
    )


def _build_detection_response(annotated, persons, unmatched_items, summary, ms, detections) -> dict:
    return {
        "annotated_b64": _encode_bgr_to_jpeg_b64(annotated),
        "persons": [p.to_dict() for p in persons],
        "summary": summary,
        "unmatched_items": unmatched_items,
        "raw_detection_count": len(detections),
        "inference_ms": round(ms, 1),
    }


def _run_detection(img_bgr: np.ndarray, source: str = "image", log: bool = True) -> dict:
    detections, persons, annotated, ms, unmatched_items, summary = _detect_and_annotate(img_bgr)
    if log:
        _log_detection_event(source, annotated, persons, summary)
    return _build_detection_response(annotated, persons, unmatched_items, summary, ms, detections)


# ---------------------------------------------------------------------------
# Image detection
# ---------------------------------------------------------------------------
@app.post("/api/detect/image")
async def detect_image(file: UploadFile = File(...), user=Depends(auth.get_current_user)):
    data = await file.read()
    img = _decode_upload_to_bgr(data)
    result = _run_detection(img, source="image")
    return JSONResponse(result)


# ---------------------------------------------------------------------------
# Video detection (background job with progress polling)
# ---------------------------------------------------------------------------
def _process_video_job(job_id: str, input_path: str, process_every_n: int):
    job = jobs[job_id]
    try:
        cap = cv2.VideoCapture(input_path)
        if not cap.isOpened():
            raise RuntimeError("Could not open uploaded video")

        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0

        output_path = str(JOBS_DIR / f"{job_id}_annotated.mp4")
        writer = None
        for fourcc_name in ("avc1", "mp4v"):
            candidate = cv2.VideoWriter(
                output_path, cv2.VideoWriter_fourcc(*fourcc_name), fps, (width, height)
            )
            if candidate.isOpened():
                writer = candidate
                break
            candidate.release()
        if writer is None:
            raise RuntimeError("Could not initialize a video writer with an available codec")

        job["status"] = "processing"
        job["total_frames"] = total_frames

        frame_idx = 0
        last_persons = []
        last_detections = []
        max_secure = 0
        max_unsecure = 0
        frames_with_unsecure = 0
        last_thumb = None
        best_full_img = None
        best_persons_json = None
        best_unsecure_seen = -1

        while True:
            ok, frame = cap.read()
            if not ok:
                break

            if frame_idx % process_every_n == 0:
                last_detections, persons, _ = detector.infer(frame)
                last_persons = persons

            annotated = annotate_frame(frame, last_persons, detections=last_detections)
            writer.write(annotated)
            if last_persons and last_thumb is None:
                last_thumb = _make_thumbnail_b64(annotated)

            secure = sum(1 for p in last_persons if p.is_secure)
            unsecure = len(last_persons) - secure
            max_secure = max(max_secure, secure)
            max_unsecure = max(max_unsecure, unsecure)
            if unsecure > 0:
                frames_with_unsecure += 1
            # Keep the most "interesting" frame (most unsecure persons seen)
            # as the representative capture for the Events detail view.
            if last_persons and unsecure > best_unsecure_seen:
                best_unsecure_seen = unsecure
                best_full_img = _encode_bgr_to_jpeg_b64(annotated, quality=85)
                best_persons_json = json.dumps(_build_person_captures(annotated, last_persons))

            frame_idx += 1
            if total_frames:
                job["progress"] = round(min(99, frame_idx / total_frames * 100), 1)

        cap.release()
        writer.release()

        job["status"] = "done"
        job["progress"] = 100
        job["output_path"] = output_path
        job["summary"] = {
            "frames_processed": frame_idx,
            "peak_secure": max_secure,
            "peak_unsecure": max_unsecure,
            "frames_with_unsecure_person": frames_with_unsecure,
        }
        database.log_event(
            "video", max_secure + max_unsecure, max_secure, max_unsecure,
            last_thumb, best_full_img, best_persons_json,
        )
    except Exception as exc:  # noqa: BLE001
        job["status"] = "error"
        job["error"] = str(exc)
    finally:
        try:
            os.remove(input_path)
        except OSError:
            pass


@app.post("/api/detect/video")
async def detect_video(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    process_every_n: int = 2,
    user=Depends(auth.get_current_user),
):
    job_id = uuid.uuid4().hex
    suffix = Path(file.filename or "upload.mp4").suffix or ".mp4"
    input_path = str(JOBS_DIR / f"{job_id}_input{suffix}")
    with open(input_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    jobs[job_id] = {"status": "queued", "progress": 0.0}
    background_tasks.add_task(_process_video_job, job_id, input_path, max(1, process_every_n))
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str, user=Depends(auth.get_current_user)):
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job id")
    return job


@app.get("/api/download/{job_id}")
async def download_job(job_id: str, user=Depends(auth.get_current_user)):
    job = jobs.get(job_id)
    if job is None or job.get("status") != "done":
        raise HTTPException(status_code=404, detail="Result not ready")
    return FileResponse(job["output_path"], media_type="video/mp4", filename="ppe_annotated.mp4")


# ---------------------------------------------------------------------------
# Live webcam detection over WebSocket
# ---------------------------------------------------------------------------
@app.websocket("/ws/live")
async def ws_live(ws: WebSocket):
    user = auth.get_user_from_ws(ws)
    if user is None:
        await ws.close(code=4401)
        return

    await ws.accept()
    global _live_incident_active, _live_incident_last_alert_ts, _live_secure_streak_start
    try:
        while True:
            msg = await ws.receive_text()
            if "," in msg:
                msg = msg.split(",", 1)[1]
            try:
                raw = base64.b64decode(msg)
            except Exception:
                continue
            img = _decode_upload_to_bgr(raw)

            detections, persons, annotated, ms, unmatched_items, summary = _detect_and_annotate(img)
            now = time.time()

            if summary["unsecure"] > 0:
                _live_secure_streak_start = None
                if not _live_incident_active:
                    # A new violation just started — log it immediately.
                    _live_incident_active = True
                    _live_incident_last_alert_ts = now
                    _log_detection_event("live", annotated, persons, summary)
                elif now - _live_incident_last_alert_ts >= LIVE_INCIDENT_REMINDER_SECONDS:
                    # Still ongoing after the reminder window — log again so
                    # it isn't silently missing from the log for minutes.
                    _live_incident_last_alert_ts = now
                    _log_detection_event("live", annotated, persons, summary)
            else:
                if _live_incident_active:
                    if _live_secure_streak_start is None:
                        _live_secure_streak_start = now
                    elif now - _live_secure_streak_start >= LIVE_SECURE_HYSTERESIS_SECONDS:
                        # Sustained secure for long enough — incident over.
                        # The next violation (if any) will log as a new one.
                        _live_incident_active = False
                        _live_secure_streak_start = None

            result = _build_detection_response(annotated, persons, unmatched_items, summary, ms, detections)
            await ws.send_json(result)
    except WebSocketDisconnect:
        pass


# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------
FRONTEND_DIR = PROJECT_ROOT / "frontend"
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR / "static")), name="static")


@app.get("/")
async def index():
    return FileResponse(
        str(FRONTEND_DIR / "index.html"),
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/health")
async def health():
    return {"status": "ok", "model_loaded": detector is not None}
