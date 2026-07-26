from __future__ import annotations

import argparse
import hashlib
import os
import secrets
import sqlite3
import time
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "ppe_platform.db"

SESSION_TTL_SECONDS = 7 * 24 * 3600


def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000).hex()


def main() -> int:
    parser = argparse.ArgumentParser(description="Reset the admin password for PPE Detect Platform.")
    parser.add_argument("--db", help="Path to the SQLite database file", default=os.environ.get("PPE_DB_PATH", str(DEFAULT_DB)))
    parser.add_argument("--username", help="Username to reset", default="admin")
    parser.add_argument("--password", help="New password to use. If omitted, a random one is generated.")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"Database file not found: {db_path}")
        return 1

    password = args.password or secrets.token_urlsafe(10)
    salt = secrets.token_bytes(16)
    password_hash = _hash_password(password, salt)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT id FROM users WHERE username = ?", (args.username,))
        row = cur.fetchone()
        if row is None:
            created_at = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
            conn.execute(
                "INSERT INTO users (username, password_hash, salt, role, created_at) VALUES (?, ?, ?, ?, ?)",
                (args.username, password_hash, salt.hex(), "admin", created_at),
            )
            action = "created"
        else:
            conn.execute(
                "UPDATE users SET password_hash = ?, salt = ? WHERE id = ?",
                (password_hash, salt.hex(), row["id"]),
            )
            action = "reset"

    print(f"Admin password {action} for user '{args.username}'.")
    print("Use the credentials below to log in:")
    print(f"  username: {args.username}")
    print(f"  password: {password}")
    print("")
    print("Then open your app and log in with the new password.")
    print("If login still fails, clear the browser cookie named 'ppe_session' and try again.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
