from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import os
import re
import sqlite3
import zipfile
from datetime import datetime, timedelta
from math import ceil
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4
from xml.etree import ElementTree


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "outputs" / "seewo_demo2" / "rehab_affect_demo2.sqlite3"
DEFAULT_UPLOAD_DIR = PROJECT_ROOT / "outputs" / "seewo_demo2" / "student_documents"
REPORT_DIR = PROJECT_ROOT / "outputs" / "seewo_demo2" / "reports"
VIDEO_TASK_DIR = PROJECT_ROOT / "outputs" / "seewo_demo2" / "video_tasks"
MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
MAX_VIDEO_BYTES = 5 * 1024 * 1024 * 1024
MAX_VIDEO_CHUNK_BYTES = 4 * 1024 * 1024
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
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

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

                CREATE TABLE IF NOT EXISTS video_analysis_tasks (
                    task_id TEXT PRIMARY KEY,
                    channel_id TEXT NOT NULL REFERENCES video_upload_channels(channel_id),
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
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
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
            connection.execute("PRAGMA user_version = 2")

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
            "max_video_bytes": MAX_VIDEO_BYTES,
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

    def create_video_task(self, payload: dict[str, Any], *, actor: str = "local_uploader") -> dict[str, Any]:
        channel_id = str(payload.get("channel_id", "")).strip()
        uploader_name = str(payload.get("uploader_name", "")).strip()
        course_name = str(payload.get("course_name", "")).strip()
        session_id = str(payload.get("session_id", "")).strip()
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
        if not 0 < byte_size <= MAX_VIDEO_BYTES:
            raise ValueError("视频大小必须在 1B 至 5GB 之间")
        expected_chunks = (byte_size + MAX_VIDEO_CHUNK_BYTES - 1) // MAX_VIDEO_CHUNK_BYTES
        if total_chunks != expected_chunks:
            raise ValueError("分片数量与文件大小不一致")
        with self._connect() as connection:
            if connection.execute(
                "SELECT 1 FROM video_upload_channels WHERE channel_id = ? AND status = 'active'",
                (channel_id,),
            ).fetchone() is None:
                raise ValueError("上传通道不存在")
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
                "session_id": session_id[:120],
                "uploader_name": uploader_name[:120],
                "course_id": str(payload.get("course_id", "")).strip()[:120],
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
                "result_path": "",
                "retention_days": retention_days,
                "reminder_days": reminder_days,
                "expires_at": _iso(created_at + timedelta(days=retention_days)),
                "created_at": _iso(created_at),
                "updated_at": _iso(created_at),
            }
            connection.execute(
                """
                INSERT INTO video_analysis_tasks
                (task_id, channel_id, session_id, uploader_name, course_id, course_name,
                 subject_id, original_filename, file_path, mime_type, byte_size,
                 received_bytes, total_chunks, next_chunk_index, sha256, upload_status,
                 analysis_status, result_path, retention_days, reminder_days, expires_at,
                 created_at, updated_at)
                VALUES (:task_id, :channel_id, :session_id, :uploader_name, :course_id,
                        :course_name, :subject_id, :original_filename, :file_path, :mime_type,
                        :byte_size, :received_bytes, :total_chunks, :next_chunk_index, :sha256,
                        :upload_status, :analysis_status, :result_path, :retention_days,
                        :reminder_days, :expires_at, :created_at, :updated_at)
                """,
                row,
            )
            self._audit(connection, actor, "create", "video_analysis_task", task_id, {
                "channel_id": channel_id,
                "session_id": session_id,
                "filename": filename,
                "byte_size": byte_size,
            })
        return self._public_video_task(row)

    def append_video_chunk(self, payload: dict[str, Any], *, actor: str = "local_uploader") -> dict[str, Any]:
        task_id = str(payload.get("task_id", "")).strip()
        chunk_index = int(payload.get("chunk_index", -1))
        encoded = str(payload.get("content_base64", "")).strip()
        if "," in encoded and encoded.lower().startswith("data:"):
            encoded = encoded.split(",", 1)[1]
        try:
            chunk = base64.b64decode(encoded, validate=True)
        except ValueError as exc:
            raise ValueError("视频分片不是有效的 Base64 数据") from exc
        if not chunk or len(chunk) > MAX_VIDEO_CHUNK_BYTES:
            raise ValueError("视频分片为空或超过 4MB")

        with self._upload_lock:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT * FROM video_analysis_tasks WHERE task_id = ?", (task_id,)
                ).fetchone()
                if row is None:
                    raise ValueError("未找到视频任务")
                task = dict(row)
                if task["upload_status"] != "uploading":
                    raise ValueError("该视频任务已结束上传")
                if chunk_index != task["next_chunk_index"]:
                    raise ValueError(f"分片顺序错误，应上传第 {task['next_chunk_index']} 片")
                received_bytes = task["received_bytes"] + len(chunk)
                if received_bytes > task["byte_size"]:
                    raise ValueError("上传内容超过登记的视频大小")
                part_path = Path(f"{task['file_path']}.part")
                with part_path.open("ab") as handle:
                    handle.write(chunk)
                next_chunk = chunk_index + 1
                complete = next_chunk == task["total_chunks"]
                if complete and received_bytes != task["byte_size"]:
                    raise ValueError("最后分片完成后文件大小不一致")
                connection.execute(
                    """
                    UPDATE video_analysis_tasks
                    SET received_bytes = ?, next_chunk_index = ?, updated_at = ?
                    WHERE task_id = ?
                    """,
                    (received_bytes, next_chunk, _iso(), task_id),
                )

            if complete:
                final_path = Path(task["file_path"])
                part_path.replace(final_path)
                digest = hashlib.sha256()
                with final_path.open("rb") as handle:
                    for block in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(block)
                result = self._build_video_precheck({**task, "received_bytes": received_bytes}, final_path)
                result_dir = self.video_task_dir / "results"
                result_dir.mkdir(parents=True, exist_ok=True)
                result_path = result_dir / f"{task_id}.json"
                result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                with self._connect() as connection:
                    connection.execute(
                        """
                        UPDATE video_analysis_tasks
                        SET sha256 = ?, upload_status = 'completed', analysis_status = ?,
                            result_path = ?, updated_at = ? WHERE task_id = ?
                        """,
                        (digest.hexdigest(), result["analysis_status"], str(result_path.resolve()), _iso(), task_id),
                    )
                    self._audit(connection, actor, "complete", "video_analysis_task", task_id, {
                        "sha256": digest.hexdigest(),
                        "analysis_status": result["analysis_status"],
                    })
            with self._connect() as connection:
                updated = connection.execute(
                    "SELECT * FROM video_analysis_tasks WHERE task_id = ?", (task_id,)
                ).fetchone()
        return self._public_video_task(dict(updated))

    def video_result_for_download(self, task_id: str) -> tuple[Path, str]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT result_path, original_filename FROM video_analysis_tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        if row is None or not row["result_path"]:
            raise ValueError("该任务尚无可下载结果")
        path = Path(row["result_path"]).resolve()
        root = (self.video_task_dir / "results").resolve()
        if root not in path.parents or not path.is_file():
            raise ValueError("分析结果文件不存在")
        return path, f"{Path(row['original_filename']).stem}_上传预检结果.json"

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
                "schema_version": 2,
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
        total = max(1, int(row.get("byte_size", 0)))
        row["progress_percent"] = min(100, round(int(row.get("received_bytes", 0)) * 100 / total))
        row["result_download_url"] = (
            f"/api/seewo_demo2/video_result_download?id={row.get('task_id', '')}"
            if row.get("analysis_status") in {"precheck_complete", "uploaded_pending_worker"}
            else ""
        )
        try:
            expires_at = datetime.fromisoformat(str(row.get("expires_at", "")))
            remaining = (expires_at - _now()).total_seconds() / 86400
            days_remaining = max(0, ceil(remaining))
        except ValueError:
            days_remaining = 0
        reminder_days = int(row.get("reminder_days", 15) or 15)
        row["days_remaining"] = days_remaining
        row["retention_state"] = (
            "expired" if days_remaining <= 0 else "due_soon" if days_remaining <= reminder_days else "active"
        )
        row["retention_label"] = {
            "expired": "已到期，等待受控删除",
            "due_soon": f"即将到期，剩余 {days_remaining} 天",
            "active": f"本地保存中，剩余 {days_remaining} 天",
        }[row["retention_state"]]
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
        upload_dir = Path(os.getenv("REHAB_DEMO2_UPLOAD_DIR", str(DEFAULT_UPLOAD_DIR)))
        _DEFAULT_STORE = Demo2StudentRecordStore(db_path=db_path, upload_dir=upload_dir)
    return _DEFAULT_STORE
