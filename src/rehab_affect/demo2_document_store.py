"""Encrypted 24-hour staging of uploaded course-task / IEP documents and their parse results.

Originals and structured results are sealed with the dossier vault (Fernet);
nothing readable is written to disk. Only the uploading account can read a
``parse_id``; another account gets 403, an expired one 410. The debug log keeps
operation, purpose, file type, sizes, counts, timing and result codes only —
never document text, file names or sensitive values.
"""
from __future__ import annotations

import json
import logging
import os
import re
import secrets
import struct
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .demo2_document_parser import (
    MAX_DOCUMENT_BYTES,
    PURPOSES,
    DocumentError,
    detect_document_type,
    extension_of,
    parse_document,
)
from .demo2_dossier_vault import DossierVault, VaultError
from .demo2_upload_debug import log_dir_for_store

PARSE_TTL = timedelta(hours=24)
# Expired rows stay as tombstones (no content) so a late read answers 410, not 404.
TOMBSTONE_TTL = timedelta(days=7)
SEAL_CHUNK_BYTES = 4 * 1024 * 1024
_SEALED_MAGIC = b"RXDOC1\n"
DEBUG_LOG_DIR_ENV = "REHAB_DEMO2_DOCUMENT_DEBUG_LOG_DIR"
DEBUG_LOGGER = logging.getLogger("rehab_affect.document_flow")
OPERATIONS = frozenset({"document_upload", "document_parse", "document_ocr", "document_reject", "document_read",
                        "document_cleanup"})
_PARSE_ID = re.compile(r"dp-[0-9a-f]{32}")
_LOCK = threading.Lock()
_INT_FIELDS = ("byte_size", "page_count", "candidate_count", "block_count", "table_count", "table_cell_count",
               "other_count", "sensitive_count", "ocr_page_count", "http_status", "deleted")
_TOKEN_FIELDS = ("parse_id", "account_id", "purpose", "file_type", "status", "code", "source")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def document_log_dir(store: Any) -> Path:
    configured = os.getenv(DEBUG_LOG_DIR_ENV, "").strip()
    if configured:
        return Path(configured)
    return log_dir_for_store(store)


def _token(value: Any) -> str:
    text = str(value)
    return text if re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", text) else "<invalid>"


def document_debug_event(store: Any, operation: str, result: str, **fields: Any) -> dict[str, Any]:
    """One JSON line in ``document_debug_YYYYMMDD.jsonl``; logging never blocks a request."""
    entry: dict[str, Any] = {
        "ts": datetime.now().astimezone().isoformat(timespec="milliseconds"),
        "operation": operation if operation in OPERATIONS else "<invalid>",
        "result": _token(result),
    }
    for key, value in fields.items():
        if value is None or value == "":
            continue
        if key in _TOKEN_FIELDS:
            entry[key] = _token(value)
        elif key in _INT_FIELDS:
            entry[key] = value if isinstance(value, int) and not isinstance(value, bool) else "<invalid>"
        elif key == "duration_ms":
            entry[key] = round(float(value), 1) if isinstance(value, (int, float)) and not isinstance(value, bool) else "<invalid>"
        elif key == "pages" and isinstance(value, (list, tuple)):
            entry[key] = [p for p in value if isinstance(p, int) and not isinstance(p, bool)][:50]
        elif key == "ocr_used":
            entry[key] = bool(value)
    line = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
    DEBUG_LOGGER.debug(line)
    try:
        folder = document_log_dir(store)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"document_debug_{entry['ts'][:10].replace('-', '')}.jsonl"
        with _LOCK, path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except (OSError, TypeError, ValueError):
        DEBUG_LOGGER.warning("document debug log write failed")
    return entry


class DocumentParseStore:
    def __init__(self, records: Any):
        self.records = records
        # Same placement rule as the other vault-backed stores: beside the upload directory.
        self.root = Path(records.upload_dir).resolve().parent / "document_parse_v1"
        self.vault = DossierVault(self.root)
        # demo2_upload_debug.log_dir_for_store looks for these attributes.
        self.upload_dir = records.upload_dir
        with records._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS demo2_document_parses (
                parse_id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL,
                purpose TEXT NOT NULL,
                file_type TEXT NOT NULL,
                byte_size INTEGER NOT NULL,
                status TEXT NOT NULL,
                page_count INTEGER NOT NULL,
                candidate_count INTEGER NOT NULL,
                sensitive_count INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                purged_at TEXT,
                body BLOB)""")
            db.execute("CREATE INDEX IF NOT EXISTS idx_demo2_document_parses_account "
                       "ON demo2_document_parses(account_id, created_at)")

    # -- sealing ----------------------------------------------------------
    def _seal(self, data: bytes) -> bytes:
        parts = [_SEALED_MAGIC]
        for offset in range(0, max(len(data), 1), SEAL_CHUNK_BYTES):
            token = self.vault.seal(data[offset:offset + SEAL_CHUNK_BYTES])
            parts.append(struct.pack(">I", len(token)))
            parts.append(token)
        return b"".join(parts)

    def _open(self, sealed: bytes) -> bytes:
        if not sealed.startswith(_SEALED_MAGIC):
            raise VaultError("vault_decrypt_failed")
        position, chunks = len(_SEALED_MAGIC), []
        while position < len(sealed):
            if position + 4 > len(sealed):
                raise VaultError("vault_decrypt_failed")
            (length,) = struct.unpack(">I", sealed[position:position + 4])
            position += 4
            chunks.append(self.vault.open(sealed[position:position + length]))
            position += length
        return b"".join(chunks)

    def _original_path(self, parse_id: str) -> Path:
        return self.root / "originals" / f"{parse_id}.sealed"

    def _write_original(self, parse_id: str, sealed: bytes) -> None:
        folder = self.root / "originals"
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        target = self._original_path(parse_id)
        temporary = folder / f".{parse_id}.{secrets.token_hex(4)}.tmp"
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(sealed)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        except BaseException:
            try:
                temporary.unlink()
            except OSError:
                pass
            raise

    # -- lifecycle --------------------------------------------------------
    def cleanup_expired(self) -> int:
        """Purge content of expired parses; drop tombstones after a week."""
        now = _now()
        with self.records._connect() as db:
            expired = [row[0] for row in db.execute(
                "SELECT parse_id FROM demo2_document_parses WHERE purged_at IS NULL AND expires_at<=?",
                (_iso(now),)).fetchall()]
            if expired:
                db.executemany("UPDATE demo2_document_parses SET body=NULL, purged_at=? WHERE parse_id=?",
                               [(_iso(now), parse_id) for parse_id in expired])
            db.execute("DELETE FROM demo2_document_parses WHERE expires_at<=?", (_iso(now - TOMBSTONE_TTL),))
        for parse_id in expired:
            try:
                self._original_path(parse_id).unlink()
            except FileNotFoundError:
                pass
            except OSError:
                DEBUG_LOGGER.warning("document original removal failed")
        if expired:
            document_debug_event(self, "document_cleanup", "purged", deleted=len(expired))
        return len(expired)

    def _purge_expired_quietly(self) -> None:
        """Run the 24-hour purge opportunistically; a failed purge never blocks the request."""
        try:
            self.cleanup_expired()
        except Exception as exc:
            DEBUG_LOGGER.warning("document cleanup failed: %s", type(exc).__name__)

    # -- API --------------------------------------------------------------
    def parse_upload(self, account_id: str, purpose: str, filename: str, data: bytes) -> dict[str, Any]:
        started = time.monotonic()
        suffix = extension_of(filename).lstrip(".")
        file_label = suffix if suffix in {"pdf", "docx", "doc"} else "other"

        def reject(error: DocumentError) -> DocumentError:
            document_debug_event(self, "document_reject", "rejected", account_id=account_id,
                                 purpose=purpose if purpose in PURPOSES else "invalid", file_type=file_label,
                                 byte_size=len(data), code=error.code, http_status=error.status,
                                 duration_ms=(time.monotonic() - started) * 1000)
            return error

        if purpose not in PURPOSES:
            raise reject(DocumentError(400, "invalid_purpose"))
        try:
            file_type = detect_document_type(filename, data)
        except DocumentError as exc:
            raise reject(exc) from None
        if not self.vault.status()["available"]:
            raise reject(DocumentError(503, "document_vault_unavailable", "资料加密服务暂不可用，文件未保存，请联系管理员"))
        document_debug_event(self, "document_upload", "accepted", account_id=account_id, purpose=purpose,
                             file_type=file_type, byte_size=len(data))
        self.cleanup_expired()
        parse_started = time.monotonic()
        try:
            result = parse_document(purpose, file_type, data)
        except DocumentError as exc:
            document_debug_event(self, "document_parse", "failed", account_id=account_id, purpose=purpose,
                                 file_type=file_type, byte_size=len(data), code=exc.code, http_status=exc.status,
                                 duration_ms=(time.monotonic() - parse_started) * 1000)
            raise
        except Exception:
            DEBUG_LOGGER.exception("document parse crashed")
            document_debug_event(self, "document_parse", "failed", account_id=account_id, purpose=purpose,
                                 file_type=file_type, byte_size=len(data), code="document_parse_failed",
                                 http_status=400, duration_ms=(time.monotonic() - parse_started) * 1000)
            raise DocumentError(400, "document_parse_failed") from None
        ocr = result["ocr"]
        if ocr["used"] or ocr["failed_pages"] or result["status"] == "needs_manual_entry":
            document_debug_event(
                self, "document_ocr",
                "used" if ocr["used"] else "no_text" if ocr["available"] else "unavailable",
                account_id=account_id, purpose=purpose, file_type=file_type, page_count=result["page_count"],
                ocr_page_count=len(ocr["pages"]), pages=ocr["pages"] or result["manual_entry_pages"],
                duration_ms=ocr["duration_ms"],
            )
        parse_id = "dp-" + secrets.token_hex(16)
        now = _now()
        expires = now + PARSE_TTL
        result.update(parse_id=parse_id, created_at=_iso(now), expires_at=_iso(expires), byte_size=len(data),
                      original_extension=f".{file_type}")
        # The original name may contain a student's name: kept only inside the sealed result.
        stored = dict(result, original_name=str(filename or "")[-200:])
        try:
            sealed_original = self._seal(data)
            sealed_result = self._seal(json.dumps(stored, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
            self._write_original(parse_id, sealed_original)
        except (VaultError, OSError):
            document_debug_event(self, "document_parse", "failed", account_id=account_id, purpose=purpose,
                                 file_type=file_type, byte_size=len(data), code="document_vault_unavailable",
                                 http_status=503)
            raise DocumentError(503, "document_vault_unavailable", "资料加密服务暂不可用，文件未保存，请联系管理员") from None
        coverage = result["coverage"]
        with self.records._connect() as db:
            db.execute(
                "INSERT INTO demo2_document_parses (parse_id, account_id, purpose, file_type, byte_size, status, "
                "page_count, candidate_count, sensitive_count, created_at, expires_at, body) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (parse_id, account_id, purpose, file_type, len(data), result["status"], int(result["page_count"]),
                 coverage["candidate_count"], result["sensitive_count"], _iso(now), _iso(expires), sealed_result),
            )
        document_debug_event(
            self, "document_parse", result["status"], account_id=account_id, parse_id=parse_id, purpose=purpose,
            file_type=file_type, byte_size=len(data), page_count=result["page_count"],
            block_count=coverage["block_count"], table_count=coverage["table_count"],
            table_cell_count=coverage["table_cell_count"], candidate_count=coverage["candidate_count"],
            other_count=coverage["other_count"], sensitive_count=result["sensitive_count"],
            ocr_used=ocr["used"], duration_ms=(time.monotonic() - started) * 1000,
        )
        return self._public(stored)

    @staticmethod
    def _public(stored: dict[str, Any]) -> dict[str, Any]:
        result = dict(stored)
        result.pop("original_name", None)
        return result

    def _row(self, account_id: str, parse_id: str, *, operation: str = "document_read") -> Any:
        self._purge_expired_quietly()
        if not isinstance(parse_id, str) or not _PARSE_ID.fullmatch(parse_id):
            document_debug_event(self, operation, "rejected", account_id=account_id, code="invalid_parse_id",
                                 http_status=400)
            raise DocumentError(400, "invalid_parse_id", "解析编号格式无效")
        with self.records._connect() as db:
            row = db.execute("SELECT parse_id, account_id, purpose, file_type, expires_at, purged_at, body "
                             "FROM demo2_document_parses WHERE parse_id=?", (parse_id,)).fetchone()
        if row is None:
            document_debug_event(self, operation, "rejected", account_id=account_id, parse_id=parse_id,
                                 code="parse_not_found", http_status=404)
            raise DocumentError(404, "parse_not_found", "解析结果不存在，请重新上传文件")
        if row[1] != account_id:
            document_debug_event(self, operation, "rejected", account_id=account_id, parse_id=parse_id,
                                 code="parse_forbidden", http_status=403)
            raise DocumentError(403, "parse_forbidden", "当前账号无权查看此解析结果")
        if row[5] or row[4] <= _iso(_now()) or row[6] is None:
            document_debug_event(self, operation, "rejected", account_id=account_id, parse_id=parse_id,
                                 purpose=row[2], file_type=row[3], code="parse_expired", http_status=410)
            raise DocumentError(410, "parse_expired", "解析结果已超过 24 小时暂存期，请重新上传文件")
        return row

    def get(self, account_id: str, parse_id: str) -> dict[str, Any]:
        started = time.monotonic()
        row = self._row(account_id, parse_id)
        try:
            stored = json.loads(self._open(row[6]).decode("utf-8"))
        except (VaultError, ValueError, UnicodeDecodeError):
            document_debug_event(self, "document_read", "failed", account_id=account_id, parse_id=parse_id,
                                 code="document_vault_unavailable", http_status=503)
            raise DocumentError(503, "document_vault_unavailable", "资料加密服务暂不可用，请稍后重试") from None
        document_debug_event(self, "document_read", "ok", account_id=account_id, parse_id=parse_id,
                             purpose=row[2], file_type=row[3],
                             candidate_count=len(stored.get("candidates") or []),
                             duration_ms=(time.monotonic() - started) * 1000)
        return self._public(stored)

    def read_original(self, account_id: str, parse_id: str) -> tuple[str, bytes]:
        """Decrypted original for the owning account (for later archive steps)."""
        row = self._row(account_id, parse_id)
        try:
            data = self._open(self._original_path(parse_id).read_bytes())
        except (VaultError, OSError):
            raise DocumentError(503, "document_vault_unavailable", "资料加密服务暂不可用，请稍后重试") from None
        return row[3], data


def max_request_bytes() -> int:
    from .demo2_document_parser import MAX_MULTIPART_OVERHEAD
    return MAX_DOCUMENT_BYTES + MAX_MULTIPART_OVERHEAD
