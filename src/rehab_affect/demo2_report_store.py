"""Persistent task-scoped classroom reports with stable report_id links.

A report is an idempotent snapshot of one task's teacher-reviewed evidence at a
given frame_revision. It links task_id, course_id, student_ids, observation
record_ids and dual-track evaluation record_ids; display names are only for
presentation and are never used as join keys.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from uuid import uuid4

from .demo2_identity_store import Demo2IdentityStore, IdentityError
from .demo2_dossier_store import material_access_state
from .demo2_iep_context import snapshot_report
from .demo2_report_debug import report_debug_event
from .evaluation_report_contract import generated_report_id, school_id_from_context
from .student_record_store import _iso


REPORT_PAGE_SIZE = 20
STALE_MESSAGE = "报告已过期：生成后评分、视频版本或引用的学生资料授权已变化，请重新生成课堂报告后再查看或下载"
STATUS_LABELS = {"saved": "可下载", "evidence_pending": "证据待补充", "stale": "已过期"}
ADMIN_REDACTED_KEYS = frozenset({"iep_links"})


class ReportError(ValueError):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


class Demo2ReportStore:
    def __init__(self, records):
        self.records = records
        self.identities = Demo2IdentityStore(records)
        with records._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS demo2_reports (
                    report_id TEXT PRIMARY KEY,
                    owner_account_id TEXT NOT NULL REFERENCES platform_accounts(account_id),
                    scope_key TEXT NOT NULL,
                    task_id TEXT NOT NULL REFERENCES video_analysis_tasks(task_id),
                    course_id TEXT NOT NULL DEFAULT '',
                    course_name TEXT NOT NULL DEFAULT '',
                    frame_revision TEXT NOT NULL DEFAULT '',
                    source_sha256 TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL DEFAULT '',
                    engine TEXT NOT NULL DEFAULT '',
                    student_ids_json TEXT NOT NULL DEFAULT '[]',
                    record_ids_json TEXT NOT NULL DEFAULT '[]',
                    evaluation_ids_json TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL DEFAULT 'saved',
                    payload_json TEXT NOT NULL,
                    generated_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(task_id, frame_revision)
                );
                CREATE INDEX IF NOT EXISTS idx_demo2_reports_task
                    ON demo2_reports(task_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_demo2_reports_course
                    ON demo2_reports(course_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_demo2_reports_owner
                    ON demo2_reports(owner_account_id, scope_key, created_at);
            """)

    # -- auth helpers ---------------------------------------------------------

    def _account(self, token, *, admin=False):
        try:
            account = self.records.account_from_session(token)
        except ValueError:
            raise ReportError(401, "authentication_required", "请重新登录") from None
        roles = {"company_admin"} if admin else {"school_uploader"}
        if account.get("role") not in roles:
            raise ReportError(403, "report_forbidden", "当前账号无权访问课程报告")
        return account

    def _scope(self, connection, account):
        context = self.identities._context(
            self.records._school_context_for_account(connection, account["account_id"]),
            required=False,
        )
        return self.identities._scope(account["account_id"], context)

    def _task(self, connection, account, task_id):
        if not isinstance(task_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", task_id):
            raise ReportError(404, "task_unavailable", "任务不存在或当前账号无权访问")
        try:
            return self.identities._task(connection, account, task_id)
        except IdentityError as exc:
            raise ReportError(exc.status, exc.code, exc.message) from None

    def _report(self, connection, account, report_id, *, admin=False):
        if not isinstance(report_id, str) or not re.fullmatch(r"[0-9a-f]{32}", report_id):
            raise ReportError(404, "report_unavailable", "报告不存在或无权访问")
        row = connection.execute(
            "SELECT * FROM demo2_reports WHERE report_id = ?", (report_id,)
        ).fetchone()
        if row is None:
            raise ReportError(404, "report_unavailable", "报告不存在或无权访问")
        # report_id is a random 128-bit value, so an explicit 403 for another
        # school's report does not make enumeration practical.
        if not admin and row["owner_account_id"] != account["account_id"]:
            raise ReportError(403, "report_forbidden", "当前账号无权访问该课堂报告")
        if not admin and row["scope_key"] != self._scope(connection, account):
            raise ReportError(403, "report_forbidden", "当前账号无权访问该课堂报告")
        return dict(row)

    def _stale_reasons(self, connection, row) -> list[str]:
        """Compare a snapshot with the live task and scoring versions."""
        reasons: list[str] = []
        task = connection.execute(
            "SELECT * FROM video_analysis_tasks WHERE task_id=?", (row["task_id"],)
        ).fetchone()
        if task is None:
            reasons.append("task_missing")
        else:
            if task["upload_status"] == "cancelled":
                reasons.append("task_cancelled")
            if task["sha256"] != row["source_sha256"]:
                reasons.append("source_changed")
            if self.identities._revision(dict(task)) != row["frame_revision"]:
                reasons.append("frame_revision_changed")
        report = json.loads(row["payload_json"] or "{}").get("report", {})
        for key, table, label in (("record_versions", "demo2_measurements", "record_changed"),
                                  ("evaluation_versions", "demo2_classroom_evaluations", "evaluation_changed")):
            for version in report.get(key, []):
                record_id = str(version.get("record_id") or "")
                current = connection.execute(
                    f"SELECT version,status FROM {table} WHERE record_id=? AND owner_account_id=?",
                    (record_id, row["owner_account_id"]),
                ).fetchone()
                if current is None or current["status"] != "active" or current["version"] != version.get("version"):
                    reasons.append(f"{label}:{record_id}")
        reasons.extend(self._dossier_stale_reasons(connection, report))
        return reasons

    @staticmethod
    def _dossier_stale_reasons(connection, report) -> list[str]:
        """A snapshot built from authorized dossier versions expires once that
        authorization, version or classroom reference is no longer usable."""
        links = report.get("iep_links", []) if isinstance(report, dict) else []
        used = [link for link in links if isinstance(link, dict) and link.get("available")]
        if not used:
            return []
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"demo2_dossier_references", "demo2_dossier_documents", "demo2_dossier_authorizations"} <= tables:
            return ["iep_source_unavailable:dossier_missing"]
        reference_columns = {row[1] for row in connection.execute("PRAGMA table_info(demo2_dossier_references)")}
        reasons: list[str] = []
        for link in used:
            reference_id = str(link.get("reference_id") or "")
            if reference_id:
                reference = connection.execute(
                    "SELECT * FROM demo2_dossier_references WHERE reference_id=?", (reference_id,)
                ).fetchone()
                if reference is None:
                    reasons.append(f"iep_reference_missing:{reference_id}")
                    continue
                if "withdrawn_at" in reference_columns and reference["withdrawn_at"]:
                    reasons.append(f"iep_reference_withdrawn:{reference_id}")
                    continue
            for version in link.get("document_versions", []) or []:
                document_id = str(version.get("document_id") or "") if isinstance(version, dict) else ""
                if not document_id:
                    continue
                state = material_access_state(connection, document_id=document_id, purpose="analysis")
                if not state["available"]:
                    reasons.append(f"iep_source_unavailable:{document_id}:{state['reason']}")
                    continue
                current = connection.execute(
                    "SELECT version FROM demo2_dossier_documents WHERE document_id=?", (document_id,)
                ).fetchone()
                if current is not None and version.get("version") is not None and current["version"] != version.get("version"):
                    reasons.append(f"iep_source_changed:{document_id}")
        return reasons

    def _check_current(self, connection, row, *, role, operation) -> list[str]:
        """Return stale reasons and persist the 「已过期」 mark on the snapshot."""
        reasons = self._stale_reasons(connection, row)
        report = json.loads(row["payload_json"] or "{}").get("report", {})
        report_debug_event(
            self.records, "report_stale_check", "stale" if reasons else "current",
            report_id=row["report_id"], task_id=row["task_id"],
            evaluation_id=_first(report.get("evaluation_ids")),
            evaluation_versions=_version_labels(report.get("evaluation_versions")),
            record_versions=_version_labels(report.get("record_versions")),
            frame_revision=row["frame_revision"], version_fingerprint=_fingerprint(row),
            role=role, stale=bool(reasons), stale_reasons=reasons, code=operation,
        )
        if reasons and row["status"] != "stale":
            connection.execute(
                "UPDATE demo2_reports SET status='stale', updated_at=? WHERE report_id=?",
                (_iso(), row["report_id"]),
            )
            row["status"] = "stale"
        elif not reasons and row["status"] == "stale":
            # Only a regeneration on the same revision restores the snapshot;
            # a rolled-back version keeps the earlier mark until then.
            reasons = ["awaiting_regeneration"]
        return reasons

    @staticmethod
    def _public_meta(row):
        payload = json.loads(row["payload_json"] or "{}")
        report = payload.get("report", {})
        summary = payload.get("summary") or {}
        evaluation_ids = json.loads(row["evaluation_ids_json"] or "[]")
        student_ids = json.loads(row["student_ids_json"] or "[]")
        return {
            "report_id": row["report_id"],
            "content_report_id": report.get("report_id", ""),
            "ready": bool(report.get("ready")),
            # Upstream stable IDs; students are joined by student_id, never by name.
            "school_id": school_id_from_context(payload.get("school_context")),
            "student_ids": student_ids,
            "task_id": row["task_id"],
            "video_task_id": row["task_id"],
            "course_id": row["course_id"],
            "course_name": row["course_name"],
            "evaluation_id": _first(evaluation_ids),
            "evaluation_ids": evaluation_ids,
            "frame_revision": row["frame_revision"],
            "source_sha256": row["source_sha256"],
            "version_fingerprint": _fingerprint(row),
            "title": row["title"],
            "engine": row["engine"],
            "character_count": int(report.get("character_count") or 0),
            "student_count": len(student_ids),
            "record_count": len(json.loads(row["record_ids_json"] or "[]")),
            "evaluation_count": len(evaluation_ids),
            "stats": _stats(summary),
            "status": row["status"],
            "stale": row["status"] == "stale",
            "status_label": STATUS_LABELS.get(row["status"], row["status"]),
            "generated_at": row["generated_at"],
            "updated_at": row["updated_at"],
        }

    def _payload_for_role(self, payload, *, admin, report_id=""):
        """Keep dossier linkage out of company-admin report responses."""
        if not admin:
            return payload
        removed: list[str] = []
        result = _strip_keys(payload, ADMIN_REDACTED_KEYS, removed)
        report_debug_event(
            self.records, "report_admin_redact", "redacted" if removed else "nothing_to_redact",
            report_id=report_id, role="company_admin", removed_fields=sorted(set(removed)),
            removed_count=len(removed),
        )
        return result

    def _iep_document_ids(self, report) -> list[str]:
        """IEP versions named by the snapshot's iep_links; professional material is excluded."""
        ids: list[str] = []
        for link in report.get("iep_links", []) if isinstance(report, dict) else []:
            for version in link.get("document_versions", []) if isinstance(link, dict) else []:
                document_id = version.get("document_id") if isinstance(version, dict) else None
                if isinstance(document_id, str) and document_id and document_id not in ids:
                    ids.append(document_id)
        if not ids:
            return []
        with self.records._connect() as connection:
            if not connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                                      "AND name='demo2_dossier_documents'").fetchone():
                return []
            placeholders = ",".join("?" for _ in ids)
            iep = {row[0] for row in connection.execute(
                f"SELECT document_id FROM demo2_dossier_documents WHERE document_type='iep' "
                f"AND document_id IN ({placeholders})", ids)}
        return [document_id for document_id in ids if document_id in iep]

    # -- persistence -----------------------------------------------------------

    def save_from_workspace(self, token, workspace) -> dict[str, Any]:
        """Persist an idempotent report snapshot for one task+frame_revision.

        Called after a teacher workspace is loaded so the company backend can
        list and download reports without re-deriving them. A re-save on the
        same revision refreshes the snapshot and keeps its stable report_id.
        """
        account = self._account(token)
        if not isinstance(workspace, dict) or not workspace.get("task_id"):
            raise ReportError(400, "invalid_workspace", "课堂工作区信息无效")
        task_id = str(workspace["task_id"])
        report = workspace.get("report")
        if not isinstance(report, dict) or not isinstance(report.get("sections"), list):
            raise ReportError(409, "report_not_ready", "当前课堂还没有可保存的教师复核报告")
        with self.records._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            task = self._task(connection, account, task_id)
            if task["account_id"] != account["account_id"]:
                raise ReportError(404, "task_unavailable", "任务不存在或当前账号无权访问")
            context = self.identities._context(task.get("school_context_json"), required=False)
            scope = self.identities._scope(account["account_id"], context)
            revision = self.identities._revision(task)
            if revision != workspace.get("frame_revision"):
                raise ReportError(409, "stale_frame_revision", "身份采样版本已变化，请刷新后重新保存")
            report = {**snapshot_report(report), "report_id": report.get("report_id") or generated_report_id(task_id)}
            student_ids = sorted({
                str(person.get("student_id")) for person in workspace.get("people", [])
                if person.get("student_id")
            })
            record_ids = sorted({
                str(record.get("record_id")) for record in workspace.get("records", [])
                if record.get("record_id")
            })
            # Only link evaluations actually used to build this report; raw
            # table queries would also pick up stale or excluded evaluations.
            evaluation_ids = sorted(set(report.get("evaluation_ids", [])))
            status = "saved" if report.get("ready") else "evidence_pending"
            payload = {
                "report": report,
                "students": [
                    {key: person.get(key, "") for key in ("student_id", "display_name", "student_code", "class_name")}
                    for person in workspace.get("people", [])
                    if person.get("student_id")
                ],
                "summary": workspace.get("summary", {}),
                "school_context": workspace.get("school_context", {}),
                "media": workspace.get("media", {}),
                "source_note": workspace.get("source_note", ""),
                "report_scope": workspace.get("report_scope", ""),
            }
            existing = connection.execute(
                "SELECT report_id FROM demo2_reports WHERE task_id = ? AND frame_revision = ?",
                (task_id, revision),
            ).fetchone()
            now = _iso()
            actor_name = account.get("username") or account.get("account_id") or "unknown"
            if existing:
                connection.execute(
                    """
                    UPDATE demo2_reports SET
                        course_id = ?, course_name = ?, source_sha256 = ?, title = ?,
                        engine = ?, student_ids_json = ?, record_ids_json = ?,
                        evaluation_ids_json = ?, status = ?, payload_json = ?, generated_at = ?,
                        updated_at = ?
                    WHERE report_id = ?
                    """,
                    (
                        task["course_id"], task["course_name"], task["sha256"],
                        str(report.get("title") or "课堂观察与学习支持报告"),
                        str(report.get("generation") or "evidence_template"),
                        json.dumps(student_ids, ensure_ascii=False),
                        json.dumps(record_ids, ensure_ascii=False),
                        json.dumps(evaluation_ids, ensure_ascii=False),
                        status,
                        json.dumps(payload, ensure_ascii=False, allow_nan=False),
                        _iso(), now, existing["report_id"],
                    ),
                )
                report_id = existing["report_id"]
            else:
                report_id = uuid4().hex
                connection.execute(
                    """
                    INSERT INTO demo2_reports
                    (report_id, owner_account_id, scope_key, task_id, course_id, course_name,
                     frame_revision, source_sha256, title, engine, student_ids_json,
                     record_ids_json, evaluation_ids_json, status, payload_json,
                     generated_at, created_at, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        report_id, account["account_id"], scope, task_id, task["course_id"],
                        task["course_name"], revision, task["sha256"],
                        str(report.get("title") or "课堂观察与学习支持报告"),
                        str(report.get("generation") or "evidence_template"),
                        json.dumps(student_ids, ensure_ascii=False),
                        json.dumps(record_ids, ensure_ascii=False),
                        json.dumps(evaluation_ids, ensure_ascii=False),
                        status, json.dumps(payload, ensure_ascii=False, allow_nan=False),
                        now, now, now,
                    ),
                )
            self.records._audit(
                connection, actor_name, "classroom_report_saved",
                "demo2_report", report_id,
                {"task_id": task_id, "student_count": len(student_ids),
                 "record_count": len(record_ids), "evaluation_count": len(evaluation_ids)},
            )
            row = connection.execute(
                "SELECT * FROM demo2_reports WHERE report_id = ?", (report_id,)
            ).fetchone()
            meta = self._public_meta(dict(row))
        stats = meta["stats"]
        report_debug_event(
            self.records, "report_generate", "regenerated" if existing else "created",
            report_id=report_id, content_report_id=meta["content_report_id"], task_id=task_id,
            course_id=meta["course_id"], evaluation_id=meta["evaluation_id"],
            evaluation_ids=evaluation_ids,
            evaluation_versions=_version_labels(report.get("evaluation_versions")),
            record_versions=_version_labels(report.get("record_versions")),
            frame_revision=revision, version_fingerprint=meta["version_fingerprint"],
            role="teacher", account_id=account["account_id"], status=status, ready=meta["ready"],
            character_count=meta["character_count"], section_count=len(report.get("sections", [])),
            student_count=stats["students"], reviewed_count=stats["reviewed"],
            scored_count=stats["scored"], pending_count=stats["pending"],
        )
        return meta

    # -- queries ----------------------------------------------------------------

    def _list_meta(self, connection, row, *, role):
        """List entries re-check freshness so old snapshots show 「已过期」."""
        row = dict(row)
        self._check_current(connection, row, role=role, operation="report_list")
        return self._public_meta(row)

    def list_for_task(self, token, task_id) -> dict[str, Any]:
        account = self._account(token)
        with self.records._connect() as connection:
            self._task(connection, account, task_id)
            rows = connection.execute(
                "SELECT * FROM demo2_reports WHERE task_id = ? AND owner_account_id = ? "
                "ORDER BY generated_at DESC, rowid DESC LIMIT 101",
                (task_id, account["account_id"]),
            ).fetchall()
            reports = [self._list_meta(connection, row, role="teacher") for row in rows]
        report_debug_event(self.records, "report_list", "ok", task_id=task_id, role="teacher",
                           account_id=account["account_id"], report_count=len(reports))
        return {"reports": reports}

    def list_admin(self, token, *, page: int = 1) -> dict[str, Any]:
        account = self._account(token, admin=True)
        if type(page) is not int or not 1 <= page <= 1_000_000:
            raise ReportError(400, "invalid_page", "报告页码须为正整数")
        with self.records._connect() as connection:
            total = connection.execute("SELECT COUNT(*) FROM demo2_reports").fetchone()[0]
            total_pages = max(1, (total + REPORT_PAGE_SIZE - 1) // REPORT_PAGE_SIZE)
            page = min(page, total_pages)
            rows = connection.execute(
                """
                SELECT r.*, a.username AS owner_username
                FROM demo2_reports AS r
                LEFT JOIN platform_accounts AS a ON a.account_id = r.owner_account_id
                ORDER BY r.generated_at DESC, r.rowid DESC LIMIT ? OFFSET ?
                """,
                (REPORT_PAGE_SIZE, (page - 1) * REPORT_PAGE_SIZE),
            ).fetchall()
            self.records._audit(
                connection, account["username"], "classroom_report_admin_viewed",
                "demo2_report", "platform", {"total": total},
            )
            items = []
            for row in rows:
                meta = self._list_meta(connection, row, role="company_admin")
                meta["owner_username"] = row["owner_username"] or ""
                items.append(meta)
        report_debug_event(self.records, "report_list", "ok", role="company_admin",
                           account_id=account["account_id"], report_count=len(items), page=page)
        return {
            "reports": items,
            "pagination": {"page": page, "page_size": REPORT_PAGE_SIZE,
                           "total": total, "total_pages": total_pages},
        }

    def admin_reports_for_tasks(self, token, task_ids) -> dict[str, list[dict[str, Any]]]:
        """Report metadata grouped by task for the company task query panel."""
        account = self._account(token, admin=True)
        if not isinstance(task_ids, (list, tuple)) or len(task_ids) > 100:
            raise ReportError(400, "invalid_request", "任务编号列表无效")
        wanted = [item for item in task_ids
                  if isinstance(item, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,120}", item)]
        grouped: dict[str, list[dict[str, Any]]] = {task_id: [] for task_id in wanted}
        if not wanted:
            return grouped
        with self.records._connect() as connection:
            placeholders = ",".join("?" for _ in wanted)
            rows = connection.execute(
                f"SELECT * FROM demo2_reports WHERE task_id IN ({placeholders}) "
                "ORDER BY generated_at DESC, rowid DESC",
                wanted,
            ).fetchall()
            for row in rows:
                grouped[row["task_id"]].append(self._list_meta(connection, row, role="company_admin"))
        report_debug_event(self.records, "report_list", "ok", role="company_admin",
                           account_id=account["account_id"], report_count=len(rows))
        return grouped

    def _load_current(self, token, report_id, operation):
        """Authorize, re-check freshness and return (account, admin, row).

        The stale mark is committed before raising so the snapshot stays
        「已过期」 in later list views even though this request is refused.
        """
        admin = _is_admin(token, self.records)
        role = "company_admin" if admin else "teacher"
        try:
            account = self._account(token, admin=admin)
            with self.records._connect() as connection:
                row = self._report(connection, account, report_id, admin=admin)
                reasons = self._check_current(connection, row, role=role, operation=operation)
        except ReportError as exc:
            report_debug_event(self.records, "report_rejected", str(exc.status), code=exc.code,
                               report_id=report_id if isinstance(report_id, str) else "",
                               role=role, message=operation)
            raise
        if reasons:
            report_debug_event(self.records, "report_rejected", "409", code="report_stale",
                               report_id=row["report_id"], task_id=row["task_id"], role=role,
                               version_fingerprint=_fingerprint(row), stale=True,
                               stale_reasons=reasons, status="stale", message=operation)
            raise ReportError(409, "report_stale", STALE_MESSAGE)
        return account, admin, role, row

    def get(self, token, report_id) -> dict[str, Any]:
        account, admin, role, row = self._load_current(token, report_id, "report_view")
        meta = self._public_meta(row)
        meta["payload"] = self._payload_for_role(
            json.loads(row["payload_json"] or "{}"), admin=admin, report_id=row["report_id"]
        )
        if not admin:
            # Dossier linkage stays teacher-side, like iep_links.
            meta["iep_document_ids"] = self._iep_document_ids(meta["payload"].get("report", {}))
        report_debug_event(
            self.records, "report_view", "ok", report_id=row["report_id"], task_id=row["task_id"],
            evaluation_id=meta["evaluation_id"], frame_revision=row["frame_revision"],
            version_fingerprint=meta["version_fingerprint"], role=role,
            account_id=account["account_id"], status=meta["status"],
            character_count=meta["character_count"],
        )
        return meta

    def download(self, token, report_id, *, fmt: str = "md") -> tuple[str, str, str]:
        if fmt not in {"md", "json"}:
            raise ReportError(400, "invalid_format", "报告下载格式仅支持 md 或 json")
        account, admin, role, row = self._load_current(token, report_id, "report_download")
        meta = self._public_meta(row)
        payload = self._payload_for_role(
            json.loads(row["payload_json"] or "{}"), admin=admin, report_id=row["report_id"]
        )
        report = payload.get("report", {})
        stats = meta["stats"]
        if fmt == "json":
            text = json.dumps(
                {
                    "report_id": row["report_id"], "task_id": row["task_id"],
                    "video_task_id": row["task_id"],
                    "content_report_id": report.get("report_id", ""),
                    "ready": bool(report.get("ready")),
                    "course_id": row["course_id"], "course_name": row["course_name"],
                    "school_id": meta["school_id"],
                    "evaluation_id": meta["evaluation_id"],
                    "frame_revision": row["frame_revision"],
                    "version_fingerprint": meta["version_fingerprint"],
                    "status": meta["status"], "status_label": meta["status_label"],
                    "stats": stats,
                    "student_ids": json.loads(row["student_ids_json"] or "[]"),
                    "record_ids": json.loads(row["record_ids_json"] or "[]"),
                    "evaluation_ids": json.loads(row["evaluation_ids_json"] or "[]"),
                    "generated_at": row["generated_at"], "report": report,
                    "boundary": "本报告用于课堂教育支持复盘，不构成医学诊断、学生能力定级或教师绩效结论。",
                },
                ensure_ascii=False, indent=2,
            )
            filename = f"report_{row['report_id']}.json"
            content_type = "application/json; charset=utf-8"
        else:
            lines = [f"# {row['title']}", "", f"报告ID：{row['report_id']}"]
            lines.append(f"课程ID：{row['course_id']} · 任务ID：{row['task_id']}"
                         + (f" · 评价ID：{meta['evaluation_id']}" if meta["evaluation_id"] else ""))
            lines.append(f"生成时间：{row['generated_at']} · 版本：{meta['version_fingerprint']}")
            lines.append(f"正文 {meta['character_count']} 字符 · {row['engine']}")
            lines.append(f"关联学生：{stats['students']} 名 · 已复核目标：{stats['reviewed']} 条 · "
                         f"可计分目标：{stats['scored']} 条 · 待处理记录：{stats['pending']} 条")
            lines.append("")
            measures = report.get("measurements") or []
            if measures:
                lines.append("## 已记录目标测量 · 10分制")
                lines.append("")
                for item in measures:
                    score = item.get("score")
                    lines.append(f"- {item.get('label', '')}：" + (f"{score:.2f}" if isinstance(score, (int, float)) else "空缺（不按0分）"))
                lines.append("")
                lines.append("不同学生、目标与支持条件不合并排名。6分为试行参考线；空缺不是0分。")
                lines.append("")
            for section in report.get("sections", []):
                lines.append(f"## {section.get('title', '')}")
                lines.append("")
                lines.append(section.get("text", ""))
                lines.append("")
            lines.append("---")
            lines.append("本报告用于课堂教育支持复盘，不构成医学诊断、学生能力定级或教师绩效结论。")
            text = "\n".join(lines)
            filename = f"report_{row['report_id']}.md"
            content_type = "text/markdown; charset=utf-8"
        report_debug_event(
            self.records, "report_download", "ok", report_id=row["report_id"], task_id=row["task_id"],
            evaluation_id=meta["evaluation_id"], frame_revision=row["frame_revision"],
            version_fingerprint=meta["version_fingerprint"], role=role,
            account_id=account["account_id"], fmt=fmt, status=meta["status"],
        )
        return text, filename, content_type


def _first(values) -> str:
    return str(values[0]) if isinstance(values, list) and values else ""


def _version_labels(versions) -> list[str]:
    if not isinstance(versions, list):
        return []
    return [f"{item.get('record_id', '')}:v{item.get('version', '')}"
            for item in versions if isinstance(item, dict)]


def _fingerprint(row) -> str:
    """Short hash of everything a download must still match."""
    report = json.loads(row["payload_json"] or "{}").get("report", {})
    basis = json.dumps({
        "frame_revision": row["frame_revision"], "source_sha256": row["source_sha256"],
        "record_versions": sorted(_version_labels(report.get("record_versions"))),
        "evaluation_versions": sorted(_version_labels(report.get("evaluation_versions"))),
    }, sort_keys=True)
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def _stats(summary) -> dict[str, int]:
    """The four report cards, taken from the same workspace summary."""
    def number(key):
        value = summary.get(key, 0) if isinstance(summary, dict) else 0
        return value if isinstance(value, int) and not isinstance(value, bool) else 0
    return {"students": number("students"), "reviewed": number("reviewed"),
            "scored": number("scored"), "pending": number("pending") + number("reconfirm")}


def _strip_keys(value, keys, removed):
    """Deep-copy ``value`` without the given keys at any nesting level."""
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key in keys:
                removed.append(key)
                continue
            result[key] = _strip_keys(item, keys, removed)
        return result
    if isinstance(value, list):
        return [_strip_keys(item, keys, removed) for item in value]
    return value


def _is_admin(token, records) -> bool:
    """Best-effort role check without raising; report access re-validates."""
    try:
        return records.account_from_session(token).get("role") == "company_admin"
    except (TypeError, ValueError):
        return False
