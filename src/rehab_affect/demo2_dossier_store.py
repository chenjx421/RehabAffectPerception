"""Scoped, authorized, encrypted dossiers; no legacy imports or clinical inference.

Dates are exclusive local-date deadlines: access ends at the start of the
specified valid_until/retain_until date. Only the new dossier tables/files are
maintained. File deletion is not a guarantee of backup or forensic erasure.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import logging
import os
import re
import sqlite3
import stat
import unicodedata
import threading
import zipfile
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path, PurePosixPath, PureWindowsPath
from uuid import uuid4

from .demo2_identity_store import Demo2IdentityStore, IdentityError
from .evaluation_report_contract import school_id_from_context
from .student_record_store import _iso


MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_RETENTION_DAYS = 60
STORAGE_OWNER_FILE = ".dossier-owner.json"
SUMMARY_FIELDS = {"learning_goals", "support_methods", "safety_notes", "professional_conclusion"}
DOCUMENT_TYPES = {"iep", "professional_assessment", "five_domain", "safety_support"}
POLICY = {"max_retention_days": 60, "training_allowed": False}
LEGACY_NOTICE = "旧全局资料未自动迁移；请核实学生身份和校方授权后，向正确学生显式重新导入。授权勾选不等同于法律同意证明。"
ACCESS_PURPOSES = {"analysis": "课堂分析", "scoring": "课堂评分"}
ACCESS_MESSAGES = {
    "available": "资料授权有效，可在授权范围内用于{purpose}",
    "authorization_missing": "该学生尚未登记有效的资料授权，资料不可用于{purpose}",
    "authorization_withdrawn": "该学生的资料授权已撤回，资料不可再用于{purpose}",
    "authorization_expired": "该学生的资料授权已于 {valid_until} 到期，资料不可再用于{purpose}",
    "document_missing": "资料版本不存在或不属于该学生，不可用于{purpose}",
    "document_deleted": "该资料版本已删除，不可再用于{purpose}",
    "document_withdrawn": "该资料版本所属授权已撤回，不可再用于{purpose}",
    "document_expired": "该资料版本保存期限已于 {retain_until} 到期，不可再用于{purpose}",
}
REFERENCE_WITHDRAWN_MESSAGE = "本课资料引用授权已撤回，分析与评分不再读取该引用中的 IEP 或专业资料"
EVIDENCE_MESSAGES = {
    "outdated_revision": "课堂身份采样版本已变化，该来源不再作为本课有效依据",
    "identity_unavailable": "课堂身份确认已失效，该来源不再作为本课有效依据",
    "task_unavailable": "课堂任务证据不可用，该来源不再作为本课有效依据",
}
DEBUG_LOG_DIR_ENV = "REHAB_DEMO2_DOSSIER_DEBUG_LOG_DIR"
DEBUG_LOGGER = logging.getLogger("rehab_affect.dossier")
# Only identifiers, enums, dates and counts are ever logged; names, summaries,
# source references, filenames and authorization text never reach the log.
_DEBUG_ID_FIELDS = ("actor_account_id", "student_id", "document_id", "authorization_id", "family_id",
                    "supersedes_id", "reference_id", "task_id")
_DEBUG_ENUM_FIELDS = {"document_type": DOCUMENT_TYPES, "storage_mode": {"summary_only", "original_and_summary"},
                      "purpose": set(ACCESS_PURPOSES)}
_DEBUG_DATE_FIELDS = ("valid_until", "retain_until", "document_date")
_DEBUG_COUNT_FIELDS = ("version", "document_count", "candidate_count", "expired_authorization_count",
                       "expired_document_count", "purged_count", "deletion_pending_count", "http_status",
                       "valid_source_count", "invalid_source_count", "reference_count", "included_count",
                       "excluded_count", "iep_included_count", "professional_included_count")
_DEBUG_TOKEN_FIELDS = ("code", "reason", "status", "error_type", "evidence_status")
_DEBUG_LOCK = threading.Lock()


class DossierError(ValueError):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def debug_log_dir(records):
    configured = os.getenv(DEBUG_LOG_DIR_ENV, "").strip()
    return Path(configured) if configured else Path(os.path.abspath(Path(records.upload_dir).parent / "logs"))


def _debug_value(key, value):
    if value is None:
        return None
    if key in _DEBUG_ID_FIELDS or key in _DEBUG_TOKEN_FIELDS:
        text = str(value)
        return text if re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", text) else "<invalid>"
    if key in _DEBUG_ENUM_FIELDS:
        return value if value in _DEBUG_ENUM_FIELDS[key] else "<invalid>"
    if key in _DEBUG_DATE_FIELDS:
        return value if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) else "<invalid>"
    if key in _DEBUG_COUNT_FIELDS:
        return value if isinstance(value, int) and not isinstance(value, bool) else "<invalid>"
    if key == "has_file":
        return bool(value)
    return None


def debug_event(records, operation, result, **fields):
    """Write one structured dossier debug line; logging never blocks the operation."""
    entry = {"ts": datetime.now().astimezone().isoformat(timespec="milliseconds"),
             "operation": _debug_value("code", operation), "result": _debug_value("status", result)}
    for key, value in fields.items():
        cleaned = _debug_value(key, value)
        if cleaned is not None:
            entry[key] = cleaned
    line = json.dumps(entry, ensure_ascii=False, sort_keys=False, separators=(",", ":"))
    DEBUG_LOGGER.debug(line)
    try:
        folder = debug_log_dir(records)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"dossier_debug_{entry['ts'][:10].replace('-', '')}.jsonl"
        with _DEBUG_LOCK, path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except (OSError, TypeError, ValueError):
        DEBUG_LOGGER.warning("dossier debug log write failed")
    return entry


def _access_result(purpose, reason, *, student_id="", authorization_id="", valid_until="", document_id="",
                   document_type="", retain_until=""):
    message = ACCESS_MESSAGES[reason].format(purpose=ACCESS_PURPOSES.get(purpose, "分析和评分"),
                                             valid_until=valid_until or "授权截止日",
                                             retain_until=retain_until or "保存截止日")
    return {"available": reason == "available", "reason": reason, "message": message, "purpose": purpose,
            "student_id": student_id, "authorization_id": authorization_id, "valid_until": valid_until,
            "document_id": document_id, "document_type": document_type, "retain_until": retain_until}


def material_access_state(db, *, student_id="", document_id="", purpose="analysis"):
    """Explain whether a student's dossier (or one version) may feed analysis/scoring."""
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {"demo2_dossier_authorizations", "demo2_dossier_documents"} <= tables:
        return _access_result(purpose, "document_missing" if document_id else "authorization_missing",
                              student_id=student_id, document_id=document_id)
    doc = None
    if document_id:
        doc = db.execute("""SELECT document_id, student_id, authorization_id, document_type, status, retain_until,
            purge_reason, metadata_ciphertext FROM demo2_dossier_documents WHERE document_id = ?""", (document_id,)).fetchone()
        if doc is None or (student_id and doc["student_id"] != student_id):
            return _access_result(purpose, "document_missing", student_id=student_id, document_id=document_id)
        student_id = doc["student_id"]
    today = _today().isoformat()
    rows = db.execute("""SELECT * FROM demo2_dossier_authorizations WHERE student_id = ?
        ORDER BY created_at DESC, rowid DESC""", (student_id,)).fetchall()
    active = next((row for row in rows if Demo2DossierStore._auth_active(row)), None)
    if doc is not None:
        own = next((row for row in rows if row["authorization_id"] == doc["authorization_id"]), None)
        common = {"student_id": student_id, "document_id": doc["document_id"], "document_type": doc["document_type"],
                  "retain_until": doc["retain_until"]}
        if own is not None and not Demo2DossierStore._auth_active(own):
            reason = "authorization_withdrawn" if own["status"] == "withdrawn" else "authorization_expired"
            return _access_result(purpose, reason, authorization_id=own["authorization_id"], valid_until=own["valid_until"], **common)
        if doc["status"] != "available" or doc["metadata_ciphertext"] is None:
            final = doc["purge_reason"] or doc["status"]
            reason = {"withdrawn": "document_withdrawn", "expired": "document_expired"}.get(final, "document_deleted")
            return _access_result(purpose, reason, authorization_id=doc["authorization_id"], **common)
        if doc["retain_until"] <= today:
            return _access_result(purpose, "document_expired", authorization_id=doc["authorization_id"], **common)
        if own is None:
            return _access_result(purpose, "authorization_missing", **common)
        return _access_result(purpose, "available", authorization_id=own["authorization_id"], valid_until=own["valid_until"], **common)
    if active is not None:
        return _access_result(purpose, "available", student_id=student_id, authorization_id=active["authorization_id"],
                              valid_until=active["valid_until"])
    if not rows:
        return _access_result(purpose, "authorization_missing", student_id=student_id)
    latest = rows[0]
    reason = "authorization_withdrawn" if latest["status"] == "withdrawn" else "authorization_expired"
    return _access_result(purpose, reason, student_id=student_id, authorization_id=latest["authorization_id"],
                          valid_until=latest["valid_until"])


def current_iep_versions(rows, available):
    """Latest still-usable version per IEP family; other types never qualify."""
    heads = {}
    for row in rows:
        if row["document_type"] != "iep" or not available(row):
            continue
        current = heads.get(row["family_id"])
        if current is None or row["version"] > current["version"]:
            heads[row["family_id"]] = row
    return sorted(heads.values(), key=lambda row: (row["document_date"], row["created_at"], row["document_id"]))


def _today():
    return datetime.now().astimezone().date()


def _text(value, limit, *, required=False, multiline=False):
    if (not isinstance(value, str) or len(value) > limit
            or any(unicodedata.category(char) in {"Cc", "Cf", "Cs"}
                   and not (multiline and char in "\n\r\t") for char in value)):
        raise DossierError(400, "invalid_field", "字段格式无效、过长或包含控制字符")
    value = value.strip()
    if required and not value:
        raise DossierError(400, "invalid_field", "必填字段不能为空")
    return value


def _payload(value, fields, *, confirmed=False):
    if not isinstance(value, dict) or set(value) != set(fields.split()):
        raise DossierError(400, "invalid_request", "请仅提交接口约定的字段")
    if confirmed and value.get("confirmed") is not True:
        raise DossierError(400, "confirmation_required", "必须由教师显式确认本次操作")


def _date(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise DossierError(400, "invalid_date", "日期须为 YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise DossierError(400, "invalid_date", "日期无效") from None


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _file_content(filename, encoded):
    if not isinstance(filename, str) or not isinstance(encoded, str):
        raise DossierError(400, "invalid_file", "文件字段格式无效")
    if not filename and not encoded:
        return b"", "", ""
    name = _text(filename, 200, required=True)
    if (name != filename or name != PureWindowsPath(name).name or name != PurePosixPath(name).name
            or ":" in name or name in {".", ".."} or len(encoded) > ((MAX_FILE_BYTES + 2) // 3) * 4):
        raise DossierError(400, "invalid_file", "文件名或文件大小无效")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, UnicodeError):
        raise DossierError(400, "invalid_file", "文件内容须为有效 Base64") from None
    if not 0 < len(data) <= MAX_FILE_BYTES:
        raise DossierError(400, "invalid_file", "文件必须非空且不超过 8 MiB")
    suffix = Path(name).suffix.lower()
    mime = {".pdf": "application/pdf", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".txt": "text/plain; charset=utf-8"}.get(suffix)
    valid = False
    if suffix == ".pdf":
        valid = data.startswith(b"%PDF-")
    elif suffix == ".png":
        valid = len(data) >= 24 and data.startswith(b"\x89PNG\r\n\x1a\n") and data[12:16] == b"IHDR"
    elif suffix in {".jpg", ".jpeg"}:
        valid = data.startswith(b"\xff\xd8\xff") and data.endswith(b"\xff\xd9")
    elif suffix == ".txt":
        try:
            text = data.decode("utf-8-sig")
            valid = bool(text.strip()) and not text.lstrip().lower().startswith(("<html", "<!doctype", "<svg", "<script", "<?xml", "#!")) and not data.startswith(b"MZ")
            valid = valid and all(unicodedata.category(char) not in {"Cc", "Cs"} or char in "\r\n\t" for char in text)
        except UnicodeError:
            valid = False
    elif suffix == ".docx":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                entries = archive.infolist()
                names = [item.filename for item in entries]
                valid = (data.startswith(b"PK\x03\x04") and 0 < len(entries) <= 2048 and len(names) == len(set(names))
                         and {"[Content_Types].xml", "word/document.xml"} <= set(names)
                         and sum(item.file_size for item in entries) <= 32 * 1024 * 1024)
                for item in entries:
                    path = PurePosixPath(item.filename.replace("\\", "/"))
                    lower = item.filename.lower()
                    if (path.is_absolute() or ".." in path.parts or PureWindowsPath(item.filename).drive or ":" in lower
                            or item.flag_bits & 1 or stat.S_ISLNK(item.external_attr >> 16)
                            or item.file_size > 8 * 1024 * 1024 or item.file_size > max(1, item.compress_size) * 100
                            or "vba" in lower or "activex" in lower or "embeddings/" in lower or lower.endswith((".exe", ".dll", ".js", ".bin"))):
                        valid = False
                if valid:
                    manifest = archive.getinfo("[Content_Types].xml")
                    valid = manifest.file_size <= 64 * 1024
                    if valid:
                        content_types = archive.read(manifest).lower()
                        valid = b"macroenabled" not in content_types and b"vbaproject" not in content_types
        except (OSError, ValueError, KeyError, RuntimeError, zipfile.BadZipFile, NotImplementedError):
            valid = False
    if not mime or not valid:
        raise DossierError(400, "invalid_file", "文件类型与内容不匹配，或包含不允许的内容")
    return data, name, mime


class Demo2DossierStore:
    def __init__(self, records, identities=None):
        self.records = records
        self.identities = identities if identities is not None else Demo2IdentityStore(records)
        self.root = Path(os.path.abspath(Path(records.upload_dir).parent / "scoped_dossier_v1"))
        self._vault_instance = None
        with records._connect() as connection:
            connection.executescript("""
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS demo2_dossier_authorizations (
                    authorization_id TEXT PRIMARY KEY, student_id TEXT NOT NULL,
                    owner_account_id TEXT NOT NULL, scope_key TEXT NOT NULL,
                    storage_mode TEXT NOT NULL CHECK(storage_mode IN ('summary_only','original_and_summary')),
                    purpose TEXT NOT NULL CHECK(purpose = 'education_support'), valid_until TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('active','withdrawn','expired')),
                    metadata_ciphertext BLOB, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    FOREIGN KEY(student_id,owner_account_id,scope_key)
                        REFERENCES demo2_identity_students(student_id,owner_account_id,scope_key)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_dossier_one_live_authorization
                    ON demo2_dossier_authorizations(student_id) WHERE status = 'active';
                CREATE TABLE IF NOT EXISTS demo2_dossier_documents (
                    document_id TEXT PRIMARY KEY, student_id TEXT NOT NULL, owner_account_id TEXT NOT NULL,
                    scope_key TEXT NOT NULL, authorization_id TEXT NOT NULL REFERENCES demo2_dossier_authorizations(authorization_id),
                    document_type TEXT NOT NULL, family_id TEXT NOT NULL, version INTEGER NOT NULL CHECK(version > 0),
                    supersedes_id TEXT REFERENCES demo2_dossier_documents(document_id), document_date TEXT NOT NULL,
                    retain_until TEXT NOT NULL, status TEXT NOT NULL,
                    metadata_ciphertext BLOB, has_file INTEGER NOT NULL DEFAULT 0,
                    encrypted_file_bytes INTEGER NOT NULL DEFAULT 0, purge_reason TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    UNIQUE(family_id,version), UNIQUE(supersedes_id),
                    FOREIGN KEY(student_id,owner_account_id,scope_key)
                        REFERENCES demo2_identity_students(student_id,owner_account_id,scope_key)
                );
                CREATE INDEX IF NOT EXISTS idx_dossier_documents_student ON demo2_dossier_documents(student_id,created_at);
                CREATE TABLE IF NOT EXISTS demo2_dossier_references (
                    reference_id TEXT PRIMARY KEY, student_id TEXT NOT NULL, owner_account_id TEXT NOT NULL,
                    scope_key TEXT NOT NULL, task_id TEXT NOT NULL REFERENCES video_analysis_tasks(task_id),
                    frame_revision TEXT NOT NULL, source_sha256 TEXT NOT NULL, binding_ids_json TEXT NOT NULL,
                    metadata_ciphertext BLOB, created_at TEXT NOT NULL,
                    FOREIGN KEY(student_id,owner_account_id,scope_key)
                        REFERENCES demo2_identity_students(student_id,owner_account_id,scope_key)
                );
                CREATE TABLE IF NOT EXISTS demo2_dossier_reference_documents (
                    reference_id TEXT NOT NULL REFERENCES demo2_dossier_references(reference_id),
                    document_id TEXT NOT NULL REFERENCES demo2_dossier_documents(document_id),
                    version INTEGER NOT NULL, ordinal INTEGER NOT NULL,
                    PRIMARY KEY(reference_id,document_id), UNIQUE(reference_id,ordinal)
                );
                CREATE TABLE IF NOT EXISTS demo2_dossier_file_cleanup (
                    document_id TEXT PRIMARY KEY, status TEXT NOT NULL,
                    encrypted_file_bytes INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS demo2_dossier_storage_identity (
                    singleton INTEGER PRIMARY KEY CHECK(singleton = 1), database_id TEXT NOT NULL
                );
            """)
            connection.execute("INSERT OR IGNORE INTO demo2_dossier_storage_identity VALUES (1, ?)", (uuid4().hex,))
            # Additive migration: a classroom may withdraw its own use of a reference without deleting history.
            columns = {row[1] for row in connection.execute("PRAGMA table_info(demo2_dossier_references)")}
            if "withdrawn_at" not in columns:
                connection.execute("ALTER TABLE demo2_dossier_references ADD COLUMN withdrawn_at TEXT NOT NULL DEFAULT ''")

    def _storage_owned(self, connection):
        # Never adopt a populated legacy root: filenames/DB rows are not proof
        # of ownership. A copied DB must not inherit access to the original root.
        try:
            database = next(row[2] for row in connection.execute("PRAGMA database_list") if row[1] == "main")
            identity = connection.execute(
                "SELECT database_id FROM demo2_dossier_storage_identity WHERE singleton = 1"
            ).fetchone()
            if not database or identity is None or not re.fullmatch(r"[0-9a-f]{32}", identity[0]):
                return False
            canonical = os.path.normcase(str(Path(database).resolve()))
            expected = {"version": 1, "database_id": identity[0],
                        "database_path_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest()}
            root = self._safe_path(self.root)
            root.mkdir(parents=True, exist_ok=True, mode=0o700)
            marker = self._safe_path(root / STORAGE_OWNER_FILE)
            if not marker.exists():
                if any(root.iterdir()):
                    return False
                try:
                    # Exclusive creation never replaces another DB's claim.
                    # An interrupted/partial marker fails closed on later reads.
                    with marker.open("xb") as handle:
                        handle.write(_json(expected).encode("utf-8"))
                        handle.flush()
                        os.fsync(handle.fileno())
                except FileExistsError:
                    pass
            marker = self._safe_path(marker)
            info = marker.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_size > 4096:
                return False
            with marker.open("rb") as handle:
                value = handle.read(4097)
            return value == _json(expected).encode("utf-8")
        except (OSError, ValueError, RuntimeError, StopIteration):
            return False

    def _vault(self):
        try:
            if self._vault_instance is None:
                from .demo2_dossier_vault import DossierVault
                self._vault_instance = DossierVault(self.root)
            return self._vault_instance
        except Exception:
            raise DossierError(503, "vault_unavailable", "加密服务不可用，资料访问已停止") from None

    def _seal(self, value):
        try:
            encrypted = self._vault().seal(value)
            if not isinstance(encrypted, bytes) or encrypted == value:
                raise ValueError
            return encrypted
        except Exception:
            raise DossierError(503, "vault_unavailable", "加密服务不可用，未保存明文资料") from None

    def _open(self, value):
        try:
            result = self._vault().open(bytes(value))
            if not isinstance(result, bytes):
                raise ValueError
            return result
        except Exception:
            raise DossierError(503, "vault_unavailable", "密文资料不可读取，请联系管理员检查加密服务") from None

    def _seal_json(self, kind, object_id, value):
        return self._seal(_json({"kind": kind, "object_id": object_id, "data": value}).encode("utf-8"))

    def _open_json(self, kind, object_id, value):
        try:
            result = json.loads(self._open(value))
            if result.get("kind") != kind or result.get("object_id") != object_id or not isinstance(result.get("data"), dict):
                raise ValueError
            return result["data"]
        except DossierError:
            raise
        except Exception:
            raise DossierError(503, "vault_unavailable", "密文资料校验失败") from None

    def _vault_status(self):
        try:
            status = self._vault().status()
            mode = status.get("mode", "unavailable")
            if not isinstance(mode, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,60}", mode):
                mode = "unavailable"
            return {"available": status.get("available") is True, "mode": mode}
        except Exception:
            return {"available": False, "mode": "unavailable"}

    def _safe_path(self, path):
        candidate = Path(os.path.abspath(path))
        if candidate != self.root and self.root not in candidate.parents:
            raise DossierError(503, "storage_unavailable", "资料存储路径不可用")
        try:
            if candidate.resolve() != candidate:
                raise ValueError
            for component in (candidate, *candidate.parents):
                try:
                    info = component.lstat()
                except FileNotFoundError:
                    continue
                if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024):
                    raise ValueError
        except (OSError, ValueError, RuntimeError):
            raise DossierError(503, "storage_unavailable", "资料存储路径不可用") from None
        return candidate

    def _file(self, document_id, *, temporary=False):
        if not isinstance(document_id, str) or not re.fullmatch(r"[0-9a-f]{32}", document_id):
            raise DossierError(503, "storage_unavailable", "资料文件编号无效")
        return self._safe_path(self.root / (document_id + (".tmp" if temporary else ".enc")))

    def _write_file(self, document_id, ciphertext):
        self._safe_path(self.root).mkdir(parents=True, exist_ok=True, mode=0o700)
        final, temporary = self._file(document_id), self._file(document_id, temporary=True)
        if final.exists():
            raise DossierError(503, "storage_unavailable", "资料文件冲突")
        with temporary.open("xb") as handle:
            handle.write(ciphertext)
            handle.flush()
            os.fsync(handle.fileno())
        self._file(document_id, temporary=True).replace(self._file(document_id))

    def _actor(self, connection, token, *, admin=False):
        if not isinstance(token, str) or not token or len(token) > 512:
            raise DossierError(401, "authentication_required", "请重新登录")
        try:
            digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        except UnicodeError:
            raise DossierError(401, "authentication_required", "请重新登录") from None
        row = connection.execute("""SELECT a.*, s.expires_at AS session_expires_at, s.revoked_at
            FROM platform_accounts a JOIN account_sessions s ON s.account_id = a.account_id
            WHERE s.token_hash = ?""", (digest,)).fetchone()
        try:
            valid = row is not None and row["status"] == "active" and not row["revoked_at"] and datetime.fromisoformat(row["session_expires_at"]) > datetime.now().astimezone()
        except (ValueError, TypeError):
            valid = False
        if not valid:
            raise DossierError(401, "authentication_required", "登录已失效")
        if row["role"] != ("company_admin" if admin else "school_uploader"):
            raise DossierError(403, "dossier_forbidden", "当前账号无权执行此资料操作")
        return dict(row)

    @contextmanager
    def _session(self, token, *, admin=False):
        with self.records._connect() as connection:
            self._actor(connection, token, admin=admin)
        # Cleanup commits independently, including when the later request fails.
        self.cleanup_expired()
        with self.records._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            actor = self._actor(connection, token, admin=admin)
            yield connection, actor

    def _debug(self, operation, result, **fields):
        return debug_event(self.records, operation, result, **fields)

    @contextmanager
    def _trace(self, operation, **fields):
        trace = dict(fields)
        try:
            yield trace
        except DossierError as error:
            trace.pop("result", None)
            self._debug(operation, "rejected", code=error.code, http_status=error.status, **trace)
            raise
        except Exception as error:
            trace.pop("result", None)
            self._debug(operation, "error", error_type=type(error).__name__, **trace)
            raise
        else:
            self._debug(operation, trace.pop("result", "ok"), **trace)

    def _audit(self, connection, actor, action, object_id, detail=None):
        self.records._audit(connection, actor if isinstance(actor, str) else actor["account_id"], action,
                            "demo2_dossier", object_id, detail or {})

    def _scope(self, connection, actor):
        context = self.identities._context(self.records._school_context_for_account(connection, actor["account_id"]), required=False)
        return self.identities._scope(actor["account_id"], context)

    @staticmethod
    def _forbidden_if_foreign(connection, actor, table, column, value, scope, code, message):
        """Records owned by another school/account answer 403; unknown or deleted ones stay 404."""
        owner = "account_id" if table == "video_analysis_tasks" else "owner_account_id"
        row = connection.execute(f"SELECT {owner} AS owner{', scope_key' if table != 'video_analysis_tasks' else ''} FROM {table} WHERE {column} = ?",
                                 (value,)).fetchone()
        if row is None:
            return
        foreign_scope = table != "video_analysis_tasks" and row["scope_key"] != scope
        if row["owner"] != actor["account_id"] or foreign_scope:
            raise DossierError(403, code, message)

    def _student(self, connection, actor, student_id):
        scope = self._scope(connection, actor)
        row = connection.execute("""SELECT * FROM demo2_identity_students
            WHERE student_id = ? AND owner_account_id = ? AND scope_key = ?""",
            (_text(student_id, 120, required=True), actor["account_id"], scope)).fetchone()
        if row is None or not scope:
            self._forbidden_if_foreign(connection, actor, "demo2_identity_students", "student_id", student_id, scope,
                                       "student_forbidden", "该学生不属于当前账号的学校，无权访问其资料")
            raise DossierError(404, "student_unavailable", "学生不存在或不在当前账号的学校范围内")
        return dict(row)

    def _authorization(self, connection, actor, authorization_id, student_id):
        self._student(connection, actor, student_id)
        row = connection.execute("""SELECT * FROM demo2_dossier_authorizations
            WHERE authorization_id = ? AND student_id = ? AND owner_account_id = ? AND scope_key = ?""",
            (_text(authorization_id, 120, required=True), student_id, actor["account_id"], self._scope(connection, actor))).fetchone()
        if row is None:
            raise DossierError(404, "authorization_unavailable", "授权不存在或不可访问")
        return dict(row)

    def _document(self, connection, actor, document_id, student_id=None):
        row = connection.execute("""SELECT * FROM demo2_dossier_documents
            WHERE document_id = ? AND owner_account_id = ? AND scope_key = ?""",
            (_text(document_id, 120, required=True), actor["account_id"], self._scope(connection, actor))).fetchone()
        if row is None:
            self._forbidden_if_foreign(connection, actor, "demo2_dossier_documents", "document_id", document_id,
                                       self._scope(connection, actor), "document_forbidden", "该资料不属于当前账号的学校，无权访问")
        if row is None or (student_id is not None and row["student_id"] != student_id):
            raise DossierError(404, "document_unavailable", "资料不存在或不可访问")
        self._student(connection, actor, row["student_id"])
        return dict(row)

    @staticmethod
    def _auth_active(row):
        return row["status"] == "active" and row["valid_until"] > _today().isoformat() and row["metadata_ciphertext"] is not None

    def _available(self, connection, document):
        auth = connection.execute("SELECT * FROM demo2_dossier_authorizations WHERE authorization_id = ?", (document["authorization_id"],)).fetchone()
        return (document["status"] == "available" and document["metadata_ciphertext"] is not None
                and document["retain_until"] > _today().isoformat() and auth is not None and self._auth_active(auth)
                and all(document[key] == auth[key] for key in ("student_id", "owner_account_id", "scope_key")))

    def _require_available(self, connection, document):
        if not self._available(connection, document):
            raise DossierError(410, "document_unavailable", "资料已过期、撤回或删除，不可访问")

    def _public_authorization(self, row):
        result = {key: row[key] for key in ("authorization_id", "student_id", "storage_mode", "valid_until", "status", "purpose")}
        result["reference"] = self._open_json("authorization", row["authorization_id"], row["metadata_ciphertext"])["reference"] if self._auth_active(row) else ""
        return result

    def _public_document(self, connection, row):
        available = self._available(connection, row)
        public = {key: row[key] for key in ("document_id", "student_id", "authorization_id", "document_type", "version", "family_id",
                                            "status", "document_date", "retain_until", "created_at")}
        public.update(supersedes_id=row["supersedes_id"] or "", available=available, source_ref="", summary={}, filename="", has_file=False)
        if available:
            meta = self._open_json("document", row["document_id"], row["metadata_ciphertext"])
            public.update(source_ref=meta["source_ref"], summary=meta["summary"], filename=meta["filename"], has_file=bool(row["has_file"]))
        return public

    def _retire(self, connection, document_id, reason):
        connection.execute("""UPDATE demo2_dossier_documents SET status = 'deletion_pending',
            metadata_ciphertext = NULL, purge_reason = ?, updated_at = ? WHERE document_id = ? AND status = 'available'""",
            (reason, _iso(), document_id))
        connection.execute("""UPDATE demo2_dossier_references SET metadata_ciphertext = NULL WHERE reference_id IN
            (SELECT reference_id FROM demo2_dossier_reference_documents WHERE document_id = ?)""", (document_id,))

    def cleanup_expired(self):
        events = []
        try:
            result = self._cleanup_expired(events)
        except Exception as error:
            self._debug("expiry_check", "error", error_type=type(error).__name__)
            raise
        for operation, outcome, fields in events:
            self._debug(operation, outcome, **fields)
        if any(result[key] for key in result):
            self._debug("expiry_check", "changed", **result)
        return result

    def _cleanup_expired(self, events):
        expired_auth = expired_docs = purged = pending = 0
        with self.records._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if not self._storage_owned(connection):
                pending = connection.execute("SELECT COUNT(*) FROM demo2_dossier_documents WHERE status = 'deletion_pending'").fetchone()[0]
                pending += connection.execute("SELECT COUNT(*) FROM demo2_dossier_file_cleanup WHERE status = 'deletion_pending'").fetchone()[0]
                return {"expired_authorization_count": 0, "expired_document_count": 0,
                        "purged_count": 0, "deletion_pending_count": pending}
            today = _today().isoformat()
            for row in connection.execute("SELECT authorization_id, student_id, valid_until FROM demo2_dossier_authorizations WHERE status = 'active' AND valid_until <= ?", (today,)).fetchall():
                connection.execute("UPDATE demo2_dossier_authorizations SET status = 'expired', metadata_ciphertext = NULL, updated_at = ? WHERE authorization_id = ?", (_iso(), row[0]))
                self._audit(connection, "dossier_maintenance", "dossier_authorization_expired", row[0])
                events.append(("authorization_expiry_check", "expired", {"student_id": row["student_id"], "authorization_id": row["authorization_id"],
                                                                         "valid_until": row["valid_until"], "status": "expired"}))
                expired_auth += 1
            rows = connection.execute("""SELECT d.document_id, d.student_id, d.document_type, d.version, d.authorization_id, d.retain_until,
                a.status AS authorization_status
                FROM demo2_dossier_documents d JOIN demo2_dossier_authorizations a ON a.authorization_id = d.authorization_id
                WHERE d.status = 'available' AND (d.retain_until <= ? OR a.status <> 'active')""", (today,)).fetchall()
            for row in rows:
                reason = "withdrawn" if row["authorization_status"] == "withdrawn" else "expired"
                self._retire(connection, row["document_id"], reason)
                self._audit(connection, "dossier_maintenance", "dossier_document_expired" if reason == "expired" else "dossier_document_withdrawn", row["document_id"])
                events.append(("document_expiry_check", reason, {"student_id": row["student_id"], "document_id": row["document_id"],
                                                                 "document_type": row["document_type"], "version": row["version"],
                                                                 "authorization_id": row["authorization_id"], "retain_until": row["retain_until"],
                                                                 "reason": "retain_until_reached" if row["retain_until"] <= today else "authorization_" + row["authorization_status"]}))
                expired_docs += reason == "expired"
            for row in connection.execute("SELECT * FROM demo2_dossier_documents WHERE status = 'deletion_pending'").fetchall():
                try:
                    for temporary in (False, True):
                        self._file(row["document_id"], temporary=temporary).unlink(missing_ok=True)
                    connection.execute("""UPDATE demo2_dossier_documents SET status = ?, has_file = 0,
                        encrypted_file_bytes = 0, metadata_ciphertext = NULL, updated_at = ? WHERE document_id = ?""",
                        (row["purge_reason"] or "deleted", _iso(), row["document_id"]))
                    self._audit(connection, "dossier_maintenance", "dossier_file_purged", row["document_id"])
                    events.append(("document_purge", "purged", {"student_id": row["student_id"], "document_id": row["document_id"],
                                                                "document_type": row["document_type"], "status": row["purge_reason"] or "deleted"}))
                    purged += 1
                except (OSError, DossierError):
                    pending += 1
                    self._audit(connection, "dossier_maintenance", "dossier_purge_retry", row["document_id"], {"pending_count": 1})
                    events.append(("document_purge", "retry", {"student_id": row["student_id"], "document_id": row["document_id"],
                                                               "document_type": row["document_type"]}))
            # Recover ciphertext left by a failed SQLite commit/process crash.
            # Only UUID files in this NEW dedicated root are ever considered.
            try:
                root = self._safe_path(self.root)
                candidates = list(root.iterdir()) if root.is_dir() else []
            except (OSError, DossierError):
                candidates = []
            for path in candidates:
                match = re.fullmatch(r"([0-9a-f]{32})\.(?:enc|tmp)", path.name)
                if match and not connection.execute("SELECT 1 FROM demo2_dossier_documents WHERE document_id = ?", (match[1],)).fetchone():
                    connection.execute("""INSERT INTO demo2_dossier_file_cleanup VALUES (?,'deletion_pending',0,?,?)
                        ON CONFLICT(document_id) DO UPDATE SET status = 'deletion_pending', updated_at = excluded.updated_at""", (match[1], _iso(), _iso()))
            for row in connection.execute("SELECT * FROM demo2_dossier_file_cleanup WHERE status = 'deletion_pending'").fetchall():
                try:
                    paths = [self._file(row["document_id"], temporary=value) for value in (False, True)]
                    size = sum(path.stat().st_size for path in paths if path.is_file())
                    connection.execute("UPDATE demo2_dossier_file_cleanup SET encrypted_file_bytes = ? WHERE document_id = ?", (size, row["document_id"]))
                    for path in paths:
                        path.unlink(missing_ok=True)
                    connection.execute("UPDATE demo2_dossier_file_cleanup SET status = 'deleted', encrypted_file_bytes = 0, updated_at = ? WHERE document_id = ?", (_iso(), row["document_id"]))
                    self._audit(connection, "dossier_maintenance", "dossier_orphan_purged", row["document_id"])
                    purged += 1
                except (OSError, DossierError):
                    pending += 1
                    self._audit(connection, "dossier_maintenance", "dossier_purge_retry", row["document_id"], {"pending_count": 1})
        return {"expired_authorization_count": expired_auth, "expired_document_count": expired_docs,
                "purged_count": purged, "deletion_pending_count": pending}

    def save_authorization(self, token, payload):
        with self._trace("authorization_save", student_id=payload.get("student_id") if isinstance(payload, dict) else None) as trace:
            result = self._save_authorization(token, payload)
            trace.update(authorization_id=result["authorization_id"], valid_until=result["valid_until"],
                         storage_mode=result["storage_mode"], status=result["status"])
            return result

    def _save_authorization(self, token, payload):
        with self._session(token) as (connection, actor):
            _payload(payload, "student_id reference storage_mode valid_until confirmed", confirmed=True)
            student = self._student(connection, actor, payload["student_id"])
            reference = _text(payload["reference"], 500, required=True, multiline=True)
            mode = payload["storage_mode"]
            if mode not in ("summary_only", "original_and_summary"):
                raise DossierError(400, "invalid_storage_mode", "请选择摘要保存或原件及摘要保存")
            until = _date(payload["valid_until"])
            if not _today() < until <= _today() + timedelta(days=MAX_RETENTION_DAYS):
                raise DossierError(400, "invalid_retention", "授权期限须为未来日期且不超过内测 60 天上限")
            if connection.execute("SELECT 1 FROM demo2_dossier_authorizations WHERE student_id = ? AND status = 'active'", (student["student_id"],)).fetchone():
                raise DossierError(409, "authorization_exists", "请先撤回现有授权，不可静默替换")
            object_id, now = uuid4().hex, _iso()
            row = {"authorization_id": object_id, "student_id": student["student_id"], "owner_account_id": actor["account_id"],
                   "scope_key": student["scope_key"], "storage_mode": mode, "purpose": "education_support", "valid_until": until.isoformat(),
                   "status": "active", "metadata_ciphertext": self._seal_json("authorization", object_id, {"reference": reference}),
                   "created_at": now, "updated_at": now}
            connection.execute("""INSERT INTO demo2_dossier_authorizations VALUES
                (:authorization_id,:student_id,:owner_account_id,:scope_key,:storage_mode,:purpose,:valid_until,:status,:metadata_ciphertext,:created_at,:updated_at)""", row)
            self._audit(connection, actor, "dossier_authorization_saved", object_id, {"student_id": student["student_id"]})
            return self._public_authorization(row)

    def withdraw_authorization(self, token, payload):
        fields = payload if isinstance(payload, dict) else {}
        with self._trace("authorization_withdraw", student_id=fields.get("student_id"), authorization_id=fields.get("authorization_id")) as trace:
            result = self._withdraw_authorization(token, payload)
            trace.update(status=result["status"], deletion_pending_count=result["deletion_pending_count"],
                         document_count=result.get("document_count", 0))
            return result

    def _withdraw_authorization(self, token, payload):
        document_count = 0
        with self._session(token) as (connection, actor):
            _payload(payload, "student_id authorization_id confirmed", confirmed=True)
            auth = self._authorization(connection, actor, payload["authorization_id"], payload["student_id"])
            if auth["status"] not in {"active", "withdrawn"}:
                raise DossierError(409, "authorization_inactive", "该授权已失效")
            if auth["status"] == "active":
                connection.execute("UPDATE demo2_dossier_authorizations SET status = 'withdrawn', metadata_ciphertext = NULL, updated_at = ? WHERE authorization_id = ?", (_iso(), auth["authorization_id"]))
                rows = connection.execute("SELECT document_id FROM demo2_dossier_documents WHERE authorization_id = ?", (auth["authorization_id"],)).fetchall()
                for row in rows:
                    self._retire(connection, row[0], "withdrawn")
                document_count = len(rows)
                self._audit(connection, actor, "dossier_authorization_withdrawn", auth["authorization_id"], {"document_count": len(rows)})
        cleanup = self.cleanup_expired()
        return {"authorization_id": auth["authorization_id"], "status": "withdrawn", "deletion_pending_count": cleanup["deletion_pending_count"],
                "document_count": document_count}

    def create_document(self, token, payload):
        fields = payload if isinstance(payload, dict) else {}
        operation = "document_version_create" if fields.get("supersedes_id") else "document_create"
        with self._trace(operation, student_id=fields.get("student_id"), authorization_id=fields.get("authorization_id"),
                         document_type=fields.get("document_type"), supersedes_id=fields.get("supersedes_id") or None,
                         retain_until=fields.get("retain_until")) as trace:
            result = self._create_document(token, payload)
            trace.update(document_id=result["document_id"], version=result["version"], family_id=result["family_id"],
                         status=result["status"], has_file=result["has_file"])
            return result

    def _create_document(self, token, payload):
        failure = None
        with self._session(token) as (connection, actor):
            _payload(payload, "student_id authorization_id document_type document_date source_ref retain_until summary filename content_base64 supersedes_id")
            student = self._student(connection, actor, payload["student_id"])
            auth = self._authorization(connection, actor, payload["authorization_id"], student["student_id"])
            if not self._auth_active(auth):
                raise DossierError(410, "authorization_inactive", "授权已失效")
            kind = payload["document_type"]
            if not isinstance(kind, str) or kind not in DOCUMENT_TYPES:
                raise DossierError(400, "invalid_document_type", "资料类型无效")
            issued, until = _date(payload["document_date"]), _date(payload["retain_until"])
            if issued > _today():
                raise DossierError(400, "invalid_document_date", "资料日期不能晚于今天")
            if until > _date(auth["valid_until"]):
                raise DossierError(400, "retention_after_authorization",
                                   f"资料保存至日期不得晚于授权截止日 {auth['valid_until']}，请调整保存期限")
            if until <= _today():
                raise DossierError(400, "invalid_retention", "资料保存至日期须晚于今天")
            source = _text(payload["source_ref"], 200, required=True)
            summary = payload["summary"]
            if not isinstance(summary, dict) or set(summary) != SUMMARY_FIELDS:
                raise DossierError(400, "invalid_summary", "请提交约定的四类教师确认摘要")
            summary = {key: _text(value, 2000, multiline=True) for key, value in summary.items()}
            if auth["storage_mode"] == "summary_only" and (payload["filename"] != "" or payload["content_base64"] != ""):
                raise DossierError(400, "original_not_authorized", "摘要授权不允许上传原件")
            data, filename, mime = _file_content(payload["filename"], payload["content_base64"])
            if data and not self._storage_owned(connection):
                raise DossierError(503, "storage_unavailable", "Dossier storage ownership could not be verified")
            if not data and not any(summary.values()):
                raise DossierError(400, "empty_document", "至少填写一项摘要或上传已授权原件")
            parent_id = _text(payload["supersedes_id"], 120)
            object_id = uuid4().hex
            family, version = object_id, 1
            if parent_id:
                parent = self._document(connection, actor, parent_id, student["student_id"])
                self._require_available(connection, parent)
                if parent["document_type"] != kind:
                    raise DossierError(409, "version_type_mismatch", "后续版本须属于同一学生及资料类型")
                if connection.execute("SELECT 1 FROM demo2_dossier_documents WHERE supersedes_id = ?", (parent_id,)).fetchone():
                    raise DossierError(409, "successor_exists", "该版本已有后续版本，请刷新资料列表")
                family, version = parent["family_id"], parent["version"] + 1
            # Digest lives inside the ID-bound encrypted metadata, not an admin
            # or public field. Encrypt raw bytes to honor the vault's 8MiB cap.
            meta = self._seal_json("document", object_id, {"source_ref": source, "summary": summary, "filename": filename,
                                   "content_type": mime, "file_sha256": hashlib.sha256(data).hexdigest() if data else ""})
            ciphertext = self._seal(data) if data else b""
            now = _iso()
            row = {"document_id": object_id, "student_id": student["student_id"], "owner_account_id": actor["account_id"], "scope_key": student["scope_key"],
                   "authorization_id": auth["authorization_id"], "document_type": kind, "family_id": family, "version": version,
                   "supersedes_id": parent_id or None, "document_date": issued.isoformat(), "retain_until": until.isoformat(), "status": "available",
                   "metadata_ciphertext": meta, "has_file": int(bool(data)), "encrypted_file_bytes": len(ciphertext), "purge_reason": "",
                   "created_at": now, "updated_at": now}
            connection.execute("""INSERT INTO demo2_dossier_documents VALUES
                (:document_id,:student_id,:owner_account_id,:scope_key,:authorization_id,:document_type,:family_id,:version,:supersedes_id,
                 :document_date,:retain_until,:status,:metadata_ciphertext,:has_file,:encrypted_file_bytes,:purge_reason,:created_at,:updated_at)""", row)
            try:
                if data:
                    self._write_file(object_id, ciphertext)
                self._audit(connection, actor, "dossier_document_created", object_id, {"student_id": student["student_id"], "authorization_id": auth["authorization_id"], "version": version})
                public = self._public_document(connection, row)
            except Exception:
                # Commit a content-free tombstone even if writing or audit fails.
                # Cleanup failure is retried, never exposed as usable material.
                self._retire(connection, object_id, "deleted")
                failure = DossierError(503, "storage_unavailable", "资料保存失败，已停止访问并安排清理")
        if failure is not None:
            self.cleanup_expired()
            raise failure
        return public

    def document_download(self, token, document_id):
        with self._trace("document_download", document_id=document_id) as trace:
            data, filename, content_type = self._document_download(token, document_id, trace)
            return data, filename, content_type

    def _document_download(self, token, document_id, trace):
        with self._session(token) as (connection, actor):
            row = self._document(connection, actor, document_id)
            trace.update(student_id=row["student_id"], document_type=row["document_type"], version=row["version"])
            self._require_available(connection, row)
            if not row["has_file"]:
                raise DossierError(404, "original_unavailable", "此版本未保存原件")
            meta = self._open_json("document", row["document_id"], row["metadata_ciphertext"])
            try:
                path = self._file(row["document_id"])
                if path.stat().st_size > (MAX_FILE_BYTES + 1024) * 2:
                    raise ValueError
                data = self._open(path.read_bytes())
                if len(data) > MAX_FILE_BYTES or not hmac.compare_digest(hashlib.sha256(data).hexdigest(), meta["file_sha256"]):
                    raise ValueError
            except DossierError:
                raise
            except (OSError, ValueError):
                raise DossierError(503, "original_unavailable", "原件不可读取或校验失败") from None
            self._audit(connection, actor, "dossier_document_downloaded", row["document_id"])
            return data, meta["filename"], meta["content_type"]

    def delete_document(self, token, payload):
        fields = payload if isinstance(payload, dict) else {}
        with self._trace("document_delete", student_id=fields.get("student_id"), document_id=fields.get("document_id")) as trace:
            return self._delete_document(token, payload, trace)

    def _delete_document(self, token, payload, trace):
        with self._session(token) as (connection, actor):
            _payload(payload, "student_id document_id confirmed", confirmed=True)
            self._student(connection, actor, payload["student_id"])
            row = self._document(connection, actor, payload["document_id"], payload["student_id"])
            trace.update(document_type=row["document_type"], version=row["version"])
            if row["status"] == "available":
                self._retire(connection, row["document_id"], "deleted")
                self._audit(connection, actor, "dossier_document_deleted", row["document_id"])
        self.cleanup_expired()
        with self.records._connect() as connection:
            status = connection.execute("SELECT status FROM demo2_dossier_documents WHERE document_id = ?", (row["document_id"],)).fetchone()[0]
        trace.update(status=status)
        return {"document_id": row["document_id"], "status": status, "available": False}

    def iep_context(self, token, student_id):
        """Current IEP for one student: only document_type='iep', never a silent pick."""
        with self._trace("iep_context_query", student_id=student_id, document_type="iep") as trace:
            with self._session(token) as (connection, actor):
                student = self._student(connection, actor, student_id)
                access = material_access_state(connection, student_id=student["student_id"], purpose="analysis")
                base = {"student_id": student["student_id"], "document_type": "iep", "iep": None, "iep_document_id": "",
                        "candidates": [], "access": access}
                if not access["available"]:
                    trace.update(result="unavailable", reason=access["reason"], authorization_id=access["authorization_id"])
                    return {**base, "status": "unavailable", "reason": access["reason"], "message": access["message"]}
                rows = [dict(row) for row in connection.execute("""SELECT * FROM demo2_dossier_documents
                    WHERE student_id = ? AND document_type = 'iep' ORDER BY created_at, version""", (student["student_id"],))]
                heads = current_iep_versions(rows, lambda row: self._available(connection, row))
                trace.update(candidate_count=len(heads), authorization_id=access["authorization_id"])
                if not heads:
                    trace.update(result="not_found", reason="iep_not_found")
                    return {**base, "status": "not_found", "reason": "iep_not_found",
                            "message": "该学生当前没有有效的 IEP 资料；专业评估等其他资料不会作为 IEP 使用"}
                if len(heads) > 1:
                    trace.update(result="ambiguous", reason="multiple_current_iep")
                    candidates = [{key: row[key] for key in ("document_id", "family_id", "version", "document_date", "retain_until")} for row in heads]
                    return {**base, "status": "ambiguous", "reason": "multiple_current_iep", "candidates": candidates,
                            "message": f"该学生同时存在 {len(heads)} 份有效 IEP，系统不自动选择；请教师核实后删除或明确使用其中一份"}
                public = self._public_document(connection, heads[0])
                trace.update(result="available", document_id=public["document_id"], version=public["version"])
                return {**base, "status": "available", "reason": "available", "iep": public,
                        "iep_document_id": public["document_id"], "message": "已读取该学生唯一有效的 IEP 当前版本"}

    def material_access(self, token, student_id, purpose):
        with self._trace("material_access_check", student_id=student_id, purpose=purpose) as trace:
            if purpose not in ACCESS_PURPOSES:
                raise DossierError(400, "invalid_purpose", "用途须为 analysis（课堂分析）或 scoring（课堂评分）")
            with self._session(token) as (connection, actor):
                student = self._student(connection, actor, student_id)
                state = material_access_state(connection, student_id=student["student_id"], purpose=purpose)
            trace.update(result="available" if state["available"] else "unavailable", reason=state["reason"],
                         authorization_id=state["authorization_id"] or None, valid_until=state["valid_until"] or None)
            return state

    def _task(self, connection, actor, task_id):
        try:
            task = self.identities._task(connection, actor, task_id)
            context = self.identities._context(task.get("school_context_json"), required=False)
            scope = self.identities._scope(task.get("account_id"), context)
            if not scope or scope != self._scope(connection, actor):
                raise ValueError
            return task
        except (ValueError, IdentityError):
            if isinstance(task_id, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,120}", task_id):
                self._forbidden_if_foreign(connection, actor, "video_analysis_tasks", "task_id", task_id,
                                           self._scope(connection, actor), "task_forbidden", "该课堂任务不属于当前账号的学校，无权访问")
            raise DossierError(404, "task_unavailable", "任务不存在或不在当前学校范围内") from None

    def _live_bindings(self, connection, task):
        try:
            self.identities._require_media(task)
            frames = self.identities._frames(task)
        except IdentityError as error:
            return [], error.code
        revision = self.identities._revision(task)
        scope = self.identities._scope(task["account_id"], self.identities._context(task["school_context_json"], required=False))
        rows = connection.execute("""SELECT * FROM demo2_identity_bindings WHERE task_id = ? AND owner_account_id = ?
            AND scope_key = ? AND frame_revision = ? AND source_sha256 = ? AND role = 'student' AND status = 'confirmed'""",
            (task["task_id"], task["account_id"], scope, revision, task["sha256"])).fetchall()
        bindings = [dict(row) for row in rows if row["frame_key"] in frames and row["time_sec"] == frames[row["frame_key"]]["time_sec"]]
        return bindings, "current" if bindings else "identity_unavailable"

    def _reference_public(self, connection, actor, row, *, log=True):
        links = [dict(item) for item in connection.execute("SELECT document_id,version FROM demo2_dossier_reference_documents WHERE reference_id = ? ORDER BY ordinal", (row["reference_id"],))]
        documents = [self._public_document(connection, self._document(connection, actor, link["document_id"], row["student_id"])) for link in links]
        recorded = json.loads(row["binding_ids_json"])
        evidence_status = "identity_unavailable"
        school_id = ""
        try:
            task = self._task(connection, actor, row["task_id"])
            school_id = school_id_from_context(self.identities._context(task.get("school_context_json"), required=False))
            current, evidence_status = self._live_bindings(connection, task)
            ids = {item["binding_id"] for item in current if item["student_id"] == row["student_id"]}
            if task["sha256"] != row["source_sha256"] or self.identities._revision(task) != row["frame_revision"]:
                evidence_status = "outdated_revision"
            elif not recorded or not all(item["binding_id"] in ids for item in recorded):
                evidence_status = "identity_unavailable" if evidence_status == "current" else evidence_status
        except DossierError:
            evidence_status = "task_unavailable"
        meta = self._open_json("reference", row["reference_id"], row["metadata_ciphertext"]) if row["metadata_ciphertext"] else {}
        withdrawn_at = row.get("withdrawn_at") or ""
        sources = []
        for link, document in zip(links, documents):
            if withdrawn_at:
                reason, message = "reference_withdrawn", REFERENCE_WITHDRAWN_MESSAGE
            elif not document["available"]:
                state = material_access_state(connection, student_id=row["student_id"], document_id=link["document_id"])
                reason = state["reason"] if not state["available"] else "document_unavailable"
                message = state["message"] if not state["available"] else "资料版本已不可用，不作为本课有效依据"
            elif evidence_status != "current":
                reason, message = evidence_status, EVIDENCE_MESSAGES.get(evidence_status, "身份依据未确认，该来源不作为本课有效依据")
            else:
                reason, message = "available", "授权、资料版本与当前身份依据均有效"
            sources.append({"document_id": link["document_id"], "version": link["version"],
                            "document_type": document["document_type"], "valid_as_evidence": reason == "available",
                            "reason": reason, "message": message})
        sources_available = all(document["available"] for document in documents) and bool(documents)
        available = sources_available and evidence_status == "current" and not withdrawn_at
        status = ("withdrawn" if withdrawn_at else "sources_unavailable" if not sources_available
                  else "available" if available else evidence_status)
        iep_docs = [doc for doc in documents if doc["document_type"] == "iep"]
        iep_ids = [doc["document_id"] for doc in iep_docs]
        # v1 and v2 of one IEP family resolve to the newest; separate families stay ambiguous.
        iep_document_id = ("" if not iep_docs else "ambiguous" if len({doc["family_id"] for doc in iep_docs}) > 1
                           else max(iep_docs, key=lambda doc: doc["version"])["document_id"])
        result = {"reference_id": row["reference_id"], "task_id": row["task_id"], "video_task_id": row["task_id"],
                  "school_id": school_id, "student_id": row["student_id"],
                  "iep_document_id": iep_document_id,
                  "course_id": meta.get("course_id", ""), "course_name": meta.get("course_name", ""),
                  "frame_revision": row["frame_revision"], "source_sha256": row["source_sha256"], "bindings": recorded,
                  "document_versions": links,
                  "iep_document_ids": iep_ids,
                  "documents": documents, "sources": sources, "created_at": row["created_at"], "available": available,
                  "withdrawn": bool(withdrawn_at), "withdrawn_at": withdrawn_at,
                  "identity_valid": evidence_status == "current", "sources_available": sources_available,
                  "evidence_status": evidence_status, "status": status,
                  "identity_scope": "single_sample_frame", "notice": "这是教师确认的单帧身份与授权资料版本引用，不是自动诊断、连续身份跟踪或教学成效结论。"}
        if log:
            invalid = [item for item in sources if not item["valid_as_evidence"]]
            self._debug("reference_validity_check", "valid" if available else "invalid", task_id=row["task_id"],
                        student_id=row["student_id"], reference_id=row["reference_id"], status=status,
                        evidence_status=evidence_status, reason=invalid[0]["reason"] if invalid else "available",
                        valid_source_count=len(sources) - len(invalid), invalid_source_count=len(invalid))
        return result

    def _references(self, connection, actor, *, student_id=None, task_id=None):
        field, value = ("student_id", student_id) if student_id is not None else ("task_id", task_id)
        rows = connection.execute(f"SELECT * FROM demo2_dossier_references WHERE owner_account_id = ? AND scope_key = ? AND {field} = ? ORDER BY created_at, rowid",
                                  (actor["account_id"], self._scope(connection, actor), value)).fetchall()
        return [self._reference_public(connection, actor, dict(row)) for row in rows]

    def student_workspace(self, token, student_id):
        with self._session(token) as (connection, actor):
            student = self._student(connection, actor, student_id)
            auth = connection.execute("SELECT * FROM demo2_dossier_authorizations WHERE student_id = ? AND status = 'active'", (student_id,)).fetchone()
            documents = [self._public_document(connection, dict(row)) for row in connection.execute("SELECT * FROM demo2_dossier_documents WHERE student_id = ? ORDER BY created_at, version", (student_id,))]
            references = self._references(connection, actor, student_id=student_id)
            self._audit(connection, actor, "dossier_student_viewed", student_id)
            return {"student": {key: student[key] for key in ("student_id", "display_name", "student_code", "class_name")},
                    "authorization": self._public_authorization(dict(auth)) if auth else None, "documents": documents,
                    "references": references, "vault": self._vault_status(), "policy": dict(POLICY), "legacy_notice": LEGACY_NOTICE}

    def task_workspace(self, token, task_id):
        with self._session(token) as (connection, actor):
            task = self._task(connection, actor, task_id)
            bindings, reason = self._live_bindings(connection, task)
            students = []
            for student_id in dict.fromkeys(item["student_id"] for item in bindings):
                student = self._student(connection, actor, student_id)
                # Only versions usable right now; withdrawn/deleted/expired versions never become new references.
                docs = [public for public in (self._public_document(connection, dict(row)) for row in connection.execute(
                    "SELECT * FROM demo2_dossier_documents WHERE student_id = ? ORDER BY created_at,version", (student_id,))) if public["available"]]
                students.append({"student_id": student_id, "display_name": student["display_name"],
                                 "confirmed_binding_count": sum(item["student_id"] == student_id for item in bindings), "documents": docs})
            self._audit(connection, actor, "dossier_task_viewed", task_id, {"student_count": len(students)})
            return {"task": {"task_id": task_id, "course_id": task["course_id"], "course_name": task["course_name"], "frame_revision": self.identities._revision(task)},
                    "students": students, "references": self._references(connection, actor, task_id=task_id),
                    "notice": "仅列出当前版本有效学生身份绑定；历史引用保留失效标记。" if reason == "current" else "当前没有可用于新资料引用的有效身份与原视频证据。"}

    def create_reference(self, token, payload):
        fields = payload if isinstance(payload, dict) else {}
        requested = fields.get("document_ids")
        with self._trace("reference_create", task_id=fields.get("task_id"), student_id=fields.get("student_id"),
                         document_count=len(requested) if isinstance(requested, list) else None) as trace:
            with self._session(token) as (connection, actor):
                _payload(payload, "task_id student_id frame_revision document_ids confirmed", confirmed=True)
                student = self._student(connection, actor, payload["student_id"])
                task = self._task(connection, actor, payload["task_id"])
                if payload["frame_revision"] != self.identities._revision(task):
                    raise DossierError(409, "stale_frame_revision", "身份采样版本已变化，请刷新后复核")
                bindings, reason = self._live_bindings(connection, task)
                bindings = [item for item in bindings if item["student_id"] == student["student_id"]]
                if reason != "current" or not bindings:
                    raise DossierError(409, "identity_unavailable", "没有当前有效的学生身份与原视频证据，不能建立新引用")
                ids = payload["document_ids"]
                if (not isinstance(ids, list) or not 1 <= len(ids) <= 10 or any(not isinstance(value, str) for value in ids)
                        or len(ids) != len(set(ids))):
                    raise DossierError(400, "invalid_document_ids", "请选择一至十个不同的资料版本")
                documents = [self._document(connection, actor, value, student["student_id"]) for value in ids]
                for document in documents:
                    self._require_available(connection, document)
                object_id = uuid4().hex
                row = {"reference_id": object_id, "student_id": student["student_id"], "owner_account_id": actor["account_id"],
                       "scope_key": student["scope_key"], "task_id": task["task_id"], "frame_revision": self.identities._revision(task),
                       "source_sha256": task["sha256"], "binding_ids_json": _json([{key: item[key] for key in ("binding_id", "frame_key", "time_sec")} for item in bindings]),
                       "metadata_ciphertext": self._seal_json("reference", object_id, {"course_id": task["course_id"], "course_name": task["course_name"]}),
                       "created_at": _iso(), "withdrawn_at": ""}
                connection.execute("""INSERT INTO demo2_dossier_references (reference_id,student_id,owner_account_id,scope_key,task_id,
                    frame_revision,source_sha256,binding_ids_json,metadata_ciphertext,created_at,withdrawn_at) VALUES
                    (:reference_id,:student_id,:owner_account_id,:scope_key,:task_id,:frame_revision,:source_sha256,:binding_ids_json,:metadata_ciphertext,:created_at,:withdrawn_at)""", row)
                connection.executemany("INSERT INTO demo2_dossier_reference_documents VALUES (?,?,?,?)",
                                       [(object_id, doc["document_id"], doc["version"], index) for index, doc in enumerate(documents)])
                self._audit(connection, actor, "dossier_reference_created", object_id, {"task_id": task["task_id"], "student_id": student["student_id"], "document_count": len(documents)})
                result = self._reference_public(connection, actor, row, log=False)
            trace.update(result="created", reference_id=object_id, task_id=task["task_id"], student_id=student["student_id"],
                         document_count=len(documents), status=result["status"], evidence_status=result["evidence_status"])
            return result

    def _reference_row(self, connection, actor, reference_id):
        row = connection.execute("SELECT * FROM demo2_dossier_references WHERE reference_id = ? AND owner_account_id = ? AND scope_key = ?",
                                 (_text(reference_id, 120, required=True), actor["account_id"], self._scope(connection, actor))).fetchone()
        if row is None:
            self._forbidden_if_foreign(connection, actor, "demo2_dossier_references", "reference_id", reference_id,
                                       self._scope(connection, actor), "reference_forbidden", "该课堂引用不属于当前账号的学校，无权访问")
            raise DossierError(404, "reference_unavailable", "引用不存在或不可访问")
        self._student(connection, actor, row["student_id"])
        return dict(row)

    def reference_export(self, token, reference_id):
        """Download re-verifies authorization, versions and identity; invalid sources are never valid evidence."""
        with self._trace("reference_export", reference_id=reference_id) as trace:
            with self._session(token) as (connection, actor):
                row = self._reference_row(connection, actor, reference_id)
                result = self._reference_public(connection, actor, row)
                valid = [item for item in result["sources"] if item["valid_as_evidence"]]
                invalid = [item for item in result["sources"] if not item["valid_as_evidence"]]
                result["export"] = {
                    "export_kind": "classroom_dossier_reference", "verified_at": _iso(),
                    "valid_evidence": result["available"],
                    "valid_sources": [{key: item[key] for key in ("document_id", "version", "document_type")} for item in valid],
                    "invalid_sources": [{key: item[key] for key in ("document_id", "version", "document_type", "reason", "message")} for item in invalid],
                    "verification_notice": "导出时已重新核验授权、资料版本和当前身份依据；已撤回、删除、过期或身份失效的来源不作为有效依据。"}
                self._audit(connection, actor, "dossier_reference_exported", reference_id,
                            {"valid_source_count": len(valid), "invalid_source_count": len(invalid)})
            trace.update(result="valid" if result["available"] else "invalid", task_id=result["task_id"],
                         student_id=result["student_id"], status=result["status"], evidence_status=result["evidence_status"],
                         valid_source_count=len(valid), invalid_source_count=len(invalid))
            return result

    def withdraw_reference(self, token, payload):
        """Withdraw this classroom's use of the referenced materials; history stays, analysis stops reading it."""
        fields = payload if isinstance(payload, dict) else {}
        with self._trace("reference_withdraw", reference_id=fields.get("reference_id")) as trace:
            with self._session(token) as (connection, actor):
                _payload(payload, "reference_id confirmed", confirmed=True)
                row = self._reference_row(connection, actor, payload["reference_id"])
                trace.update(task_id=row["task_id"], student_id=row["student_id"])
                if row.get("withdrawn_at"):
                    raise DossierError(409, "reference_already_withdrawn", "该课堂引用授权已撤回")
                row["withdrawn_at"] = _iso()
                connection.execute("UPDATE demo2_dossier_references SET withdrawn_at = ? WHERE reference_id = ? AND withdrawn_at = ''",
                                   (row["withdrawn_at"], row["reference_id"]))
                self._audit(connection, actor, "dossier_reference_withdrawn", row["reference_id"], {"task_id": row["task_id"]})
                result = self._reference_public(connection, actor, row, log=False)
            trace.update(result="withdrawn", status=result["status"])
            return result

    def analysis_context(self, token, task_id):
        """Snapshot of which dossier versions may enter this task's analysis/scoring context right now."""
        with self._trace("analysis_context_snapshot", task_id=task_id) as trace:
            with self._session(token) as (connection, actor):
                task = self._task(connection, actor, task_id)
                references = self._references(connection, actor, task_id=task["task_id"])
            entries, included_total, iep_total = [], 0, 0
            for ref in references:
                included = [{key: item[key] for key in ("document_id", "version", "document_type")}
                            for item in ref["sources"] if ref["available"] and item["valid_as_evidence"]]
                excluded = [{key: item[key] for key in ("document_id", "version", "document_type", "reason", "message")}
                            for item in ref["sources"] if not (ref["available"] and item["valid_as_evidence"])]
                included_total += len(included)
                iep_total += sum(item["document_type"] == "iep" for item in included)
                entries.append({"reference_id": ref["reference_id"], "student_id": ref["student_id"],
                                "video_task_id": ref["task_id"], "status": ref["status"], "withdrawn": ref["withdrawn"],
                                "included": included, "excluded": excluded})
            professional_total = included_total - iep_total
            snapshot = {"video_task_id": task["task_id"], "task_id": task["task_id"], "course_id": task["course_id"],
                        "generated_at": _iso(), "references": entries,
                        "reads_iep": iep_total > 0, "reads_professional_materials": professional_total > 0,
                        "iep_included_count": iep_total, "professional_included_count": professional_total,
                        "notice": "仅当课堂引用未撤回、授权与资料版本有效且当前身份依据有效时，IEP 或专业资料才会进入分析与评分上下文。"}
            trace.update(result="included" if included_total else "none", task_id=task["task_id"],
                         reference_count=len(entries), included_count=included_total,
                         excluded_count=sum(len(entry["excluded"]) for entry in entries),
                         iep_included_count=iep_total, professional_included_count=professional_total)
            return snapshot

    def admin_summary(self, token):
        with self._session(token, admin=True) as (connection, actor):
            count = lambda sql: connection.execute(sql).fetchone()[0]
            totals = {"authorization_count": count("SELECT COUNT(*) FROM demo2_dossier_authorizations"),
                      "active_authorization_count": count("SELECT COUNT(*) FROM demo2_dossier_authorizations WHERE status = 'active'"),
                      "document_count": count("SELECT COUNT(*) FROM demo2_dossier_documents"),
                      "available_document_count": count("SELECT COUNT(*) FROM demo2_dossier_documents WHERE status = 'available'"),
                      "expired_document_count": count("SELECT COUNT(*) FROM demo2_dossier_documents WHERE status = 'expired' OR purge_reason = 'expired'"),
                      "deletion_pending_count": count("SELECT COUNT(*) FROM demo2_dossier_documents WHERE status = 'deletion_pending'") + count("SELECT COUNT(*) FROM demo2_dossier_file_cleanup WHERE status = 'deletion_pending'"),
                      "reference_count": count("SELECT COUNT(*) FROM demo2_dossier_references"),
                      "encrypted_file_bytes": count("SELECT COALESCE(SUM(encrypted_file_bytes),0) FROM demo2_dossier_documents") + count("SELECT COALESCE(SUM(encrypted_file_bytes),0) FROM demo2_dossier_file_cleanup WHERE status = 'deletion_pending'")}
            channels = [dict(row) for row in connection.execute("""SELECT c.channel_no, COUNT(d.document_id) AS document_count,
                COALESCE(SUM(d.status = 'available'),0) AS available_document_count,
                COALESCE(SUM(d.status = 'deletion_pending'),0) AS deletion_pending_count,
                COALESCE(SUM(d.encrypted_file_bytes),0) AS encrypted_file_bytes
                FROM video_upload_channels c LEFT JOIN platform_accounts a ON a.bound_channel_id = c.channel_id
                LEFT JOIN demo2_dossier_documents d ON d.owner_account_id = a.account_id
                GROUP BY c.channel_no ORDER BY c.channel_no""")]
            self._audit(connection, actor, "dossier_admin_viewed", "platform", {"document_count": totals["document_count"]})
            return {"totals": totals, "channels": channels, "policy": {**POLICY, "raw_documents_visible": False}, "vault": self._vault_status()}
