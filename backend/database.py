"""
Lightweight SQLite persistence layer — stdlib only (no ORM, no extra
dependencies) so installs stay simple on machines that already struggled
with compiled packages.

Tables
------
users     - login accounts (username, salted+hashed password, role)
sessions  - opaque session tokens issued at login, checked on every request
settings  - single key/value store for app-wide configuration
events    - a log of past detections (image / video / live) for the
            History page and for basic reporting
"""

from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

DB_PATH = os.environ.get("PPE_DB_PATH", str(Path(__file__).resolve().parent.parent / "data" / "ppe_platform.db"))
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)

SESSION_TTL_SECONDS = 7 * 24 * 3600  # 7 days

DEFAULT_SETTINGS = {
    "site_name": "Construction Site",
    "confidence_threshold": "0.35",
    "theme_default": "dark",          # dark | light | auto
    "video_frame_skip": "2",
    "event_retention_days": "30",
    "alerts_enabled": "true",
}


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> tuple[str, str] | None:
    """Create tables if needed. Returns (username, password) if a fresh
    default admin account was just created, else None."""
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'admin',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                source TEXT NOT NULL,
                total_persons INTEGER NOT NULL,
                secure_count INTEGER NOT NULL,
                unsecure_count INTEGER NOT NULL,
                thumbnail_b64 TEXT
            );

            CREATE TABLE IF NOT EXISTS cameras (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                rtsp_url TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );
            """
        )

        # Older databases won't have these columns yet — add them if missing
        # rather than requiring a fresh database.
        existing_cols = {r["name"] for r in conn.execute("PRAGMA table_info(events)").fetchall()}
        if "full_image_b64" not in existing_cols:
            conn.execute("ALTER TABLE events ADD COLUMN full_image_b64 TEXT")
        if "persons_json" not in existing_cols:
            conn.execute("ALTER TABLE events ADD COLUMN persons_json TEXT")
        if "camera_name" not in existing_cols:
            conn.execute("ALTER TABLE events ADD COLUMN camera_name TEXT")

        for key, value in DEFAULT_SETTINGS.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value)
            )

        created = None
        row = conn.execute("SELECT COUNT(*) AS c FROM users WHERE username = 'admin'").fetchone()
        if row["c"] == 0:
            password = os.environ.get("PPE_ADMIN_PASSWORD", "admin123")
            _create_user(conn, "admin", password, role="admin")
            created = ("admin", password)

        return created


# ---------------------------------------------------------------------------
# Users / auth
# ---------------------------------------------------------------------------
def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000).hex()


def _create_user(conn, username: str, password: str, role: str = "admin") -> int:
    salt = secrets.token_bytes(16)
    password_hash = _hash_password(password, salt)
    cur = conn.execute(
        "INSERT INTO users (username, password_hash, salt, role, created_at) VALUES (?, ?, ?, ?, ?)",
        (username, password_hash, salt.hex(), role, time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())),
    )
    return cur.lastrowid


def create_user(username: str, password: str, role: str = "admin") -> int:
    with get_conn() as conn:
        return _create_user(conn, username, password, role)


def verify_user(username: str, password: str) -> sqlite3.Row | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if row is None:
            return None
        salt = bytes.fromhex(row["salt"])
        if _hash_password(password, salt) != row["password_hash"]:
            return None
        return row


def change_password(user_id: int, new_password: str) -> None:
    salt = secrets.token_bytes(16)
    password_hash = _hash_password(new_password, salt)
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET password_hash = ?, salt = ? WHERE id = ?",
            (password_hash, salt.hex(), user_id),
        )


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    now = time.time()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token, user_id, now, now + SESSION_TTL_SECONDS),
        )
    return token


def get_user_by_token(token: str) -> sqlite3.Row | None:
    if not token:
        return None
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT users.* FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.token = ? AND sessions.expires_at > ?
            """,
            (token, time.time()),
        ).fetchone()
        return row


def delete_session(token: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
def get_settings() -> dict:
    with get_conn() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
        return {r["key"]: r["value"] for r in rows}


def update_settings(updates: dict) -> dict:
    with get_conn() as conn:
        for key, value in updates.items():
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(value)),
            )
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
        return {r["key"]: r["value"] for r in rows}


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------
def log_event(
    source: str,
    total_persons: int,
    secure: int,
    unsecure: int,
    thumbnail_b64: str | None = None,
    full_image_b64: str | None = None,
    persons_json: str | None = None,
    camera_name: str | None = None,
) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO events (created_at, source, total_persons, secure_count, unsecure_count, "
            "thumbnail_b64, full_image_b64, persons_json, camera_name) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
                source,
                total_persons,
                secure,
                unsecure,
                thumbnail_b64,
                full_image_b64,
                persons_json,
                camera_name,
            ),
        )


def list_events(limit: int = 50, offset: int = 0, unsecure_only: bool = False) -> list[dict]:
    # Deliberately excludes full_image_b64/persons_json — the list view only
    # needs the small thumbnail; full detail is fetched per-event on click.
    with get_conn() as conn:
        where = "WHERE unsecure_count > 0" if unsecure_only else ""
        rows = conn.execute(
            f"SELECT id, created_at, source, total_persons, secure_count, unsecure_count, thumbnail_b64, camera_name "
            f"FROM events {where} ORDER BY id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]


def _build_report_filter(
    status: str = "all",
    source: str = "all",
    start_date: str | None = None,
    end_date: str | None = None,
) -> tuple[str, list]:
    """Shared WHERE-clause builder for the Events report view and CSV
    export, so the two can never drift out of sync with each other."""
    clauses = []
    params: list = []

    if status == "secure":
        clauses.append("unsecure_count = 0")
    elif status == "unsecure":
        clauses.append("unsecure_count > 0")

    if source != "all":
        clauses.append("source = ?")
        params.append(source)

    if start_date:
        clauses.append("created_at >= ?")
        params.append(f"{start_date}T00:00:00")
    if end_date:
        clauses.append("created_at <= ?")
        params.append(f"{end_date}T23:59:59")

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def query_events_report(
    status: str = "all",
    source: str = "all",
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """Filtered, paginated event list for the Events report page. Returns
    (rows, total_matching_count) so the UI can show pagination info."""
    where, params = _build_report_filter(status, source, start_date, end_date)
    with get_conn() as conn:
        total = conn.execute(f"SELECT COUNT(*) AS c FROM events {where}", params).fetchone()["c"]
        rows = conn.execute(
            f"SELECT id, created_at, source, total_persons, secure_count, unsecure_count, thumbnail_b64, camera_name "
            f"FROM events {where} ORDER BY id DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
        return [dict(r) for r in rows], total


def query_events_for_export(
    status: str = "all",
    source: str = "all",
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[dict]:
    """Same filters as query_events_report but no pagination and no image
    blobs — used to build the CSV export."""
    where, params = _build_report_filter(status, source, start_date, end_date)
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT id, created_at, source, camera_name, total_persons, secure_count, unsecure_count "
            f"FROM events {where} ORDER BY id DESC",
            params,
        ).fetchall()
        return [dict(r) for r in rows]


def list_unsecure_events_after(since_id: int, limit: int = 20) -> list[dict]:
    """Used by the Dashboard's alert poller — new unsecure events only,
    oldest-first so toasts appear in the order they happened."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, created_at, source, total_persons, secure_count, unsecure_count, thumbnail_b64, camera_name "
            "FROM events WHERE id > ? AND unsecure_count > 0 ORDER BY id ASC LIMIT ?",
            (since_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def get_event(event_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        return dict(row) if row else None


def event_stats_last_n_days(days: int = 7) -> dict:
    cutoff = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - days * 86400))
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS events, COALESCE(SUM(secure_count),0) AS secure, "
            "COALESCE(SUM(unsecure_count),0) AS unsecure FROM events WHERE created_at >= ?",
            (cutoff,),
        ).fetchone()
        return dict(row)


def purge_old_events(retention_days: int) -> int:
    cutoff = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - retention_days * 86400))
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM events WHERE created_at < ?", (cutoff,))
        return cur.rowcount


# ---------------------------------------------------------------------------
# Cameras (RTSP)
# ---------------------------------------------------------------------------
def list_cameras(enabled_only: bool = False) -> list[dict]:
    with get_conn() as conn:
        where = "WHERE enabled = 1" if enabled_only else ""
        rows = conn.execute(f"SELECT * FROM cameras {where} ORDER BY id ASC").fetchall()
        return [dict(r) for r in rows]


def get_camera(camera_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM cameras WHERE id = ?", (camera_id,)).fetchone()
        return dict(row) if row else None


def create_camera(name: str, rtsp_url: str, enabled: bool = True) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO cameras (name, rtsp_url, enabled, created_at) VALUES (?, ?, ?, ?)",
            (name, rtsp_url, 1 if enabled else 0, time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())),
        )
        return cur.lastrowid


def update_camera(camera_id: int, name: str | None = None, rtsp_url: str | None = None, enabled: bool | None = None) -> None:
    with get_conn() as conn:
        current = conn.execute("SELECT * FROM cameras WHERE id = ?", (camera_id,)).fetchone()
        if current is None:
            return
        new_name = name if name is not None else current["name"]
        new_url = rtsp_url if rtsp_url is not None else current["rtsp_url"]
        new_enabled = (1 if enabled else 0) if enabled is not None else current["enabled"]
        conn.execute(
            "UPDATE cameras SET name = ?, rtsp_url = ?, enabled = ? WHERE id = ?",
            (new_name, new_url, new_enabled, camera_id),
        )


def delete_camera(camera_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM cameras WHERE id = ?", (camera_id,))
