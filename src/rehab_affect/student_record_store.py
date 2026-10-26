from __future__ import annotations

import base64
import errno
import hashlib
import hmac
import json
import math
import mimetypes
import os
import re
import secrets
import shutil
import sqlite3
import stat
import time
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from math import ceil
from pathlib import Path, PurePosixPath, PureWindowsPath
from threading import Event, Lock
from typing import Any
from urllib.parse import quote
from uuid import uuid4
from xml.etree import ElementTree


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "outputs" / "seewo_demo2" / "rehab_affect_demo2.sqlite3"
DEFAULT_UPLOAD_DIR = PROJECT_ROOT / "outputs" / "seewo_demo2" / "student_documents"
REPORT_DIR = PROJECT_ROOT / "outputs" / "seewo_demo2" / "reports"
VIDEO_TASK_DIR = PROJECT_ROOT / "outputs" / "seewo_demo2" / "video_tasks"
MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
MAX_VIDEO_BYTES = 5 * 1024 * 1024 * 1024
MAX_NEW_VIDEO_BYTES = 1024 * 1024 * 1024
MAX_VIDEO_CHUNK_BYTES = 4 * 1024 * 1024
VIDEO_CREATE_RESERVE_BYTES = 1024 * 1024 * 1024
VIDEO_APPEND_RESERVE_BYTES = 64 * 1024 * 1024
PASSWORD_HASH_ITERATIONS = 210_000
PASSWORD_SALT_BYTES = 16
SESSION_TOKEN_BYTES = 32
DEFAULT_SESSION_HOURS = 8
DEFAULT_COURSE_UPLOAD_LIMIT = 5
MIN_COURSE_UPLOAD_LIMIT = 3
MAX_COURSE_UPLOAD_LIMIT = 5
ACCOUNT_PASSWORD_PREFIX_ENV = "REHAB_DEMO2_ACCOUNT_PASSWORD_PREFIX"
DEFAULT_ACCOUNT_PASSWORD_PREFIX = "RehabDemo2-"
PILOT_ACCOUNT_ALIASES = {
    **{f"t{index}": f"school_uploader_{index:02d}" for index in range(1, 5)},
    "admin": "company_admin",
}
REGISTRATION_AGREEMENT_VERSION = "2026-09-08"
REGISTRATION_WINDOW_SECONDS = 3600
REGISTRATION_PER_SOURCE_LIMIT = 5
REGISTRATION_GLOBAL_LIMIT = 100
SCHOOL_CONTEXT_LIMITS = {"city": 80, "district": 80, "school_name": 200}
ENTRY_FIELD_LABELS = {
    "name": "联系人", "contact": "联系方式", "city": "城市", "district": "区县", "school_name": "学校名称",
}
MAX_PROCESSING_CONFIG_BYTES = 32 * 1024
MAX_PROCESSING_RESULT_BYTES = 10 * 1024 * 1024
SIMPLE_REFRESH_RETRY_SECONDS = 30
SIMPLE_REFRESH_MAX_RETRY_SECONDS = 300
PERSON_CROP_VERSION = "v3_full_head"
_PERSON_PREVIEW_LOCK = Lock()
LEGACY_VIDEO_ANALYSIS_STATUSES = {"precheck_complete", "uploaded_pending_worker"}
READY_VIDEO_ANALYSIS_STATUSES = LEGACY_VIDEO_ANALYSIS_STATUSES | {"evidence_ready", "completed"}
ALLOWED_DOCUMENT_EXTENSIONS = {
    ".docx",
    ".pdf",
    ".xlsx",
    ".xls",
    ".csv",
    ".json",
    ".txt",
    ".png",
    ".jpg",
    ".jpeg",
}
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}

DOCUMENT_TYPE_LABELS = {
    "iep": "IEP / 个别化教育计划",
    "five_domain": "五大领域评估",
    "professional_assessment": "专业评估资料",
    "safety_support": "行为指导与安全支持",
    "other": "其他校方授权资料",
}

DEFAULT_POLICIES = {
    "raw_media": {
        "label": "课堂原始视频与音频",
        "retention_days": 60,
        "reminder_days": 15,
        "auto_delete": True,
        "downloadable": True,
    },
    "student_document": {
        "label": "IEP 与专业评估原文件",
        "retention_days": 365,
        "reminder_days": 30,
        "auto_delete": False,
        "downloadable": True,
    },
    "generated_report": {
        "label": "课程报告与教师复核表",
        "retention_days": 365,
        "reminder_days": 30,
        "auto_delete": False,
        "downloadable": True,
    },
    "structured_record": {
        "label": "脱敏结构化学生档案",
        "retention_days": 730,
        "reminder_days": 30,
        "auto_delete": False,
        "downloadable": True,
    },
}


def _now() -> datetime:
    return datetime.now().astimezone()


class RegistrationRateLimitError(ValueError):
    """The public application endpoint has exhausted its submission budget."""


class VideoUploadError(ValueError):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code = status, code


def _bounded_fields(payload: dict[str, Any], limits: dict[str, int]) -> dict[str, str]:
    fields = {}
    for key, limit in limits.items():
        value = payload.get(key)
        label = ENTRY_FIELD_LABELS[key]
        if not isinstance(value, str) or not 1 <= len(value.strip()) <= limit:
            raise ValueError(f"{label}须填写 1 至 {limit} 个字符")
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError(f"{label}不能包含换行或控制字符")
        fields[key] = value.strip()
    return fields


def _valid_registration_contact(contact: str) -> bool:
    local, separator, domain = contact.rpartition("@")
    if separator:
        return bool(
            re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}", local)
            and not local.startswith(".") and not local.endswith(".") and ".." not in local
            and re.fullmatch(r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}", domain)
        )
    phone = re.sub(r"[ -]", "", contact)
    return bool(
        re.fullmatch(r"(?:\+?86)?1[3-9][0-9]{9}", phone)
        or (not phone.startswith("+86") and re.fullmatch(r"\+[1-9][0-9]{7,14}", phone))
    )


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).isoformat(timespec="seconds")


def _safe_filename(filename: str) -> str:
    name = Path(str(filename or "document")).name.strip()
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    return name[:160] or "document"


def _directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _decode_document(content_base64: str) -> bytes:
    encoded = str(content_base64 or "").strip()
    if "," in encoded and encoded.lower().startswith("data:"):
        encoded = encoded.split(",", 1)[1]
    try:
        data = base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        raise ValueError("上传文件内容不是有效的 Base64 数据") from exc
    if not data:
        raise ValueError("上传文件为空")
    if len(data) > MAX_DOCUMENT_BYTES:
        raise ValueError("单个资料文件不能超过 10MB")
    return data


def _password_hash(password: str, salt: bytes, iterations: int = PASSWORD_HASH_ITERATIONS) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    ).hex()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _processing_json(value: Any, *, max_bytes: int) -> str:
    if not isinstance(value, dict):
        raise ValueError("处理配置和结果必须是 JSON 对象")
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        if len(encoded.encode("utf-8")) > max_bytes:
            raise ValueError("处理配置或结果超过大小限制")
    except (TypeError, RecursionError) as exc:
        raise ValueError("处理配置或结果不是有效的 JSON 对象") from exc
    return encoded


def _public_processing_data(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _public_processing_data(item) for key, item in value.items()
            if key not in {"path", "directory", "processing_claim_id"}
            and not key.endswith(("_path", "_dir", "_directory"))
        }
    if isinstance(value, list):
        return [_public_processing_data(item) for item in value]
    if isinstance(value, str) and (re.match(r"^[A-Za-z]:[\\/]", value) or value.startswith(("/", "\\\\", "file://"))):
        return ""
    return value


def _initial_password(username: str) -> str:
    prefix = os.getenv(ACCOUNT_PASSWORD_PREFIX_ENV, DEFAULT_ACCOUNT_PASSWORD_PREFIX)
    return f"{prefix}{username}"


def _configured_course_upload_limit() -> int:
    raw = os.getenv("REHAB_DEMO2_COURSE_UPLOAD_LIMIT", str(DEFAULT_COURSE_UPLOAD_LIMIT))
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_COURSE_UPLOAD_LIMIT
    if MIN_COURSE_UPLOAD_LIMIT <= value <= MAX_COURSE_UPLOAD_LIMIT:
        return value
    return DEFAULT_COURSE_UPLOAD_LIMIT


def _extract_preview(path: Path) -> tuple[str, str]:
    suffix = path.suffix.lower()
    try:
        if suffix in {".txt", ".csv", ".json"}:
            text = path.read_text(encoding="utf-8", errors="ignore")
            return "已提取文本", re.sub(r"\s+", " ", text).strip()[:1200]
        if suffix == ".docx":
            with zipfile.ZipFile(path) as archive:
                xml = archive.read("word/document.xml")
            root = ElementTree.fromstring(xml)
            text = " ".join(node.text or "" for node in root.iter() if node.tag.endswith("}t"))
            return "已提取 DOCX 文本", re.sub(r"\s+", " ", text).strip()[:1200]
    except (OSError, KeyError, zipfile.BadZipFile, ElementTree.ParseError):
        return "解析失败，待人工核对", ""
    return "文件已保存，待教师填写结构化摘要", ""


class Demo2StudentRecordStore:
    """Small local persistence layer for the school-demo product workflow.

    SQLite stores structured records and file metadata. Original documents remain in
    a controlled local directory so the schema can later move to PostgreSQL plus
    object storage without changing the browser workflow.
    """

    def __init__(self, db_path: Path = DEFAULT_DB_PATH, upload_dir: Path = DEFAULT_UPLOAD_DIR):
        self.db_path = Path(db_path)
        self.upload_dir = Path(upload_dir)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.video_task_dir = self.db_path.parent / "video_tasks"
        self.video_task_dir.mkdir(parents=True, exist_ok=True)
        self._upload_lock = Lock()
        self._analysis_claims: dict[str, str] = {}
        self._simple_refresh_retry: dict[tuple[str, str], datetime] = {}
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path, timeout=10)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA journal_mode = WAL")
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS students (
                    student_id TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    school_id TEXT NOT NULL DEFAULT 'demo_school',
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS student_documents (
                    document_id TEXT PRIMARY KEY,
                    student_id TEXT NOT NULL REFERENCES students(student_id),
                    document_type TEXT NOT NULL,
                    original_filename TEXT NOT NULL,
                    stored_filename TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    byte_size INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    source_org TEXT NOT NULL DEFAULT '',
                    document_date TEXT NOT NULL DEFAULT '',
                    note TEXT NOT NULL DEFAULT '',
                    parse_status TEXT NOT NULL,
                    extracted_preview TEXT NOT NULL DEFAULT '',
                    retention_days INTEGER NOT NULL,
                    expires_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS student_support_profiles (
                    student_id TEXT PRIMARY KEY REFERENCES students(student_id),
                    professional_conclusion TEXT NOT NULL DEFAULT '',
                    support_summary TEXT NOT NULL DEFAULT '',
                    effective_support TEXT NOT NULL DEFAULT '',
                    safety_constraints TEXT NOT NULL DEFAULT '',
                    updated_by TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS retention_policies (
                    data_type TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    storage_backend TEXT NOT NULL DEFAULT 'local_controlled',
                    retention_days INTEGER NOT NULL,
                    reminder_days INTEGER NOT NULL DEFAULT 15,
                    auto_delete INTEGER NOT NULL DEFAULT 0,
                    downloadable INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS audit_logs (
                    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    actor TEXT NOT NULL,
                    action TEXT NOT NULL,
                    object_type TEXT NOT NULL,
                    object_id TEXT NOT NULL,
                    detail_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS video_upload_channels (
                    channel_id TEXT PRIMARY KEY,
                    channel_no INTEGER NOT NULL UNIQUE,
                    channel_name TEXT NOT NULL,
                    owner_label TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS platform_accounts (
                    account_id TEXT PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    password_salt TEXT NOT NULL,
                    password_iterations INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    bound_channel_id TEXT UNIQUE REFERENCES video_upload_channels(channel_id),
                    course_upload_limit INTEGER NOT NULL DEFAULT 5
                        CHECK(course_upload_limit BETWEEN 3 AND 5),
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS account_sessions (
                    session_id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL REFERENCES platform_accounts(account_id),
                    token_hash TEXT NOT NULL UNIQUE,
                    expires_at TEXT NOT NULL,
                    revoked_at TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS school_contexts (
                    account_id TEXT PRIMARY KEY REFERENCES platform_accounts(account_id),
                    city TEXT NOT NULL CHECK(length(trim(city)) BETWEEN 1 AND 80),
                    district TEXT NOT NULL CHECK(length(trim(district)) BETWEEN 1 AND 80),
                    school_name TEXT NOT NULL CHECK(length(trim(school_name)) BETWEEN 1 AND 200),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS school_selection_metadata (
                    account_id TEXT PRIMARY KEY REFERENCES platform_accounts(account_id),
                    details_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS registration_requests (
                    request_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL CHECK(length(trim(name)) BETWEEN 1 AND 80),
                    contact TEXT NOT NULL CHECK(length(trim(contact)) BETWEEN 1 AND 160),
                    city TEXT NOT NULL CHECK(length(trim(city)) BETWEEN 1 AND 80),
                    district TEXT NOT NULL CHECK(length(trim(district)) BETWEEN 1 AND 80),
                    school_name TEXT NOT NULL CHECK(length(trim(school_name)) BETWEEN 1 AND 200),
                    agreement_version TEXT NOT NULL,
                    accepted INTEGER NOT NULL CHECK(accepted = 1),
                    status TEXT NOT NULL DEFAULT 'pending' CHECK(status = 'pending'),
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS registration_rate_limits (
                    source_hash TEXT PRIMARY KEY,
                    window_started_at REAL NOT NULL,
                    attempts INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS video_analysis_tasks (
                    task_id TEXT PRIMARY KEY,
                    channel_id TEXT NOT NULL REFERENCES video_upload_channels(channel_id),
                    account_id TEXT REFERENCES platform_accounts(account_id),
                    session_id TEXT NOT NULL,
                    uploader_name TEXT NOT NULL,
                    course_id TEXT NOT NULL DEFAULT '',
                    course_name TEXT NOT NULL,
                    subject_id TEXT NOT NULL DEFAULT '',
                    original_filename TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    byte_size INTEGER NOT NULL,
                    received_bytes INTEGER NOT NULL DEFAULT 0,
                    total_chunks INTEGER NOT NULL,
                    next_chunk_index INTEGER NOT NULL DEFAULT 0,
                    sha256 TEXT NOT NULL DEFAULT '',
                    upload_status TEXT NOT NULL DEFAULT 'created',
                    analysis_status TEXT NOT NULL DEFAULT 'waiting_upload',
                    result_path TEXT NOT NULL DEFAULT '',
                    retention_days INTEGER NOT NULL,
                    reminder_days INTEGER NOT NULL DEFAULT 15,
                    expires_at TEXT NOT NULL,
                    raw_media_deleted_at TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS simple_analysis_refresh_requests (
                    task_id TEXT PRIMARY KEY REFERENCES video_analysis_tasks(task_id) ON DELETE CASCADE,
                    analysis_version TEXT NOT NULL,
                    requested_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS data_security_acceptances (
                    acceptance_id TEXT PRIMARY KEY,
                    course_id TEXT NOT NULL,
                    course_name TEXT NOT NULL,
                    confirmed_by TEXT NOT NULL,
                    agreement_version TEXT NOT NULL,
                    allow_company_archive INTEGER NOT NULL DEFAULT 0,
                    authorized_scope_json TEXT NOT NULL,
                    accepted_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS long_term_resource_records (
                    resource_id TEXT PRIMARY KEY,
                    source_type TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    course_id TEXT NOT NULL,
                    subject_ref TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL,
                    deidentification_level TEXT NOT NULL,
                    authorization_id TEXT NOT NULL REFERENCES data_security_acceptances(acceptance_id),
                    status TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(source_type, source_id)
                );

                CREATE INDEX IF NOT EXISTS idx_documents_student
                    ON student_documents(student_id, status, created_at);
                CREATE INDEX IF NOT EXISTS idx_documents_expiry
                    ON student_documents(status, expires_at);
                CREATE INDEX IF NOT EXISTS idx_audit_created
                    ON audit_logs(created_at);
                CREATE INDEX IF NOT EXISTS idx_video_tasks_channel
                    ON video_analysis_tasks(channel_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_video_tasks_session
                    ON video_analysis_tasks(session_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_account_sessions_token
                    ON account_sessions(token_hash);
                CREATE INDEX IF NOT EXISTS idx_account_sessions_expiry
                    ON account_sessions(expires_at, revoked_at);
                CREATE INDEX IF NOT EXISTS idx_security_acceptance_course
                    ON data_security_acceptances(course_id, accepted_at);
                CREATE INDEX IF NOT EXISTS idx_resource_status
                    ON long_term_resource_records(status, created_at);
                """
            )
            policy_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(retention_policies)")
            }
            policy_reminder_added = "reminder_days" not in policy_columns
            if policy_reminder_added:
                connection.execute(
                    "ALTER TABLE retention_policies ADD COLUMN reminder_days INTEGER NOT NULL DEFAULT 15"
                )
            video_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(video_analysis_tasks)")
            }
            if "reminder_days" not in video_columns:
                connection.execute(
                    "ALTER TABLE video_analysis_tasks ADD COLUMN reminder_days INTEGER NOT NULL DEFAULT 15"
                )
            if "account_id" not in video_columns:
                connection.execute(
                    "ALTER TABLE video_analysis_tasks "
                    "ADD COLUMN account_id TEXT REFERENCES platform_accounts(account_id)"
                )
            if "raw_media_deleted_at" not in video_columns:
                connection.execute(
                    "ALTER TABLE video_analysis_tasks "
                    "ADD COLUMN raw_media_deleted_at TEXT NOT NULL DEFAULT ''"
                )
            if "school_context_json" not in video_columns:
                connection.execute(
                    "ALTER TABLE video_analysis_tasks "
                    "ADD COLUMN school_context_json TEXT NOT NULL DEFAULT '{}'"
                )
            for name, definition in {
                "processing_progress": "INTEGER NOT NULL DEFAULT 0",
                "processing_stage": "TEXT NOT NULL DEFAULT 'waiting_upload'",
                "processing_error_json": "TEXT NOT NULL DEFAULT '{}'",
                "attempt_count": "INTEGER NOT NULL DEFAULT 0",
                "processing_config_json": "TEXT NOT NULL DEFAULT '{}'",
                "processing_config_hash": "TEXT NOT NULL DEFAULT ''",
                "processing_key": "TEXT NOT NULL DEFAULT ''",
                "processing_claim_id": "TEXT NOT NULL DEFAULT ''",
                "processing_result_json": "TEXT NOT NULL DEFAULT '{}'",
            }.items():
                if name not in video_columns:
                    connection.execute(f"ALTER TABLE video_analysis_tasks ADD COLUMN {name} {definition}")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_video_analysis_queue ON video_analysis_tasks(analysis_status, created_at)"
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_video_tasks_account_course
                ON video_analysis_tasks(account_id, course_id, created_at)
                """
            )
            for data_type, policy in DEFAULT_POLICIES.items():
                connection.execute(
                    """
                    INSERT OR IGNORE INTO retention_policies
                    (data_type, label, storage_backend, retention_days, reminder_days,
                     auto_delete, downloadable, updated_at)
                    VALUES (?, ?, 'local_controlled', ?, ?, ?, ?, ?)
                    """,
                    (
                        data_type,
                        policy["label"],
                        policy["retention_days"],
                        policy["reminder_days"],
                        int(policy["auto_delete"]),
                        int(policy["downloadable"]),
                        _iso(),
                    ),
                )
            if policy_reminder_added:
                for data_type, policy in DEFAULT_POLICIES.items():
                    connection.execute(
                        "UPDATE retention_policies SET reminder_days = ? WHERE data_type = ?",
                        (policy["reminder_days"], data_type),
                    )
            now = _iso()
            for channel_no in range(1, 5):
                connection.execute(
                    """
                    INSERT OR IGNORE INTO video_upload_channels
                    (channel_id, channel_no, channel_name, owner_label, status, created_at, updated_at)
                    VALUES (?, ?, ?, '', 'active', ?, ?)
                    """,
                    (f"channel_{channel_no}", channel_no, f"上传通道 {channel_no}", now, now),
                )
            self._seed_initial_accounts(connection)
            connection.execute("PRAGMA user_version = 6")

    @staticmethod
    def _seed_initial_accounts(connection: sqlite3.Connection) -> None:
        now = _iso()
        upload_limit = _configured_course_upload_limit()
        seeds = [
            (f"school_uploader_{index:02d}", "school_uploader", f"channel_{index}")
            for index in range(1, 5)
        ]
        seeds.append(("company_admin", "company_admin", None))
        for username, role, channel_id in seeds:
            # Renaming the pilot administrator must not recreate the old login.
            if role == "company_admin" and connection.execute(
                "SELECT 1 FROM platform_accounts WHERE role = 'company_admin'"
            ).fetchone() is not None:
                continue
            if connection.execute(
                "SELECT 1 FROM platform_accounts WHERE username = ?", (username,)
            ).fetchone() is not None:
                continue
            salt = secrets.token_bytes(PASSWORD_SALT_BYTES)
            connection.execute(
                """
                INSERT INTO platform_accounts
                (account_id, username, password_hash, password_salt, password_iterations,
                 role, bound_channel_id, course_upload_limit, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
                """,
                (
                    uuid4().hex,
                    username,
                    _password_hash(_initial_password(username), salt),
                    salt.hex(),
                    PASSWORD_HASH_ITERATIONS,
                    role,
                    channel_id,
                    upload_limit,
                    now,
                    now,
                ),
            )

    def ensure_students(self, students: list[dict[str, Any]]) -> None:
        with self._connect() as connection:
            for student in students:
                student_id = str(student.get("student_id", "")).strip()
                display_name = str(student.get("display_name", student_id)).strip()
                if not student_id:
                    continue
                now = _iso()
                connection.execute(
                    """
                    INSERT INTO students(student_id, display_name, created_at, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(student_id) DO UPDATE SET
                        display_name = excluded.display_name,
                        updated_at = excluded.updated_at
                    """,
                    (student_id, display_name, now, now),
                )

    def authenticate_account(self, username: str, password: str) -> dict[str, Any]:
        normalized_username = str(username or "").strip()
        normalized_username = PILOT_ACCOUNT_ALIASES.get(normalized_username, normalized_username)
        supplied_password = str(password or "")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM platform_accounts WHERE username = ?",
                (normalized_username,),
            ).fetchone()
            authenticated = False
            reason = "account_not_found"
            if row is not None:
                account = dict(row)
                if account["status"] != "active":
                    reason = "account_inactive"
                else:
                    try:
                        salt = bytes.fromhex(account["password_salt"])
                        candidate = _password_hash(
                            supplied_password,
                            salt,
                            int(account["password_iterations"]),
                        )
                        authenticated = hmac.compare_digest(account["password_hash"], candidate)
                    except (TypeError, ValueError):
                        authenticated = False
                    reason = "success" if authenticated else "wrong_password"
            object_id = row["account_id"] if row is not None else normalized_username[:120]
            self._audit(
                connection,
                normalized_username[:120] or "anonymous",
                "login",
                "platform_account",
                object_id,
                {"success": authenticated, "reason": reason},
            )
            if not authenticated:
                connection.commit()
                raise ValueError("账号或密码错误，或账号不可用")
            return self._public_account(dict(row))

    @classmethod
    def set_seeded_pilot_passwords(
        cls, db_path: Path, passwords: dict[str, str]
    ) -> dict[str, Any]:
        """Explicit local maintenance only; never initialize a DB or create accounts.

        Supply all five alias keys with distinct passwords. No HTTP route calls this
        method, and neither its result nor its audit records include credentials.
        """
        if not isinstance(passwords, dict) or set(passwords) != set(PILOT_ACCOUNT_ALIASES):
            raise ValueError("请仅为 t1、t2、t3、t4 和 admin 五个账号提供密码")
        if any(
            not isinstance(value, str) or not 8 <= len(value) <= 128
            or value != value.strip() or any(ord(char) < 32 for char in value)
            for value in passwords.values()
        ):
            raise ValueError("试点密码须为 8 至 128 个字符，且不能包含首尾空白或控制字符")
        if len(set(passwords.values())) != len(PILOT_ACCOUNT_ALIASES):
            raise ValueError("五个账号须使用不同密码")
        connection = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=rw", uri=True, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                accounts = []
                for alias, username in PILOT_ACCOUNT_ALIASES.items():
                    row = connection.execute(
                        "SELECT * FROM platform_accounts WHERE username = ?", (username,)
                    ).fetchone()
                    expected_role = "company_admin" if alias == "admin" else "school_uploader"
                    expected_channel = None if alias == "admin" else f"channel_{alias[1:]}"
                    if row is None or row["role"] != expected_role or row["bound_channel_id"] != expected_channel:
                        raise ValueError("须已存在全部五个种子账号，且角色和通道绑定未变更")
                    accounts.append((alias, row))
                now = _iso()
                for alias, row in accounts:
                    salt = secrets.token_bytes(PASSWORD_SALT_BYTES)
                    connection.execute(
                        """UPDATE platform_accounts SET password_hash = ?, password_salt = ?,
                           password_iterations = ?, updated_at = ? WHERE account_id = ?""",
                        (_password_hash(passwords[alias], salt), salt.hex(),
                         PASSWORD_HASH_ITERATIONS, now, row["account_id"]),
                    )
                    connection.execute(
                        "UPDATE account_sessions SET revoked_at = ? WHERE account_id = ? AND revoked_at = ''",
                        (now, row["account_id"]),
                    )
                    cls._audit(connection, "local_maintenance", "pilot_password_set",
                               "platform_account", row["account_id"], {"sessions_revoked": True})
            return {"updated_accounts": [row["username"] for _, row in accounts]}
        finally:
            connection.close()

    @staticmethod
    def _school_context_for_account(connection: sqlite3.Connection, account_id: str) -> dict[str, str]:
        row = connection.execute(
            "SELECT city, district, school_name FROM school_contexts WHERE account_id = ?",
            (account_id,),
        ).fetchone()
        return dict(row) if row is not None else {key: "" for key in SCHOOL_CONTEXT_LIMITS}

    def account_school_context(self, session_token: str) -> dict[str, Any]:
        from .school_directory import school_directory
        account = self.account_from_session(session_token)
        if account["role"] != "school_uploader":
            raise ValueError("仅学校上传账号可查看学校信息")
        with self._connect() as connection:
            context = self._school_context_for_account(connection, account["account_id"])
            metadata = connection.execute("SELECT details_json FROM school_selection_metadata WHERE account_id=?", (account["account_id"],)).fetchone()
            has_students = self._has_scoped_students(connection, account["account_id"])
        # Organization metadata only, not a tenant identifier or permission grant.
        return {"context": context, "options": [dict(context)] if context["school_name"] else [],
                "details": json.loads(metadata[0]) if metadata else {}, "directory": school_directory(),
                "selection_enabled": True, "context_change_allowed": not has_students}

    @staticmethod
    def _has_scoped_students(connection, account_id):
        if not connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='demo2_identity_students'").fetchone():
            return False
        return connection.execute("SELECT 1 FROM demo2_identity_students WHERE owner_account_id=? LIMIT 1", (account_id,)).fetchone() is not None

    def save_account_school_context(self, session_token: str, payload: dict[str, Any]) -> dict[str, Any]:
        account = self.account_from_session(session_token)
        if account["role"] != "school_uploader":
            raise ValueError("仅学校上传账号可保存学校信息")
        if not isinstance(payload, dict):
            raise ValueError("请仅提交城市、区县和学校名称")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = self._school_context_for_account(connection, account["account_id"])
            has_students = self._has_scoped_students(connection, account["account_id"])
            previous = connection.execute("SELECT details_json FROM school_selection_metadata WHERE account_id=?", (account["account_id"],)).fetchone()
            if "selection_source" in payload:
                from .school_directory import prepare_school_selection
                selection = prepare_school_selection(payload, current_context=current, has_existing_students=has_students)
                context, details = selection["context"], selection["details"]
                if details["selection_source"] == "existing" and previous:
                    details = json.loads(previous[0])
            else:
                if set(payload) != set(SCHOOL_CONTEXT_LIMITS):
                    raise ValueError("请仅提交城市、区县和学校名称")
                context = _bounded_fields(payload, SCHOOL_CONTEXT_LIMITS)
                if current != context and has_students:
                    raise ValueError("该账号已有学生名册，更换学校需管理员迁移；历史任务和名册不会自动改名")
                details = json.loads(previous[0]) if previous and current == context else {"selection_source": "legacy", "source_status": "pending"}
            now = _iso()
            connection.execute(
                """INSERT INTO school_contexts
                   (account_id, city, district, school_name, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(account_id) DO UPDATE SET city = excluded.city,
                   district = excluded.district, school_name = excluded.school_name,
                   updated_at = excluded.updated_at""",
                (account["account_id"], context["city"], context["district"], context["school_name"], now, now),
            )
            connection.execute("""INSERT INTO school_selection_metadata(account_id,details_json,updated_at) VALUES (?,?,?)
                ON CONFLICT(account_id) DO UPDATE SET details_json=excluded.details_json,updated_at=excluded.updated_at""",
                (account["account_id"], json.dumps(details, ensure_ascii=False), now))
            self._audit(connection, account["username"], "school_context_saved",
                        "school_context", account["account_id"], {"organization_metadata_only": True})
        return self.account_school_context(session_token)

    def check_registration_rate_limit(self, client_address: str) -> None:
        """Consume a bounded attempt before reading a public registration body.

        Use the socket peer, never a caller-supplied forwarding header. Limits are
        shared across processes/restarts; old buckets are removed on each attempt.
        """
        now = _now().timestamp()
        source_hash = _token_hash("demo2-registration:" + client_address)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "DELETE FROM registration_rate_limits WHERE window_started_at <= ?",
                (now - REGISTRATION_WINDOW_SECONDS,),
            )
            total = connection.execute(
                "SELECT COALESCE(SUM(attempts), 0) FROM registration_rate_limits"
            ).fetchone()[0]
            row = connection.execute(
                "SELECT attempts FROM registration_rate_limits WHERE source_hash = ?", (source_hash,)
            ).fetchone()
            if total >= REGISTRATION_GLOBAL_LIMIT or (row and row["attempts"] >= REGISTRATION_PER_SOURCE_LIMIT):
                connection.commit()
                raise RegistrationRateLimitError("申请提交过于频繁，请一小时后重试")
            connection.execute(
                """INSERT INTO registration_rate_limits(source_hash, window_started_at, attempts)
                   VALUES (?, ?, 1) ON CONFLICT(source_hash) DO UPDATE SET attempts = attempts + 1""",
                (source_hash, now),
            )

    def submit_registration_application(self, payload: dict[str, Any]) -> dict[str, Any]:
        limits = {"name": 80, "contact": 160, **SCHOOL_CONTEXT_LIMITS}
        try:
            if not isinstance(payload, dict) or set(payload) != set(limits) | {"agreement_version", "accepted"}:
                raise ValueError("申请字段不完整或包含多余内容，请刷新后重试")
            if payload.get("accepted") is not True:
                raise ValueError("请阅读并明确同意申请信息处理说明")
            if payload.get("agreement_version") != REGISTRATION_AGREEMENT_VERSION:
                raise ValueError("申请说明版本已更新，请刷新页面后重新确认")
            fields = _bounded_fields(payload, limits)
            if not _valid_registration_contact(fields["contact"]):
                raise ValueError("请填写有效的手机号或邮箱")
        except ValueError:
            with self._connect() as connection:
                self._audit(connection, "anonymous", "registration_rejected",
                            "registration_request", "", {"reason": "invalid_application"})
            raise
        request = {"request_id": uuid4().hex, "status": "pending", "created_at": _iso()}
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO registration_requests
                   (request_id, name, contact, city, district, school_name,
                    agreement_version, accepted, status, created_at)
                   VALUES (:request_id, :name, :contact, :city, :district, :school_name,
                           :agreement_version, 1, 'pending', :created_at)""",
                {**fields, **request, "agreement_version": REGISTRATION_AGREEMENT_VERSION},
            )
            self._audit(connection, "anonymous", "registration_submitted", "registration_request",
                        request["request_id"], {"status": "pending", "agreement_version": REGISTRATION_AGREEMENT_VERSION})
        return request

    def create_account_session(
        self,
        account_id: str | dict[str, Any],
        *,
        expires_hours: float = DEFAULT_SESSION_HOURS,
        ttl_hours: float | None = None,
    ) -> dict[str, Any]:
        account_key = str(
            account_id.get("account_id", account_id.get("username", ""))
            if isinstance(account_id, dict)
            else account_id
        ).strip()
        duration_hours = float(ttl_hours if ttl_hours is not None else expires_hours)
        if not 0 < duration_hours <= 24:
            raise ValueError("会话有效期必须大于 0 且不超过 24 小时")
        token = secrets.token_urlsafe(SESSION_TOKEN_BYTES)
        created_at = _now()
        session = {
            "session_id": uuid4().hex,
            "token_hash": _token_hash(token),
            "created_at": _iso(created_at),
            "expires_at": _iso(created_at + timedelta(hours=duration_hours)),
            "last_seen_at": _iso(created_at),
        }
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM platform_accounts
                WHERE (account_id = ? OR username = ?) AND status = 'active'
                """,
                (account_key, account_key),
            ).fetchone()
            if row is None:
                raise ValueError("账号不存在或已停用")
            session["account_id"] = row["account_id"]
            connection.execute(
                """
                INSERT INTO account_sessions
                (session_id, account_id, token_hash, expires_at, revoked_at,
                 created_at, last_seen_at)
                VALUES (:session_id, :account_id, :token_hash, :expires_at, '',
                        :created_at, :last_seen_at)
                """,
                session,
            )
            self._audit(
                connection,
                row["username"],
                "session_create",
                "account_session",
                session["session_id"],
                {"account_id": row["account_id"], "expires_at": session["expires_at"]},
            )
        return {
            "session_id": session["session_id"],
            "token": token,
            "expires_at": session["expires_at"],
            "account": self._public_account(dict(row)),
        }

    def account_from_session(self, session_token: str) -> dict[str, Any]:
        token_digest = _token_hash(str(session_token or ""))
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT s.session_id, s.expires_at, s.revoked_at,
                       a.*
                FROM account_sessions AS s
                JOIN platform_accounts AS a ON a.account_id = s.account_id
                WHERE s.token_hash = ?
                """,
                (token_digest,),
            ).fetchone()
            if row is None or row["revoked_at"] or row["status"] != "active":
                raise ValueError("会话无效或已注销")
            try:
                expired = datetime.fromisoformat(row["expires_at"]) <= _now()
            except ValueError:
                expired = True
            if expired:
                expired_at = _iso()
                connection.execute(
                    "UPDATE account_sessions SET revoked_at = ? WHERE session_id = ?",
                    (expired_at, row["session_id"]),
                )
                self._audit(
                    connection,
                    row["username"],
                    "session_expired",
                    "account_session",
                    row["session_id"],
                    {"account_id": row["account_id"], "expires_at": row["expires_at"]},
                )
                connection.commit()
                raise ValueError("会话已过期，请重新登录")
            connection.execute(
                "UPDATE account_sessions SET last_seen_at = ? WHERE session_id = ?",
                (_iso(), row["session_id"]),
            )
            account = self._public_account(dict(row))
            account["session_id"] = row["session_id"]
            account["session_expires_at"] = row["expires_at"]
            return account

    def revoke_account_session(self, session_token: str) -> dict[str, Any]:
        token_digest = _token_hash(str(session_token or ""))
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT s.session_id, s.account_id, s.revoked_at, a.username
                FROM account_sessions AS s
                JOIN platform_accounts AS a ON a.account_id = s.account_id
                WHERE s.token_hash = ?
                """,
                (token_digest,),
            ).fetchone()
            if row is None:
                raise ValueError("会话不存在")
            if not row["revoked_at"]:
                connection.execute(
                    "UPDATE account_sessions SET revoked_at = ? WHERE session_id = ?",
                    (_iso(), row["session_id"]),
                )
                self._audit(
                    connection,
                    row["username"],
                    "session_revoke",
                    "account_session",
                    row["session_id"],
                    {"account_id": row["account_id"]},
                )
        return {"session_id": row["session_id"], "revoked": True}

    def account_upload_workspace(self, session_token: str, course_id: str) -> dict[str, Any]:
        account = self.account_from_session(session_token)
        normalized_course_id = str(course_id or "").strip()
        if account["role"] != "school_uploader":
            raise ValueError("该账号没有学校视频上传权限")
        if not normalized_course_id:
            raise ValueError("course_id 不能为空")
        if not str(account.get("bound_channel_id") or "").strip():
            raise ValueError("该账号尚未绑定视频上传通道")
        with self._connect() as connection:
            preferred_channel_id = str(account.get("bound_channel_id") or "").strip()
            # Keep the account's channel visible when an administrator pauses
            # it.  A paused channel must be shown as paused so the teacher can
            # understand why a new upload is blocked and resume later without
            # being silently switched to another channel.
            channels = connection.execute(
                "SELECT * FROM video_upload_channels "
                "WHERE status = 'active' OR channel_id = ? ORDER BY channel_no",
                (preferred_channel_id,),
            ).fetchall()
            # The selected channel is always the bound one, never the first
            # other active channel, so a paused binding is not silently replaced.
            selected_channel = next(
                (row for row in channels if row["channel_id"] == preferred_channel_id), None
            )
            students = connection.execute(
                """
                SELECT student_id, display_name FROM students
                WHERE status = 'active' ORDER BY student_id
                """
            ).fetchall()
            security_acceptance = connection.execute(
                """
                SELECT * FROM data_security_acceptances
                WHERE course_id = ? ORDER BY accepted_at DESC, rowid DESC LIMIT 1
                """,
                (normalized_course_id,),
            ).fetchone()
            tasks = connection.execute(
                """
                SELECT * FROM video_analysis_tasks
                WHERE account_id = ? AND course_id = ?
                ORDER BY created_at DESC
                """,
                (account["account_id"], normalized_course_id),
            ).fetchall()
        used_slots = sum(
            row["upload_status"] not in {"cancelled", "expired"} for row in tasks
        )
        max_slots = int(account["course_upload_limit"])
        quota = {
            "course_id": normalized_course_id,
            "used_slots": used_slots,
            "max_slots": max_slots,
            "remaining_slots": max(0, max_slots - used_slots),
        }
        channel_status = str(selected_channel["status"]) if selected_channel else "missing"
        if channel_status == "active":
            upload_block = None
        elif channel_status == "missing":
            upload_block = {"code": "channel_missing",
                            "message": "账号绑定的上传通道不存在，请联系管理员核对通道配置"}
        else:
            upload_block = {"code": "channel_paused",
                            "message": "账号绑定的上传通道已暂停，暂不能新建上传；请联系管理员恢复通道，系统不会自动切换到其他通道"}
        return {
            "account": account,
            "channel": dict(selected_channel) if selected_channel else None,
            "channels": [dict(row) for row in channels],
            "selected_channel_id": selected_channel["channel_id"] if selected_channel else "",
            "bound_channel_id": preferred_channel_id,
            "channel_status": channel_status,
            "upload_blocked": upload_block,
            "students": [dict(row) for row in students],
            "security_acceptance": (
                self._public_acceptance(dict(security_acceptance))
                if security_acceptance is not None
                else None
            ),
            **quota,
            "quota": quota,
            "max_video_bytes": MAX_NEW_VIDEO_BYTES,
            "tasks": [self._public_video_task(dict(row)) for row in tasks],
        }

    def admin_platform_summary(self, session_token: str, *, upload_page: int = 1) -> dict[str, Any]:
        admin = self.account_from_session(session_token)
        if admin["role"] != "company_admin":
            raise ValueError("仅 company_admin 可查看平台汇总")
        if type(upload_page) is not int or not 1 <= upload_page <= 1_000_000:
            raise ValueError("视频记录页码须为正整数")
        with self._connect() as connection:
            uploader_rows = connection.execute(
                """
                SELECT * FROM platform_accounts
                WHERE role = 'school_uploader' ORDER BY bound_channel_id
                """
            ).fetchall()
            channel_rows = connection.execute(
                """
                SELECT c.*, a.account_id, a.username, a.status AS account_status,
                       COUNT(t.task_id) AS task_count
                FROM video_upload_channels AS c
                LEFT JOIN platform_accounts AS a ON a.bound_channel_id = c.channel_id
                LEFT JOIN video_analysis_tasks AS t
                  ON t.channel_id = c.channel_id
                 AND t.upload_status NOT IN ('cancelled', 'expired')
                GROUP BY c.channel_id, a.account_id
                ORDER BY c.channel_no
                """
            ).fetchall()
            usage_rows = connection.execute(
                """
                SELECT t.account_id, a.username, t.course_id,
                       a.course_upload_limit AS max_slots, COUNT(*) AS used_slots
                FROM video_analysis_tasks AS t
                JOIN platform_accounts AS a ON a.account_id = t.account_id
                WHERE t.account_id IS NOT NULL
                  AND t.upload_status NOT IN ('cancelled', 'expired')
                GROUP BY t.account_id, a.username, t.course_id, a.course_upload_limit
                ORDER BY t.course_id, a.username
                """
            ).fetchall()
            upload_status = {
                row["upload_status"]: row["count"]
                for row in connection.execute(
                    "SELECT upload_status, COUNT(*) AS count FROM video_analysis_tasks GROUP BY upload_status"
                )
            }
            analysis_status = {
                row["analysis_status"]: row["count"]
                for row in connection.execute(
                    "SELECT analysis_status, COUNT(*) AS count FROM video_analysis_tasks GROUP BY analysis_status"
                )
            }
            raw_policy = connection.execute(
                "SELECT * FROM retention_policies WHERE data_type = 'raw_media'"
            ).fetchone()
            completed_tasks = [
                self._public_video_task(dict(row))
                for row in connection.execute(
                    "SELECT * FROM video_analysis_tasks WHERE upload_status = 'completed'"
                )
            ]
            upload_total = sum(upload_status.values())
            upload_page_size = 20
            upload_total_pages = max(1, (upload_total + upload_page_size - 1) // upload_page_size)
            upload_page = min(upload_page, upload_total_pages)
            recent_uploads = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT t.task_id,
                           COALESCE(a.username, t.uploader_name, 'legacy_upload') AS username,
                           t.channel_id, t.course_id, t.course_name,
                           t.original_filename, t.byte_size, t.subject_id,
                           t.upload_status, t.analysis_status,
                           t.analysis_status AS status,
                           t.created_at AS time, t.created_at, t.updated_at
                    FROM video_analysis_tasks AS t
                    LEFT JOIN platform_accounts AS a ON a.account_id = t.account_id
                    ORDER BY t.created_at DESC, t.rowid DESC LIMIT ? OFFSET ?
                    """,
                    (upload_page_size, (upload_page - 1) * upload_page_size),
                )
            ]
            recent_security_acceptances = [
                self._public_acceptance(dict(row))
                for row in connection.execute(
                    """
                    SELECT * FROM data_security_acceptances
                    ORDER BY accepted_at DESC, rowid DESC LIMIT 10
                    """
                )
            ]
            registration_requests = [
                {**dict(row), "accepted": bool(row["accepted"])}
                for row in connection.execute(
                    "SELECT * FROM registration_requests ORDER BY created_at DESC, rowid DESC LIMIT 100"
                )
            ]
            school_contexts = [
                {**dict(row), "selection_details": json.loads(row["details_json"] or "{}")} for row in connection.execute(
                    """SELECT c.*, a.username, m.details_json FROM school_contexts AS c
                       JOIN platform_accounts AS a ON a.account_id = c.account_id
                       LEFT JOIN school_selection_metadata AS m ON m.account_id=c.account_id
                       ORDER BY a.username"""
                )
            ]
            self._audit(
                connection,
                admin["username"],
                "view_summary",
                "admin_platform",
                "all_channels",
                {"channel_count": len(channel_rows)},
            )
        course_usage = []
        for row in usage_rows:
            item = dict(row)
            item["remaining_slots"] = max(0, item["max_slots"] - item["used_slots"])
            course_usage.append(item)
        due_soon = sum(task["retention_state"] == "due_soon" for task in completed_tasks)
        expired = sum(task["retention_state"] == "expired" for task in completed_tasks)
        storage = self.storage_summary()
        public_storage = {
            section: {
                key: value
                for key, value in storage[section].items()
                if key not in {"location", "file_path", "result_path"}
            }
            for section in (
                "database",
                "document_storage",
                "report_storage",
                "video_task_storage",
            )
        }
        return {
            "admin_account": admin,
            "upload_accounts": [self._public_account(dict(row)) for row in uploader_rows],
            "channels": [dict(row) for row in channel_rows],
            "course_usage": course_usage,
            "recent_uploads": recent_uploads,
            "upload_pagination": {"page": upload_page, "page_size": upload_page_size,
                                  "total": upload_total, "total_pages": upload_total_pages},
            "recent_security_acceptances": recent_security_acceptances,
            "registration_requests": registration_requests,
            "school_contexts": school_contexts,
            "task_status": {
                "total": sum(upload_status.values()),
                "by_upload_status": upload_status,
                "by_analysis_status": analysis_status,
            },
            "storage": public_storage,
            "retention": {
                "raw_media_retention_days": int(raw_policy["retention_days"]),
                "expiry_reminder_days": int(raw_policy["reminder_days"]),
                "auto_delete": bool(raw_policy["auto_delete"]),
                "due_soon_count": due_soon,
                "expired_count": expired,
            },
        }

    ADMIN_TASK_PAGE_SIZE = 20

    def admin_task_query(
        self, session_token: str, *, query: str = "", analysis_status: str = "", page: int = 1,
    ) -> dict[str, Any]:
        """Company-admin task lookup by task id, course or file name fragment.

        Only task metadata and processing state are returned; classroom
        results, frames and student data stay behind the per-task routes.
        """
        admin = self.account_from_session(session_token)
        if admin["role"] != "company_admin":
            raise ValueError("仅 company_admin 可查询平台任务")
        if not isinstance(query, str) or len(query) > 80:
            raise ValueError("任务查询关键词最多 80 个字符")
        query = query.strip()
        if any(ord(char) < 32 for char in query):
            raise ValueError("任务查询关键词包含不支持的字符")
        if analysis_status and not re.fullmatch(r"[a-z_]{1,40}", analysis_status):
            raise ValueError("处理状态筛选值无效")
        if type(page) is not int or not 1 <= page <= 1_000_000:
            raise ValueError("任务查询页码须为正整数")
        clauses: list[str] = []
        params: list[Any] = []
        if query:
            pattern = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            clauses.append(
                "(t.task_id = ? OR t.task_id LIKE ? ESCAPE '\\' OR t.course_id LIKE ? ESCAPE '\\'"
                " OR t.course_name LIKE ? ESCAPE '\\' OR t.original_filename LIKE ? ESCAPE '\\'"
                " OR a.username LIKE ? ESCAPE '\\')"
            )
            params.extend([query, pattern, pattern, pattern, pattern, pattern])
        if analysis_status:
            clauses.append("t.analysis_status = ?")
            params.append(analysis_status)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        page_size = self.ADMIN_TASK_PAGE_SIZE
        with self._connect() as connection:
            total = connection.execute(
                "SELECT COUNT(*) FROM video_analysis_tasks AS t "
                "LEFT JOIN platform_accounts AS a ON a.account_id = t.account_id" + where,
                params,
            ).fetchone()[0]
            total_pages = max(1, (total + page_size - 1) // page_size)
            page = min(page, total_pages)
            rows = connection.execute(
                "SELECT t.*, COALESCE(a.username, t.uploader_name, 'legacy_upload') AS owner_username "
                "FROM video_analysis_tasks AS t "
                "LEFT JOIN platform_accounts AS a ON a.account_id = t.account_id" + where
                + " ORDER BY t.created_at DESC, t.rowid DESC LIMIT ? OFFSET ?",
                [*params, page_size, (page - 1) * page_size],
            ).fetchall()
            tasks = []
            for row in rows:
                public = self._public_video_task(dict(row))
                media_available = (
                    public.get("upload_status") == "completed"
                    and public.get("retention_state") not in {"deleted", "expired"}
                )
                tasks.append({
                    "task_id": public.get("task_id", ""),
                    "video_task_id": public.get("task_id", ""),
                    "account_id": public.get("account_id") or "",
                    "username": row["owner_username"],
                    "channel_id": public.get("channel_id") or "",
                    "course_id": public.get("course_id") or "",
                    "course_name": public.get("course_name") or "",
                    "original_filename": public.get("original_filename") or "",
                    "byte_size": int(public.get("byte_size") or 0),
                    "upload_status": public.get("upload_status") or "",
                    "analysis_status": public.get("analysis_status") or "",
                    "processing_stage": public.get("processing_stage") or "",
                    "processing_progress": int(public.get("processing_progress") or 0),
                    "progress_percent": int(public.get("progress_percent") or 0),
                    "retention_state": public.get("retention_state") or "",
                    "days_remaining": int(public.get("days_remaining") or 0),
                    "media_available": media_available,
                    "result_available": public.get("analysis_status") in READY_VIDEO_ANALYSIS_STATUSES,
                    "created_at": public.get("created_at") or "",
                    "updated_at": public.get("updated_at") or "",
                })
            self._audit(
                connection, admin["username"], "admin_task_query", "admin_platform", "video_tasks",
                {"has_query": bool(query), "analysis_status": analysis_status, "page": page, "total": total},
            )
        return {
            "tasks": tasks,
            "pagination": {"page": page, "page_size": page_size, "total": total, "total_pages": total_pages},
        }

    def student_record(self, student_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            student = connection.execute(
                "SELECT * FROM students WHERE student_id = ?", (student_id,)
            ).fetchone()
            if student is None:
                raise ValueError("未找到学生档案")
            documents = connection.execute(
                """
                SELECT * FROM student_documents
                WHERE student_id = ? AND status = 'active'
                ORDER BY created_at DESC
                """,
                (student_id,),
            ).fetchall()
            profile = connection.execute(
                "SELECT * FROM student_support_profiles WHERE student_id = ?", (student_id,)
            ).fetchone()
        return {
            "student": dict(student),
            "documents": [self._public_document(dict(row)) for row in documents],
            "support_profile": dict(profile) if profile else {},
            "document_types": DOCUMENT_TYPE_LABELS,
            "upload_limit_bytes": MAX_DOCUMENT_BYTES,
            "boundary": "资料仅用于教育支持与安全约束，不由系统推断医学诊断。",
        }

    def save_document(self, payload: dict[str, Any], *, actor: str = "local_teacher") -> dict[str, Any]:
        student_id = str(payload.get("student_id", "")).strip()
        document_type = str(payload.get("document_type", "")).strip()
        filename = _safe_filename(str(payload.get("filename", "")))
        suffix = Path(filename).suffix.lower()
        if document_type not in DOCUMENT_TYPE_LABELS:
            raise ValueError("请选择有效的资料类型")
        if suffix not in ALLOWED_DOCUMENT_EXTENSIONS:
            raise ValueError("仅支持 DOCX、PDF、Excel、CSV、JSON、TXT 和常见图片")
        data = _decode_document(str(payload.get("content_base64", "")))
        with self._connect() as connection:
            if connection.execute(
                "SELECT 1 FROM students WHERE student_id = ?", (student_id,)
            ).fetchone() is None:
                raise ValueError("未找到学生档案")
            retention_days = int(
                connection.execute(
                    "SELECT retention_days FROM retention_policies WHERE data_type = 'student_document'"
                ).fetchone()[0]
            )

        document_id = uuid4().hex
        student_dir = self.upload_dir / _safe_filename(student_id)
        student_dir.mkdir(parents=True, exist_ok=True)
        stored_filename = f"{document_id[:12]}_{filename}"
        file_path = student_dir / stored_filename
        file_path.write_bytes(data)
        parse_status, preview = _extract_preview(file_path)
        created_at = _now()
        expires_at = created_at + timedelta(days=retention_days)
        mime_type = str(payload.get("mime_type", "")).strip() or mimetypes.guess_type(filename)[0] or "application/octet-stream"
        row = {
            "document_id": document_id,
            "student_id": student_id,
            "document_type": document_type,
            "original_filename": filename,
            "stored_filename": stored_filename,
            "file_path": str(file_path.resolve()),
            "mime_type": mime_type,
            "byte_size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "source_org": str(payload.get("source_org", "")).strip(),
            "document_date": str(payload.get("document_date", "")).strip(),
            "note": str(payload.get("note", "")).strip(),
            "parse_status": parse_status,
            "extracted_preview": preview,
            "retention_days": retention_days,
            "expires_at": _iso(expires_at),
            "status": "active",
            "created_at": _iso(created_at),
            "updated_at": _iso(created_at),
        }
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO student_documents
                    (document_id, student_id, document_type, original_filename, stored_filename,
                     file_path, mime_type, byte_size, sha256, source_org, document_date, note,
                     parse_status, extracted_preview, retention_days, expires_at, status,
                     created_at, updated_at)
                    VALUES (:document_id, :student_id, :document_type, :original_filename,
                            :stored_filename, :file_path, :mime_type, :byte_size, :sha256,
                            :source_org, :document_date, :note, :parse_status, :extracted_preview,
                            :retention_days, :expires_at, :status, :created_at, :updated_at)
                    """,
                    row,
                )
                self._audit(connection, actor, "upload", "student_document", document_id, {
                    "student_id": student_id,
                    "document_type": document_type,
                    "filename": filename,
                    "byte_size": len(data),
                })
        except Exception:
            file_path.unlink(missing_ok=True)
            raise
        return self._public_document(row)

    def save_support_profile(self, payload: dict[str, Any], *, actor: str = "local_teacher") -> dict[str, Any]:
        student_id = str(payload.get("student_id", "")).strip()
        values = {
            "student_id": student_id,
            "professional_conclusion": str(payload.get("professional_conclusion", "")).strip(),
            "support_summary": str(payload.get("support_summary", "")).strip(),
            "effective_support": str(payload.get("effective_support", "")).strip(),
            "safety_constraints": str(payload.get("safety_constraints", "")).strip(),
            "updated_by": str(payload.get("updated_by", actor)).strip() or actor,
            "updated_at": _iso(),
        }
        with self._connect() as connection:
            if connection.execute(
                "SELECT 1 FROM students WHERE student_id = ?", (student_id,)
            ).fetchone() is None:
                raise ValueError("未找到学生档案")
            connection.execute(
                """
                INSERT INTO student_support_profiles
                (student_id, professional_conclusion, support_summary, effective_support,
                 safety_constraints, updated_by, updated_at)
                VALUES (:student_id, :professional_conclusion, :support_summary,
                        :effective_support, :safety_constraints, :updated_by, :updated_at)
                ON CONFLICT(student_id) DO UPDATE SET
                    professional_conclusion = excluded.professional_conclusion,
                    support_summary = excluded.support_summary,
                    effective_support = excluded.effective_support,
                    safety_constraints = excluded.safety_constraints,
                    updated_by = excluded.updated_by,
                    updated_at = excluded.updated_at
                """,
                values,
            )
            self._audit(connection, actor, "update", "student_support_profile", student_id, {
                "updated_by": values["updated_by"],
            })
        return values

    def delete_document(self, document_id: str, *, actor: str = "local_admin") -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM student_documents WHERE document_id = ? AND status = 'active'",
                (document_id,),
            ).fetchone()
            if row is None:
                raise ValueError("未找到可删除的资料")
            file_path = Path(row["file_path"])
            file_path.unlink(missing_ok=True)
            connection.execute(
                "UPDATE student_documents SET status = 'deleted', updated_at = ? WHERE document_id = ?",
                (_iso(), document_id),
            )
            self._audit(connection, actor, "delete", "student_document", document_id, {
                "student_id": row["student_id"],
                "filename": row["original_filename"],
            })
        return {"document_id": document_id, "deleted": True}

    def document_for_download(self, document_id: str) -> tuple[Path, dict[str, Any]]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM student_documents WHERE document_id = ? AND status = 'active'",
                (document_id,),
            ).fetchone()
        if row is None:
            raise ValueError("未找到资料")
        path = Path(row["file_path"]).resolve()
        root = self.upload_dir.resolve()
        if root not in path.parents or not path.is_file():
            raise ValueError("资料文件不存在或路径无效")
        return path, self._public_document(dict(row))

    def video_channels(self) -> dict[str, Any]:
        with self._connect() as connection:
            channels = []
            for channel in connection.execute(
                "SELECT * FROM video_upload_channels WHERE status = 'active' ORDER BY channel_no"
            ):
                tasks = connection.execute(
                    """
                    SELECT * FROM video_analysis_tasks
                    WHERE channel_id = ? ORDER BY created_at DESC LIMIT 5
                    """,
                    (channel["channel_id"],),
                ).fetchall()
                public_tasks = []
                for task in tasks:
                    public_task = self._public_video_task(dict(task))
                    archive = connection.execute(
                        """
                        SELECT status FROM long_term_resource_records
                        WHERE source_type = 'video_precheck' AND source_id = ?
                        """,
                        (task["task_id"],),
                    ).fetchone()
                    authorization = connection.execute(
                        """
                        SELECT acceptance_id FROM data_security_acceptances
                        WHERE course_id = ? AND allow_company_archive = 1
                        ORDER BY accepted_at DESC LIMIT 1
                        """,
                        (task["course_id"],),
                    ).fetchone()
                    public_task["archive_status"] = archive["status"] if archive else ""
                    public_task["archive_authorized"] = authorization is not None
                    public_tasks.append(public_task)
                channels.append({
                    **dict(channel),
                    "tasks": public_tasks,
                })
        return {
            "channels": channels,
            "chunk_size_bytes": MAX_VIDEO_CHUNK_BYTES,
            "max_video_bytes": MAX_NEW_VIDEO_BYTES,
            "allowed_extensions": sorted(ALLOWED_VIDEO_EXTENSIONS),
            "mode": "同一平台内四个隔离上传通道",
            "fusion_rule": "相同 session_id 的视频可在校方授权后进入时间对齐与多视角融合；默认各通道独立分析。",
            "analysis_boundary": "当前本地版在上传完成后生成视频完整性和画面质量预检；课堂状态结论仍需绑定课程、学生和教师复核。",
        }

    def record_security_acceptance(
        self, payload: dict[str, Any], *, actor: str = "local_teacher"
    ) -> dict[str, Any]:
        if not bool(payload.get("security_confirmed")):
            raise ValueError("请先确认数据安全协议")
        course_id = str(payload.get("course_id", "")).strip()
        course_name = str(payload.get("course_name", "")).strip()
        confirmed_by = str(payload.get("confirmed_by", "")).strip()
        if not course_id or not course_name or not confirmed_by:
            raise ValueError("课程、课程名称和确认人不能为空")
        acceptance = {
            "acceptance_id": uuid4().hex,
            "course_id": course_id[:120],
            "course_name": course_name[:200],
            "confirmed_by": confirmed_by[:120],
            "agreement_version": str(payload.get("agreement_version", "2026-08-v1")).strip()[:40],
            "allow_company_archive": int(bool(payload.get("allow_company_archive"))),
            "authorized_scope_json": json.dumps(
                {
                    "local_analysis": True,
                    "local_raw_media_retention_days": 60,
                    "expiry_reminder_days": 15,
                    "company_archive_scope": (
                        "deidentified_structured_results_only"
                        if payload.get("allow_company_archive")
                        else "not_authorized"
                    ),
                    "raw_media_company_archive": False,
                },
                ensure_ascii=False,
            ),
            "accepted_at": _iso(),
            "created_at": _iso(),
        }
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO data_security_acceptances
                (acceptance_id, course_id, course_name, confirmed_by, agreement_version,
                 allow_company_archive, authorized_scope_json, accepted_at, created_at)
                VALUES (:acceptance_id, :course_id, :course_name, :confirmed_by,
                        :agreement_version, :allow_company_archive, :authorized_scope_json,
                        :accepted_at, :created_at)
                """,
                acceptance,
            )
            self._audit(
                connection,
                confirmed_by or actor,
                "accept",
                "data_security_agreement",
                acceptance["acceptance_id"],
                {
                    "course_id": acceptance["course_id"],
                    "agreement_version": acceptance["agreement_version"],
                    "allow_company_archive": bool(acceptance["allow_company_archive"]),
                },
            )
        return self._public_acceptance(acceptance)

    def archive_video_result(
        self, payload: dict[str, Any], *, actor: str = "local_teacher"
    ) -> dict[str, Any]:
        task_id = str(payload.get("task_id", "")).strip()
        if not task_id:
            raise ValueError("task_id 不能为空")
        with self._connect() as connection:
            task_row = connection.execute(
                "SELECT * FROM video_analysis_tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if task_row is None:
                raise ValueError("未找到视频分析任务")
            task = dict(task_row)
            if not task.get("result_path") or not Path(task["result_path"]).is_file():
                raise ValueError("该任务尚无可归档的分析结果")
            acceptance_row = connection.execute(
                """
                SELECT * FROM data_security_acceptances
                WHERE course_id = ? AND allow_company_archive = 1
                ORDER BY accepted_at DESC LIMIT 1
                """,
                (task["course_id"],),
            ).fetchone()
            if acceptance_row is None:
                raise ValueError("本课程尚未获得脱敏结果长期归档授权")
            existing = connection.execute(
                """
                SELECT * FROM long_term_resource_records
                WHERE source_type = 'video_precheck' AND source_id = ?
                """,
                (task_id,),
            ).fetchone()
            if existing is not None:
                return self._public_resource(dict(existing))

            result = json.loads(Path(task["result_path"]).read_text(encoding="utf-8"))
            subject_id = str(task.get("subject_id", ""))
            subject_ref = (
                hashlib.sha256(f"demo_school:{subject_id}".encode("utf-8")).hexdigest()[:16]
                if subject_id
                else "group_or_unbound"
            )
            sanitized_payload = {
                "source_type": "video_precheck",
                "course_id": task["course_id"],
                "course_name": task["course_name"],
                "subject_ref": subject_ref,
                "analysis_status": result.get("analysis_status"),
                "analysis_scope": result.get("analysis_scope"),
                "video_quality": result.get("video_quality", {}),
                "generated_at": result.get("generated_at"),
            }
            now = _iso()
            resource = {
                "resource_id": uuid4().hex,
                "source_type": "video_precheck",
                "source_id": task_id,
                "course_id": task["course_id"],
                "subject_ref": subject_ref,
                "payload_json": json.dumps(sanitized_payload, ensure_ascii=False),
                "deidentification_level": "结构化结果脱敏；不含姓名、原文件名、原始视频与音频",
                "authorization_id": acceptance_row["acceptance_id"],
                "status": "local_approved_pending_company_sync",
                "created_by": str(payload.get("created_by", actor)).strip()[:120] or actor,
                "created_at": now,
                "updated_at": now,
            }
            connection.execute(
                """
                INSERT INTO long_term_resource_records
                (resource_id, source_type, source_id, course_id, subject_ref, payload_json,
                 deidentification_level, authorization_id, status, created_by, created_at, updated_at)
                VALUES (:resource_id, :source_type, :source_id, :course_id, :subject_ref,
                        :payload_json, :deidentification_level, :authorization_id, :status,
                        :created_by, :created_at, :updated_at)
                """,
                resource,
            )
            self._audit(
                connection,
                resource["created_by"],
                "archive_approved",
                "long_term_resource",
                resource["resource_id"],
                {
                    "source_type": resource["source_type"],
                    "source_id": task_id,
                    "raw_media_included": False,
                    "status": resource["status"],
                },
            )
        return self._public_resource(resource)

    @staticmethod
    @contextmanager
    def _upload_storage_errors():
        try:
            yield
        except OSError as exc:
            if exc.errno in {errno.ENOSPC, errno.EDQUOT} or getattr(exc, "winerror", None) == 112:
                raise VideoUploadError(507, "insufficient_storage", "存储空间不足，请联系管理员扩容后重试；已确认分片仍保留") from None
            raise VideoUploadError(503, "upload_storage_unavailable", "上传存储暂不可用，请稍后重试") from None
        except sqlite3.OperationalError as exc:
            if getattr(exc, "sqlite_errorcode", None) == sqlite3.SQLITE_FULL:
                raise VideoUploadError(507, "insufficient_storage", "存储空间不足，请联系管理员扩容后重试；已确认分片仍保留") from None
            raise

    def create_video_task(self, payload: dict[str, Any], *, actor: str = "local_uploader") -> dict[str, Any]:
        config = json.loads(_processing_json(
            payload.get("processing_config", {}), max_bytes=MAX_PROCESSING_CONFIG_BYTES
        ))
        config["upload_max_duration_sec"] = 3600
        processing_config = _processing_json(config, max_bytes=MAX_PROCESSING_CONFIG_BYTES)
        channel_id = str(payload.get("channel_id", "")).strip()
        uploader_name = str(payload.get("uploader_name", "")).strip()
        course_name = str(payload.get("course_name", "")).strip()
        course_id = str(payload.get("course_id", "")).strip()[:120]
        session_id = str(payload.get("session_id", "")).strip()
        account_id = str(payload.get("account_id", "")).strip()
        account_session_token = str(
            payload.get("account_session_token", payload.get("auth_token", ""))
        ).strip()
        if account_session_token:
            session_account = self.account_from_session(account_session_token)
            if account_id and account_id != session_account["account_id"]:
                raise ValueError("会话账号与上传账号不一致")
            account_id = session_account["account_id"]
        filename = _safe_filename(str(payload.get("filename", "")))
        suffix = Path(filename).suffix.lower()
        byte_size = int(payload.get("byte_size", 0))
        total_chunks = int(payload.get("total_chunks", 0))
        if suffix not in ALLOWED_VIDEO_EXTENSIONS:
            raise ValueError("仅支持 MP4、MOV、AVI、MKV 和 WebM 视频")
        if not uploader_name:
            raise ValueError("请填写上传主体")
        if not course_name:
            raise ValueError("请填写课程名称")
        if not session_id:
            raise ValueError("请填写课堂批次号")
        if not 0 < byte_size <= MAX_NEW_VIDEO_BYTES:
            raise ValueError("测试阶段单个新视频须在 1B 至 1GiB 之间，请选择不超过 60 分钟的视频")
        expected_chunks = (byte_size + MAX_VIDEO_CHUNK_BYTES - 1) // MAX_VIDEO_CHUNK_BYTES
        if total_chunks != expected_chunks:
            raise ValueError("分片数量与文件大小不一致")
        with self._upload_storage_errors(), self._connect() as connection:
            # Serialize all new reservations with channel pause/quota updates,
            # including the legacy account-less upload entry point.
            connection.execute("BEGIN IMMEDIATE")
            account_row = None
            if account_id:
                account_row = connection.execute(
                    "SELECT * FROM platform_accounts WHERE account_id = ?",
                    (account_id,),
                ).fetchone()
                rejection_reason = ""
                if account_row is None:
                    rejection_reason = "account_not_found"
                elif account_row["status"] != "active":
                    rejection_reason = "account_inactive"
                elif account_row["role"] != "school_uploader":
                    rejection_reason = "account_cannot_upload"
                elif not course_id:
                    rejection_reason = "course_id_required"
                if rejection_reason:
                    audit_actor = account_row["username"] if account_row is not None else actor
                    self._audit(
                        connection,
                        audit_actor,
                        "upload_rejected",
                        "video_analysis_task",
                        account_id or "unknown_account",
                        {
                            "reason": rejection_reason,
                            "channel_id": channel_id,
                            "course_id": course_id,
                        },
                    )
                    connection.commit()
                    if rejection_reason == "course_id_required":
                        raise ValueError("账号上传必须提供 course_id")
                    raise ValueError("账号不存在、已停用或没有上传权限")
                used_slots = connection.execute(
                    """
                    SELECT COUNT(*) FROM video_analysis_tasks
                    WHERE account_id = ? AND course_id = ?
                      AND upload_status NOT IN ('cancelled', 'expired')
                    """,
                    (account_id, course_id),
                ).fetchone()[0]
                max_slots = int(account_row["course_upload_limit"])
                if used_slots >= max_slots:
                    self._audit(
                        connection,
                        account_row["username"],
                        "quota_rejected",
                        "video_analysis_task",
                        account_id,
                        {
                            "course_id": course_id,
                            "used_slots": used_slots,
                            "max_slots": max_slots,
                        },
                    )
                    connection.commit()
                    raise ValueError(f"该课程上传名额已满（最多 {max_slots} 段）")
            channel = connection.execute(
                "SELECT status FROM video_upload_channels WHERE channel_id = ?",
                (channel_id,),
            ).fetchone()
            if channel is None:
                raise ValueError("上传通道不存在")
            if channel["status"] != "active":
                raise ValueError("上传通道已暂停，暂不接受新建上传任务")
            reserved = connection.execute(
                "SELECT COALESCE(SUM(MAX(0, byte_size - received_bytes)), 0) "
                "FROM video_analysis_tasks WHERE upload_status = 'uploading'"
            ).fetchone()[0]
            if shutil.disk_usage(self.video_task_dir).free < reserved + byte_size + VIDEO_CREATE_RESERVE_BYTES:
                raise VideoUploadError(507, "insufficient_storage", "剩余空间不足以接收此视频及待上传任务，请联系管理员扩容")
            policy = connection.execute(
                """
                SELECT retention_days, reminder_days FROM retention_policies
                WHERE data_type = 'raw_media'
                """
            ).fetchone()
            retention_days = int(policy["retention_days"])
            reminder_days = int(policy["reminder_days"])
            task_id = uuid4().hex
            upload_dir = self.video_task_dir / "uploads" / channel_id
            upload_dir.mkdir(parents=True, exist_ok=True)
            file_path = upload_dir / f"{task_id[:12]}_{filename}"
            Path(f"{file_path}.part").write_bytes(b"")
            created_at = _now()
            row = {
                "task_id": task_id,
                "channel_id": channel_id,
                "account_id": account_id or None,
                "school_context_json": json.dumps(
                    self._school_context_for_account(connection, account_id), ensure_ascii=False
                ),
                "session_id": session_id[:120],
                "uploader_name": uploader_name[:120],
                "course_id": course_id,
                "course_name": course_name[:200],
                "subject_id": str(payload.get("subject_id", "")).strip()[:120],
                "original_filename": filename,
                "file_path": str(file_path.resolve()),
                "mime_type": str(payload.get("mime_type", "")).strip() or mimetypes.guess_type(filename)[0] or "video/mp4",
                "byte_size": byte_size,
                "received_bytes": 0,
                "total_chunks": total_chunks,
                "next_chunk_index": 0,
                "sha256": "",
                "upload_status": "uploading",
                "analysis_status": "waiting_upload",
                "processing_config_json": processing_config,
                "processing_config_hash": _token_hash(processing_config),
                "result_path": "",
                "retention_days": retention_days,
                "reminder_days": reminder_days,
                "expires_at": _iso(created_at + timedelta(days=retention_days)),
                "raw_media_deleted_at": "",
                "created_at": _iso(created_at),
                "updated_at": _iso(created_at),
            }
            connection.execute(
                """
                INSERT INTO video_analysis_tasks
                (task_id, channel_id, account_id, session_id, uploader_name, course_id, course_name,
                 subject_id, original_filename, file_path, mime_type, byte_size,
                 received_bytes, total_chunks, next_chunk_index, sha256, upload_status,
                 analysis_status, result_path, retention_days, reminder_days, expires_at,
                 raw_media_deleted_at, created_at, updated_at, school_context_json,
                 processing_config_json, processing_config_hash)
                VALUES (:task_id, :channel_id, :account_id, :session_id, :uploader_name, :course_id,
                        :course_name, :subject_id, :original_filename, :file_path, :mime_type,
                        :byte_size, :received_bytes, :total_chunks, :next_chunk_index, :sha256,
                        :upload_status, :analysis_status, :result_path, :retention_days,
                        :reminder_days, :expires_at, :raw_media_deleted_at,
                        :created_at, :updated_at, :school_context_json,
                        :processing_config_json, :processing_config_hash)
                """,
                row,
            )
            audit_actor = account_row["username"] if account_row is not None else actor
            self._audit(connection, audit_actor, "upload" if account_row is not None else "create", "video_analysis_task", task_id, {
                "account_id": account_id or None,
                "channel_id": channel_id,
                "session_id": session_id,
                "filename": filename,
                "byte_size": byte_size,
            })
        return self._public_video_task(row)

    def _check_upload_owner(self, connection, task, account_id, course_id=None) -> None:
        account = connection.execute(
            "SELECT * FROM platform_accounts WHERE account_id=?", (account_id,)
        ).fetchone()
        if (account is None or account["status"] != "active" or account["role"] != "school_uploader"
                or account_id != task.get("account_id")
                or account["bound_channel_id"] != task.get("channel_id")
                or (course_id is not None and course_id != task["course_id"])):
            raise VideoUploadError(403, "task_forbidden", "当前账号或课程无权续传此任务，请返回自己的课程确认")
        snapshot = json.loads(task.get("school_context_json") or "{}")
        if any(snapshot.values()) and snapshot != self._school_context_for_account(connection, account_id):
            raise VideoUploadError(403, "task_forbidden", "任务所属学校与当前账号不一致，请联系管理员确认，勿继续上传")

    @staticmethod
    def _check_upload_offset(task) -> None:
        size, index, received = task["byte_size"], task["next_chunk_index"], task["received_bytes"]
        if (task["total_chunks"] != (size + MAX_VIDEO_CHUNK_BYTES - 1) // MAX_VIDEO_CHUNK_BYTES
                or not 0 <= index <= task["total_chunks"]
                or received != min(index * MAX_VIDEO_CHUNK_BYTES, size)
                or (task["upload_status"] == "uploading" and index == task["total_chunks"])
                or (task["upload_status"] == "completed" and index != task["total_chunks"])):
            raise VideoUploadError(409, "upload_offset_conflict", "上传进度记录不一致，请停止续传并联系管理员；已确认分片保留")

    def append_video_chunk(self, payload: dict[str, Any], *, actor: str = "local_uploader",
                           chunk: bytes | None = None) -> dict[str, Any]:
        task_id = str(payload.get("task_id", "")).strip()
        session_token = payload.get("account_session_token", payload.get("auth_token", ""))
        session_account = self.account_from_session(session_token) if session_token else None
        raw_index = payload.get("chunk_index", -1)
        if type(raw_index) is not int and not (isinstance(raw_index, str) and re.fullmatch(r"[0-9]{1,10}", raw_index)):
            raise ValueError("分片序号必须是非负整数，请刷新上传进度后重试")
        chunk_index = int(raw_index)
        if chunk is None:
            encoded = str(payload.get("content_base64", "")).strip()
            if "," in encoded and encoded.lower().startswith("data:"):
                encoded = encoded.split(",", 1)[1]
            if len(encoded) > 4 * ((MAX_VIDEO_CHUNK_BYTES + 2) // 3):
                raise ValueError("视频分片超过 4 MiB，请按原分片大小重试")
            try:
                chunk = base64.b64decode(encoded, validate=True)
            except ValueError as exc:
                raise ValueError("视频分片不是有效的 Base64 数据") from exc
        if not isinstance(chunk, bytes) or not chunk or len(chunk) > MAX_VIDEO_CHUNK_BYTES:
            raise ValueError("视频分片为空或超过 4MB")

        with self._upload_lock, self._upload_storage_errors():
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT * FROM video_analysis_tasks WHERE task_id = ?", (task_id,)
                ).fetchone()
                if row is None:
                    raise ValueError("未找到视频任务")
                task = dict(row)
                if session_account is not None and (
                    session_account["role"] != "school_uploader" or session_account["account_id"] != task.get("account_id")
                ):
                    raise ValueError("会话账号与上传任务不一致")
                if payload.get("account_id") and payload["account_id"] != task.get("account_id"):
                    raise ValueError("分片账号与任务所属账号不一致")
                account_id = session_account["account_id"] if session_account else payload.get("account_id")
                if account_id:
                    self._check_upload_owner(connection, task, account_id, payload.get("course_id"))
                if task["upload_status"] not in {"uploading", "completed"}:
                    raise VideoUploadError(409, "upload_not_active", "任务已取消或不可用，请返回课程查看状态，勿继续续传")
                self._require_live_video(task, completed=False)
                self._check_upload_offset(task)
                if not 0 <= chunk_index < task["total_chunks"]:
                    raise VideoUploadError(409, "chunk_order_conflict", "分片序号超出任务范围，请刷新进度后重试")
                offset = chunk_index * MAX_VIDEO_CHUNK_BYTES
                if len(chunk) != min(MAX_VIDEO_CHUNK_BYTES, task["byte_size"] - offset):
                    raise VideoUploadError(409, "chunk_size_conflict", "分片大小与登记文件不一致，请重新选择原视频并校验后续传")
                final_path = self._video_source_path(task)
                part_path = self._controlled_video_path(Path(f"{final_path}.part"), "uploads")
                if part_path.exists() and final_path.exists():
                    raise VideoUploadError(409, "upload_offset_conflict", "上传文件状态冲突，已停止写入；请联系管理员确认")
                if chunk_index < task["next_chunk_index"]:
                    # A lost HTTP response must not append again or restart analysis.
                    source = final_path if task["upload_status"] == "completed" or not part_path.exists() else part_path
                    try:
                        with source.open("rb") as handle:
                            actual_size = handle.seek(0, 2)
                            if (actual_size < task["received_bytes"] or actual_size > task["byte_size"]
                                    or (task["upload_status"] == "completed" and actual_size != task["byte_size"])):
                                raise VideoUploadError(409, "upload_offset_conflict", "已保存文件与确认进度不一致，请停止续传并联系管理员")
                            handle.seek(offset)
                            if handle.read(len(chunk)) != chunk:
                                raise VideoUploadError(409, "chunk_replay_mismatch", "重试分片与已保存内容不同，请重新选择原视频并校验后续传")
                    except OSError as exc:
                        raise VideoUploadError(409, "upload_file_unavailable", "已确认分片暂不可读取，请停止续传并联系管理员") from exc
                    return self._public_video_task(task)
                if chunk_index != task["next_chunk_index"] or task["upload_status"] != "uploading":
                    raise VideoUploadError(409, "chunk_order_conflict", "分片顺序与服务端进度不一致，请刷新进度后按顺序续传")
                received_bytes = task["received_bytes"] + len(chunk)
                if received_bytes > task["byte_size"]:
                    raise ValueError("上传内容超过登记的视频大小")
                next_chunk = chunk_index + 1
                complete = next_chunk == task["total_chunks"]
                if complete and received_bytes != task["byte_size"]:
                    raise ValueError("最后分片完成后文件大小不一致")
                if shutil.disk_usage(self.video_task_dir).free < len(chunk) + VIDEO_APPEND_RESERVE_BYTES:
                    raise VideoUploadError(507, "insufficient_storage", "剩余空间不足，已确认分片保留；请联系管理员扩容后重试")
                if not part_path.exists() and final_path.exists():
                    final_path.replace(part_path)
                with part_path.open("r+b") as handle:
                    actual_size = handle.seek(0, 2)
                    if actual_size < task["received_bytes"]:
                        raise VideoUploadError(409, "upload_offset_conflict", "已保存文件与确认进度不一致，请停止续传并联系管理员")
                    # Discard only bytes left beyond the DB offset by an interrupted transaction.
                    handle.truncate(task["received_bytes"])
                    handle.seek(task["received_bytes"])
                    try:
                        if handle.write(chunk) != len(chunk):
                            raise OSError(errno.ENOSPC, "Short upload write")
                        handle.flush()
                        os.fsync(handle.fileno())
                    except OSError:
                        # DB rollback preserves the committed offset; best-effort remove only this write.
                        try:
                            handle.truncate(task["received_bytes"])
                            handle.flush()
                            os.fsync(handle.fileno())
                        except OSError:
                            pass
                        raise
                connection.execute(
                    """
                    UPDATE video_analysis_tasks
                    SET received_bytes = ?, next_chunk_index = ?, updated_at = ?
                    WHERE task_id = ?
                    """,
                    (received_bytes, next_chunk, _iso(), task_id),
                )

                if complete:
                    digest = hashlib.sha256()
                    with part_path.open("rb") as handle:
                        for block in iter(lambda: handle.read(1024 * 1024), b""):
                            digest.update(block)
                    part_path.replace(final_path)
                    connection.execute(
                        """
                        UPDATE video_analysis_tasks
                        SET sha256 = ?, upload_status = 'completed', analysis_status = 'queued',
                            processing_stage = 'queued', processing_progress = 0,
                            processing_key = ?, updated_at = ? WHERE task_id = ?
                        """,
                        (digest.hexdigest(), _token_hash(f"{task_id}:{digest.hexdigest()}:{task['processing_config_hash']}"),
                         _iso(), task_id),
                    )
                    self._audit(connection, actor, "complete", "video_analysis_task", task_id, {
                        "sha256": digest.hexdigest(),
                        "analysis_status": "queued",
                    })
            with self._connect() as connection:
                updated = connection.execute(
                    "SELECT * FROM video_analysis_tasks WHERE task_id = ?", (task_id,)
                ).fetchone()
        return self._public_video_task(dict(updated))

    def resume_video_upload(self, session_token: str, payload: dict[str, Any]) -> dict[str, Any]:
        account = self.account_from_session(session_token)
        fields = {"task_id", "course_id", "byte_size", "filename", "chunk_sha256"}
        if (set(payload) != fields or type(payload["byte_size"]) is not int
                or not isinstance(payload["filename"], str) or not payload["filename"]
                or any(not isinstance(payload[key], str) or not 1 <= len(payload[key]) <= 120
                       for key in ("task_id", "course_id"))):
            raise ValueError("续传参数不完整或格式无效，请重新选择原视频后重试")
        hashes = payload["chunk_sha256"]
        if (not isinstance(hashes, list) or len(hashes) > (MAX_VIDEO_BYTES + MAX_VIDEO_CHUNK_BYTES - 1) // MAX_VIDEO_CHUNK_BYTES
                or any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", value) for value in hashes)):
            raise ValueError("已确认分片的校验列表格式无效，请重新选择原视频并重新校验")
        with self._upload_lock:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute("SELECT * FROM video_analysis_tasks WHERE task_id=?", (payload["task_id"],)).fetchone()
                if row is None:
                    raise VideoUploadError(403, "task_forbidden", "当前账号或课程无权续传此任务，请返回自己的课程确认")
                task = dict(row)
                self._check_upload_owner(connection, task, account["account_id"], payload["course_id"])
                if task["upload_status"] != "uploading":
                    raise VideoUploadError(409, "upload_not_active", "仅未完成的上传任务可续传，请返回课程查看当前状态")
                self._require_live_video(task, completed=False)
                self._check_upload_offset(task)
                if (payload["byte_size"] != task["byte_size"]
                        or _safe_filename(payload["filename"]) != task["original_filename"]):
                    raise VideoUploadError(409, "resume_file_mismatch", "所选文件名称或大小与原任务不同，请选择最初上传的原视频")
                if len(hashes) != task["next_chunk_index"]:
                    raise VideoUploadError(409, "resume_offset_changed", "服务端上传进度已变化，请刷新任务并重新校验全部已确认分片")
                final_path = self._video_source_path(task)
                part_path = self._controlled_video_path(Path(f"{final_path}.part"), "uploads")
                if part_path.exists() and final_path.exists():
                    raise VideoUploadError(409, "upload_offset_conflict", "上传文件状态冲突，请停止续传并联系管理员")
                source = part_path if part_path.exists() else final_path
                try:
                    with source.open("rb") as handle:
                        if not task["received_bytes"] <= handle.seek(0, 2) <= task["byte_size"]:
                            raise VideoUploadError(409, "upload_offset_conflict", "已保存文件与确认进度不一致，请停止续传并联系管理员")
                        handle.seek(0)
                        for expected in hashes:
                            block = handle.read(MAX_VIDEO_CHUNK_BYTES)
                            if len(block) != MAX_VIDEO_CHUNK_BYTES or not hmac.compare_digest(hashlib.sha256(block).hexdigest(), expected.lower()):
                                raise VideoUploadError(409, "resume_file_mismatch", "所选视频与已保存分片内容不同，请选择最初上传的原视频，勿混传文件")
                except OSError as exc:
                    raise VideoUploadError(409, "upload_file_unavailable", "已确认分片暂不可读取，请停止续传并联系管理员") from exc
        return self._public_video_task(task)

    def cancel_video_task(self, session_token: str, task_id: str) -> dict[str, Any]:
        account = self.account_from_session(session_token)
        normalized_task_id = str(task_id or "").strip()
        if account["role"] != "school_uploader":
            raise ValueError("仅学校上传账号可取消未完成任务")
        if not normalized_task_id:
            raise ValueError("task_id 不能为空")

        with self._upload_lock:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT * FROM video_analysis_tasks WHERE task_id = ?",
                    (normalized_task_id,),
                ).fetchone()
                if row is None:
                    raise ValueError("未找到视频任务")
                task = dict(row)
                if task.get("account_id") != account["account_id"]:
                    raise ValueError("无权取消其他账号的视频任务")
                if task["upload_status"] != "uploading":
                    raise ValueError("仅可取消尚未完成的上传任务")

                part_path = Path(f"{task['file_path']}.part").resolve()
                upload_root = (self.video_task_dir / "uploads").resolve()
                if upload_root not in part_path.parents:
                    raise ValueError("上传临时文件路径不在受控目录内")
                part_path.unlink(missing_ok=True)

                updated_at = _iso()
                connection.execute(
                    """
                    UPDATE video_analysis_tasks
                    SET upload_status = 'cancelled', analysis_status = 'cancelled',
                        updated_at = ? WHERE task_id = ?
                    """,
                    (updated_at, normalized_task_id),
                )
                self._audit(
                    connection,
                    account["username"],
                    "upload_cancelled",
                    "video_analysis_task",
                    normalized_task_id,
                    {
                        "account_id": account["account_id"],
                        "course_id": task["course_id"],
                        "released_quota": True,
                    },
                )
                updated = connection.execute(
                    "SELECT * FROM video_analysis_tasks WHERE task_id = ?",
                    (normalized_task_id,),
                ).fetchone()
        return self._public_video_task(dict(updated))

    def _controlled_video_path(self, path: Path, subtree: str) -> Path:
        root = self.video_task_dir.resolve() / subtree
        candidate = Path(os.path.abspath(path))
        if root not in candidate.parents or root.resolve() != root or candidate.resolve() != candidate:
            raise ValueError("视频文件路径不在受控目录内，或包含目录链接")
        # resolve() also needs an explicit reparse-point check on Windows:
        # some reparse tags do not redirect paths and still must not be followed.
        for component in (candidate, *candidate.parents):
            try:
                info = component.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise ValueError("视频文件路径不在受控目录内，或包含目录链接")
            if component == root:
                break
        return candidate

    def _video_analysis_dir(self, task_id: str) -> Path:
        if not isinstance(task_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", task_id):
            raise ValueError("视频任务编号无效")
        return self._controlled_video_path(self.video_task_dir.resolve() / "analysis" / task_id, "analysis")

    def _video_source_path(self, task: dict[str, Any]) -> Path:
        path = self._controlled_video_path(Path(task["file_path"]), "uploads")
        expected = self.video_task_dir.resolve() / "uploads" / task["channel_id"] / (
            f"{task['task_id'][:12]}_{_safe_filename(task['original_filename'])}"
        )
        if path != expected:
            raise ValueError("视频路径与任务记录不一致")
        return path

    @staticmethod
    def _require_live_video(task: dict[str, Any], *, completed: bool = True) -> None:
        try:
            expired = datetime.fromisoformat(task["expires_at"]) <= _now()
        except (TypeError, ValueError):
            expired = True
        if expired or task.get("raw_media_deleted_at"):
            raise ValueError("原视频已到期或已删除，不能读取或重新处理")
        if completed and task["upload_status"] != "completed":
            raise ValueError("视频尚未完成上传")

    @staticmethod
    def _video_task_row(connection: sqlite3.Connection, task_id: str) -> dict[str, Any]:
        row = connection.execute("SELECT * FROM video_analysis_tasks WHERE task_id = ?", (task_id,)).fetchone()
        if row is None:
            raise ValueError("未找到视频任务")
        return dict(row)

    def _authorized_video_task(self, connection: sqlite3.Connection, account: dict[str, Any], task_id: str) -> dict[str, Any]:
        task = self._video_task_row(connection, task_id)
        if account["role"] != "company_admin" and (
            account["role"] != "school_uploader" or account["account_id"] != task.get("account_id")
        ):
            raise ValueError("无权访问其他账号的视频任务")
        return task

    def account_video_task(self, session_token: str, task_id: str) -> dict[str, Any]:
        account = self.account_from_session(session_token)
        with self._connect() as connection:
            return self._public_video_task(self._authorized_video_task(connection, account, task_id))

    def account_simple_analysis(self, session_token: str, task_id: str) -> dict[str, Any]:
        """Return the teacher-first result without requiring roster identity binding."""
        account = self.account_from_session(session_token)
        with self._connect() as connection:
            task = self._authorized_video_task(connection, account, task_id)
            public_task = self._public_video_task(task)
            try:
                result = json.loads(task.get("processing_result_json") or "null")
            except (TypeError, ValueError):
                result = None
            if not isinstance(result, dict):
                result = {}
            public_task["simple_result_url"] = (
                f"/api/v1/demo2/simple-result?task_id={quote(task_id, safe='')}"
                if task.get("analysis_status") in READY_VIDEO_ANALYSIS_STATUSES else ""
            )
            analysis = {
                "available": False, "reason": "analysis_not_ready",
                "message": "后台分析尚未生成学生状态结果。"
            }
            if task.get("analysis_status") in {"evidence_ready", "completed"}:
                from .demo2_media_analysis import SIMPLE_ANALYSIS_VERSION

                self._require_live_video(task)
                stored = result.get("simple_student_analysis")
                cache = self._read_simple_analysis_cache(task, SIMPLE_ANALYSIS_VERSION)
                if self._current_simple_analysis(stored, SIMPLE_ANALYSIS_VERSION):
                    analysis = dict(stored, refresh_status="ready")
                elif cache and cache["status"] == "completed":
                    analysis = dict(cache["analysis"], refresh_status="ready")
                else:
                    # Only queue metadata is mutable here; inference and cache writes belong to the worker.
                    connection.execute(
                        "INSERT INTO simple_analysis_refresh_requests(task_id, analysis_version, requested_at) "
                        "VALUES (?, ?, ?) ON CONFLICT(task_id) DO UPDATE SET "
                        "analysis_version=excluded.analysis_version, requested_at=excluded.requested_at "
                        "WHERE analysis_version<>excluded.analysis_version OR requested_at<?",
                        (task_id, SIMPLE_ANALYSIS_VERSION, _iso(), _iso(_now() - timedelta(seconds=30))),
                    )
                    analysis = {
                        "available": False, "persons": [], "status": "processing",
                        "analysis_version": SIMPLE_ANALYSIS_VERSION,
                        "reason": "analysis_refresh_pending", "refresh_status": "pending",
                        "message": "后台正在更新人物状态分析，请稍后刷新。",
                    }
                    if cache and cache["status"] == "failed":
                        analysis.update(reason="analysis_refresh_failed", refresh_status="retry_wait",
                                        retry_after=cache["retry_after"],
                                        message="人物状态分析更新暂未完成，后台将稍后重试。")
                from .demo2_student_tracking import present_motion_analysis
                analysis = _public_processing_data(present_motion_analysis(analysis))
            if isinstance(analysis, dict):
                archives = []
                if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='demo2_simple_lesson_archives'").fetchone():
                    for row in connection.execute("""SELECT a.*,s.display_name AS student_name,s.class_name
                        FROM demo2_simple_lesson_archives a LEFT JOIN demo2_identity_students s ON s.student_id=a.student_id
                        WHERE a.task_id=? AND a.owner_account_id=? ORDER BY a.person_id""",
                        (task_id, account["account_id"])):
                        item = dict(row)
                        item["key_times_sec"] = json.loads(item.pop("key_times_json"))
                        item["state_breakdown"] = json.loads(item.pop("state_breakdown_json"))
                        binding = connection.execute("SELECT time_sec,bbox_json FROM demo2_identity_bindings WHERE binding_id=?",
                                                     (item["binding_id"],)).fetchone()
                        item["candidate_matches_current"] = bool(binding and self._simple_binding_matches_analysis(
                            analysis, dict(binding), item["person_id"]))
                        archives.append(item)
                analysis = dict(analysis, lesson_archives=archives)
            return {"task": public_task, "analysis": analysis}

    @staticmethod
    def _current_simple_analysis(analysis: Any, version: str) -> bool:
        return (isinstance(analysis, dict) and analysis.get("analysis_version") == version
                and isinstance(analysis.get("available"), bool)
                and isinstance(analysis.get("persons", []), list))

    @staticmethod
    def _simple_binding_matches_analysis(analysis, binding, person_id):
        """A local binding cannot silently migrate to a same-numbered new track."""
        try:
            box = json.loads(binding['bbox_json'])
            person = next(p for p in analysis.get('persons', []) if p['person_id'] == person_id)
            for window in person.get('windows', []):
                other = window.get('bbox')
                if not other or abs(float(window.get('frame_time_sec', -1)) - float(binding['time_sec'])) > .01:
                    continue
                x = max(0., min(box['x']+box['width'], other['x']+other['width']) - max(box['x'], other['x']))
                y = max(0., min(box['y']+box['height'], other['y']+other['height']) - max(box['y'], other['y']))
                intersection = x*y
                union = box['width']*box['height'] + other['width']*other['height'] - intersection
                if union > 0 and intersection/union >= .5:
                    return True
        except (ValueError, TypeError, KeyError, StopIteration):
            pass
        return False

    def _simple_analysis_cache_path(self, task: dict[str, Any], version: str) -> tuple[Path, str]:
        if not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}", version):
            raise ValueError("Invalid simple analysis version")
        digest = hashlib.sha256((task.get("processing_result_json") or "").encode("utf-8")).hexdigest()
        directory = self._video_analysis_dir(task["task_id"])
        return self._controlled_video_path(directory / f"simple_{version}_{digest}.json", "analysis"), digest

    def _read_simple_analysis_cache(self, task: dict[str, Any], version: str) -> dict[str, Any] | None:
        try:
            path, digest = self._simple_analysis_cache_path(task, version)
            info = path.stat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_PROCESSING_RESULT_BYTES:
                return None
            with path.open("rb") as handle:
                raw = handle.read(MAX_PROCESSING_RESULT_BYTES + 1)
            if len(raw) > MAX_PROCESSING_RESULT_BYTES:
                return None
            cache = json.loads(raw)
            if (not isinstance(cache, dict) or cache.get("cache_version") != 1
                    or cache.get("task_id") != task["task_id"] or cache.get("source_sha256") != digest
                    or cache.get("analysis_version") != version):
                return None
            if cache.get("status") == "completed" and self._current_simple_analysis(cache.get("analysis"), version):
                return cache
            if cache.get("status") == "failed" and type(cache.get("attempt")) is int and 1 <= cache["attempt"] <= 12:
                # Also reject timestamps that cannot be compared with the store clock.
                datetime.fromisoformat(cache["retry_after"]) > _now()
                return cache
        except (OSError, ValueError, TypeError, KeyError, RecursionError):
            pass
        return None

    def _write_simple_analysis_cache(
        self, task: dict[str, Any], version: str, cache: dict[str, Any], *, stop_event: Event | None = None,
    ) -> None:
        path, _ = self._simple_analysis_cache_path(task, version)
        encoded = _processing_json(cache, max_bytes=MAX_PROCESSING_RESULT_BYTES)
        temporary = self._controlled_video_path(path.with_suffix(f".{uuid4().hex}.tmp"), "analysis")
        try:
            with temporary.open("x", encoding="utf-8") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            # Retention and task reprocessing use the same SQLite write lock.
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                current = self._video_task_row(connection, task["task_id"])
                self._require_live_video(current)
                if ((stop_event is not None and stop_event.is_set())
                        or current["analysis_status"] not in {"evidence_ready", "completed"}
                        or current["processing_result_json"] != task["processing_result_json"]
                        or not self._video_source_path(current).is_file()):
                    raise ValueError("Simple analysis refresh is no longer current")
                self._controlled_video_path(temporary, "analysis").replace(
                    self._controlled_video_path(path, "analysis"))
                if cache["status"] == "completed":
                    connection.execute("DELETE FROM simple_analysis_refresh_requests WHERE task_id=?", (task["task_id"],))
        finally:
            self._controlled_video_path(temporary, "analysis").unlink(missing_ok=True)

    def refresh_next_simple_analysis(self, *, stop_event: Event | None = None) -> bool:
        """Refresh at most one old result off-request, without changing binding revisions."""
        from .demo2_media_analysis import SIMPLE_ANALYSIS_VERSION, _build_simple_student_analysis
        from .demo2_media_worker import WorkerLock

        if stop_event is not None and stop_event.is_set():
            return False
        store = self

        class RefreshStop(Event):
            def __init__(self, parent):
                super().__init__()
                self.parent = parent
                self.next_check = 0.0

            def is_set(self):
                if super().is_set() or (self.parent is not None and self.parent.is_set()):
                    return True
                if time.monotonic() >= self.next_check:
                    self.next_check = time.monotonic() + 2
                    with store._connect() as db:
                        pending = db.execute("SELECT 1 FROM video_analysis_tasks WHERE analysis_status IN ('queued','processing') LIMIT 1").fetchone()
                    if pending:
                        super().set()
                return super().is_set()

        # An old result refresh must yield promptly when a new upload is ready.
        stop_event = RefreshStop(stop_event)
        lock_path = self._controlled_video_path(self.video_task_dir.resolve() / "analysis" / ".simple_refresh.lock", "analysis")
        lock = WorkerLock(lock_path)
        if not lock.acquire():
            return False
        try:
            now = _now()
            self._simple_refresh_retry = {key: deadline for key, deadline in self._simple_refresh_retry.items()
                                          if deadline > now}
            with self._connect() as connection:
                if connection.execute("SELECT 1 FROM video_analysis_tasks WHERE analysis_status IN ('queued','processing') LIMIT 1").fetchone():
                    return False
                task_ids = [row[0] for row in connection.execute(
                    "SELECT t.task_id FROM video_analysis_tasks t LEFT JOIN simple_analysis_refresh_requests r "
                    "ON r.task_id=t.task_id AND r.analysis_version=? WHERE t.upload_status = 'completed' "
                    "AND t.analysis_status IN ('evidence_ready','completed') AND t.raw_media_deleted_at = '' "
                    "AND julianday(t.expires_at) > julianday(?) "
                    "ORDER BY (r.task_id IS NULL), r.requested_at DESC, t.updated_at, t.rowid",
                    (SIMPLE_ANALYSIS_VERSION, _iso()))]
            for task_id in task_ids:
                if stop_event is not None and stop_event.is_set():
                    return False
                with self._connect() as connection:
                    task = self._video_task_row(connection, task_id)
                version = SIMPLE_ANALYSIS_VERSION
                raw = task.get("processing_result_json") or ""
                digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
                retry_key = (task_id, f"{version}_{digest}")
                if self._simple_refresh_retry.get(retry_key, _now()) > _now():
                    continue
                cache = self._read_simple_analysis_cache(task, version)
                if cache and (cache["status"] == "completed" or datetime.fromisoformat(cache["retry_after"]) > _now()):
                    continue
                attempt = min(12, cache.get("attempt", 0) + 1) if cache else 1
                envelope = {"cache_version": 1, "task_id": task_id, "analysis_version": version,
                            "source_sha256": digest, "attempt": attempt}
                try:
                    self._require_live_video(task)
                    if task["analysis_status"] not in {"evidence_ready", "completed"}:
                        continue
                    result = json.loads(raw)
                    if not isinstance(result, dict):
                        raise ValueError("Invalid source analysis")
                    if self._current_simple_analysis(result.get("simple_student_analysis"), version):
                        continue
                    if not isinstance(result.get("segments"), list) or not isinstance(result.get("media"), dict):
                        raise ValueError("Source analysis has no media evidence")
                    artifacts = result.get("artifacts") or {}
                    relative_frames = artifacts.get("frames", "frames")
                    relative = PurePosixPath(relative_frames.replace("\\", "/"))
                    if (relative.is_absolute() or PureWindowsPath(relative_frames).drive or ":" in relative_frames
                            or ".." in relative.parts or relative.name != "frames"):
                        raise ValueError("Invalid frame manifest")
                    directory = self._video_analysis_dir(task_id)
                    frames_dir = self._controlled_video_path(directory.joinpath(*relative.parts), "analysis")
                    if directory not in frames_dir.parents or not frames_dir.is_dir() or not self._video_source_path(task).is_file():
                        raise ValueError("Source media evidence is unavailable")
                    refreshed = _build_simple_student_analysis(result["segments"], frames_dir.parent, result["media"],
                                                                stop_event=stop_event)
                    if stop_event is not None and stop_event.is_set():
                        return False
                    if not isinstance(refreshed, dict) or refreshed.get("analysis_version", version) != version:
                        raise ValueError("Invalid refreshed analysis")
                    analysis = dict(_public_processing_data(refreshed), analysis_version=version,
                                    refreshed_from_legacy_result=True)
                    if not self._current_simple_analysis(analysis, version):
                        raise ValueError("Invalid refreshed analysis")
                    self._write_simple_analysis_cache(task, version, dict(envelope, status="completed", analysis=analysis),
                                                      stop_event=stop_event)
                    self._simple_refresh_retry.pop(retry_key, None)
                except Exception:
                    if stop_event is not None and stop_event.is_set():
                        return False
                    delay = min(SIMPLE_REFRESH_MAX_RETRY_SECONDS, SIMPLE_REFRESH_RETRY_SECONDS * 2 ** (attempt - 1))
                    retry_after = _now() + timedelta(seconds=delay)
                    self._simple_refresh_retry[retry_key] = retry_after
                    # Persist backoff for restarts; do not leak decoder text or paths.
                    failure = dict(envelope, status="failed", retry_after=_iso(retry_after), error="refresh_failed")
                    try:
                        self._write_simple_analysis_cache(task, version, failure, stop_event=stop_event)
                    except (OSError, ValueError, sqlite3.Error):
                        pass
                return True
            return False
        finally:
            lock.release()

    def archive_simple_lesson(self, session_token: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Save one compact lesson summary after a teacher binds a person.

        This is deliberately smaller than the protected IEP workflow: it stores
        the lesson conclusion, key time points and a teacher-entered support
        hint. The full timeline and source video remain attached to the task.
        """
        if not isinstance(payload, dict):
            raise ValueError("归档内容格式无效")
        allowed = {"task_id", "person_id", "student_id", "binding_id", "main_state",
                   "average_score", "key_times_sec", "state_breakdown", "lesson_summary",
                   "iep_support_summary"}
        if set(payload) - allowed or not {"task_id", "person_id", "student_id", "binding_id"} <= set(payload):
            raise ValueError("归档字段不完整")
        text_fields = ("task_id", "person_id", "student_id", "binding_id", "main_state",
                       "lesson_summary", "iep_support_summary")
        for key in text_fields:
            value = payload.get(key, "")
            if not isinstance(value, str) or len(value) > (80 if key in text_fields[:5] else 1000):
                raise ValueError("归档字段长度无效")
        if not payload.get("student_id") or not payload.get("binding_id"):
            raise ValueError("请先绑定学生姓名")
        for value in (payload.get("lesson_summary", ""), payload.get("iep_support_summary", "")):
            if any(term in value.casefold() for term in ("诊断", "病理", "完整iep", "diagnosis", "medical diagnosis")):
                raise ValueError("这里只能填写课堂支持摘要，不能录入诊断原文")
        score = payload.get("average_score")
        if score is not None and (type(score) not in (int, float) or not 0 <= float(score) <= 10):
            raise ValueError("参考分无效")
        key_times = payload.get("key_times_sec", [])
        if not isinstance(key_times, list) or len(key_times) > 12 or any(
                type(value) not in (int, float) or value < 0 for value in key_times):
            raise ValueError("关键时间点无效")
        breakdown = payload.get("state_breakdown", {})
        if not isinstance(breakdown, dict) or len(breakdown) > 12 or any(
                not isinstance(key, str) or not isinstance(value, int) or value < 0 for key, value in breakdown.items()):
            raise ValueError("状态统计无效")

        account = self.account_from_session(session_token)
        with self._connect() as connection:
            task = self._authorized_video_task(connection, account, payload["task_id"])
            if account.get("role") != "school_uploader" or task.get("account_id") != account.get("account_id"):
                raise ValueError("当前账号无权归档此课堂")
            binding = connection.execute("""SELECT binding_id,student_id,task_id,owner_account_id,
                    scope_key,frame_revision,source_sha256,status,role,time_sec,bbox_json FROM demo2_identity_bindings
                    WHERE binding_id=? AND task_id=? AND student_id=?""",
                (payload["binding_id"], task["task_id"], payload["student_id"])).fetchone()
            if binding is None or binding["status"] != "confirmed" or binding["role"] != "student":
                raise ValueError("学生绑定不存在或已撤销")
            revision = hashlib.sha256((task.get("processing_result_json") or "").encode("utf-8")).hexdigest()
            if binding["owner_account_id"] != account["account_id"] or binding["source_sha256"] != task.get("sha256"):
                raise ValueError("学生绑定不属于当前课堂")
            if binding["frame_revision"] != revision:
                raise ValueError("学生绑定已过期，请刷新结果后重新绑定")
            from .demo2_media_analysis import SIMPLE_ANALYSIS_VERSION
            cached = self._read_simple_analysis_cache(task, SIMPLE_ANALYSIS_VERSION)
            analysis = cached['analysis'] if cached and cached['status'] == 'completed' else json.loads(task['processing_result_json']).get('simple_student_analysis', {})
            if not self._simple_binding_matches_analysis(analysis, dict(binding), payload['person_id']):
                raise ValueError("人物分析已更新，请对当前人物截图重新确认姓名；原有学生档案不会删除")
            student = connection.execute("""SELECT display_name,class_name FROM demo2_identity_students
                WHERE student_id=? AND owner_account_id=? AND scope_key=?""",
                (payload["student_id"], account["account_id"], binding["scope_key"])).fetchone()
            if student is None:
                raise ValueError("学生不属于当前学校")
            connection.execute("""CREATE TABLE IF NOT EXISTS demo2_simple_lesson_archives (
                archive_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, person_id TEXT NOT NULL,
                student_id TEXT NOT NULL, binding_id TEXT NOT NULL, owner_account_id TEXT NOT NULL,
                main_state TEXT NOT NULL, average_score REAL, key_times_json TEXT NOT NULL,
                state_breakdown_json TEXT NOT NULL, lesson_summary TEXT NOT NULL,
                iep_support_summary TEXT NOT NULL, created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL, UNIQUE(task_id, person_id, student_id)
            )""")
            now = _iso()
            archive_id = "sla_" + uuid4().hex
            connection.execute("""INSERT INTO demo2_simple_lesson_archives
                (archive_id,task_id,person_id,student_id,binding_id,owner_account_id,main_state,
                 average_score,key_times_json,state_breakdown_json,lesson_summary,iep_support_summary,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(task_id,person_id,student_id) DO UPDATE SET binding_id=excluded.binding_id,
                 main_state=excluded.main_state,average_score=excluded.average_score,key_times_json=excluded.key_times_json,
                 state_breakdown_json=excluded.state_breakdown_json,lesson_summary=excluded.lesson_summary,
                 iep_support_summary=excluded.iep_support_summary,updated_at=excluded.updated_at""",
                (archive_id, task["task_id"], payload["person_id"], payload["student_id"], payload["binding_id"],
                 account["account_id"], payload.get("main_state", ""), score,
                 json.dumps(key_times, ensure_ascii=False), json.dumps(breakdown, ensure_ascii=False),
                 payload.get("lesson_summary", "").strip(), payload.get("iep_support_summary", "").strip(), now, now))
            row = connection.execute("""SELECT archive_id,task_id,person_id,student_id,main_state,average_score,
                key_times_json,state_breakdown_json,lesson_summary,iep_support_summary,created_at,updated_at
                FROM demo2_simple_lesson_archives WHERE task_id=? AND person_id=? AND student_id=?""",
                (task["task_id"], payload["person_id"], payload["student_id"])).fetchone()
            self._audit(connection, account["username"], "simple_lesson_archived", "student_lesson_summary",
                        row["archive_id"], {"task_id": task["task_id"], "student_id": payload["student_id"],
                                            "person_id": payload["person_id"]})
        result = dict(row)
        result["key_times_sec"] = json.loads(result.pop("key_times_json"))
        result["state_breakdown"] = json.loads(result.pop("state_breakdown_json"))
        result["student_name"] = student["display_name"]
        result["class_name"] = student["class_name"]
        return result

    def account_simple_analysis_frame(
        self, session_token: str, task_id: str, frame_name: str,
        crop_bbox: dict[str, float] | None = None,
        source_preview: bool = False,
    ) -> tuple[Path, str]:
        account = self.account_from_session(session_token)
        if not isinstance(frame_name, str) or not re.fullmatch(r"frame_[0-9]{6}\.jpg", frame_name):
            raise ValueError("分析画面编号无效")
        with self._connect() as connection:
            task = self._authorized_video_task(connection, account, task_id)
            self._require_live_video(task)
            if task.get("analysis_status") not in READY_VIDEO_ANALYSIS_STATUSES:
                raise ValueError("分析结果尚未就绪")
            directory = self._video_analysis_dir(task_id)
            frames_dir = directory / "frames"
            # Current workers store all artifacts below a per-run directory
            # (for example media_<id>/frames). Older runs wrote frames directly
            # under the task directory, so keep that layout as a fallback.
            try:
                result = json.loads(task.get("processing_result_json") or "null")
            except (TypeError, ValueError):
                result = None
            artifacts = result.get("artifacts") if isinstance(result, dict) else None
            relative_frames = artifacts.get("frames") if isinstance(artifacts, dict) else None
            if isinstance(relative_frames, str) and relative_frames:
                relative = PurePosixPath(relative_frames.replace("\\", "/"))
                if (relative.is_absolute() or PureWindowsPath(relative_frames).drive
                        or ":" in relative_frames or ".." in relative.parts
                        or relative.name != "frames"):
                    raise ValueError("分析结果清单路径不在任务受控目录内")
                frames_dir = self._controlled_video_path(directory.joinpath(*relative.parts), "analysis")
                if directory not in frames_dir.parents:
                    raise ValueError("分析结果清单路径不在任务受控目录内")
            path = self._controlled_video_path(frames_dir / frame_name, "analysis")
            if not path.is_file():
                raise ValueError("分析画面不存在")
            if crop_bbox is not None:
                try:
                    values = {key: float(crop_bbox[key]) for key in ("x", "y", "width", "height")}
                except (KeyError, TypeError, ValueError, OverflowError):
                    raise ValueError("人物截图框无效") from None
                if (not all(math.isfinite(value) for value in values.values())
                        or values["x"] < 0 or values["y"] < 0
                        or values["width"] <= 0 or values["height"] <= 0
                        or values["x"] + values["width"] > 1
                        or values["y"] + values["height"] > 1):
                    raise ValueError("人物截图框无效")
                if source_preview:
                    path = self._simple_person_preview(task, result, directory, path, values)
                digest = hashlib.sha256(
                    json.dumps(
                        {"version": PERSON_CROP_VERSION, "bbox": values, "source": path.name},
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("ascii")
                ).hexdigest()[:16]
                crop_dir = self._controlled_video_path(directory / "person_crops", "analysis")
                crop_dir.mkdir(parents=True, exist_ok=True)
                crop_path = self._controlled_video_path(
                    crop_dir / f"{Path(frame_name).stem}_{digest}.jpg", "analysis"
                )
                if not crop_path.is_file():
                    try:
                        import cv2
                        import numpy as np
                        image = cv2.imdecode(
                            np.frombuffer(path.read_bytes(), dtype=np.uint8), cv2.IMREAD_COLOR
                        )
                        if image is None or image.ndim != 3:
                            raise ValueError
                        height, width = image.shape[:2]
                        x, y = values["x"] * width, values["y"] * height
                        box_width, box_height = values["width"] * width, values["height"] * height
                        # A compact head-and-shoulders crop avoids neighbouring
                        # faces. The UI uses contain, so no headroom is lost.
                        crop_width = min(float(width), max(box_width * 2.8, box_height * 2.8))
                        crop_height = min(float(height), max(box_height * 3.2, box_width * 3.2))
                        face_center_x = x + box_width / 2
                        crop_center_y = y + box_height * 0.55
                        left = int(round(min(max(face_center_x - crop_width / 2, 0), width - crop_width)))
                        top = int(round(min(max(crop_center_y - crop_height / 2, 0), height - crop_height)))
                        right = min(width, int(round(left + crop_width)))
                        bottom = min(height, int(round(top + crop_height)))
                        if right - left < 4 or bottom - top < 4:
                            raise ValueError
                        cropped = image[top:bottom, left:right]
                        ok, encoded = cv2.imencode(".jpg", cropped, [cv2.IMWRITE_JPEG_QUALITY, 88])
                        if not ok:
                            raise ValueError
                        with crop_path.open("xb") as handle:
                            handle.write(encoded.tobytes())
                    except FileExistsError:
                        pass
                    except (ImportError, OSError, ValueError):
                        raise ValueError("人物截图生成失败") from None
                path = crop_path
            self._audit(connection, account["username"], "read_media", "video_analysis_task", task_id,
                        {"asset": "simple_analysis_person_crop" if crop_bbox is not None else "simple_analysis_frame"})
        return path, "image/jpeg"

    def _simple_person_preview(self, task, result, directory, evidence, bbox):
        """Higher-resolution viewing aid; never replace stored evidence or bindings."""
        if not isinstance(result, dict):
            return evidence
        samples = [s for seg in result.get("segments", [])
                   for s in seg.get("visual", {}).get("samples", [])]
        index = int(evidence.stem.split("_")[-1])
        if index >= len(samples):
            return evidence
        sample = samples[index]
        named = sample.get("image_path")
        if named and Path(named).name != evidence.name:
            return evidence
        timestamp = sample.get("timestamp_sec")
        if type(timestamp) not in (int, float) or not math.isfinite(timestamp) or timestamp < 0:
            return evidence
        try:
            from .demo2_frame_preview import extract_preview
            import cv2
            import numpy as np
            source = self._video_source_path(task)
            signature = source.stat()
            key = hashlib.sha256(json.dumps([
                task.get("sha256"), signature.st_size, signature.st_mtime_ns,
                evidence.name, timestamp, evidence.stat().st_mtime_ns,
            ]).encode()).hexdigest()[:20]
            cache = self._controlled_video_path(directory / "person_previews", "analysis")
            cache.mkdir(exist_ok=True)
            preview = self._controlled_video_path(cache / f"source_{key}.jpg", "analysis")
            # Share one bounded decode between the three portrait requests.
            if not _PERSON_PREVIEW_LOCK.acquire(timeout=9):
                return evidence
            try:
                if not preview.is_file():
                    raw = extract_preview(source, float(timestamp))["image_bytes"]
                    temporary = self._controlled_video_path(cache / f"{key}_{uuid4().hex}.tmp", "analysis")
                    try:
                        with temporary.open("xb") as handle:
                            handle.write(raw)
                        os.replace(temporary, preview)
                    finally:
                        temporary.unlink(missing_ok=True)
            finally:
                _PERSON_PREVIEW_LOCK.release()
            original = cv2.imdecode(np.frombuffer(evidence.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
            larger = cv2.imdecode(np.frombuffer(preview.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
            if original is None or larger is None:
                return evidence
            h, w = original.shape[:2]
            lh, lw = larger.shape[:2]
            if lw <= w or abs((lw / lh) / (w / h) - 1) > .02:
                return evidence
            reduced = cv2.resize(larger, (w, h), interpolation=cv2.INTER_AREA)
            x1, y1 = int(bbox["x"] * w), int(bbox["y"] * h)
            x2, y2 = min(w, math.ceil((bbox["x"] + bbox["width"]) * w)), min(h, math.ceil((bbox["y"] + bbox["height"]) * h))
            # Seeking is not pixel-identical sampling. Reject a changed scene
            # or changed local face patch rather than show a different person.
            delta = cv2.absdiff(original, reduced)
            if delta.mean() > 25 or delta[y1:y2, x1:x2].mean() > 30:
                return evidence
            return preview
        except (ImportError, OSError, ValueError, KeyError, TypeError, RuntimeError):
            return evidence

    def _video_audio_path(self, task: dict[str, Any]) -> Path:
        # Only the persisted worker result may select an artifact. Never accept
        # a request-supplied file path or fall back from an invalid manifest.
        try:
            result = json.loads(task.get("processing_result_json") or "null")
        except (TypeError, ValueError):
            raise ValueError("音轨结果清单无效") from None
        if not isinstance(result, dict) or not result:
            raise ValueError("音轨结果清单无效")
        directory = self._video_analysis_dir(task["task_id"])
        if "artifacts" not in result:
            # Older completed worker results wrote directly to the task root.
            return self._controlled_video_path(directory / "audio.wav", "analysis")
        artifacts = result["artifacts"]
        if not isinstance(artifacts, dict):
            raise ValueError("音轨结果清单无效")
        audio = artifacts.get("audio")
        if audio is None:
            raise ValueError("分析结果中不存在音轨")
        if not isinstance(audio, str) or not audio or any(ord(char) < 32 for char in audio):
            raise ValueError("音轨结果清单路径无效")
        relative = PurePosixPath(audio.replace("\\", "/"))
        if (relative.is_absolute() or PureWindowsPath(audio).drive or ":" in audio
                or ".." in relative.parts or relative.name != "audio.wav"):
            raise ValueError("音轨结果清单路径不在任务受控目录内")
        path = self._controlled_video_path(directory.joinpath(*relative.parts), "analysis")
        if directory not in path.parents:
            raise ValueError("音轨结果清单路径不在任务受控目录内")
        return path

    def account_video_media(self, session_token: str, task_id: str, asset: str = "source") -> tuple[Path, str]:
        if asset not in {"source", "audio"}:
            raise ValueError("不支持的媒体类型")
        account = self.account_from_session(session_token)
        with self._connect() as connection:
            task = self._authorized_video_task(connection, account, task_id)
            self._require_live_video(task)
            source = self._video_source_path(task)
            if not source.is_file():
                raise ValueError("原视频不存在，派生音轨也不可读取")
            if asset == "source":
                path, mime = source, mimetypes.guess_type(source.name)[0] or "application/octet-stream"
            else:
                if task["analysis_status"] not in {"evidence_ready", "completed"}:
                    raise ValueError("音轨尚未处理完成")
                path = self._video_audio_path(task)
                mime = "audio/wav"
            if not path.is_file():
                raise ValueError("媒体文件不存在")
            self._audit(connection, account["username"], "read_media", "video_analysis_task", task_id, {"asset": asset})
        return path, mime

    def _remove_video_analysis_artifacts(self, task_id: str) -> None:
        directory = self._video_analysis_dir(task_id)
        if not directory.exists():
            return
        # Validate the whole tree before deleting anything; never follow links.
        pending, files, directories = [directory], [], []
        while pending:
            current = self._controlled_video_path(pending.pop(), "analysis")
            if current.is_dir():
                directories.append(current)
                pending.extend(current.iterdir())
            elif current.is_file():
                files.append(current)
            else:
                raise ValueError("派生数据目录包含不支持的文件类型")
        for path in files:
            self._controlled_video_path(path, "analysis").unlink()
        for path in sorted(directories, key=lambda item: len(item.parts), reverse=True):
            self._controlled_video_path(path, "analysis").rmdir()

    def claim_next_video_analysis(self) -> dict[str, Any] | None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute("SELECT 1 FROM video_analysis_tasks WHERE analysis_status = 'processing' LIMIT 1").fetchone():
                return None
            rows = connection.execute(
                "SELECT * FROM video_analysis_tasks WHERE analysis_status = 'queued' ORDER BY created_at, rowid"
            ).fetchall()
            for row in rows:
                task = dict(row)
                try:
                    self._require_live_video(task)
                    source = self._video_source_path(task)
                    if not source.is_file():
                        raise ValueError("原视频不存在，无法开始处理")
                    self._remove_video_analysis_artifacts(task["task_id"])
                    directory = self._video_analysis_dir(task["task_id"])
                    directory.mkdir(parents=True, exist_ok=True)
                except (OSError, ValueError):
                    connection.execute(
                        "UPDATE video_analysis_tasks SET analysis_status = 'failed', processing_stage = 'failed', "
                        "processing_error_json = ?, updated_at = ? WHERE task_id = ?",
                        (json.dumps({"code": "media_unavailable", "message": "原视频已到期、缺失或路径无效"}, ensure_ascii=False),
                         _iso(), task["task_id"]),
                    )
                    self._audit(connection, "analysis_worker", "analysis_rejected", "video_analysis_task", task["task_id"], {"code": "media_unavailable"})
                    continue
                claim_id = uuid4().hex
                connection.execute(
                    """UPDATE video_analysis_tasks SET analysis_status = 'processing', processing_stage = 'starting',
                       processing_progress = 0, processing_error_json = '{}', attempt_count = attempt_count + 1,
                       processing_claim_id = ?, updated_at = ? WHERE task_id = ?""",
                    (claim_id, _iso(), task["task_id"]),
                )
                self._audit(connection, "analysis_worker", "analysis_claimed", "video_analysis_task", task["task_id"],
                            {"attempt_count": task["attempt_count"] + 1})
                claimed = self._video_task_row(connection, task["task_id"])
                claimed["analysis_dir"] = str(directory)
                claimed["processing_config"] = json.loads(claimed["processing_config_json"])
                self._analysis_claims[task["task_id"]] = claim_id
                return claimed
        return None

    def _claimed_video_task(self, connection: sqlite3.Connection, task_id: str) -> dict[str, Any]:
        task = self._video_task_row(connection, task_id)
        claim_id = self._analysis_claims.get(task_id)
        if not claim_id or task["analysis_status"] != "processing" or task["processing_claim_id"] != claim_id:
            raise ValueError("当前 worker 未领取此任务，或本次处理已失效")
        return task

    def update_video_analysis_progress(self, task_id: str, stage: str, progress: int) -> dict[str, Any]:
        if not isinstance(stage, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,79}", stage):
            raise ValueError("处理阶段编号无效")
        if isinstance(progress, bool) or not isinstance(progress, (int, float)) or not 0 <= progress <= 100:
            raise ValueError("处理进度必须在 0 至 100 之间")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            task = self._claimed_video_task(connection, task_id)
            self._require_live_video(task)
            connection.execute(
                "UPDATE video_analysis_tasks SET processing_stage = ?, processing_progress = ?, updated_at = ? WHERE task_id = ?",
                (stage, max(task["processing_progress"], min(99, int(progress))), _iso(), task_id),
            )
            return self._public_video_task(self._video_task_row(connection, task_id))

    def finish_video_analysis(self, task_id: str, result: dict[str, Any]) -> dict[str, Any]:
        version = result.get("analysis_version", result.get("version")) if isinstance(result, dict) else None
        if not isinstance(version, str) or not 1 <= len(version.strip()) <= 120 or not (
            "content" in result or (isinstance(result.get("media"), dict) and isinstance(result.get("segments"), list))
        ):
            raise ValueError("分析结果必须包含处理版本和结果内容")
        if result.get("task_id", task_id) != task_id:
            raise ValueError("分析结果与任务编号不一致")
        encoded = _processing_json(_public_processing_data(result), max_bytes=MAX_PROCESSING_RESULT_BYTES)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._video_task_row(connection, task_id)
            if existing["analysis_status"] in {"evidence_ready", "completed"} and existing["processing_result_json"] == encoded:
                return self._public_video_task(existing)
            task = self._claimed_video_task(connection, task_id)
            self._require_live_video(task)
            if not self._video_source_path(task).is_file():
                raise ValueError("原视频已不存在，不能完成处理")
            result_path = self._controlled_video_path(self.video_task_dir.resolve() / "results" / f"{task_id}.json", "results")
            result_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._controlled_video_path(result_path.with_suffix(f".{uuid4().hex}.tmp"), "results")
            try:
                with temporary.open("x", encoding="utf-8") as handle:
                    handle.write(encoded)
                    handle.flush()
                    os.fsync(handle.fileno())
                temporary.replace(result_path)
            finally:
                temporary.unlink(missing_ok=True)
            connection.execute(
                """UPDATE video_analysis_tasks SET analysis_status = 'evidence_ready', processing_stage = 'evidence_ready',
                   processing_progress = 100, processing_error_json = '{}', processing_result_json = ?,
                   result_path = ?, processing_claim_id = '', updated_at = ? WHERE task_id = ?""",
                (encoded, str(result_path), _iso(), task_id),
            )
            self._audit(connection, "analysis_worker", "analysis_completed", "video_analysis_task", task_id,
                        {"version": version, "attempt_count": task["attempt_count"]})
            public = self._public_video_task(self._video_task_row(connection, task_id))
        self._analysis_claims.pop(task_id, None)
        return public

    def fail_video_analysis(self, task_id: str, code: str, message: str) -> dict[str, Any]:
        if not isinstance(code, str) or not re.fullmatch(r"[A-Za-z0-9_]{1,80}", code):
            raise ValueError("处理错误编号无效")
        if not isinstance(message, str) or not message.strip():
            raise ValueError("请提供处理错误说明")
        message = re.sub(r"(?:[A-Za-z]:[\\/]|file://|/)[^\s\"'<>]+", "[受控文件]", message)
        error = {"code": code, "message": " ".join(message.split())[:500]}
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._claimed_video_task(connection, task_id)
            connection.execute(
                "UPDATE video_analysis_tasks SET analysis_status = 'failed', processing_stage = 'failed', "
                "processing_error_json = ?, processing_claim_id = '', updated_at = ? WHERE task_id = ?",
                (json.dumps(error, ensure_ascii=False), _iso(), task_id),
            )
            self._audit(connection, "analysis_worker", "analysis_failed", "video_analysis_task", task_id, {"code": code})
            public = self._public_video_task(self._video_task_row(connection, task_id))
        self._analysis_claims.pop(task_id, None)
        return public

    def recover_interrupted_video_analysis(self) -> dict[str, Any]:
        """Call once at worker startup after the old worker has stopped, never on requests."""
        recovered = []
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute("SELECT * FROM video_analysis_tasks WHERE analysis_status = 'processing'").fetchall()
            for row in rows:
                task = dict(row)
                try:
                    self._require_live_video(task)
                    if not self._video_source_path(task).is_file():
                        raise ValueError("原视频不存在")
                    status, error = "queued", {}
                    recovered.append(task["task_id"])
                except (OSError, ValueError):
                    status, error = "failed", {"code": "media_unavailable", "message": "原视频已到期、删除或缺失"}
                connection.execute(
                    "UPDATE video_analysis_tasks SET analysis_status = ?, processing_stage = ?, processing_progress = 0, "
                    "processing_claim_id = '', processing_error_json = ?, updated_at = ? WHERE task_id = ?",
                    (status, status, json.dumps(error, ensure_ascii=False), _iso(), task["task_id"]),
                )
                self._analysis_claims.pop(task["task_id"], None)
                self._audit(connection, "analysis_worker", "analysis_recovered", "video_analysis_task", task["task_id"], {"status": status})
        return {"recovered_count": len(recovered), "recovered_task_ids": recovered}

    def retry_account_video_analysis(self, session_token: str, task_id: str) -> dict[str, Any]:
        return self._enqueue_account_video_analysis(session_token, task_id, legacy=False)

    def enqueue_legacy_video_analysis(self, session_token: str, task_id: str) -> dict[str, Any]:
        return self._enqueue_account_video_analysis(session_token, task_id, legacy=True)

    def _enqueue_account_video_analysis(self, session_token: str, task_id: str, *, legacy: bool) -> dict[str, Any]:
        account = self.account_from_session(session_token)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            task = self._authorized_video_task(connection, account, task_id)
            allowed = LEGACY_VIDEO_ANALYSIS_STATUSES if legacy else {"failed"}
            if task["analysis_status"] not in allowed:
                raise ValueError("仅旧预检任务可显式加入处理队列" if legacy else "仅失败任务可重试")
            self._require_live_video(task)
            if not self._video_source_path(task).is_file():
                raise ValueError("原视频不存在，无法重新处理")
            config_hash = _token_hash(task["processing_config_json"])
            connection.execute(
                """UPDATE video_analysis_tasks SET analysis_status = 'queued', processing_stage = 'queued',
                   processing_progress = 0, processing_error_json = '{}', processing_claim_id = '',
                   processing_config_hash = ?, processing_key = ?, updated_at = ? WHERE task_id = ?""",
                (config_hash, _token_hash(f"{task_id}:{task['sha256']}:{config_hash}"), _iso(), task_id),
            )
            self._audit(connection, account["username"], "analysis_enqueued" if legacy else "analysis_retry",
                        "video_analysis_task", task_id, {"configuration_unchanged": True})
            return self._public_video_task(self._video_task_row(connection, task_id))

    def enforce_raw_media_retention(
        self,
        *,
        now: datetime | None = None,
        actor: str = "system_retention",
    ) -> dict[str, Any]:
        scan_time = now or _now()
        scan_iso = _iso(scan_time)
        deleted_task_ids: list[str] = []
        failed: list[dict[str, str]] = []
        with self._upload_lock:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                policy = connection.execute(
                    "SELECT auto_delete FROM retention_policies WHERE data_type = 'raw_media'"
                ).fetchone()
                if policy is None or not bool(policy["auto_delete"]):
                    return {
                        "scanned_at": scan_iso,
                        "auto_delete": False,
                        "deleted_count": 0,
                        "deleted_task_ids": [],
                        "failed": [],
                    }
                rows = connection.execute(
                    """
                    SELECT * FROM video_analysis_tasks
                    WHERE julianday(expires_at) <= julianday(?)
                      AND upload_status NOT IN ('cancelled', 'expired')
                    ORDER BY expires_at, created_at
                    """,
                    (scan_iso,),
                ).fetchall()

                for row in rows:
                    task = dict(row)
                    try:
                        directory = self._video_analysis_dir(task["task_id"])
                        final_path = self._controlled_video_path(Path(task["file_path"]), "uploads")
                        part_path = self._controlled_video_path(Path(f"{task['file_path']}.part"), "uploads")
                        if task["raw_media_deleted_at"] and not any(path.exists() for path in (directory, final_path, part_path)):
                            continue
                        raw_media_present = final_path.is_file()
                        derived_media_present = False
                        # An idempotent unlink is not proof that evidence existed
                        # immediately before scheduled deletion.
                        from .demo2_identity_store import Demo2IdentityStore, IdentityError
                        try:
                            frames = Demo2IdentityStore._parse_frames(task)
                            derived_media_present = bool(frames) and all(
                                self._controlled_video_path(directory.joinpath(
                                    *Demo2IdentityStore._image_parts(frame["relative_image"]).parts
                                ), "analysis").is_file() for frame in frames.values()
                            )
                        except (IdentityError, ValueError, TypeError, OSError):
                            pass
                        self._remove_video_analysis_artifacts(task["task_id"])
                        final_path.unlink(missing_ok=True)
                        part_path.unlink(missing_ok=True)
                        next_upload_status = (
                            "expired" if task["upload_status"] == "uploading" else task["upload_status"]
                        )
                        next_analysis_status = (
                            task["analysis_status"] if task["analysis_status"] in READY_VIDEO_ANALYSIS_STATUSES else "expired"
                        )
                        connection.execute(
                            """
                            UPDATE video_analysis_tasks
                            SET raw_media_deleted_at = ?, upload_status = ?, analysis_status = ?, processing_claim_id = '',
                                processing_stage = ?, updated_at = ? WHERE task_id = ?
                            """,
                            (
                                scan_iso,
                                next_upload_status,
                                next_analysis_status,
                                task["processing_stage"] if next_analysis_status in READY_VIDEO_ANALYSIS_STATUSES else "expired",
                                scan_iso,
                                task["task_id"],
                            ),
                        )
                        self._analysis_claims.pop(task["task_id"], None)
                        self._audit(
                            connection,
                            actor,
                            "retention_delete",
                            "video_raw_media",
                            task["task_id"],
                            {
                                "course_id": task["course_id"],
                                "expired_at": task["expires_at"],
                                "structured_result_preserved": bool(task.get("result_path")),
                                "derived_media_deleted": True,
                                "raw_media_present_before_delete": raw_media_present,
                                "derived_media_present_before_delete": derived_media_present,
                            },
                        )
                        deleted_task_ids.append(task["task_id"])
                    except (OSError, ValueError) as exc:
                        failed.append({"task_id": task["task_id"], "error": str(exc)})
                        self._audit(
                            connection,
                            actor,
                            "retention_delete_failed",
                            "video_raw_media",
                            task["task_id"],
                            {"error": str(exc)},
                        )

        return {
            "scanned_at": scan_iso,
            "auto_delete": True,
            "deleted_count": len(deleted_task_ids),
            "deleted_task_ids": deleted_task_ids,
            "failed": failed,
        }

    def video_result_for_download(self, task_id: str) -> tuple[Path, str]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT result_path, original_filename, analysis_status FROM video_analysis_tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        if row is None or not row["result_path"] or row["analysis_status"] not in READY_VIDEO_ANALYSIS_STATUSES:
            raise ValueError("该任务尚无可下载结果")
        path = self._controlled_video_path(Path(row["result_path"]), "results")
        if not path.is_file():
            raise ValueError("分析结果文件不存在")
        result_label = (
            "上传预检结果" if row["analysis_status"] in LEGACY_VIDEO_ANALYSIS_STATUSES else "视频证据记录"
        )
        return path, f"{Path(row['original_filename']).stem}_{result_label}.json"

    def account_video_result_for_download(
        self,
        session_token: str,
        task_id: str,
    ) -> tuple[Path, str]:
        account = self.account_from_session(session_token)
        normalized_task_id = str(task_id or "").strip()
        with self._connect() as connection:
            task = connection.execute(
                "SELECT * FROM video_analysis_tasks WHERE task_id = ?",
                (normalized_task_id,),
            ).fetchone()
        if task is None:
            raise ValueError("未找到视频任务")
        if account["role"] == "school_uploader":
            if task["account_id"] != account["account_id"]:
                raise ValueError("无权下载其他上传账号的任务结果")
        elif account["role"] != "company_admin":
            raise ValueError("该账号没有视频结果下载权限")

        path, filename = self.video_result_for_download(normalized_task_id)
        from .demo2_media_analysis import SIMPLE_ANALYSIS_VERSION
        cache = self._read_simple_analysis_cache(dict(task), SIMPLE_ANALYSIS_VERSION)
        from .demo2_student_tracking import present_motion_analysis
        # Present repaired prose in a derived export; source evidence remains immutable.
        with path.open("rb") as handle:
            raw = handle.read(MAX_PROCESSING_RESULT_BYTES + 1)
        if len(raw) > MAX_PROCESSING_RESULT_BYTES:
            raise ValueError("分析报告超过读取限制")
        document = json.loads(raw)
        has_cache = bool(cache and cache["status"] == "completed")
        selected = cache["analysis"] if has_cache else document.get("simple_student_analysis")
        presented = present_motion_analysis(selected)
        if has_cache or presented != selected:
            document["simple_student_analysis"] = presented
            encoded = _processing_json(document, max_bytes=MAX_PROCESSING_RESULT_BYTES)
            # Content changes must get a fresh name; previous exports are preserved.
            digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
            cache_path, _ = self._simple_analysis_cache_path(dict(task), SIMPLE_ANALYSIS_VERSION)
            exported = self._controlled_video_path(
                cache_path.with_name(f"simple_export_{SIMPLE_ANALYSIS_VERSION}_{digest}.json"), "analysis")
            if not exported.is_file():
                temporary = self._controlled_video_path(exported.with_suffix(f".{uuid4().hex}.tmp"), "analysis")
                try:
                    with temporary.open("x", encoding="utf-8") as handle:
                        handle.write(encoded)
                    temporary.replace(exported)
                finally:
                    temporary.unlink(missing_ok=True)
            path = exported
        with self._connect() as connection:
            self._audit(
                connection,
                account["username"],
                "download",
                "video_analysis_result",
                normalized_task_id,
                {"account_id": account["account_id"], "role": account["role"]},
            )
        return path, filename

    @staticmethod
    def _build_video_precheck(task: dict[str, Any], path: Path) -> dict[str, Any]:
        result: dict[str, Any] = {
            "task_id": task["task_id"],
            "channel_id": task["channel_id"],
            "session_id": task["session_id"],
            "course_name": task["course_name"],
            "subject_id": task["subject_id"],
            "filename": task["original_filename"],
            "byte_size": task["byte_size"],
            "generated_at": _iso(),
            "analysis_scope": "上传完整性与视频质量预检，不是学生课堂状态结论",
            "analysis_status": "precheck_complete",
            "video_quality": {},
            "next_step": "绑定课程目标、学生身份/座位区域和教师复核责任后，进入课堂状态模型分析。",
        }
        try:
            import cv2  # type: ignore

            capture = cv2.VideoCapture(str(path))
            if not capture.isOpened():
                raise RuntimeError("OpenCV 无法读取视频")
            frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
            width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
            duration_sec = frame_count / fps if fps > 0 else 0.0
            sample_count = min(40, max(1, frame_count))
            sample_indices = [int(index * max(0, frame_count - 1) / max(1, sample_count - 1)) for index in range(sample_count)]
            brightness_values: list[float] = []
            sharpness_values: list[float] = []
            motion_values: list[float] = []
            previous = None
            for frame_index in sample_indices:
                capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
                ok, frame = capture.read()
                if not ok:
                    continue
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                brightness_values.append(float(gray.mean()))
                sharpness_values.append(float(cv2.Laplacian(gray, cv2.CV_64F).var()))
                reduced = cv2.resize(gray, (160, 90))
                if previous is not None:
                    motion_values.append(float(cv2.absdiff(reduced, previous).mean()))
                previous = reduced
            capture.release()
            brightness = sum(brightness_values) / len(brightness_values) if brightness_values else 0.0
            sharpness = sum(sharpness_values) / len(sharpness_values) if sharpness_values else 0.0
            motion = sum(motion_values) / len(motion_values) if motion_values else 0.0
            readable = bool(width and height and duration_sec > 0 and brightness_values)
            quality_score = 0
            quality_score += 35 if min(width, height) >= 720 else 20 if min(width, height) >= 480 else 8
            quality_score += 30 if 45 <= brightness <= 210 else 15 if 25 <= brightness <= 230 else 5
            quality_score += 25 if sharpness >= 70 else 15 if sharpness >= 30 else 5
            quality_score += 10 if fps >= 15 else 5
            grade = "适合进入课堂分析" if quality_score >= 75 else "可用但建议教师复核" if quality_score >= 55 else "建议更换或补充视频"
            result["video_quality"] = {
                "readable": readable,
                "duration_sec": round(duration_sec, 2),
                "fps": round(fps, 2),
                "resolution": f"{width}x{height}",
                "sampled_frames": len(brightness_values),
                "mean_brightness": round(brightness, 2),
                "mean_sharpness": round(sharpness, 2),
                "mean_motion": round(motion, 2),
                "quality_score": quality_score,
                "quality_grade": grade,
            }
        except (ImportError, RuntimeError, OSError) as exc:
            result["analysis_status"] = "uploaded_pending_worker"
            result["video_quality"] = {
                "readable": None,
                "quality_grade": "文件已完整上传，当前环境未完成视频解码",
                "detail": str(exc),
            }
        return result

    def update_policy(self, payload: dict[str, Any], *, actor: str = "local_admin") -> dict[str, Any]:
        data_type = str(payload.get("data_type", "")).strip()
        retention_days = int(payload.get("retention_days", 0))
        reminder_days = int(payload.get("reminder_days", 15))
        if data_type not in DEFAULT_POLICIES:
            raise ValueError("未知的数据类型")
        if not 1 <= retention_days <= 3650:
            raise ValueError("保存期限必须在 1 至 3650 天之间")
        if not 1 <= reminder_days < retention_days:
            raise ValueError("提醒时间必须大于 0 且小于保存期限")
        auto_delete = bool(payload.get("auto_delete", False))
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE retention_policies
                SET retention_days = ?, reminder_days = ?, auto_delete = ?, updated_at = ?
                WHERE data_type = ?
                """,
                (retention_days, reminder_days, int(auto_delete), _iso(), data_type),
            )
            self._audit(connection, actor, "update", "retention_policy", data_type, {
                "retention_days": retention_days,
                "reminder_days": reminder_days,
                "auto_delete": auto_delete,
            })
            row = connection.execute(
                "SELECT * FROM retention_policies WHERE data_type = ?", (data_type,)
            ).fetchone()
        return self._public_policy(dict(row))

    def storage_summary(self) -> dict[str, Any]:
        with self._connect() as connection:
            sqlite_user_version = connection.execute("PRAGMA user_version").fetchone()[0]
            policies = [
                self._public_policy(dict(row))
                for row in connection.execute("SELECT * FROM retention_policies ORDER BY rowid")
            ]
            counts = {
                "students": connection.execute("SELECT COUNT(*) FROM students WHERE status = 'active'").fetchone()[0],
                "documents": connection.execute("SELECT COUNT(*) FROM student_documents WHERE status = 'active'").fetchone()[0],
                "profiles": connection.execute("SELECT COUNT(*) FROM student_support_profiles").fetchone()[0],
                "video_tasks": connection.execute("SELECT COUNT(*) FROM video_analysis_tasks").fetchone()[0],
                "security_acceptances": connection.execute("SELECT COUNT(*) FROM data_security_acceptances").fetchone()[0],
                "archive_records": connection.execute("SELECT COUNT(*) FROM long_term_resource_records").fetchone()[0],
                "audit_events": connection.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0],
                "accounts": connection.execute("SELECT COUNT(*) FROM platform_accounts").fetchone()[0],
                "active_sessions": connection.execute(
                    "SELECT COUNT(*) FROM account_sessions WHERE revoked_at = '' AND expires_at > ?",
                    (_iso(),),
                ).fetchone()[0],
            }
            recent_documents = [
                self._public_document(dict(row))
                for row in connection.execute(
                    "SELECT * FROM student_documents WHERE status = 'active' ORDER BY created_at DESC LIMIT 12"
                )
            ]
            video_tasks = [
                self._public_video_task(dict(row))
                for row in connection.execute(
                    """
                    SELECT * FROM video_analysis_tasks
                    WHERE upload_status = 'completed' ORDER BY expires_at ASC
                    """
                )
            ]
            expiry_reminders = [
                task for task in video_tasks if task["retention_state"] in {"due_soon", "expired"}
            ]
            archive_records = [
                self._public_resource(dict(row))
                for row in connection.execute(
                    """
                    SELECT * FROM long_term_resource_records
                    ORDER BY created_at DESC LIMIT 12
                    """
                )
            ]
            recent_acceptance = connection.execute(
                """
                SELECT * FROM data_security_acceptances
                ORDER BY accepted_at DESC LIMIT 1
                """
            ).fetchone()
        reports = []
        if REPORT_DIR.exists():
            for path in sorted(REPORT_DIR.glob("*"), key=lambda item: item.stat().st_mtime, reverse=True)[:12]:
                if not path.is_file():
                    continue
                reports.append({
                    "filename": path.name,
                    "byte_size": path.stat().st_size,
                    "updated_at": datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="seconds"),
                    "download_url": f"/assets/seewo_demo2/reports/{path.name}",
                })
        return {
            "database": {
                "engine": "SQLite 3",
                # Keep the established Demo2 storage-summary contract while exposing
                # the additive account/session schema version separately.
                "schema_version": 2,
                "sqlite_user_version": sqlite_user_version,
                "location": str(self.db_path.resolve()),
                "byte_size": self.db_path.stat().st_size if self.db_path.exists() else 0,
                "status": "本地数据库运行中",
            },
            "document_storage": {
                "location": str(self.upload_dir.resolve()),
                "byte_size": _directory_size(self.upload_dir),
            },
            "report_storage": {
                "location": str(REPORT_DIR.resolve()),
                "byte_size": _directory_size(REPORT_DIR),
            },
            "video_task_storage": {
                "location": str(self.video_task_dir.resolve()),
                "byte_size": _directory_size(self.video_task_dir),
            },
            "cloud": {
                "configured": False,
                "status": "公司长期数据库尚未连接；已提供脱敏资源授权归档队列",
                "planned_architecture": "学校私有空间 / PostgreSQL + 对象存储 + HTTPS + 角色权限 + 审计",
            },
            "counts": counts,
            "policies": policies,
            "recent_documents": recent_documents,
            "expiry_reminders": expiry_reminders,
            "archive_records": archive_records,
            "latest_security_acceptance": (
                self._public_acceptance(dict(recent_acceptance)) if recent_acceptance else None
            ),
            "reports": reports,
            "scope_note": "新上传原始视频按 60 天保存并在到期前 15 天提醒；公司长期资源仅登记经授权的脱敏结构化结果，默认不含原始学生视频。",
        }

    @staticmethod
    def _public_account(row: dict[str, Any]) -> dict[str, Any]:
        account = {
            key: row.get(key)
            for key in (
                "account_id",
                "username",
                "role",
                "bound_channel_id",
                "course_upload_limit",
                "status",
                "created_at",
                "updated_at",
            )
        }
        account["login_alias"] = next(
            (alias for alias, username in PILOT_ACCOUNT_ALIASES.items() if username == row.get("username")),
            row.get("username", ""),
        )
        return account

    @staticmethod
    def _public_document(row: dict[str, Any]) -> dict[str, Any]:
        row = dict(row)
        row.pop("file_path", None)
        row["document_type_label"] = DOCUMENT_TYPE_LABELS.get(row.get("document_type"), "其他资料")
        row["download_url"] = f"/api/seewo_demo2/document_download?id={row.get('document_id', '')}"
        return row

    @staticmethod
    def _public_policy(row: dict[str, Any]) -> dict[str, Any]:
        row = dict(row)
        row["auto_delete"] = bool(row.get("auto_delete"))
        row["downloadable"] = bool(row.get("downloadable"))
        return row

    @staticmethod
    def _public_acceptance(row: dict[str, Any]) -> dict[str, Any]:
        row = dict(row)
        row["allow_company_archive"] = bool(row.get("allow_company_archive"))
        try:
            row["authorized_scope"] = json.loads(row.pop("authorized_scope_json", "{}"))
        except json.JSONDecodeError:
            row["authorized_scope"] = {}
        return row

    @staticmethod
    def _public_resource(row: dict[str, Any]) -> dict[str, Any]:
        row = dict(row)
        row.pop("payload_json", None)
        row["status_label"] = {
            "local_approved_pending_company_sync": "已授权，等待公司数据库接入",
            "synced": "已同步公司数据库",
        }.get(row.get("status"), "待处理")
        return row

    @staticmethod
    def _public_video_task(row: dict[str, Any]) -> dict[str, Any]:
        row = dict(row)
        row.pop("file_path", None)
        row.pop("result_path", None)
        row.pop("processing_claim_id", None)
        row.pop("processing_result_json", None)
        row["processing_config"] = _public_processing_data(json.loads(row.pop("processing_config_json", "{}")))
        row["processing_error"] = _public_processing_data(json.loads(row.pop("processing_error_json", "{}"))) or None
        row.setdefault("processing_progress", 0)
        row.setdefault("processing_stage", "waiting_upload")
        row.setdefault("attempt_count", 0)
        context = json.loads(row.pop("school_context_json", "{}"))
        row["school_context"] = {key: context.get(key, "") for key in SCHOOL_CONTEXT_LIMITS}
        total = max(1, int(row.get("byte_size", 0)))
        progress = round(int(row.get("received_bytes", 0)) * 100 / total)
        row["progress_percent"] = (
            100 if row.get("upload_status") == "completed" else min(99, progress)
        )
        row["result_download_url"] = (
            f"/api/seewo_demo2/video_result_download?id={row.get('task_id', '')}"
            if row.get("analysis_status") in READY_VIDEO_ANALYSIS_STATUSES
            else ""
        )
        row["secure_result_download_url"] = (
            f"/api/v1/demo2/upload/result?id={row.get('task_id', '')}"
            if row.get("analysis_status") in READY_VIDEO_ANALYSIS_STATUSES
            else ""
        )
        try:
            expires_at = datetime.fromisoformat(str(row.get("expires_at", "")))
            remaining = (expires_at - _now()).total_seconds() / 86400
            days_remaining = max(0, ceil(remaining))
        except (TypeError, ValueError):
            days_remaining = 0
        reminder_days = int(row.get("reminder_days", 15) or 15)
        row["days_remaining"] = days_remaining
        row["retention_state"] = (
            "deleted"
            if row.get("raw_media_deleted_at")
            else "expired"
            if days_remaining <= 0
            else "due_soon"
            if days_remaining <= reminder_days
            else "active"
        )
        row["retention_label"] = {
            "deleted": "原视频已按期删除，结构化记录保留",
            "expired": "已到期，等待受控删除",
            "due_soon": f"即将到期，剩余 {days_remaining} 天",
            "active": f"本地保存中，剩余 {days_remaining} 天",
        }[row["retention_state"]]
        task_id = quote(str(row.get("task_id", "")), safe="")
        row["result_url"] = row["secure_result_download_url"]
        row["review_url"] = f"/demo2/video?id={task_id}"
        row["media_url"] = (
            f"/api/v1/demo2/upload/media?id={task_id}&asset=source"
            if row.get("upload_status") == "completed" and row["retention_state"] not in {"expired", "deleted"}
            else ""
        )
        return row

    @staticmethod
    def _audit(
        connection: sqlite3.Connection,
        actor: str,
        action: str,
        object_type: str,
        object_id: str,
        detail: dict[str, Any],
    ) -> None:
        connection.execute(
            """
            INSERT INTO audit_logs(actor, action, object_type, object_id, detail_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (actor, action, object_type, object_id, json.dumps(detail, ensure_ascii=False), _iso()),
        )


_DEFAULT_STORE: Demo2StudentRecordStore | None = None


def get_demo2_student_store() -> Demo2StudentRecordStore:
    global _DEFAULT_STORE
    if _DEFAULT_STORE is None:
        db_path = Path(os.getenv("REHAB_DEMO2_DB_PATH", str(DEFAULT_DB_PATH)))
        default_upload = DEFAULT_UPLOAD_DIR if db_path.resolve() == DEFAULT_DB_PATH.resolve() else db_path.parent / "student_documents"
        upload_dir = Path(os.getenv("REHAB_DEMO2_UPLOAD_DIR", str(default_upload)))
        if db_path.resolve() != DEFAULT_DB_PATH.resolve() and upload_dir.resolve() == DEFAULT_UPLOAD_DIR.resolve():
            raise ValueError("An alternate database cannot use the live default student document directory")
        _DEFAULT_STORE = Demo2StudentRecordStore(db_path=db_path, upload_dir=upload_dir)
    return _DEFAULT_STORE


def main() -> None:
    import argparse
    import getpass

    parser = argparse.ArgumentParser(description="Explicit maintenance of existing Demo2 pilot accounts")
    parser.add_argument("command", choices=["set-pilot-passwords"])
    parser.add_argument("--db", type=Path, required=True, help="Existing initialized SQLite database")
    args = parser.parse_args()
    passwords = {}
    for alias in PILOT_ACCOUNT_ALIASES:
        password = getpass.getpass(f"New password for {alias} (8-128 characters): ")
        if password != getpass.getpass(f"Confirm password for {alias}: "):
            parser.exit(1, "Passwords did not match; no changes made.\n")
        passwords[alias] = password
    try:
        result = Demo2StudentRecordStore.set_seeded_pilot_passwords(args.db, passwords)
    except (ValueError, sqlite3.Error):
        parser.exit(1, "No changes made. Check the existing seeded database and five distinct 8-128 character passwords.\n")
    print(f"Updated {len(result['updated_accounts'])} seeded accounts and revoked their sessions.")


if __name__ == "__main__":
    main()
