"""Persistent task-scoped classroom reports with stable report_id links.

A report is an idempotent snapshot of one task's teacher-reviewed evidence at a
given frame_revision. It links task_id, course_id, student_ids, observation
record_ids and dual-track evaluation record_ids; display names are only for
presentation and are never used as join keys.
"""
from __future__ import annotations

import json
import re
from typing import Any
from uuid import uuid4

from .demo2_identity_store import Demo2IdentityStore, IdentityError
from .demo2_iep_context import snapshot_report
from .evaluation_report_contract import generated_report_id
from .student_record_store import _iso


REPORT_PAGE_SIZE = 20


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
        if not admin and row["owner_account_id"] != account["account_id"]:
            raise ReportError(404, "report_unavailable", "报告不存在或无权访问")
        if not admin and row["scope_key"] != self._scope(connection, account):
            raise ReportError(404, "report_unavailable", "报告不存在或无权访问")
        return dict(row)

    def _require_current(self, connection, row):
        task = connection.execute('SELECT * FROM video_analysis_tasks WHERE task_id=?', (row['task_id'],)).fetchone()
        valid = (task is not None and task['upload_status'] != 'cancelled'
                 and task['sha256'] == row['source_sha256']
                 and self.identities._revision(dict(task)) == row['frame_revision'])
        report = json.loads(row['payload_json']).get('report', {})
        for key, table in (('record_versions', 'demo2_measurements'),
                           ('evaluation_versions', 'demo2_classroom_evaluations')):
            for version in report.get(key, []):
                current = connection.execute(f'SELECT version,status FROM {table} WHERE record_id=? AND owner_account_id=?',
                                             (version['record_id'], row['owner_account_id'])).fetchone()
                valid = valid and current is not None and current['status'] == 'active' and current['version'] == version['version']
        if not valid:
            raise ReportError(409, 'report_stale', '报告引用的视频或评分已变化，请由学校刷新课堂报告后再下载')

    @staticmethod
    def _public_meta(row):
        report = json.loads(row["payload_json"] or "{}").get("report", {})
        return {
            "report_id": row["report_id"],
            "content_report_id": report.get("report_id", ""),
            "ready": bool(report.get("ready")),
            "task_id": row["task_id"],
            "course_id": row["course_id"],
            "course_name": row["course_name"],
            "frame_revision": row["frame_revision"],
            "source_sha256": row["source_sha256"],
            "title": row["title"],
            "engine": row["engine"],
            "student_count": len(json.loads(row["student_ids_json"] or "[]")),
            "record_count": len(json.loads(row["record_ids_json"] or "[]")),
            "evaluation_count": len(json.loads(row["evaluation_ids_json"] or "[]")),
            "status": row["status"],
            "generated_at": row["generated_at"],
            "updated_at": row["updated_at"],
        }

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
            return self._public_meta(dict(row))

    # -- queries ----------------------------------------------------------------

    def list_for_task(self, token, task_id) -> dict[str, Any]:
        account = self._account(token)
        with self.records._connect() as connection:
            self._task(connection, account, task_id)
            rows = connection.execute(
                "SELECT * FROM demo2_reports WHERE task_id = ? AND owner_account_id = ? "
                "ORDER BY generated_at DESC, rowid DESC LIMIT 101",
                (task_id, account["account_id"]),
            ).fetchall()
            return {"reports": [self._public_meta(dict(row)) for row in rows]}

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
                meta = self._public_meta(dict(row))
                meta["owner_username"] = row["owner_username"] or ""
                items.append(meta)
            return {
                "reports": items,
                "pagination": {"page": page, "page_size": REPORT_PAGE_SIZE,
                               "total": total, "total_pages": total_pages},
            }

    def get(self, token, report_id) -> dict[str, Any]:
        admin = _is_admin(token, self.records)
        account = self._account(token, admin=admin)
        with self.records._connect() as connection:
            row = self._report(connection, account, report_id, admin=admin)
            self._require_current(connection, row)
            meta = self._public_meta(row)
            meta["payload"] = json.loads(row["payload_json"] or "{}")
            return meta

    def download(self, token, report_id, *, fmt: str = "md") -> tuple[str, str, str]:
        admin = _is_admin(token, self.records)
        account = self._account(token, admin=admin)
        if fmt not in {"md", "json"}:
            raise ReportError(400, "invalid_format", "报告下载格式仅支持 md 或 json")
        with self.records._connect() as connection:
            row = self._report(connection, account, report_id, admin=admin)
            self._require_current(connection, row)
            payload = json.loads(row["payload_json"] or "{}")
            report = payload.get("report", {})
            if fmt == "json":
                text = json.dumps(
                    {
                        "report_id": row["report_id"], "task_id": row["task_id"],
                        "content_report_id": report.get("report_id", ""),
                        "ready": bool(report.get("ready")),
                        "course_id": row["course_id"], "course_name": row["course_name"],
                        "frame_revision": row["frame_revision"],
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
                lines.append(f"课程ID：{row['course_id']} · 任务ID：{row['task_id']}")
                lines.append(f"生成时间：{row['generated_at']} · 引擎：{row['engine']}")
                lines.append(f"关联学生：{len(json.loads(row['student_ids_json'] or '[]'))} 名 · "
                             f"观察记录：{len(json.loads(row['record_ids_json'] or '[]'))} 条 · "
                             f"课堂评价：{len(json.loads(row['evaluation_ids_json'] or '[]'))} 条")
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
            return text, filename, content_type


def _is_admin(token, records) -> bool:
    """Best-effort role check without raising; report access re-validates."""
    try:
        return records.account_from_session(token).get("role") == "company_admin"
    except (TypeError, ValueError):
        return False
