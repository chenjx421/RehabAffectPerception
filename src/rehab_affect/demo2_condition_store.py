"""Teacher-confirmed condition/safety notes, sealed separately from classroom data.

The AI extraction step is intentionally not implemented yet. This store only accepts
a teacher's explicit confirmation and keeps the free text encrypted with the dossier
vault; it is never part of the classroom support summary or report.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .demo2_dossier_vault import DossierVault, VaultError

CATEGORIES = {
    "seizure": "发作 / 癫痫 / 急救",
    "medication": "用药 / 过敏 / 健康限制",
    "regulation": "情绪 / 创伤 / 行为安全",
    "sensory": "感官 / 沟通 / 运动限制",
}
MAX_SUPPLEMENT = 1200


class ConditionError(ValueError):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class Demo2ConditionStore:
    def __init__(self, records):
        self.records = records
        self.root = Path(records.upload_dir).parent / "scoped_dossier_v1"
        self.vault = DossierVault(self.root)
        with records._connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS demo2_condition_confirmations (
                    condition_id TEXT PRIMARY KEY,
                    archive_id TEXT NOT NULL UNIQUE,
                    task_id TEXT NOT NULL,
                    person_id TEXT NOT NULL,
                    student_id TEXT NOT NULL,
                    owner_account_id TEXT NOT NULL,
                    scope_key TEXT NOT NULL,
                    iep_document_id TEXT NOT NULL,
                    ciphertext BLOB NOT NULL,
                    confirmed_by TEXT NOT NULL,
                    confirmed_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_condition_archive ON demo2_condition_confirmations(archive_id);
                CREATE INDEX IF NOT EXISTS idx_condition_task ON demo2_condition_confirmations(task_id);
            """)

    def _account(self, token: str) -> dict[str, Any]:
        try:
            return self.records.account_from_session(token)
        except Exception as exc:
            raise ConditionError(401, "authentication_required", "登录已失效，请重新登录") from exc

    def _text(self, value: Any, limit: int, field: str) -> str:
        if value is None:
            return ""
        if not isinstance(value, str):
            raise ConditionError(400, "invalid_condition", f"{field}格式无效")
        text = value.strip()
        if len(text) > limit:
            raise ConditionError(400, "invalid_condition", f"{field}不能超过 {limit} 字")
        return text

    def save(self, token: str, payload: Any, *, archive: dict[str, Any]) -> dict[str, Any]:
        account = self._account(token)
        if not isinstance(payload, dict):
            raise ConditionError(400, "invalid_condition", "病况确认格式无效")
        allowed = {"confirmed", "categories", "supplement", "source_document_id"}
        if set(payload) - allowed or payload.get("confirmed") is not True:
            raise ConditionError(400, "condition_confirmation_required", "请先由教师确认病况/健康与安全要点")
        categories = payload.get("categories", [])
        if not isinstance(categories, list) or len(categories) > len(CATEGORIES) or any(
                not isinstance(item, str) or item not in CATEGORIES for item in categories):
            raise ConditionError(400, "invalid_condition", "病况类别无效")
        supplement = self._text(payload.get("supplement", ""), MAX_SUPPLEMENT, "其他病症补充")
        if not categories and not supplement:
            raise ConditionError(400, "condition_confirmation_required",
                                 "请至少勾选一项病况/安全要点，或在补充中填写“已核对无相关病况”")
        source_document_id = self._text(payload.get("source_document_id", ""), 160, "IEP 资料编号")
        archive_id = str(archive.get("archive_id") or "")
        task_id = str(archive.get("task_id") or "")
        person_id = str(archive.get("person_id") or "")
        student_id = str(archive.get("student_id") or "")
        if not all((archive_id, task_id, person_id, student_id)):
            raise ConditionError(400, "archive_unavailable", "档案尚未保存，不能确认病况")
        with self.records._connect() as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute("""SELECT * FROM demo2_simple_lesson_archives
                WHERE archive_id=? AND owner_account_id=?""", (archive_id, account["account_id"])).fetchone()
            if row is None:
                raise ConditionError(404, "archive_unavailable", "档案不存在或无权确认")
            if row["task_id"] != task_id or row["student_id"] != student_id or row["person_id"] != person_id:
                raise ConditionError(409, "archive_changed", "档案内容已变化，请刷新后重新确认")
            student_row = connection.execute("""SELECT scope_key FROM demo2_identity_students
                WHERE student_id=? AND owner_account_id=?""", (student_id, account["account_id"])).fetchone()
            if student_row is None:
                raise ConditionError(404, "student_unavailable", "学生不存在或无权确认")
            iep_document_id = str(row["iep_document_id"] or "")
            if not iep_document_id:
                raise ConditionError(400, "iep_required", "请先关联 IEP，再确认病况/健康要点")
            if source_document_id and source_document_id != iep_document_id:
                raise ConditionError(409, "iep_changed", "IEP 版本已变化，请重新核对")
            try:
                ciphertext = self.vault.seal(json.dumps({
                    "categories": sorted(set(categories)),
                    "supplement": supplement,
                }, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
            except VaultError as exc:
                raise ConditionError(503, "vault_unavailable", "病况资料加密服务不可用，未保存明文") from exc
            existing = connection.execute(
                "SELECT condition_id FROM demo2_condition_confirmations WHERE archive_id=?", (archive_id,)).fetchone()
            condition_id = existing["condition_id"] if existing else f"cond-{uuid4().hex}"
            now = _now()
            connection.execute("""INSERT INTO demo2_condition_confirmations
                (condition_id, archive_id, task_id, person_id, student_id, owner_account_id, scope_key,
                 iep_document_id, ciphertext, confirmed_by, confirmed_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(archive_id) DO UPDATE SET ciphertext=excluded.ciphertext,
                 iep_document_id=excluded.iep_document_id, confirmed_by=excluded.confirmed_by,
                 confirmed_at=excluded.confirmed_at""",
                (condition_id, archive_id, task_id, person_id, student_id, account["account_id"],
                 student_row["scope_key"], iep_document_id, ciphertext, account["username"], now))
        return {
            "condition_id": condition_id,
            "archive_id": archive_id,
            "confirmed": True,
            "categories": sorted(set(categories)),
            "category_labels": [CATEGORIES[item] for item in sorted(set(categories))],
            "supplement": supplement,
            "source_document_id": iep_document_id,
            "confirmed_by": account["username"],
            "confirmed_at": now,
        }
