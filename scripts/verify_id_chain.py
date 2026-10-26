"""Read-only verification of the Demo2 stable-ID chain.

Traces one classroom report (``--report-id``) backwards, or one video task
(``--video-task-id``) forwards, through::

    school_id -> student_id -> iep_document_id -> course_id
      -> video_task_id -> evaluation_id -> report_id

Every level is printed with its IDs and whether each one exists.  A broken
link (missing row, mismatched upstream ID, orphan record) or a join that uses a
student's display name instead of a stable ID makes the script exit non-zero
and name the exact level that failed.  A student with more than one current IEP
is reported as ``ambiguous`` instead of choosing one.

The database is opened with SQLite ``mode=ro``; the script never writes to it.
Each step is logged as a timestamped JSON line (default
``.runtime/logs/verify_id_chain_YYYYMMDD.jsonl``).  Logs carry IDs only, never
student names or dossier content.

Exit codes::

    0  chain complete (IEP may be ``not_linked`` unless --require-iep)
    1  chain broken, orphan records or name-based joins found
    2  usage error or database cannot be opened
    3  chain complete but at least one student's IEP is ambiguous

Usage (from the repository root)::

    PYTHONPATH=src .venv/bin/python scripts/verify_id_chain.py --db PATH --report-id ID
    PYTHONPATH=src .venv/bin/python scripts/verify_id_chain.py --db PATH --video-task-id ID --json
    PYTHONPATH=src .venv/bin/python scripts/verify_id_chain.py --db PATH --video-task-id ID --scan-orphans
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from rehab_affect.evaluation_report_contract import school_id_from_context  # noqa: E402

LEVELS = ("school_id", "student_id", "iep_document_id", "course_id",
          "video_task_id", "evaluation_id", "report_id")
LEVEL_LABELS = {
    "school_id": "学校", "student_id": "学生", "iep_document_id": "IEP 资料",
    "course_id": "课程", "video_task_id": "课堂视频任务", "evaluation_id": "课堂评价",
    "report_id": "课堂报告",
}
DEFAULT_DB = ROOT / "outputs" / "seewo_demo2" / "rehab_affect_demo2.sqlite3"
DEFAULT_LOG_DIR = ROOT / ".runtime" / "logs"
# Names shorter than this are too likely to collide with random hex IDs.
MIN_NAME_LENGTH = 2

EXIT_OK, EXIT_BROKEN, EXIT_USAGE, EXIT_AMBIGUOUS = 0, 1, 2, 3


class ChainLogger:
    """Timestamped JSON-lines log plus an optional human echo on stderr."""

    def __init__(self, path: Path | None, *, echo: bool):
        self.path = path
        self.echo = echo
        self.run_id = uuid4().hex[:12]
        self.started = time.monotonic()
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)

    def event(self, step: str, result: str, **fields: Any) -> None:
        entry = {"ts": datetime.now().astimezone().isoformat(timespec="milliseconds"),
                 "run_id": self.run_id, "step": step, "result": result}
        entry.update({key: value for key, value in fields.items() if value is not None})
        if self.path is not None:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
        if self.echo:
            extras = " ".join(f"{key}={_short(value)}" for key, value in fields.items() if value not in (None, "", [], {}))
            print(f"[{entry['ts']}] {step} -> {result}" + (f" | {extras}" if extras else ""), file=sys.stderr)

    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self.started) * 1000)


def _short(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= 160 else text[:157] + "..."


def _today() -> str:
    return datetime.now().astimezone().date().isoformat()


def _json(raw: Any, default: Any) -> Any:
    if raw is None or raw == "":
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def _context(raw: Any) -> dict[str, str]:
    value = _json(raw, {}) if isinstance(raw, str) else (raw or {})
    if not isinstance(value, dict):
        return {}
    return {key: str(value.get(key, "")).strip() for key in ("city", "district", "school_name")}


def _scope_key(owner: str, context: dict[str, str]) -> str:
    """Mirror Demo2IdentityStore._scope without importing the storage layer."""
    import hashlib
    if not owner or not context or not all(context.values()):
        return ""
    encoded = json.dumps({"owner_account_id": owner, "school_context": context},
                         ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class ChainVerifier:
    def __init__(self, connection: sqlite3.Connection, logger: ChainLogger, *, require_iep: bool):
        self.db = connection
        self.log = logger
        self.require_iep = require_iep
        self.tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.today = _today()

    # -- helpers ---------------------------------------------------------------

    def _has(self, *tables: str) -> bool:
        return set(tables) <= self.tables

    def _row(self, sql: str, params: tuple) -> dict[str, Any] | None:
        row = self.db.execute(sql, params).fetchone()
        return dict(row) if row is not None else None

    def _rows(self, sql: str, params: tuple) -> list[dict[str, Any]]:
        return [dict(row) for row in self.db.execute(sql, params).fetchall()]

    @staticmethod
    def _new_chain(start_kind: str, start_id: str) -> dict[str, Any]:
        return {"start": {"kind": start_kind, "id": start_id},
                "levels": {level: {"level": level, "label": LEVEL_LABELS[level], "status": "pending",
                                   "entries": [], "problems": []} for level in LEVELS},
                "errors": [], "warnings": []}

    def _entry(self, chain, level, value, exists, *, status=None, detail="", **extra):
        entry = {"id": value, "exists": bool(exists), "status": status or ("ok" if exists else "missing"),
                 "detail": detail, **extra}
        chain["levels"][level]["entries"].append(entry)
        self.log.event("level_query", entry["status"], level=level, id=value, exists=bool(exists),
                       detail=detail or None, **{k: v for k, v in extra.items() if isinstance(v, (str, int, bool))})
        return entry

    def _break(self, chain, level, code, message, **fields):
        problem = {"level": level, "code": code, "message": message, **fields}
        chain["levels"][level]["problems"].append(problem)
        chain["errors"].append(problem)
        self.log.event("chain_break", code, level=level, reason=message, **fields)

    def _warn(self, chain, level, code, message, **fields):
        warning = {"level": level, "code": code, "message": message, **fields}
        chain["warnings"].append(warning)
        self.log.event("chain_warning", code, level=level, reason=message, **fields)

    # -- entry points ------------------------------------------------------------

    def from_report(self, report_id: str) -> dict[str, Any]:
        chain = self._new_chain("report_id", report_id)
        self.log.event("trace_start", "begin", direction="reverse", start_kind="report_id", start_id=report_id)
        if not self._has("demo2_reports"):
            self._entry(chain, "report_id", report_id, False, detail="数据库中没有 demo2_reports 表")
            self._break(chain, "report_id", "report_table_missing", "数据库尚未初始化课堂报告表", report_id=report_id)
            return self._finish(chain)
        row = self._row("SELECT * FROM demo2_reports WHERE report_id=?", (report_id,))
        if row is None:
            # Content-level IDs ("report-<hash>") are accepted as aliases of the stored snapshot.
            matches = self._rows("SELECT * FROM demo2_reports WHERE json_extract(payload_json,'$.report.report_id')=?",
                                 (report_id,))
            row = matches[0] if len(matches) == 1 else None
            if len(matches) > 1:
                self._entry(chain, "report_id", report_id, False, status="ambiguous",
                            detail=f"内容报告编号对应 {len(matches)} 份快照")
                self._break(chain, "report_id", "report_alias_ambiguous", "内容报告编号对应多份报告快照，请改用 32 位 report_id",
                            report_id=report_id)
                return self._finish(chain)
        if row is None:
            self._entry(chain, "report_id", report_id, False, detail="demo2_reports 中不存在")
            self._break(chain, "report_id", "report_missing", "报告不存在", report_id=report_id)
            return self._finish(chain)
        self._verify_report(chain, row)
        return self._finish(chain)

    def from_task(self, task_id: str) -> list[dict[str, Any]]:
        self.log.event("trace_start", "begin", direction="forward", start_kind="video_task_id", start_id=task_id)
        task = self._row("SELECT * FROM video_analysis_tasks WHERE task_id=?", (task_id,)) \
            if self._has("video_analysis_tasks") else None
        if task is None:
            chain = self._new_chain("video_task_id", task_id)
            self._entry(chain, "video_task_id", task_id, False, detail="video_analysis_tasks 中不存在")
            self._break(chain, "video_task_id", "task_missing", "课堂视频任务不存在", video_task_id=task_id)
            return [self._finish(chain)]
        reports = self._rows("SELECT * FROM demo2_reports WHERE task_id=? ORDER BY generated_at DESC, rowid DESC",
                             (task_id,)) if self._has("demo2_reports") else []
        self.log.event("forward_reports", "found" if reports else "none", video_task_id=task_id,
                       report_count=len(reports))
        if not reports:
            chain = self._new_chain("video_task_id", task_id)
            self._verify_task_upstream(chain, task, report=None)
            self._verify_evaluations(chain, task, self._task_evaluation_ids(task_id), report=None)
            self._entry(chain, "report_id", "", False, detail="该任务尚未保存课堂报告")
            self._break(chain, "report_id", "report_missing", "课堂视频任务尚未生成报告，链路在 report_id 处中断",
                        video_task_id=task_id)
            return [self._finish(chain)]
        results = []
        for report in reports:
            chain = self._new_chain("video_task_id", task_id)
            chain["start"]["report_id"] = report["report_id"]
            self._verify_report(chain, report)
            self._orphans_for_task(chain, task, report)
            results.append(self._finish(chain))
        return results

    # -- level checks ------------------------------------------------------------

    def _verify_report(self, chain, report: dict[str, Any]) -> None:
        payload = _json(report.get("payload_json"), {})
        content = payload.get("report", {}) if isinstance(payload, dict) else {}
        self._entry(chain, "report_id", report["report_id"], True, detail=f"状态 {report['status']}",
                    content_report_id=str(content.get("report_id", "")), report_status=report["status"])
        if report["status"] == "stale":
            self._warn(chain, "report_id", "report_stale", "报告已标记为已过期，下载前需重新生成",
                       report_id=report["report_id"])
        task_id = report["task_id"]
        task = self._row("SELECT * FROM video_analysis_tasks WHERE task_id=?", (task_id,)) \
            if self._has("video_analysis_tasks") else None
        if task is None:
            self._entry(chain, "video_task_id", task_id, False, detail="报告指向的课堂视频任务不存在")
            self._break(chain, "video_task_id", "task_missing", "报告指向不存在的 video_task_id",
                        report_id=report["report_id"], video_task_id=task_id)
            evaluation_ids = _json(report.get("evaluation_ids_json"), [])
            self._verify_evaluations(chain, None, evaluation_ids, report=report, expected_task_id=task_id)
            return
        self._verify_task_upstream(chain, task, report=report)
        evaluation_ids = _json(report.get("evaluation_ids_json"), [])
        if not isinstance(evaluation_ids, list):
            evaluation_ids = []
        self._verify_evaluations(chain, task, evaluation_ids, report=report)
        for version in content.get("evaluation_versions", []) if isinstance(content, dict) else []:
            record_id = str(version.get("record_id") or "") if isinstance(version, dict) else ""
            if record_id and self._has("demo2_classroom_evaluations") and self._row(
                    "SELECT 1 AS present FROM demo2_classroom_evaluations WHERE record_id=?", (record_id,)) is None:
                self._break(chain, "evaluation_id", "evaluation_version_orphan",
                            "报告快照中的评价版本指向不存在的评价记录", report_id=report["report_id"],
                            evaluation_record_id=record_id)

    def _verify_task_upstream(self, chain, task: dict[str, Any], *, report: dict[str, Any] | None) -> None:
        task_id = task["task_id"]
        self._entry(chain, "video_task_id", task_id, True,
                    detail=f"上传 {task.get('upload_status', '')} / 分析 {task.get('analysis_status', '')}")
        context = _context(task.get("school_context_json"))
        owner = task.get("account_id") or ""
        if report is not None and report["owner_account_id"] != owner:
            self._break(chain, "video_task_id", "owner_mismatch", "报告所属账号与课堂视频任务账号不一致",
                        report_id=report["report_id"], video_task_id=task_id)

        # course_id: stored on the task; every downstream record must agree.
        course_id = str(task.get("course_id") or "")
        if not course_id:
            self._entry(chain, "course_id", "", False, detail="课堂视频任务没有 course_id")
            self._break(chain, "course_id", "course_missing", "课堂视频任务缺少 course_id", video_task_id=task_id)
        else:
            self._entry(chain, "course_id", course_id, True, detail="来自 video_analysis_tasks.course_id")
            if report is not None and report.get("course_id") != course_id:
                self._break(chain, "course_id", "course_mismatch", "报告 course_id 与课堂视频任务不一致",
                            report_id=report["report_id"], expected=course_id, found=report.get("course_id"))

        # students: the report's stable IDs, or confirmed bindings when no report exists yet.
        if report is not None:
            student_ids = _json(report.get("student_ids_json"), [])
            student_ids = student_ids if isinstance(student_ids, list) else []
        else:
            student_ids = [row["student_id"] for row in self._rows(
                "SELECT DISTINCT student_id FROM demo2_identity_bindings WHERE task_id=? AND role='student' "
                "AND status='confirmed' AND student_id IS NOT NULL ORDER BY student_id", (task_id,))] \
                if self._has("demo2_identity_bindings") else []
        students = self._verify_students(chain, task, student_ids, report=report)

        # school_id: derived from the upload-time school snapshot, cross-checked with each student.
        school_id = school_id_from_context(context)
        if not school_id:
            self._entry(chain, "school_id", "", False, detail="课堂视频任务缺少学校快照")
            self._break(chain, "school_id", "school_missing", "课堂视频任务没有学校信息，无法得到 school_id",
                        video_task_id=task_id)
        else:
            self._entry(chain, "school_id", school_id, True, detail="由任务学校快照（城市/区县/学校）派生")
            scope = _scope_key(owner, context)
            if report is not None and report.get("scope_key") and report["scope_key"] != scope:
                self._break(chain, "school_id", "school_scope_mismatch", "报告学校范围与课堂视频任务学校快照不一致",
                            report_id=report["report_id"], video_task_id=task_id)
            for student in students:
                student_school = school_id_from_context(_context(student.get("school_context_json")))
                if student_school != school_id or student.get("scope_key") != scope:
                    self._break(chain, "school_id", "student_school_mismatch", "学生所属学校与课堂视频任务学校不一致",
                                student_id=student["student_id"], expected=school_id, found=student_school)
        if report is not None:
            identifiers = (_json(report.get("payload_json"), {}).get("report", {}) or {}).get("identifiers", {})
            declared = identifiers.get("school_id") if isinstance(identifiers, dict) else ""
            if declared and school_id and declared != school_id:
                self._break(chain, "school_id", "report_school_mismatch", "报告内容声明的 school_id 与任务学校不一致",
                            report_id=report["report_id"], expected=school_id, found=declared)

        self._verify_iep(chain, task, students, report=report)

    def _verify_students(self, chain, task, student_ids, *, report) -> list[dict[str, Any]]:
        task_id = task["task_id"]
        if not student_ids:
            self._entry(chain, "student_id", "", False, detail="链路中没有关联学生")
            self._break(chain, "student_id", "student_missing", "报告或课堂任务没有关联任何学生 student_id",
                        video_task_id=task_id)
            return []
        if not self._has("demo2_identity_students"):
            for student_id in student_ids:
                self._entry(chain, "student_id", str(student_id), False, detail="学生身份表不存在")
            self._break(chain, "student_id", "student_table_missing", "数据库没有 demo2_identity_students 表")
            return []
        found = []
        for student_id in student_ids:
            student_id = str(student_id)
            student = self._row("SELECT * FROM demo2_identity_students WHERE student_id=?", (student_id,))
            if student is None:
                by_name = self._row("SELECT student_id FROM demo2_identity_students WHERE display_name=?", (student_id,))
                self._entry(chain, "student_id", "<redacted-name>" if by_name else student_id, False,
                            detail="链路使用学生姓名而不是 student_id" if by_name else "学生不存在")
                if by_name:
                    self._break(chain, "student_id", "name_join", "关联字段中出现学生姓名，未使用稳定 student_id",
                                matched_student_id=by_name["student_id"], video_task_id=task_id)
                else:
                    self._break(chain, "student_id", "student_missing", "报告关联的 student_id 在学生身份表中不存在",
                                student_id=student_id, video_task_id=task_id)
                continue
            bound = self._row("SELECT COUNT(*) AS n FROM demo2_identity_bindings WHERE task_id=? AND student_id=? "
                              "AND role='student' AND status='confirmed'", (task_id, student_id)) \
                if self._has("demo2_identity_bindings") else {"n": 0}
            self._entry(chain, "student_id", student_id, True, detail=f"本课确认身份 {bound['n']} 次",
                        confirmed_bindings=int(bound["n"]))
            if student["owner_account_id"] != (task.get("account_id") or ""):
                self._break(chain, "student_id", "student_owner_mismatch", "学生所属账号与课堂视频任务账号不一致",
                            student_id=student_id, video_task_id=task_id)
            if not bound["n"]:
                self._break(chain, "student_id", "student_not_bound", "学生在该课堂视频任务中没有已确认的身份绑定（孤儿关联）",
                            student_id=student_id, video_task_id=task_id)
            found.append(student)
        if report is not None:
            payload = _json(report.get("payload_json"), {})
            listed = {str(item.get("student_id", "")) for item in payload.get("students", []) if isinstance(item, dict)}
            if listed and listed != {str(item) for item in student_ids}:
                self._break(chain, "student_id", "student_list_mismatch", "报告快照学生列表与 student_ids 不一致",
                            report_id=report["report_id"])
        return found

    def _verify_iep(self, chain, task, students, *, report) -> None:
        task_id = task["task_id"]
        dossier_ready = self._has("demo2_dossier_documents", "demo2_dossier_authorizations",
                                  "demo2_dossier_references", "demo2_dossier_reference_documents")
        for student in students:
            student_id = student["student_id"]
            if not dossier_ready:
                self._entry(chain, "iep_document_id", "", False, status="not_linked", student_id=student_id,
                            detail="资料库未初始化，本课未关联 IEP")
                continue
            heads = self._current_iep_heads(student_id)
            references = self._rows(
                "SELECT * FROM demo2_dossier_references WHERE task_id=? AND student_id=? ORDER BY created_at, rowid",
                (task_id, student_id))
            live_refs = [ref for ref in references if not ref.get("withdrawn_at")]
            linked = []
            for ref in live_refs:
                for link in self._rows("""SELECT l.document_id, l.version AS linked_version, d.* FROM demo2_dossier_reference_documents l
                        LEFT JOIN demo2_dossier_documents d ON d.document_id=l.document_id WHERE l.reference_id=?""",
                                       (ref["reference_id"],)):
                    if link.get("student_id") is None:
                        self._break(chain, "iep_document_id", "reference_document_orphan",
                                    "课堂引用指向不存在的资料版本", reference_id=ref["reference_id"],
                                    document_id=link["document_id"], student_id=student_id)
                        continue
                    if link["student_id"] != student_id:
                        self._break(chain, "iep_document_id", "reference_student_mismatch",
                                    "课堂引用的资料版本属于另一位学生", reference_id=ref["reference_id"],
                                    document_id=link["document_id"], student_id=student_id)
                        continue
                    if link["document_type"] == "iep":
                        linked.append({**link, "reference_id": ref["reference_id"]})
            linked_current = [doc for doc in linked if self._document_available(doc)]
            linked_families = {doc["family_id"] for doc in linked_current}
            current_refs = {doc["reference_id"] for doc in linked_current}
            self.log.event("iep_lookup", "queried", student_id=student_id, video_task_id=task_id,
                           current_iep_heads=len(heads), reference_count=len(references),
                           live_reference_count=len(live_refs), linked_iep_versions=len(linked),
                           linked_current_versions=len(linked_current))
            if len(heads) > 1 or len(linked_families) > 1 or len(current_refs) > 1:
                candidates = sorted({doc["document_id"] for doc in heads} | {doc["document_id"] for doc in linked_current})
                self._entry(chain, "iep_document_id", "ambiguous", True, status="ambiguous", student_id=student_id,
                            candidates=candidates,
                            detail=f"该学生存在 {max(len(heads), len(linked_families))} 份当前有效 IEP，系统不自动选择")
                chain["levels"]["iep_document_id"]["problems"].append(
                    {"level": "iep_document_id", "code": "multiple_current_iep", "student_id": student_id,
                     "message": "同一学生存在多份当前有效 IEP，标记为 ambiguous", "candidates": candidates})
                continue
            if linked_current:
                newest = max(linked_current, key=lambda doc: doc["version"])
                self._entry(chain, "iep_document_id", newest["document_id"], True, student_id=student_id,
                            reference_id=newest["reference_id"], version=int(newest["version"]),
                            detail="document_type='iep'，经本课引用关联且当前有效")
                if newest["owner_account_id"] != student["owner_account_id"] or newest["scope_key"] != student["scope_key"]:
                    self._break(chain, "iep_document_id", "iep_scope_mismatch", "IEP 资料的账号或学校范围与学生不一致",
                                document_id=newest["document_id"], student_id=student_id)
                continue
            if linked:
                self._entry(chain, "iep_document_id", "", False, status="unavailable", student_id=student_id,
                            detail="本课引用的 IEP 已撤回、删除或过期，不再进入分析与评分")
            else:
                self._entry(chain, "iep_document_id", "", False, status="not_linked", student_id=student_id,
                            detail="本课未引用该学生的 IEP")
            if self.require_iep:
                self._break(chain, "iep_document_id", "iep_missing", "要求 IEP 但该学生在本课没有当前有效的 IEP 引用",
                            student_id=student_id, video_task_id=task_id)
        if report is not None:
            self._verify_report_iep_links(chain, report, {s["student_id"] for s in students})

    def _verify_report_iep_links(self, chain, report, student_ids: set[str]) -> None:
        content = (_json(report.get("payload_json"), {}).get("report", {})) or {}
        for link in content.get("iep_links", []) if isinstance(content, dict) else []:
            if not isinstance(link, dict):
                continue
            student_id = str(link.get("student_id") or "")
            if not student_id:
                self._break(chain, "iep_document_id", "iep_link_without_student_id",
                            "报告 iep_links 未使用 student_id 关联", report_id=report["report_id"])
                continue
            if student_id not in student_ids:
                self._break(chain, "iep_document_id", "iep_link_student_orphan",
                            "报告 iep_links 指向未在报告学生列表中的 student_id", report_id=report["report_id"],
                            student_id=student_id)
            for version in link.get("document_versions", []) or []:
                document_id = str(version.get("document_id") or "") if isinstance(version, dict) else ""
                if document_id and self._has("demo2_dossier_documents") and self._row(
                        "SELECT 1 AS present FROM demo2_dossier_documents WHERE document_id=?", (document_id,)) is None:
                    self._break(chain, "iep_document_id", "iep_link_document_orphan",
                                "报告 iep_links 指向不存在的资料版本", report_id=report["report_id"],
                                document_id=document_id)

    def _current_iep_heads(self, student_id: str) -> list[dict[str, Any]]:
        """Same rule as Demo2DossierStore.iep_context: newest usable version per IEP family."""
        rows = self._rows("SELECT * FROM demo2_dossier_documents WHERE student_id=? AND document_type='iep' "
                          "ORDER BY created_at, version", (student_id,))
        heads: dict[str, dict[str, Any]] = {}
        for row in rows:
            if not self._document_available(row):
                continue
            current = heads.get(row["family_id"])
            if current is None or row["version"] > current["version"]:
                heads[row["family_id"]] = row
        return list(heads.values())

    def _document_available(self, document: dict[str, Any]) -> bool:
        auth = self._row("SELECT * FROM demo2_dossier_authorizations WHERE authorization_id=?",
                         (document["authorization_id"],))
        return (document["status"] == "available" and document["metadata_ciphertext"] is not None
                and document["retain_until"] > self.today and auth is not None
                and auth["status"] == "active" and auth["valid_until"] > self.today
                and auth["metadata_ciphertext"] is not None
                and all(document[key] == auth[key] for key in ("student_id", "owner_account_id", "scope_key")))

    def _task_evaluation_ids(self, task_id: str) -> list[str]:
        if not self._has("demo2_classroom_evaluations"):
            return []
        return [row["record_id"] for row in self._rows(
            "SELECT record_id FROM demo2_classroom_evaluations WHERE status='active' "
            "AND json_extract(payload_json,'$.task_id')=? ORDER BY updated_at", (task_id,))]

    def _evaluation_row(self, evaluation_id: str) -> dict[str, Any] | None:
        candidates = [evaluation_id]
        if evaluation_id.startswith("evaluation-"):
            candidates.append(evaluation_id[len("evaluation-"):])
        for record_id in candidates:
            row = self._row("SELECT * FROM demo2_classroom_evaluations WHERE record_id=?", (record_id,))
            if row is not None:
                return row
        return self._row("SELECT * FROM demo2_classroom_evaluations WHERE json_extract(payload_json,'$.evaluation_id')=?",
                         (evaluation_id,))

    def _verify_evaluations(self, chain, task, evaluation_ids, *, report, expected_task_id=None) -> None:
        task_id = task["task_id"] if task is not None else expected_task_id
        if not evaluation_ids:
            self._entry(chain, "evaluation_id", "", False, detail="没有关联课堂评价")
            self._break(chain, "evaluation_id", "evaluation_missing", "报告/课堂任务未关联任何 evaluation_id",
                        video_task_id=task_id, report_id=report["report_id"] if report else None)
            return
        if not self._has("demo2_classroom_evaluations"):
            for evaluation_id in evaluation_ids:
                self._entry(chain, "evaluation_id", str(evaluation_id), False, detail="评价表不存在")
            self._break(chain, "evaluation_id", "evaluation_table_missing", "数据库没有 demo2_classroom_evaluations 表")
            return
        task_exists_cache: dict[str, bool] = {}
        for evaluation_id in evaluation_ids:
            evaluation_id = str(evaluation_id)
            row = self._evaluation_row(evaluation_id)
            if row is None:
                self._entry(chain, "evaluation_id", evaluation_id, False, detail="评价记录不存在")
                self._break(chain, "evaluation_id", "evaluation_missing", "报告关联的 evaluation_id 不存在",
                            evaluation_id=evaluation_id, report_id=report["report_id"] if report else None)
                continue
            data = _json(row["payload_json"], {})
            linked_task = str(data.get("task_id") or data.get("video_task_id") or "")
            stable_id = str(data.get("evaluation_id") or f"evaluation-{row['record_id']}")
            self._entry(chain, "evaluation_id", stable_id, True, record_id=row["record_id"],
                        evaluation_status=row["status"], version=int(row["version"]),
                        linked_video_task_id=linked_task,
                        detail=f"状态 {row['status']} · v{row['version']} · 指向任务 {linked_task or '（空）'}")
            if row["status"] != "active":
                self._warn(chain, "evaluation_id", "evaluation_not_active", "评价记录已撤销，报告需重新生成",
                           evaluation_id=stable_id)
            if not linked_task:
                self._break(chain, "evaluation_id", "evaluation_task_missing", "评价未关联 video_task_id",
                            evaluation_id=stable_id)
                continue
            if linked_task not in task_exists_cache:
                task_exists_cache[linked_task] = self._row(
                    "SELECT 1 AS present FROM video_analysis_tasks WHERE task_id=?", (linked_task,)) is not None
            if not task_exists_cache[linked_task]:
                self._break(chain, "evaluation_id", "evaluation_task_dangling",
                            "评价指向不存在的 video_task_id", evaluation_id=stable_id, video_task_id=linked_task)
                continue
            if task_id and linked_task != task_id:
                self._break(chain, "evaluation_id", "evaluation_task_mismatch",
                            "评价指向的 video_task_id 与报告/起点任务不一致", evaluation_id=stable_id,
                            expected=task_id, found=linked_task)
                continue
            if task is not None:
                course_id = str(data.get("course_id") or "")
                if not course_id:
                    self._break(chain, "course_id", "evaluation_course_missing", "评价缺少 course_id",
                                evaluation_id=stable_id)
                elif course_id != str(task.get("course_id") or ""):
                    self._break(chain, "course_id", "evaluation_course_mismatch", "评价 course_id 与课堂视频任务不一致",
                                evaluation_id=stable_id, expected=task.get("course_id"), found=course_id)
                if row["owner_account_id"] != (task.get("account_id") or ""):
                    self._break(chain, "evaluation_id", "evaluation_owner_mismatch", "评价所属账号与课堂视频任务不一致",
                                evaluation_id=stable_id)
                iep_id = str(data.get("iep_summary_id") or "")
                if iep_id:
                    self._verify_evaluation_iep(chain, stable_id, iep_id, task)

    def _verify_evaluation_iep(self, chain, evaluation_id, document_id, task) -> None:
        document = self._row("SELECT * FROM demo2_dossier_documents WHERE document_id=?", (document_id,)) \
            if self._has("demo2_dossier_documents") else None
        if document is None:
            self._break(chain, "iep_document_id", "evaluation_iep_dangling", "评价引用的 IEP 资料不存在",
                        evaluation_id=evaluation_id, document_id=document_id)
            return
        if document["document_type"] != "iep":
            self._break(chain, "iep_document_id", "evaluation_iep_wrong_type",
                        "评价的 iep_summary_id 指向非 IEP 资料（专业资料不得作为 IEP）",
                        evaluation_id=evaluation_id, document_id=document_id, document_type=document["document_type"])
            return
        bound = self._row("SELECT COUNT(*) AS n FROM demo2_identity_bindings WHERE task_id=? AND student_id=? "
                          "AND role='student' AND status='confirmed'", (task["task_id"], document["student_id"])) \
            if self._has("demo2_identity_bindings") else {"n": 0}
        if not bound["n"]:
            self._break(chain, "iep_document_id", "evaluation_iep_student_unbound",
                        "评价引用的 IEP 所属学生未在本课确认身份", evaluation_id=evaluation_id,
                        document_id=document_id, student_id=document["student_id"])

    # -- name-join and orphan checks ----------------------------------------------

    def _name_join_check(self, chain) -> None:
        student_ids = [e["id"] for e in chain["levels"]["student_id"]["entries"] if e["exists"]]
        if not student_ids or not self._has("demo2_identity_students"):
            return
        placeholders = ",".join("?" for _ in student_ids)
        names = {row["student_id"]: row["display_name"] for row in self._rows(
            f"SELECT student_id, display_name FROM demo2_identity_students WHERE student_id IN ({placeholders})",
            tuple(student_ids))}
        checked = 0
        for level in LEVELS:
            for entry in chain["levels"][level]["entries"]:
                values = [entry["id"]] + [str(entry.get(key) or "") for key in
                                          ("content_report_id", "record_id", "reference_id", "linked_video_task_id")]
                for value in values:
                    if not value:
                        continue
                    checked += 1
                    for student_id, name in names.items():
                        name = (name or "").strip()
                        if len(name) >= MIN_NAME_LENGTH and name in value:
                            self._break(chain, level, "name_join",
                                        "链路编号中包含学生姓名，说明使用了姓名拼接而不是稳定 ID",
                                        matched_student_id=student_id, field=level)
        self.log.event("name_join_check", "done", checked_values=checked, student_count=len(names))

    def _orphans_for_task(self, chain, task, report) -> None:
        task_id = task["task_id"]
        in_report = {str(item) for item in _json(report.get("evaluation_ids_json"), [])}
        for record_id in self._task_evaluation_ids(task_id):
            stable = f"evaluation-{record_id}"
            if stable not in in_report and record_id not in in_report:
                self._warn(chain, "evaluation_id", "evaluation_not_in_report",
                           "该任务存在未进入本报告的有效评价，报告可能需要重新生成", evaluation_id=stable,
                           report_id=report["report_id"])

    def scan_orphans(self) -> list[dict[str, Any]]:
        """Database-wide dangling references, independent of a start ID."""
        checks = []
        if self._has("demo2_classroom_evaluations", "video_analysis_tasks"):
            checks.append(("evaluation_id", "evaluation_task_dangling", "评价指向不存在的 video_task_id",
                           """SELECT e.record_id AS id, json_extract(e.payload_json,'$.task_id') AS target
                              FROM demo2_classroom_evaluations e
                              WHERE COALESCE(json_extract(e.payload_json,'$.task_id'),'')<>''
                                AND NOT EXISTS (SELECT 1 FROM video_analysis_tasks t
                                                WHERE t.task_id=json_extract(e.payload_json,'$.task_id'))"""))
        if self._has("demo2_reports", "video_analysis_tasks"):
            checks.append(("report_id", "report_task_dangling", "报告指向不存在的 video_task_id",
                           """SELECT r.report_id AS id, r.task_id AS target FROM demo2_reports r
                              WHERE NOT EXISTS (SELECT 1 FROM video_analysis_tasks t WHERE t.task_id=r.task_id)"""))
        if self._has("demo2_dossier_references", "video_analysis_tasks"):
            checks.append(("iep_document_id", "reference_task_dangling", "课堂引用指向不存在的 video_task_id",
                           """SELECT r.reference_id AS id, r.task_id AS target FROM demo2_dossier_references r
                              WHERE NOT EXISTS (SELECT 1 FROM video_analysis_tasks t WHERE t.task_id=r.task_id)"""))
        if self._has("demo2_dossier_reference_documents", "demo2_dossier_documents"):
            checks.append(("iep_document_id", "reference_document_dangling", "课堂引用指向不存在的资料版本",
                           """SELECT l.reference_id AS id, l.document_id AS target FROM demo2_dossier_reference_documents l
                              WHERE NOT EXISTS (SELECT 1 FROM demo2_dossier_documents d WHERE d.document_id=l.document_id)"""))
        if self._has("demo2_dossier_documents", "demo2_identity_students"):
            checks.append(("student_id", "document_student_dangling", "资料版本指向不存在的 student_id",
                           """SELECT d.document_id AS id, d.student_id AS target FROM demo2_dossier_documents d
                              WHERE NOT EXISTS (SELECT 1 FROM demo2_identity_students s WHERE s.student_id=d.student_id)"""))
        if self._has("demo2_identity_bindings", "demo2_identity_students"):
            checks.append(("student_id", "binding_student_dangling", "身份绑定指向不存在的 student_id",
                           """SELECT b.binding_id AS id, b.student_id AS target FROM demo2_identity_bindings b
                              WHERE b.student_id IS NOT NULL AND NOT EXISTS
                              (SELECT 1 FROM demo2_identity_students s WHERE s.student_id=b.student_id)"""))
        problems = []
        for level, code, message, sql in checks:
            rows = self._rows(sql, ())
            self.log.event("orphan_scan", "found" if rows else "clean", level=level, check=code, count=len(rows))
            for row in rows:
                problems.append({"level": level, "code": code, "message": message,
                                 "id": row["id"], "target": row["target"]})
                self.log.event("chain_break", code, level=level, reason=message, id=row["id"], target=row["target"])
        return problems

    # -- final status -------------------------------------------------------------------

    def _finish(self, chain) -> dict[str, Any]:
        self._name_join_check(chain)
        ambiguous = False
        for level in LEVELS:
            info = chain["levels"][level]
            entries = info["entries"]
            statuses = {entry["status"] for entry in entries}
            blocking = [problem for problem in info["problems"] if problem.get("code") != "multiple_current_iep"]
            if not entries:
                info["status"] = "broken"
                if not blocking:
                    problem = {"level": level, "code": "level_not_reached", "message": "上游断链，未能追溯到该层级"}
                    info["problems"].append(problem)
                    chain["errors"].append(problem)
            elif blocking:
                info["status"] = "broken"
            elif "ambiguous" in statuses:
                info["status"] = "ambiguous"
                ambiguous = True
            elif level == "iep_document_id" and statuses <= {"not_linked", "unavailable"}:
                info["status"] = "not_linked"
            elif level == "iep_document_id" and statuses & {"not_linked", "unavailable"}:
                info["status"] = "partial"
            elif all(entry["exists"] for entry in entries):
                info["status"] = "ok"
            else:
                info["status"] = "broken"
        first_break = next((level for level in LEVELS if chain["levels"][level]["status"] == "broken"), None)
        if chain["errors"]:
            final = "broken"
        elif ambiguous:
            final = "ambiguous"
        elif chain["levels"]["iep_document_id"]["status"] in {"not_linked", "partial"}:
            final = "complete_without_iep"
        else:
            final = "complete"
        chain["final_status"] = final
        chain["first_broken_level"] = first_break
        chain["chain"] = {level: [entry["id"] for entry in chain["levels"][level]["entries"]] for level in LEVELS}
        self.log.event("trace_result", final, start_kind=chain["start"]["kind"], start_id=chain["start"]["id"],
                       first_broken_level=first_break, error_count=len(chain["errors"]),
                       warning_count=len(chain["warnings"]),
                       error_codes=sorted({error["code"] for error in chain["errors"]}) or None)
        return chain


def open_readonly(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(f"数据库文件不存在：{path}")
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    connection.execute("SELECT name FROM sqlite_master LIMIT 1").fetchall()
    return connection


def render_text(results: list[dict[str, Any]], orphans: list[dict[str, Any]] | None) -> str:
    marks = {"ok": "✔", "broken": "✘", "ambiguous": "?", "not_linked": "-", "partial": "~", "pending": "·"}
    lines = []
    for chain in results:
        start = chain["start"]
        lines.append(f"== 稳定 ID 链路校验：起点 {start['kind']}={start['id']}"
                     + (f"（报告 {start['report_id']}）" if start.get("report_id") else ""))
        for index, level in enumerate(LEVELS, 1):
            info = chain["levels"][level]
            lines.append(f"  {index}. [{marks.get(info['status'], '?')}] {level:<16} {info['label']} · {info['status']}")
            for entry in info["entries"]:
                owner = f" student_id={entry['student_id']}" if entry.get("student_id") else ""
                exists = "存在" if entry["exists"] else "不存在"
                lines.append(f"       - {entry['id'] or '（空）'} · {exists} · {entry['status']}{owner}"
                             + (f" · {entry['detail']}" if entry.get("detail") else ""))
                if entry.get("candidates"):
                    lines.append(f"         候选 IEP：{', '.join(entry['candidates'])}")
        for error in chain["errors"]:
            lines.append(f"  ✘ 断链 [{error['level']}] {error['code']}：{error['message']}"
                         + "".join(f" {k}={v}" for k, v in error.items() if k not in {"level", "code", "message"}))
        for warning in chain["warnings"]:
            lines.append(f"  ! 提示 [{warning['level']}] {warning['code']}：{warning['message']}")
        lines.append(f"  最终状态：{chain['final_status']}"
                     + (f"（首个断链位置：{chain['first_broken_level']}）" if chain["first_broken_level"] else ""))
    if orphans is not None:
        lines.append(f"== 全库孤儿记录扫描：{len(orphans)} 项")
        for item in orphans:
            lines.append(f"  ✘ [{item['level']}] {item['code']}：{item['message']} id={item['id']} target={item['target']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="只读校验 school_id → student_id → iep_document_id → course_id → "
                                                 "video_task_id → evaluation_id → report_id 稳定 ID 链路")
    start = parser.add_mutually_exclusive_group(required=True)
    start.add_argument("--report-id", help="从报告反向追溯（32 位 report_id，或报告内容中的 report-xxx 编号）")
    start.add_argument("--video-task-id", "--task-id", dest="video_task_id", help="从课堂视频任务正向追溯")
    parser.add_argument("--db", type=Path, default=Path(os.getenv("REHAB_DEMO2_DB_PATH", str(DEFAULT_DB))),
                        help="SQLite 数据库路径（默认 REHAB_DEMO2_DB_PATH 或 outputs/seewo_demo2/rehab_affect_demo2.sqlite3）")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出校验结果")
    parser.add_argument("--require-iep", action="store_true", help="每位学生都必须有当前有效 IEP，否则视为断链")
    parser.add_argument("--scan-orphans", action="store_true", help="同时扫描全库孤儿记录（悬空的任务/资料/学生引用）")
    parser.add_argument("--log-file", type=Path, default=None,
                        help="JSON 行日志路径（默认 .runtime/logs/verify_id_chain_YYYYMMDD.jsonl）")
    parser.add_argument("--no-log-file", action="store_true", help="不写日志文件")
    parser.add_argument("--quiet", action="store_true", help="不在 stderr 回显逐步日志")
    args = parser.parse_args(argv)

    log_path = None if args.no_log_file else (
        args.log_file or DEFAULT_LOG_DIR / f"verify_id_chain_{datetime.now().strftime('%Y%m%d')}.jsonl")
    logger = ChainLogger(log_path, echo=not args.quiet)
    start_kind = "report_id" if args.report_id else "video_task_id"
    start_id = args.report_id or args.video_task_id
    logger.event("run_start", "begin", start_kind=start_kind, start_id=start_id, db=str(args.db),
                 require_iep=args.require_iep, scan_orphans=args.scan_orphans)
    if not isinstance(start_id, str) or not start_id.strip() or len(start_id) > 160:
        logger.event("run_end", "usage_error", reason="起始 ID 为空或过长", exit_code=EXIT_USAGE)
        print("起始 ID 为空或过长", file=sys.stderr)
        return EXIT_USAGE
    try:
        connection = open_readonly(args.db)
    except (OSError, sqlite3.Error) as error:
        logger.event("run_end", "db_error", reason=str(error), exit_code=EXIT_USAGE)
        print(f"无法以只读方式打开数据库：{error}", file=sys.stderr)
        return EXIT_USAGE
    try:
        verifier = ChainVerifier(connection, logger, require_iep=args.require_iep)
        results = [verifier.from_report(start_id.strip())] if args.report_id else verifier.from_task(start_id.strip())
        orphans = verifier.scan_orphans() if args.scan_orphans else None
    except sqlite3.Error as error:
        logger.event("run_end", "db_error", reason=str(error), exit_code=EXIT_USAGE)
        print(f"读取数据库失败：{error}", file=sys.stderr)
        return EXIT_USAGE
    finally:
        connection.close()

    if any(chain["final_status"] == "broken" for chain in results) or orphans:
        code, final = EXIT_BROKEN, "broken"
    elif any(chain["final_status"] == "ambiguous" for chain in results):
        code, final = EXIT_AMBIGUOUS, "ambiguous"
    else:
        code = EXIT_OK
        final = "complete" if all(chain["final_status"] == "complete" for chain in results) else "complete_without_iep"
    if args.json:
        print(json.dumps({"final_status": final, "exit_code": code, "run_id": logger.run_id,
                          "log_file": str(log_path) if log_path else None, "results": results,
                          "orphans": orphans}, ensure_ascii=False, indent=2))
    else:
        print(render_text(results, orphans))
        print(f"== 总结：{final}（退出码 {code}）" + (f" · 日志 {log_path}" if log_path else ""))
    logger.event("run_end", final, start_kind=start_kind, start_id=start_id, exit_code=code,
                 chain_count=len(results), orphan_count=len(orphans) if orphans is not None else None,
                 elapsed_ms=logger.elapsed_ms())
    return code


if __name__ == "__main__":
    sys.exit(main())
