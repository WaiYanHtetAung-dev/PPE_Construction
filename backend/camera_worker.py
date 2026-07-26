"""
Background worker for one RTSP camera.

Each camera gets its own OS thread (RTSP reading + OpenCV decode is
blocking I/O, so this can't share the asyncio event loop). The worker:

1. Opens the RTSP stream and continuously reads frames (so the decoder
   doesn't fall behind and start lagging).
2. Only runs PPE detection on a sampled subset of frames (SAMPLE_INTERVAL_
   SECONDS apart) — a person's helmet/vest status doesn't change frame to
   frame, so detecting at ~1fps is plenty and keeps CPU usage sane even
   with several cameras running at once.
3. Keeps the latest annotated frame (as JPEG bytes) available for the
   MJPEG streaming endpoint to read.
4. Applies the same "incident" logging pattern as the browser-webcam feed
   (log once when a violation starts, remind periodically while it's
   ongoing, stop once secure for a sustained period) — but tracked
   independently per camera, since each camera is its own scene.
5. Reconnects automatically if the stream drops.
"""

from __future__ import annotations

import os
import threading
import time

import cv2

REMINDER_SECONDS = 120            # re-log/re-alert every 2 min if a violation is still ongoing
SECURE_HYSTERESIS_SECONDS = 5     # need this many seconds of "all secure" before calling it resolved
SAMPLE_INTERVAL_SECONDS = 1.0     # how often we run detection (not every RTSP frame)
RECONNECT_DELAY_SECONDS = 5
OPEN_TIMEOUT_MS = 8000            # give up opening the stream after this long
READ_TIMEOUT_MS = 8000            # give up on a stalled read after this long

# Most RTSP cameras/apps (e.g. Android "IP Webcam") default to UDP transport,
# which frequently fails to traverse Wi-Fi/NAT setups and shows up as
# OpenCV/FFmpeg silently failing to open the stream. Forcing TCP transport
# here fixes the large majority of "won't connect" reports. This must be set
# before any cv2.VideoCapture(...) call — FFmpeg reads it as an environment
# variable, not a per-call option — so it's applied once at import time.
os.environ.setdefault(
    "OPENCV_FFMPEG_CAPTURE_OPTIONS",
    f"rtsp_transport;tcp|stimeout;{OPEN_TIMEOUT_MS * 1000}|max_delay;500000",
)


class CameraWorker:
    def __init__(self, camera_id: int, name: str, rtsp_url: str, detect_and_annotate, log_event):
        self.camera_id = camera_id
        self.name = name
        self.rtsp_url = rtsp_url

        # Injected callables so this module doesn't need to import the
        # FastAPI app or the detector directly:
        #   detect_and_annotate(frame) -> (detections, persons, annotated, ms, unmatched_items, summary)
        #   log_event(source, annotated, persons, summary, camera_name) -> None
        self._detect_and_annotate = detect_and_annotate
        self._log_event = log_event

        self.latest_jpeg: bytes | None = None
        self.status = "starting"   # starting | running | error | stopped
        self.last_error: str | None = None

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

        self._incident_active = False
        self._incident_last_alert_ts = 0.0
        self._secure_streak_start: float | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True, name=f"camera-{self.camera_id}")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self.status = "stopped"

    def _run(self) -> None:
        while not self._stop_event.is_set():
            # CAP_FFMPEG is requested explicitly rather than left to
            # auto-detection — on some platforms OpenCV picks a backend
            # (e.g. GStreamer) that doesn't honor OPENCV_FFMPEG_CAPTURE_OPTIONS
            # and silently fails on rtsp:// URLs that FFmpeg handles fine.
            cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
            try:
                cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, OPEN_TIMEOUT_MS)
                cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, READ_TIMEOUT_MS)
            except Exception:  # noqa: BLE001 — older OpenCV builds lack these props
                pass

            if not cap.isOpened():
                self.status = "error"
                self.last_error = (
                    "Could not open the RTSP stream. Double-check the URL, username/password, "
                    "and that this server can reach the camera's IP and port (same network/VLAN, "
                    "no firewall blocking it) — see the README's RTSP troubleshooting section."
                )
                cap.release()
                if self._stop_event.wait(RECONNECT_DELAY_SECONDS):
                    return
                continue

            self.status = "running"
            self.last_error = None
            last_sample_time = 0.0

            while not self._stop_event.is_set():
                ok, frame = cap.read()
                if not ok:
                    self.status = "error"
                    self.last_error = "Lost connection to camera — reconnecting"
                    break

                now = time.time()
                if now - last_sample_time < SAMPLE_INTERVAL_SECONDS:
                    continue
                last_sample_time = now

                try:
                    _, persons, annotated, _, _, summary = self._detect_and_annotate(frame)
                except Exception as exc:  # noqa: BLE001
                    self.status = "error"
                    self.last_error = f"Detection error: {exc}"
                    break

                self._apply_incident_logic(annotated, persons, summary, now)

                ok2, buf = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 80])
                if ok2:
                    self.latest_jpeg = buf.tobytes()

            cap.release()
            if self._stop_event.is_set():
                break
            # Connection dropped (or a detection error occurred) — wait a
            # bit and retry rather than giving up on the camera entirely.
            if self._stop_event.wait(RECONNECT_DELAY_SECONDS):
                return

        self.status = "stopped"

    def _apply_incident_logic(self, annotated, persons, summary: dict, now: float) -> None:
        if summary["unsecure"] > 0:
            self._secure_streak_start = None
            if not self._incident_active:
                self._incident_active = True
                self._incident_last_alert_ts = now
                self._log_event("rtsp", annotated, persons, summary, self.name)
            elif now - self._incident_last_alert_ts >= REMINDER_SECONDS:
                self._incident_last_alert_ts = now
                self._log_event("rtsp", annotated, persons, summary, self.name)
        else:
            if self._incident_active:
                if self._secure_streak_start is None:
                    self._secure_streak_start = now
                elif now - self._secure_streak_start >= SECURE_HYSTERESIS_SECONDS:
                    self._incident_active = False
                    self._secure_streak_start = None
