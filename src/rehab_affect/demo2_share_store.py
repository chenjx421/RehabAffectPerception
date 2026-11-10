"""Short-lived, teacher-created report share links; no account is created."""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Any


class ShareError(Exception):
    def __init__(self, status: int, code: str):
        super().__init__(code)
        self.status = status
        self.code = code


class Demo2ShareStore:
    def __init__(self, records: Any):
        self.records = records

    def _ensure(self, db) -> None:
        db.execute("""CREATE TABLE IF NOT EXISTS demo2_shared_reports (
            token_hash TEXT PRIMARY KEY,
            account_id TEXT NOT NULL,
            filename TEXT NOT NULL,
            body BLOB NOT NULL,
            byte_size INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        )""")

    def create(self, account_id: str, filename: str, body: bytes, hours: int = 24) -> dict[str, Any]:
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        now = datetime.now().astimezone()
        expires = now + timedelta(hours=max(1, min(168, int(hours or 24))))
        with self.records._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._ensure(db)
            db.execute("DELETE FROM demo2_shared_reports WHERE expires_at < ?", (now.isoformat(timespec="seconds"),))
            db.execute("""INSERT INTO demo2_shared_reports
                (token_hash, account_id, filename, body, byte_size, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                       (token_hash, account_id, filename, body, len(body),
                        now.isoformat(timespec="seconds"), expires.isoformat(timespec="seconds")))
            db.commit()
        return {"token": token, "filename": filename, "byte_size": len(body),
                "expires_at": expires.isoformat(timespec="seconds")}

    def get(self, token: str) -> tuple[bytes, str]:
        if not token or len(token) > 256:
            raise ShareError(404, "share_not_found")
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        with self.records._connect() as db:
            self._ensure(db)
            row = db.execute("SELECT filename, body, expires_at FROM demo2_shared_reports WHERE token_hash=?",
                             (token_hash,)).fetchone()
        if row is None:
            raise ShareError(404, "share_not_found")
        if str(row["expires_at"]) < now:
            raise ShareError(410, "share_expired")
        return bytes(row["body"]), str(row["filename"])
