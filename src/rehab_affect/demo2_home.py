"""Teacher home page: classroom-loop progress, to-do list and recent tasks.

``build_home_summary`` reads only the signed-in teacher's own data through the
existing stores (school context, identity roster, measurement course task
list, measurement / evaluation workspaces, applicability and report lists).
The two pieces that have no cheap store method – current identity bindings
and dossier authorisation dates – are read with read-only SQL that applies
the same owner/scope filters and validity rules as the stores, without
decrypting any dossier metadata.

Each page load writes one line to ``home_debug_YYYYMMDD.jsonl`` (beside the
store's data directory or in ``REHAB_DEMO2_HOME_DEBUG_LOG_DIR``) with the
account id, per-step status codes, to-do counts, elapsed time and section
errors. Student names, course names and document text never reach the log.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from .demo2_identity_store import Demo2IdentityStore
from .demo2_ui_kit import inject_kit, teacher_header
from .demo2_upload_debug import log_dir_for_store

HOME_DEBUG_LOG_DIR_ENV = "REHAB_DEMO2_HOME_DEBUG_LOG_DIR"
HOME_LOGGER = logging.getLogger("rehab_affect.home")
_LOG_LOCK = threading.Lock()

HOME_PATH = "/demo2/home"
HOME_API_PATH = "/api/v1/demo2/home/summary"

STEP_KEYS = ("school", "roster", "dossier", "upload", "identity", "applicability", "assessment", "report")
STEP_STATUSES = ("not_started", "in_progress", "done", "attention")
STATUS_TEXT = {"not_started": "未开始", "in_progress": "进行中", "done": "已完成", "attention": "需处理"}

READY_STATUSES = frozenset({"evidence_ready", "completed"})
FAILED_STATUSES = frozenset({"failed", "error", "processing_failed"})
# Backend task codes folded into the shared badge vocabulary of the UI kit.
TASK_BADGE_CODES = {
    "waiting_upload": "uploading", "uploading": "uploading", "queued": "queued", "pending": "queued",
    "uploaded_pending_worker": "queued", "precheck_complete": "processing", "processing": "processing",
    "analyzing": "processing", "running": "processing", "evidence_ready": "evidence_ready",
    "completed": "evidence_ready", "failed": "failed", "error": "failed", "processing_failed": "failed",
    "cancelled": "cancelled", "expired": "expired",
}
INACTIVE_STATUSES = frozenset({"cancelled", "expired"})
# To-do types added with course-task files, the required IEP summary and video measurements.
NEW_TODO_KEYS = ("course_task_uploads", "iep_summaries", "lesson_measurement_reviews")
# To-do types added with course evaluation, the course overview and multi-student detection.
V4_TODO_KEYS = ("course_evaluations", "course_overviews", "few_students")
COURSE_EVALUATION_TEMPLATE = "basic_100"
MIN_LESSON_STUDENTS = 3
# Person-filter views parse each analysis result, so only the newest ready lessons are checked.
FEW_STUDENT_CHECK_LIMIT = 10
RECENT_TASK_LIMIT = 5
# Per-task checks (applicability, report freshness) run for the newest ready
# tasks only, so a long history cannot make the home page slow.
TASK_CHECK_LIMIT = 20
TODO_ITEM_LIMIT = 10
EXPIRY_WINDOW_DAYS = 30
_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,128}")


@dataclass
class HomeSources:
    """Store entry points supplied by the HTTP handler (shared locks/errors)."""

    identity: Callable[..., Any]
    measurement: Callable[..., Any]
    evaluation: Callable[..., Any]
    report: Callable[..., Any]
    applicability: Callable[..., Any]


# --------------------------------------------------------------------------
# Debug log
# --------------------------------------------------------------------------


def home_log_dir(store: Any) -> Path:
    configured = os.getenv(HOME_DEBUG_LOG_DIR_ENV, "").strip()
    if configured:
        return Path(configured)
    return log_dir_for_store(store)


def _clean_id(value: Any) -> str:
    text = str(value)
    return text if re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", text) else "<invalid>"


def home_debug_event(store: Any, operation: str, result: str, **fields: Any) -> dict[str, Any]:
    """Write one structured line; a logging failure never blocks the page."""
    entry: dict[str, Any] = {
        "ts": datetime.now().astimezone().isoformat(timespec="milliseconds"),
        "operation": _clean_id(operation),
        "result": _clean_id(result),
    }
    for key, value in fields.items():
        if value is None or value == "":
            continue
        if key in {"account_id", "role", "next_step", "code", "page"}:
            entry[key] = _clean_id(value)
        elif key in {"elapsed_ms", "http_status", "todo_total", "task_count", "ready_task_count"}:
            entry[key] = value if isinstance(value, (int, float)) and not isinstance(value, bool) else "<invalid>"
        elif key == "step_status":
            entry[key] = {_clean_id(k): _clean_id(v) for k, v in dict(value).items()}
        elif key in {"todo_counts", "new_todo_counts", "v4_todo_counts"}:
            entry[key] = {_clean_id(k): int(v) for k, v in dict(value).items() if isinstance(v, int)}
        elif key == "errors":
            entry[key] = {_clean_id(k): _clean_id(v) for k, v in dict(value).items()}
        elif key == "message":
            entry[key] = str(value)[:160]
    line = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
    HOME_LOGGER.debug(line)
    try:
        folder = home_log_dir(store)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"home_debug_{entry['ts'][:10].replace('-', '')}.jsonl"
        with _LOG_LOCK, path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except (OSError, TypeError, ValueError):
        HOME_LOGGER.warning("home debug log write failed")
    return entry


# --------------------------------------------------------------------------
# Data collection
# --------------------------------------------------------------------------


def _error_code(exc: BaseException) -> str:
    code = getattr(exc, "code", "")
    return str(code) if isinstance(code, str) and code else type(exc).__name__


def _safe_id(value: Any) -> str:
    text = str(value or "")
    return text if _ID_RE.fullmatch(text) else ""


def _query(path: str, **params: str) -> str:
    from urllib.parse import urlencode

    clean = {key: value for key, value in params.items() if value}
    return path + ("?" + urlencode(clean) if clean else "")


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    return connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _current_student_bindings(records: Any, account_id: str) -> dict[str, int]:
    """Count confirmed student bindings on the current frame revision per task."""
    counts: dict[str, int] = {}
    with records._connect() as connection:
        if not _table_exists(connection, "demo2_identity_bindings"):
            return counts
        rows = connection.execute(
            """SELECT b.task_id, b.frame_revision, t.processing_result_json
               FROM demo2_identity_bindings b JOIN video_analysis_tasks t ON t.task_id = b.task_id
               WHERE b.owner_account_id = ? AND t.account_id = ? AND b.status = 'confirmed' AND b.role = 'student'""",
            (account_id, account_id),
        ).fetchall()
    for row in rows:
        revision = Demo2IdentityStore._revision({"processing_result_json": row["processing_result_json"]})
        if revision and row["frame_revision"] == revision:
            counts[row["task_id"]] = counts.get(row["task_id"], 0) + 1
    return counts


def _unlinked_iep_students(records: Any, account_id: str, task_ids: list[str],
                           iep_students: set[str]) -> dict[str, list[str]]:
    """Per task: confirmed students that have a usable IEP but no live classroom
    reference to an IEP version for that task (the iep_document_id link)."""
    gaps: dict[str, list[str]] = {}
    if not task_ids or not iep_students:
        return gaps
    with records._connect() as connection:
        if not _table_exists(connection, "demo2_identity_bindings"):
            return gaps
        placeholders = ",".join("?" for _ in task_ids)
        rows = connection.execute(
            f"""SELECT DISTINCT b.task_id, b.student_id, b.frame_revision, t.processing_result_json
                FROM demo2_identity_bindings b JOIN video_analysis_tasks t ON t.task_id = b.task_id
                WHERE b.owner_account_id = ? AND t.account_id = ? AND b.status = 'confirmed'
                AND b.role = 'student' AND b.task_id IN ({placeholders})""",
            (account_id, account_id, *task_ids),
        ).fetchall()
        linked: set[tuple[str, str]] = set()
        if (_table_exists(connection, "demo2_dossier_references")
                and _table_exists(connection, "demo2_dossier_reference_documents")
                and _table_exists(connection, "demo2_dossier_documents")):
            columns = {row[1] for row in connection.execute("PRAGMA table_info(demo2_dossier_references)")}
            # withdrawn_at is NOT NULL DEFAULT '' – an empty value means the reference is live.
            live = "AND COALESCE(r.withdrawn_at, '') = ''" if "withdrawn_at" in columns else ""
            for row in connection.execute(
                f"""SELECT DISTINCT r.task_id, r.student_id FROM demo2_dossier_references r
                    JOIN demo2_dossier_reference_documents rd ON rd.reference_id = r.reference_id
                    JOIN demo2_dossier_documents d ON d.document_id = rd.document_id
                    WHERE r.owner_account_id = ? AND d.document_type = 'iep' {live}
                    AND r.task_id IN ({placeholders})""",
                (account_id, *task_ids),
            ):
                linked.add((row["task_id"], row["student_id"]))
    for row in rows:
        revision = Demo2IdentityStore._revision({"processing_result_json": row["processing_result_json"]})
        if not revision or row["frame_revision"] != revision:
            continue
        task_id, student_id = row["task_id"], row["student_id"]
        if student_id in iep_students and (task_id, student_id) not in linked:
            students = gaps.setdefault(task_id, [])
            if student_id not in students:
                students.append(student_id)
    return gaps


def _bound_students(records: Any, account_id: str, task_ids: list[str]) -> dict[str, list[str]]:
    """Per task: students confirmed on the current frame revision (same rules as the identity store)."""
    bound: dict[str, list[str]] = {}
    if not task_ids:
        return bound
    with records._connect() as connection:
        if not _table_exists(connection, "demo2_identity_bindings"):
            return bound
        placeholders = ",".join("?" for _ in task_ids)
        rows = connection.execute(
            f"""SELECT DISTINCT b.task_id, b.student_id, b.frame_revision, t.processing_result_json
                FROM demo2_identity_bindings b JOIN video_analysis_tasks t ON t.task_id = b.task_id
                WHERE b.owner_account_id = ? AND t.account_id = ? AND b.status = 'confirmed'
                AND b.role = 'student' AND b.task_id IN ({placeholders})""",
            (account_id, account_id, *task_ids),
        ).fetchall()
    for row in rows:
        revision = Demo2IdentityStore._revision({"processing_result_json": row["processing_result_json"]})
        if not revision or row["frame_revision"] != revision:
            continue
        students = bound.setdefault(row["task_id"], [])
        if row["student_id"] not in students:
            students.append(row["student_id"])
    return bound


def _confirmed_course_task_courses(records: Any, account_id: str) -> set[str]:
    """Course ids of this account that have a confirmed course-task document (Word/PDF)."""
    with records._connect() as connection:
        if not _table_exists(connection, "demo2_course_task_documents"):
            return set()
        return {row["course_id"] for row in connection.execute(
            """SELECT DISTINCT course_id FROM demo2_course_task_documents
               WHERE owner_account_id = ? AND status = 'confirmed'""", (account_id,))}


def _reviewed_course_evaluation_tasks(evaluations: list[dict[str, Any]]) -> set[str]:
    """Task ids that have a teacher-checked course evaluation (school standard basic_100 template)."""
    reviewed: set[str] = set()
    for item in evaluations:
        result = item.get("result") if isinstance(item.get("result"), dict) else {}
        task_id = _safe_id(item.get("task_id") or item.get("video_task_id"))
        if (task_id and item.get("template_id") == COURSE_EVALUATION_TEMPLATE
                and item.get("reviewed") is True and result.get("status") == "reviewed"):
            reviewed.add(task_id)
    return reviewed


def _report_conclusions(records: Any, account_id: str, report_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Per report id: the course-overview conclusion stored in the teacher's own report snapshot."""
    found: dict[str, dict[str, Any]] = {}
    wanted = [item for item in report_ids if _safe_id(item)]
    if not wanted:
        return found
    with records._connect() as connection:
        if not _table_exists(connection, "demo2_reports"):
            return found
        placeholders = ",".join("?" for _ in wanted)
        rows = connection.execute(
            f"SELECT report_id, payload_json FROM demo2_reports WHERE owner_account_id = ? AND report_id IN ({placeholders})",
            (account_id, *wanted),
        ).fetchall()
    for row in rows:
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except (TypeError, ValueError):
            continue
        overview = ((payload.get("report") or {}).get("course_overview") if isinstance(payload, dict) else None) or {}
        conclusion = overview.get("conclusion") if isinstance(overview, dict) else None
        if isinstance(conclusion, dict) and conclusion.get("available") is True:
            grade = conclusion.get("grade") if isinstance(conclusion.get("grade"), dict) else {}
            found[row["report_id"]] = {"grade_key": str(grade.get("key") or ""), "grade_label": str(grade.get("label") or ""),
                                       "score": conclusion.get("score"),
                                       "student_count": overview.get("student_count")}
    return found


def _lesson_student_counts(records: Any, token: str, task_ids: list[str]) -> tuple[dict[str, int], str]:
    """Per task: students currently included by the person filter (teacher overrides applied).

    Tasks analysed before the person filter existed return no count and are skipped.
    """
    counts: dict[str, int] = {}
    viewer = getattr(records, "account_person_filter_view", None)
    if not callable(viewer):
        return counts, ""
    error = ""
    for task_id in task_ids:
        try:
            view = viewer(token, task_id)
        except Exception as exc:  # one unreadable analysis must not hide the others
            error = error or _error_code(exc)
            continue
        summary = (view or {}).get("person_filter_summary") if isinstance(view, dict) else None
        if isinstance(summary, dict) and isinstance(summary.get("student_count"), int):
            counts[task_id] = summary["student_count"]
    return counts, error


def _dossier_state(records: Any, account_id: str, scope_key: str, today: date) -> dict[str, Any]:
    """Authorisation dates and usable IEP counts, mirroring the dossier store rules."""
    today_text = today.isoformat()
    state: dict[str, Any] = {"authorizations": {}, "iep_counts": {}}
    if not scope_key:
        return state
    with records._connect() as connection:
        if not (_table_exists(connection, "demo2_dossier_authorizations")
                and _table_exists(connection, "demo2_dossier_documents")):
            return state
        for row in connection.execute(
            """SELECT student_id, valid_until FROM demo2_dossier_authorizations
               WHERE owner_account_id = ? AND scope_key = ? AND status = 'active'
               AND metadata_ciphertext IS NOT NULL AND valid_until > ?""",
            (account_id, scope_key, today_text),
        ):
            state["authorizations"][row["student_id"]] = row["valid_until"]
        for row in connection.execute(
            """SELECT d.student_id, COUNT(*) AS total FROM demo2_dossier_documents d
               JOIN demo2_dossier_authorizations a ON a.authorization_id = d.authorization_id
               WHERE d.owner_account_id = ? AND d.scope_key = ? AND d.document_type = 'iep'
               AND d.status = 'available' AND d.metadata_ciphertext IS NOT NULL AND d.retain_until > ?
               AND a.status = 'active' AND a.metadata_ciphertext IS NOT NULL AND a.valid_until > ?
               AND a.student_id = d.student_id AND a.owner_account_id = d.owner_account_id
               AND a.scope_key = d.scope_key
               GROUP BY d.student_id""",
            (account_id, scope_key, today_text, today_text),
        ):
            state["iep_counts"][row["student_id"]] = int(row["total"])
    return state


def _step(key: str, title: str, status: str, count: str, detail: str, action_label: str, action_href: str,
          *, secondary: dict[str, str] | None = None) -> dict[str, Any]:
    if status not in STEP_STATUSES:
        status = "attention"
    step = {"key": key, "title": title, "status": status, "status_label": STATUS_TEXT[status], "count": count,
            "detail": detail, "action": {"label": action_label, "href": action_href}}
    if secondary:
        step["secondary_action"] = secondary
    return step


def build_home_summary(records: Any, token: str, account: dict[str, Any], sources: HomeSources, *,
                       today: date | None = None) -> dict[str, Any]:
    """Collect the teacher's loop state. Never raises for one failing section."""
    started = time.perf_counter()
    today = today or datetime.now().astimezone().date()
    account_id = str(account.get("account_id") or "")
    errors: dict[str, str] = {}

    def section(name: str, default: Any, loader: Callable[[], Any]) -> Any:
        try:
            return loader()
        except Exception as exc:  # one broken store must not hide the rest of the page
            errors[name] = _error_code(exc)
            return default

    school_payload = section("school", {}, lambda: records.account_school_context(token))
    school = dict((school_payload or {}).get("context") or {})
    roster = section("roster", {}, lambda: sources.identity("roster", token))
    students = [item for item in (roster or {}).get("students") or [] if isinstance(item, dict)]
    student_names = {str(item.get("student_id")): str(item.get("display_name") or "") for item in students}
    scope_key = str((roster or {}).get("scope_key") or "")
    tasks_payload = section("tasks", {}, lambda: sources.measurement("course_tasks", token))
    tasks = [dict(item) for item in (tasks_payload or {}).get("tasks") or [] if isinstance(item, dict)]
    tasks.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    ready_tasks = [task for task in tasks if task.get("analysis_status") in READY_STATUSES]
    checked_tasks = ready_tasks[:TASK_CHECK_LIMIT]
    failed_tasks = [task for task in tasks if task.get("analysis_status") in FAILED_STATUSES]
    processing_tasks = [task for task in tasks
                        if task.get("analysis_status") not in READY_STATUSES | FAILED_STATUSES]

    bindings = section("identity", {}, lambda: _current_student_bindings(records, account_id))
    dossier = section("dossier", {"authorizations": {}, "iep_counts": {}},
                      lambda: _dossier_state(records, account_id, scope_key, today))

    applicability: dict[str, dict[str, Any]] = {}
    for task in checked_tasks:
        task_id = str(task.get("task_id"))
        try:
            applicability[task_id] = dict(sources.applicability("workspace", token, task_id) or {})
        except Exception as exc:
            applicability[task_id] = {"error": _error_code(exc)}

    latest_reports: dict[str, dict[str, Any]] = {}
    for task in checked_tasks:
        task_id = str(task.get("task_id"))
        try:
            reports = (sources.report("list_for_task", token, task_id) or {}).get("reports") or []
        except Exception as exc:
            errors.setdefault("report", _error_code(exc))
            continue
        if reports:
            latest_reports[task_id] = dict(reports[0])

    measurement_ws = section("measurement", {}, lambda: sources.measurement("workspace", token))
    measurements = [item for item in (measurement_ws or {}).get("records") or [] if isinstance(item, dict)]
    evaluation_ws = section("evaluation", {}, lambda: sources.evaluation("workspace", token))
    evaluations = [item for item in (evaluation_ws or {}).get("records") or [] if isinstance(item, dict)]

    steps: list[dict[str, Any]] = []

    # 1. School information -------------------------------------------------
    school_name = str(school.get("school_name") or "")
    if "school" in errors:
        steps.append(_step("school", "学校信息", "attention", "暂时无法读取", "请刷新页面后重试。",
                           "查看学校信息", "/demo2/school"))
    elif school_name:
        steps.append(_step("school", "学校信息", "done", school_name,
                           " · ".join(filter(None, [school.get("city"), school.get("district")])) or "学校归属已填写",
                           "查看学校信息", "/demo2/school"))
    else:
        steps.append(_step("school", "学校信息", "not_started", "尚未填写",
                           "先填写城市、区县和学校，名册和上传才能归属到本校。", "填写学校信息", "/demo2/school"))

    # 2. Roster ----------------------------------------------------------------
    student_count = len(students)
    if "roster" in errors:
        steps.append(_step("roster", "学生名册建档", "attention", "暂时无法读取", "请刷新页面后重试。",
                           "打开学生名册", "/demo2/students"))
    elif not school_name or (roster or {}).get("needs_school_context"):
        steps.append(_step("roster", "学生名册建档", "not_started", "名册 0 人", "需先完成学校信息。",
                           "打开学生名册", "/demo2/students"))
    elif student_count:
        steps.append(_step("roster", "学生名册建档", "done", f"名册 {student_count} 人",
                           "可随时补充新学生。", "管理学生名册", "/demo2/students"))
    else:
        steps.append(_step("roster", "学生名册建档", "not_started", "名册 0 人",
                           "为本班学生建立名册，后续才能确认画面中的学生。", "建立学生名册", "/demo2/students"))

    # 3. Dossier authorisation and IEP ------------------------------------------
    authorizations: dict[str, str] = dossier.get("authorizations", {})
    iep_counts: dict[str, int] = dossier.get("iep_counts", {})
    roster_ids = [str(item.get("student_id")) for item in students if _safe_id(item.get("student_id"))]
    authorized = [sid for sid in roster_ids if sid in authorizations]
    with_iep = [sid for sid in roster_ids if iep_counts.get(sid, 0) == 1]
    ambiguous = [sid for sid in roster_ids if iep_counts.get(sid, 0) > 1]
    missing = [sid for sid in roster_ids if sid not in authorizations or iep_counts.get(sid, 0) != 1]
    dossier_target = (ambiguous or missing or roster_ids or [""])[0]
    dossier_href = _query("/demo2/dossier", student_id=dossier_target) if dossier_target else "/demo2/students"
    dossier_count = f"已授权 {len(authorized)}/{student_count} 人 · IEP {len(with_iep)} 人"
    if "dossier" in errors:
        steps.append(_step("dossier", "资料授权与 IEP", "attention", "暂时无法读取", "请刷新页面后重试。",
                           "打开学生名册", "/demo2/students"))
    elif not student_count:
        steps.append(_step("dossier", "资料授权与 IEP", "not_started", "已授权 0 人",
                           "建立名册后，为每位学生登记资料授权并导入 IEP 摘要。", "打开学生名册", "/demo2/students"))
    elif ambiguous:
        steps.append(_step("dossier", "资料授权与 IEP", "attention", dossier_count,
                           f"{len(ambiguous)} 位学生同时有多份有效 IEP，系统不会自动选择，请保留一份。",
                           "处理 IEP 资料", dossier_href))
    elif not missing:
        steps.append(_step("dossier", "资料授权与 IEP", "done", dossier_count,
                           "全部学生已授权并有有效 IEP。", "查看学生资料", dossier_href))
    elif authorized or with_iep:
        steps.append(_step("dossier", "资料授权与 IEP", "in_progress", dossier_count,
                           f"还有 {len(missing)} 位学生缺少有效授权或 IEP。", "继续补充资料", dossier_href))
    else:
        steps.append(_step("dossier", "资料授权与 IEP", "not_started", dossier_count,
                           "登记资料授权（含有效期）并导入 IEP 摘要。", "登记资料授权", dossier_href))

    # 4. Upload ------------------------------------------------------------------
    course_task_courses = section("course_tasks", None,
                                  lambda: _confirmed_course_task_courses(records, account_id))
    missing_course_tasks: list[dict[str, Any]] = []
    if course_task_courses is not None:
        seen_courses: set[str] = set()
        for task in tasks:
            course_id = _safe_id(task.get("course_id"))
            status = str(task.get("analysis_status") or "")
            if (not course_id or course_id in seen_courses or course_id in course_task_courses
                    or status in FAILED_STATUSES or status in INACTIVE_STATUSES):
                continue
            seen_courses.add(course_id)
            missing_course_tasks.append(task)
    course_task_tip = "上传课程任务文件可自动带入课程目标"
    course_task_secondary = ({"label": "上传课程任务文件",
                              "href": _query("/demo2/upload", course_id=_safe_id(missing_course_tasks[0].get("course_id")))}
                             if missing_course_tasks else None)
    upload_count = f"已上传 {len(tasks)} 个 · 分析完成 {len(ready_tasks)} 个"
    if "tasks" in errors:
        steps.append(_step("upload", "上传课堂视频", "attention", "暂时无法读取", "请刷新页面后重试。",
                           "打开上传页", "/demo2/upload"))
    elif not tasks:
        steps.append(_step("upload", "上传课堂视频", "not_started", "已上传 0 个",
                           f"选择课堂视频上传，后台会自动完成分析；{course_task_tip}（Word/PDF），供评分与报告使用。",
                           "上传课堂视频", "/demo2/upload"))
    elif ready_tasks:
        steps.append(_step("upload", "上传课堂视频", "done", upload_count,
                           (f"{len(processing_tasks)} 个仍在处理。" if processing_tasks else "可继续上传新的课堂。")
                           + (f"{len(missing_course_tasks)} 个课程未上传课程任务：{course_task_tip}。"
                              if missing_course_tasks else ""),
                           "继续上传", "/demo2/upload", secondary=course_task_secondary))
    elif failed_tasks and not processing_tasks:
        steps.append(_step("upload", "上传课堂视频", "attention", upload_count,
                           "视频分析失败，请在上传页重试或重新上传。", "处理失败任务", "/demo2/upload"))
    else:
        steps.append(_step("upload", "上传课堂视频", "in_progress", upload_count,
                           "视频正在上传或分析，完成后会出现在最近任务中。"
                           + (f"{course_task_tip}。" if missing_course_tasks else ""),
                           "查看处理进度", "/demo2/upload", secondary=course_task_secondary))

    # 5. Identity confirmation -----------------------------------------------------
    identity_pending = [task for task in checked_tasks if not bindings.get(str(task.get("task_id")))]
    identity_target = _safe_id((identity_pending or checked_tasks or [{}])[0].get("task_id"))
    identity_href = _query("/demo2/identity", task_id=identity_target) if identity_target else "/demo2/upload"
    identity_count = f"待确认身份的任务 {len(identity_pending)} 个"
    iep_students = {student for student, total in (dossier.get("iep_counts") or {}).items() if total}
    bound_task_ids = [str(task.get("task_id")) for task in checked_tasks if bindings.get(str(task.get("task_id")))]
    iep_link_gaps = section("iep_links", {},
                            lambda: _unlinked_iep_students(records, account_id, bound_task_ids, iep_students))
    iep_link_tasks = [task for task in checked_tasks if iep_link_gaps.get(str(task.get("task_id")))]
    if "identity" in errors:
        steps.append(_step("identity", "确认画面中的学生", "attention", "暂时无法读取", "请刷新页面后重试。",
                           "打开上传页", "/demo2/upload"))
    elif not checked_tasks:
        steps.append(_step("identity", "确认画面中的学生", "not_started", identity_count,
                           "视频分析完成后，在采样帧中框选并确认学生。", "等待视频分析", "/demo2/upload"))
    elif not identity_pending and iep_link_tasks:
        link_target = _safe_id(iep_link_tasks[0].get("task_id"))
        unlinked = sum(len(iep_link_gaps.get(str(task.get("task_id")), [])) for task in iep_link_tasks)
        steps.append(_step("identity", "确认画面中的学生", "in_progress", identity_count,
                           f"身份已确认；还有 {unlinked} 位学生未关联本课 IEP，关联后报告和评分才能引用。",
                           "关联本课 IEP", _query("/demo2/course-dossier", task_id=link_target)))
    elif not identity_pending:
        steps.append(_step("identity", "确认画面中的学生", "done", identity_count,
                           "已分析的视频都已确认学生身份。", "查看身份确认", identity_href))
    elif len(identity_pending) < len(checked_tasks):
        steps.append(_step("identity", "确认画面中的学生", "in_progress", identity_count,
                           "还有视频未确认画面中的学生。", "继续确认身份", identity_href))
    else:
        steps.append(_step("identity", "确认画面中的学生", "not_started", identity_count,
                           "在采样帧中框选学生并对应到名册。", "确认画面中的学生", identity_href))

    # 6. Applicability ------------------------------------------------------------
    applicability_errors = [task for task in checked_tasks if applicability.get(str(task.get("task_id")), {}).get("error")]
    applicability_pending = [task for task in checked_tasks
                             if not applicability.get(str(task.get("task_id")), {}).get("error")
                             and applicability.get(str(task.get("task_id")), {}).get("category", "pending") == "pending"]
    applicability_target = _safe_id((applicability_errors or applicability_pending or checked_tasks or [{}])[0].get("task_id"))
    applicability_href = (_query("/demo2/analysis", task_id=applicability_target) if applicability_target
                          else "/demo2/upload")
    applicability_count = f"待确认适用性 {len(applicability_pending)} 个"
    if not checked_tasks:
        steps.append(_step("applicability", "确认视频适用性", "not_started", applicability_count,
                           "回看视频后确认内容类型与本课目标。", "等待视频分析", "/demo2/upload"))
    elif applicability_errors:
        steps.append(_step("applicability", "确认视频适用性", "attention", applicability_count,
                           f"{len(applicability_errors)} 个视频的学校归属或原视频需要核对。", "核对视频", applicability_href))
    elif not applicability_pending:
        steps.append(_step("applicability", "确认视频适用性", "done", applicability_count,
                           "已分析的视频都已确认内容类型。", "查看课堂复核", applicability_href))
    elif len(applicability_pending) < len(checked_tasks):
        steps.append(_step("applicability", "确认视频适用性", "in_progress", applicability_count,
                           "还有视频未确认适用性。", "继续确认适用性", applicability_href))
    else:
        steps.append(_step("applicability", "确认视频适用性", "not_started", applicability_count,
                           "确认后才能保存已复核或有分数的测量。", "确认视频适用性", applicability_href))

    # 7. Measurement / dual-track evaluation ----------------------------------------
    pending_measurements = [item for item in measurements
                            if item.get("reviewed") is not True or item.get("evidence_status") == "needs_reconfirmation"]
    evaluation_task = _safe_id((checked_tasks or [{}])[0].get("task_id"))
    secondary = {"label": "为本课评课",
                 "href": _query("/demo2/evaluation", task_id=evaluation_task) if evaluation_task else "/demo2/evaluation"}
    assessment_count = (f"测量 {len(measurements)} 条（待复核 {len(pending_measurements)}）"
                        f" · 评课 {len(evaluations)} 条")
    # Lessons with teacher-reviewed measurements but no checked course evaluation (basic_100).
    reviewed_course_eval_tasks = _reviewed_course_evaluation_tasks(evaluations)
    checked_ids = {str(task.get("task_id")) for task in checked_tasks}
    reviewed_measurement_tasks: dict[str, int] = {}
    for item in measurements:
        task_id = _safe_id(item.get("task_id"))
        if (task_id in checked_ids and item.get("reviewed") is True
                and item.get("evidence_status") != "needs_reconfirmation"):
            reviewed_measurement_tasks[task_id] = reviewed_measurement_tasks.get(task_id, 0) + 1
    course_eval_missing = ([task for task in checked_tasks
                            if str(task.get("task_id")) in reviewed_measurement_tasks
                            and str(task.get("task_id")) not in reviewed_course_eval_tasks]
                           if "evaluation" not in errors and "measurement" not in errors else [])
    if "measurement" in errors and "evaluation" in errors:
        steps.append(_step("assessment", "学生测量 / 评课", "attention", "暂时无法读取", "请刷新页面后重试。",
                           "打开学生测量", "/demo2/measurement", secondary=secondary))
    elif not measurements and not evaluations:
        steps.append(_step("assessment", "学生测量 / 评课", "not_started", assessment_count,
                           "按评分标准记录学生测量，或为本课做评课（系统建议分自动预填）。", "开始学生测量", "/demo2/measurement",
                           secondary=secondary))
    elif pending_measurements:
        steps.append(_step("assessment", "学生测量 / 评课", "in_progress", assessment_count,
                           "有测量记录待复核，复核后才计入趋势。", "复核测量记录", "/demo2/measurement",
                           secondary=secondary))
    elif course_eval_missing:
        missing_target = _safe_id(course_eval_missing[0].get("task_id"))
        steps.append(_step("assessment", "学生测量 / 评课", "in_progress", assessment_count,
                           f"测量记录均已复核；还有 {len(course_eval_missing)} 节课没有核对过的评课，"
                           "核对后课程总览才能给出结论。", "做评课",
                           _query("/demo2/evaluation", task_id=missing_target),
                           secondary={"label": "查看学生测量", "href": "/demo2/measurement"}))
    else:
        steps.append(_step("assessment", "学生测量 / 评课", "done", assessment_count,
                           "测量记录均已复核。", "查看学生测量", "/demo2/measurement", secondary=secondary))

    # 8. Report --------------------------------------------------------------------
    stale_reports = [report for report in latest_reports.values() if report.get("stale")]
    report_target = _safe_id((stale_reports[0].get("task_id") if stale_reports
                              else (checked_tasks or [{}])[0].get("task_id")))
    report_href = _query("/demo2/analysis", task_id=report_target) if report_target else "/demo2/upload"
    report_count = f"报告 {len(latest_reports)} 份 · 已过期 {len(stale_reports)} 份"
    if "report" in errors and not latest_reports:
        steps.append(_step("report", "查看并下载课堂报告", "attention", "暂时无法读取", "请刷新页面后重试。",
                           "打开课堂报告", report_href))
    elif not latest_reports:
        steps.append(_step("report", "查看并下载课堂报告", "not_started", report_count,
                           "打开课堂复核页的「图文报告」即可生成并下载。", "生成课堂报告", report_href))
    elif stale_reports:
        steps.append(_step("report", "查看并下载课堂报告", "attention", report_count,
                           "评分或资料变化后旧报告已过期，打开后会按最新数据重新生成。", "更新过期报告", report_href))
    else:
        steps.append(_step("report", "查看并下载课堂报告", "done", report_count,
                           "报告与当前评分一致，可下载 Word / PDF 文字报告。", "查看并下载报告", report_href))

    # To-do list -------------------------------------------------------------------
    todos: dict[str, list[dict[str, Any]]] = {"failed_tasks": [], "course_task_uploads": [], "iep_summaries": [],
                                              "lesson_measurement_reviews": [], "measurement_reviews": [],
                                              "stale_reports": [], "expiring_authorizations": [],
                                              "course_evaluations": [], "course_overviews": [], "few_students": []}
    for task in failed_tasks:
        task_id = _safe_id(task.get("task_id"))
        if not task_id:
            continue
        todos["failed_tasks"].append({
            "kind": "failed_task", "task_id": task_id,
            "text": f"「{task.get('course_name') or task.get('filename') or '未命名课程'}」视频分析失败，可在上传页重试或重新上传。",
            "action": {"label": "去处理",
                       "href": _query("/demo2/upload", course_id=_safe_id(task.get("course_id")), task_id=task_id)},
            "created_at": task.get("created_at") or "",
        })
    for task in missing_course_tasks:
        course_id = _safe_id(task.get("course_id"))
        todos["course_task_uploads"].append({
            "kind": "course_task_upload", "course_id": course_id,
            "text": f"上传课程任务文件：「{task.get('course_name') or '未命名课程'}」还没有确认的课程任务，"
                    f"{course_task_tip}，并用于评价、测量与报告。",
            "action": {"label": "上传课程任务文件", "href": _query("/demo2/upload", course_id=course_id)},
        })
    bound_students = section("iep_summaries", {},
                             lambda: _bound_students(records, account_id,
                                                     [str(task.get("task_id")) for task in checked_tasks]))
    if "dossier" not in errors:
        roster_set = set(roster_ids)
        needs_iep: list[str] = []
        for task in checked_tasks:
            for student_id in bound_students.get(str(task.get("task_id")), []):
                if student_id in roster_set and not iep_counts.get(student_id) and student_id not in needs_iep:
                    needs_iep.append(student_id)
        for student_id in needs_iep:
            name = student_names.get(student_id, "")
            todos["iep_summaries"].append({
                "kind": "iep_summary_missing", "student_id": student_id,
                "text": f"补充 IEP 支持摘要：{('学生「' + name + '」') if name else '一位学生'}已在课堂视频中确认，"
                        "但还没有有效的 IEP 支持摘要（必填）。",
                "action": {"label": "补充 IEP 支持摘要", "href": _query("/demo2/dossier", student_id=student_id)},
            })
    video_pending: dict[str, list[dict[str, Any]]] = {}
    field_pending: list[dict[str, Any]] = []
    for item in pending_measurements:
        task_id = _safe_id(item.get("task_id"))
        if task_id:
            video_pending.setdefault(task_id, []).append(item)
        else:
            field_pending.append(item)
    task_names = {str(task.get("task_id")): str(task.get("course_name") or task.get("filename") or "") for task in tasks}
    for task_id, items in video_pending.items():
        first = items[0]
        todos["lesson_measurement_reviews"].append({
            "kind": "lesson_measurement_review", "task_id": task_id, "count": len(items),
            "student_id": _safe_id(first.get("student_id")), "record_id": _safe_id(first.get("record_id")),
            "text": f"复核本课测量（{len(items)} 条）：「{task_names.get(task_id) or '课堂视频'}」由视频生成的测量记录"
                    "需要老师复核后才计入趋势和报告。",
            "action": {"label": "去复核",
                       "href": _query("/demo2/measurement", student_id=_safe_id(first.get("student_id")),
                                      task_id=task_id, record_id=_safe_id(first.get("record_id")))},
        })
    for item in field_pending:
        student_id = _safe_id(item.get("student_id"))
        task_id = _safe_id(item.get("task_id"))
        name = student_names.get(student_id, "")
        reason = "身份或适用性依据已失效，需重新确认" if item.get("evidence_status") == "needs_reconfirmation" else "尚未复核"
        todos["measurement_reviews"].append({
            "kind": "measurement_review", "student_id": student_id, "task_id": task_id,
            "record_id": _safe_id(item.get("record_id")),
            "text": f"{('学生「' + name + '」') if name else '一位学生'}{item.get('lesson_date') or ''} 的测量记录{reason}。",
            "action": {"label": "去复核", "href": _query("/demo2/measurement", student_id=student_id, task_id=task_id)},
        })
    for report in stale_reports:
        task_id = _safe_id(report.get("task_id"))
        todos["stale_reports"].append({
            "kind": "stale_report", "task_id": task_id, "report_id": _safe_id(report.get("report_id")),
            "text": f"「{task_names.get(task_id) or report.get('course_name') or '课堂'}」的课堂报告已过期，打开后会按最新数据重新生成。",
            "action": {"label": "更新报告", "href": _query("/demo2/analysis", task_id=task_id)},
        })
    for task in course_eval_missing:
        task_id = _safe_id(task.get("task_id"))
        todos["course_evaluations"].append({
            "kind": "course_evaluation_missing", "task_id": task_id,
            "count": reviewed_measurement_tasks.get(task_id, 0),
            "text": f"做评课：「{task_names.get(task_id) or '课堂视频'}」已有 {reviewed_measurement_tasks.get(task_id, 0)} 条"
                    "复核过的学生测量，但还没有核对过的评课（系统建议分会自动预填），核对后课程总览才能给出结论。",
            "action": {"label": "去做评课", "href": _query("/demo2/evaluation", task_id=task_id)},
        })
    fresh_reports = {task_id: report for task_id, report in latest_reports.items()
                     if not report.get("stale") and _safe_id(report.get("report_id"))}
    conclusions = section("course_overviews", {},
                          lambda: _report_conclusions(records, account_id,
                                                      [str(report.get("report_id")) for report in fresh_reports.values()]))
    for task in checked_tasks:
        task_id = _safe_id(task.get("task_id"))
        report = fresh_reports.get(task_id)
        conclusion = conclusions.get(str(report.get("report_id"))) if report else None
        if not conclusion:
            continue
        score = conclusion.get("score")
        score_text = f"，结论分 {score:g}" if isinstance(score, (int, float)) and not isinstance(score, bool) else ""
        grade_text = conclusion.get("grade_label") or "已生成"
        todos["course_overviews"].append({
            "kind": "course_overview_ready", "task_id": task_id, "grade": conclusion.get("grade_key") or "",
            "text": f"课程总览已出结论：「{task_names.get(task_id) or '课堂视频'}」试行等级 {grade_text}{score_text}，"
                    "可查看每个学生的评价和整体课程指标。",
            "action": {"label": "查看课程总览", "href": _query("/demo2/course-overview", task_id=task_id)},
        })
    student_counts: dict[str, int] = {}
    if checked_tasks:
        student_counts, count_error = _lesson_student_counts(
            records, token, [str(task.get("task_id")) for task in checked_tasks[:FEW_STUDENT_CHECK_LIMIT]])
        if count_error:
            errors.setdefault("few_students", count_error)
    for task in checked_tasks:
        task_id = _safe_id(task.get("task_id"))
        if task_id not in student_counts or student_counts[task_id] >= MIN_LESSON_STUDENTS:
            continue
        included = student_counts[task_id]
        todos["few_students"].append({
            "kind": "few_students_detected", "task_id": task_id, "student_count": included,
            "text": f"检测学生不足：「{task_names.get(task_id) or '课堂视频'}」本课只纳入 {included} 名学生"
                    f"（建议至少 {MIN_LESSON_STUDENTS} 名），可在「本课检测学生」中恢复被排除的人物或手动画框添加。",
            "action": {"label": "管理本课检测学生",
                       "href": _query("/demo2/simple-result", task_id=task_id) + "#detectionPanel"},
        })
    expiry_limit = today + timedelta(days=EXPIRY_WINDOW_DAYS)
    for student_id in roster_ids:
        valid_until = authorizations.get(student_id)
        try:
            until = date.fromisoformat(str(valid_until)[:10]) if valid_until else None
        except ValueError:
            until = None
        if until is None or until > expiry_limit:
            continue
        days_left = (until - today).days
        name = student_names.get(student_id, "")
        todos["expiring_authorizations"].append({
            "kind": "expiring_authorization", "student_id": student_id, "valid_until": until.isoformat(),
            "days_left": days_left,
            "text": f"{('学生「' + name + '」') if name else '一位学生'}的资料授权将于 {until.isoformat()} 到期（剩 {days_left} 天），到期后资料不可再用于评分。",
            "action": {"label": "去续期", "href": _query("/demo2/dossier", student_id=student_id)},
        })
    todos["expiring_authorizations"].sort(key=lambda item: item["valid_until"])
    todo_counts = {key: len(items) for key, items in todos.items()}
    todo_items = [item for items in todos.values() for item in items[:TODO_ITEM_LIMIT]]

    # Recent tasks -------------------------------------------------------------------
    recent = []
    for task in tasks[:RECENT_TASK_LIMIT]:
        task_id = _safe_id(task.get("task_id"))
        status = str(task.get("analysis_status") or "")
        ready = status in READY_STATUSES
        recent.append({
            "task_id": task_id, "course_id": _safe_id(task.get("course_id")),
            "course_name": task.get("course_name") or "", "filename": task.get("filename") or "",
            "created_at": task.get("created_at") or "", "analysis_status": status,
            "status_code": TASK_BADGE_CODES.get(status, status or "queued"),
            "action": ({"label": "进入结果", "href": _query("/demo2/simple-result", task_id=task_id)} if ready else
                       {"label": "查看进度", "href": _query("/demo2/upload", course_id=_safe_id(task.get("course_id")))}),
        })

    next_step = next((step for step in steps if step["status"] != "done"), None)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    summary = {
        "account": {"account_id": account_id, "username": account.get("username") or "",
                    "login_alias": account.get("login_alias") or ""},
        "school": {"school_name": school_name, "city": school.get("city") or "", "district": school.get("district") or ""},
        "today": today.isoformat(),
        "is_new_account": not school_name,
        "steps": steps,
        "next_step": ({"key": next_step["key"], "title": next_step["title"], "status": next_step["status"],
                       "detail": next_step["detail"], "action": next_step["action"]} if next_step else None),
        "todos": todo_items,
        "todo_counts": todo_counts,
        "todo_total": sum(todo_counts.values()),
        "recent_tasks": recent,
        "task_count": len(tasks),
        "errors": sorted(errors),
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    home_debug_event(records, "home_load", "partial" if errors else "ok", account_id=account_id,
                     role=account.get("role"), step_status={step["key"]: step["status"] for step in steps},
                     next_step=next_step["key"] if next_step else "all_done", todo_counts=todo_counts,
                     new_todo_counts={key: todo_counts[key] for key in NEW_TODO_KEYS},
                     v4_todo_counts={key: todo_counts[key] for key in V4_TODO_KEYS},
                     todo_total=summary["todo_total"], task_count=len(tasks), ready_task_count=len(ready_tasks),
                     errors=errors, elapsed_ms=elapsed_ms)
    return summary


# --------------------------------------------------------------------------
# Page
# --------------------------------------------------------------------------


def _account_json(account: Any) -> str:
    value: dict[str, Any] = {}
    if isinstance(account, dict):
        value = {key: account.get(key) for key in ("username", "login_alias", "role") if account.get(key)}
    return json.dumps(value, ensure_ascii=False).replace("<", "\\u003c")


def render_home(account: Any | None = None) -> str:
    header = teacher_header("home", account, logout_bound=False, page="home")
    return inject_kit(HOME_HTML.replace("__ACCOUNT_JSON__", _account_json(account)), header=header, page="home")


HOME_HTML = r'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>教师工作台首页</title><style>
*{box-sizing:border-box;letter-spacing:0}
body{margin:0;background:var(--rx-canvas,#f4f7fb);color:var(--rx-text,#26364a);font:14px/1.7 "Segoe UI","Microsoft YaHei","PingFang SC",sans-serif}
a{color:var(--rx-primary,#1f5fbf)}
.home-main{width:min(1180px,calc(100% - 32px));margin:0 auto;padding:24px 0 64px}
.home-welcome{display:flex;flex-wrap:wrap;align-items:flex-end;justify-content:space-between;gap:16px;padding:22px 24px;background:#fff;border:1px solid var(--rx-line);border-left:4px solid var(--rx-primary);border-radius:var(--rx-radius-lg);box-shadow:var(--rx-shadow-sm)}
.home-welcome .eyebrow{display:block;color:var(--rx-primary);font-size:12px;font-weight:700}
.home-welcome h1{margin:2px 0 4px;font-size:24px;line-height:1.3;color:var(--rx-ink)}
.home-welcome p{margin:0;color:var(--rx-muted)}
.home-facts{display:flex;flex-wrap:wrap;gap:8px}
.home-fact{display:flex;flex-direction:column;min-width:120px;padding:6px 12px;background:var(--rx-primary-pale);border-left:2px solid var(--rx-primary);line-height:1.35}
.home-fact span{color:var(--rx-muted);font-size:11px}.home-fact strong{color:var(--rx-ink);font-size:14px;overflow-wrap:anywhere}
.home-message{margin:16px 0 0;padding:12px 16px;border-left:3px solid var(--rx-danger);background:var(--rx-danger-soft);color:var(--rx-danger);font-weight:700}
.home-message[hidden]{display:none}
.home-next{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:12px;margin-top:16px;padding:14px 18px;background:var(--rx-primary-soft);border:1px solid #b9cff0;border-radius:var(--rx-radius-lg)}
.home-next strong{color:var(--rx-primary-hover);font-size:15px}.home-next p{margin:2px 0 0;color:var(--rx-text)}
.home-next[hidden]{display:none}
.home-section{margin-top:24px}
.home-section-head{display:flex;flex-wrap:wrap;align-items:flex-end;justify-content:space-between;gap:8px;margin-bottom:12px}
.home-section-head h2{margin:0;font-size:18px;color:var(--rx-ink)}
.home-section-head p{margin:0;color:var(--rx-muted);font-size:13px}
.loop-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:0;padding:0;list-style:none}
.loop-step{position:relative;display:flex;flex-direction:column;gap:6px;min-width:0;padding:16px;background:#fff;border:1px solid var(--rx-line);border-top:3px solid var(--rx-line-strong);border-radius:var(--rx-radius-lg);box-shadow:var(--rx-shadow-sm)}
.loop-step[data-status="done"]{border-top-color:var(--rx-success)}
.loop-step[data-status="in_progress"]{border-top-color:var(--rx-primary)}
.loop-step[data-status="attention"]{border-top-color:var(--rx-warning)}
.loop-step.is-next{border-color:var(--rx-primary);box-shadow:0 0 0 3px var(--rx-primary-soft),var(--rx-shadow)}
.loop-step-top{display:flex;align-items:center;justify-content:space-between;gap:8px}
.loop-no{display:inline-flex;align-items:center;justify-content:center;width:28px;height:28px;flex:none;border-radius:50%;background:var(--rx-neutral-soft);color:var(--rx-neutral);font-weight:800;font-size:13px}
.loop-step[data-status="done"] .loop-no{background:var(--rx-success-soft);color:var(--rx-success)}
.loop-step.is-next .loop-no{background:var(--rx-primary);color:#fff}
.loop-step h3{margin:2px 0 0;font-size:15px;color:var(--rx-ink)}
.loop-count{margin:0;color:var(--rx-ink);font-weight:700;font-size:13px;overflow-wrap:anywhere}
.loop-detail{margin:0;color:var(--rx-muted);font-size:12px;flex:1}
.loop-actions{display:flex;flex-wrap:wrap;gap:6px;margin-top:4px}
.loop-actions .rx-btn{min-height:36px;padding:0 12px;font-size:13px}
.next-flag{position:absolute;top:-11px;right:12px;padding:0 8px;border-radius:10px;background:var(--rx-primary);color:#fff;font-size:11px;font-weight:700;line-height:20px}
.home-columns{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(0,1fr);gap:20px;align-items:start}
.home-panel{background:#fff;border:1px solid var(--rx-line);border-radius:var(--rx-radius-lg);box-shadow:var(--rx-shadow-sm);padding:18px 20px}
.todo-list,.recent-list{margin:0;padding:0;list-style:none}
.todo-item,.recent-item{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 0;border-top:1px solid var(--rx-line)}
.todo-item:first-child,.recent-item:first-child{border-top:0;padding-top:0}
.todo-item p{margin:0;min-width:0;overflow-wrap:anywhere}
.todo-kind{display:inline-block;margin-right:6px}
.todo-item .rx-btn,.recent-item .rx-btn{min-height:36px;padding:0 12px;font-size:13px;flex:none}
.recent-main{min-width:0;display:flex;flex-direction:column}
.recent-main strong{color:var(--rx-ink);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.recent-main small{color:var(--rx-muted);font-size:12px}
.recent-side{display:flex;align-items:center;gap:10px;flex:none}
.home-foot{margin-top:24px;color:var(--rx-muted);font-size:12px}
@media(max-width:1000px){.loop-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.home-columns{grid-template-columns:minmax(0,1fr)}}
@media(max-width:560px){.loop-grid{grid-template-columns:minmax(0,1fr)}.home-welcome{padding:18px}.todo-item,.recent-item{flex-direction:column;align-items:flex-start}.recent-side{width:100%;justify-content:space-between}}
</style></head><body><header></header>
<main class="home-main" id="mainContent">
<section class="home-welcome" aria-labelledby="homeTitle"><div><span class="eyebrow">教师工作台 · 首页</span><h1 id="homeTitle">欢迎回来</h1><p id="homeLead">按下面的课堂分析闭环逐步完成，每一步都会根据本账号的真实数据更新状态。</p></div>
<div class="home-facts"><div class="home-fact"><span>学校</span><strong id="homeSchool">读取中</strong></div><div class="home-fact"><span>登录账号</span><strong id="homeAccount">读取中</strong></div><div class="home-fact"><span>今天</span><strong id="homeToday">—</strong></div></div></section>
<p class="home-message" id="homeMessage" role="alert" hidden></p>
<section class="home-next" id="homeNext" aria-live="polite" hidden><div><strong id="homeNextTitle"></strong><p id="homeNextDetail"></p></div><a class="rx-btn rx-btn-primary" id="homeNextAction" href="/demo2/upload">去完成</a></section>
<section class="home-section" aria-labelledby="loopTitle"><div class="home-section-head"><h2 id="loopTitle">课堂分析闭环</h2><p id="loopProgress">正在读取进度…</p></div>
<ol class="loop-grid" id="loopSteps"><li class="loop-step"><div class="rx-skeleton" aria-hidden="true"><span class="rx-skeleton-line"></span><span class="rx-skeleton-line"></span><span class="rx-skeleton-line"></span></div><span class="rx-sr" role="status">正在加载</span></li></ol></section>
<div class="home-columns">
<section class="home-section home-panel" aria-labelledby="todoTitle"><div class="home-section-head"><h2 id="todoTitle">待办事项</h2><p id="todoSummary"></p></div><ul class="todo-list" id="todoList"></ul></section>
<section class="home-section home-panel" aria-labelledby="recentTitle"><div class="home-section-head"><h2 id="recentTitle">最近任务</h2><a href="/demo2/upload">全部任务</a></div><ul class="recent-list" id="recentList"></ul></section>
</div>
<p class="home-foot">首页只显示当前登录账号与本校范围内的数据；状态与评分仍需教师复核，不代表教育准确性结论。</p>
</main>
<script>
'use strict';
const HOME_ACCOUNT=__ACCOUNT_JSON__;
const byId=id=>document.getElementById(id);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const safeHref=v=>typeof v==='string'&&v.startsWith('/demo2/')&&!v.startsWith('//')?v:'/demo2/upload';
const STATUS_BADGE={not_started:['未开始','neutral'],in_progress:['进行中','info'],done:['已完成','success'],attention:['需处理','warning']};
const TODO_LABEL={failed_task:['失败任务','danger'],course_task_upload:['课程任务','info'],iep_summary_missing:['IEP 摘要','warning'],lesson_measurement_review:['本课测量','warning'],measurement_review:['待复核测量','warning'],stale_report:['报告已过期','muted'],expiring_authorization:['授权即将到期','warning'],course_evaluation_missing:['评课','warning'],course_overview_ready:['课程总览','success'],few_students_detected:['检测学生不足','warning']};
const badge=(label,tone)=>'<span class="rx-badge rx-badge-'+esc(tone)+'">'+esc(label)+'</span>';
const pad=n=>String(n).padStart(2,'0');
const todayText=()=>{const d=new Date();return d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate());};
const relTime=v=>window.RxUI?RxUI.relativeTime(v):String(v||'');
const taskBadge=code=>window.RxUI?RxUI.statusBadge(code):badge(code,'neutral');
function showMessage(text){const node=byId('homeMessage');node.textContent=text;node.hidden=!text;}
function renderSteps(data){
  const steps=Array.isArray(data.steps)?data.steps:[];const nextKey=data.next_step?data.next_step.key:'';
  byId('loopSteps').innerHTML=steps.map((s,i)=>{const b=STATUS_BADGE[s.status]||STATUS_BADGE.attention;const isNext=s.key===nextKey;
    const second=s.secondary_action?'<a class="rx-btn rx-btn-secondary" href="'+esc(safeHref(s.secondary_action.href))+'">'+esc(s.secondary_action.label)+'</a>':'';
    return '<li class="loop-step'+(isNext?' is-next':'')+'" data-step="'+esc(s.key)+'" data-status="'+esc(s.status)+'" id="homeStep_'+esc(s.key)+'"'+(isNext?' aria-current="step"':'')+'>'
      +(isNext?'<span class="next-flag">下一步</span>':'')
      +'<div class="loop-step-top"><span class="loop-no">'+(i+1)+'</span>'+badge(b[0],b[1])+'</div>'
      +'<h3>'+esc(s.title)+'</h3><p class="loop-count">'+esc(s.count)+'</p><p class="loop-detail">'+esc(s.detail)+'</p>'
      +'<div class="loop-actions"><a class="rx-btn '+(isNext?'rx-btn-primary':'rx-btn-secondary')+'" href="'+esc(safeHref(s.action&&s.action.href))+'">'+esc(s.action&&s.action.label||'进入')+'</a>'+second+'</div></li>';}).join('');
  const done=steps.filter(s=>s.status==='done').length;
  byId('loopProgress').textContent='已完成 '+done+' / '+steps.length+' 步';
}
function renderNext(data){
  const next=data.next_step;const box=byId('homeNext');
  if(!next){box.hidden=false;byId('homeNextTitle').textContent='闭环已全部完成';byId('homeNextDetail').textContent='可以继续上传新的课堂视频，开始下一节课的分析。';byId('homeNextAction').textContent='上传新课堂';byId('homeNextAction').href='/demo2/upload';return;}
  box.hidden=false;
  byId('homeNextTitle').textContent=(data.is_new_account?'第一步：':'下一步：')+next.title;
  byId('homeNextDetail').textContent=data.is_new_account?'新账号请先填写学校信息，名册、资料和上传都会归属到这所学校。':next.detail;
  byId('homeNextAction').textContent=next.action&&next.action.label||'去完成';byId('homeNextAction').href=safeHref(next.action&&next.action.href);
}
function renderTodos(data){
  const items=Array.isArray(data.todos)?data.todos:[];const total=Number(data.todo_total)||0;
  byId('todoSummary').textContent=total?'共 '+total+' 项'+(total>items.length?'，显示前 '+items.length+' 项':''):'';
  if(!items.length){byId('todoList').innerHTML='<li><div class="rx-empty" id="todoEmpty"><p>目前没有需要处理的事项</p></div></li>';return;}
  byId('todoList').innerHTML=items.map(t=>{const k=TODO_LABEL[t.kind]||['待办','neutral'];
    return '<li class="todo-item" data-kind="'+esc(t.kind)+'"'+(t.task_id?' data-task="'+esc(t.task_id)+'"':'')+(t.student_id?' data-student="'+esc(t.student_id)+'"':'')+'><p><span class="todo-kind">'+badge(k[0],k[1])+'</span>'+esc(t.text)+'</p><a class="rx-btn rx-btn-secondary" href="'+esc(safeHref(t.action&&t.action.href))+'">'+esc(t.action&&t.action.label||'去处理')+'</a></li>';}).join('');
}
function renderRecent(data){
  const items=Array.isArray(data.recent_tasks)?data.recent_tasks:[];
  if(!items.length){byId('recentList').innerHTML='<li><div class="rx-empty"><p>还没有上传过课堂视频</p><a class="rx-btn rx-btn-primary" href="/demo2/upload">上传课堂视频</a></div></li>';return;}
  byId('recentList').innerHTML=items.map(t=>'<li class="recent-item" data-task="'+esc(t.task_id)+'"><div class="recent-main"><strong title="'+esc(t.course_name||t.filename)+'">'+esc(t.course_name||t.filename||'未命名课程')+'</strong><small>'+esc(t.filename||'')+' · <span title="'+esc(t.created_at)+'">'+esc(relTime(t.created_at))+'上传</span></small></div><div class="recent-side">'+taskBadge(t.status_code)+'<a class="rx-btn rx-btn-secondary" href="'+esc(safeHref(t.action&&t.action.href))+'">'+esc(t.action&&t.action.label||'查看')+'</a></div></li>').join('');
}
function render(data){
  byId('homeSchool').textContent=data.school&&data.school.school_name||'尚未填写学校';
  byId('homeAccount').textContent=(data.account&&(data.account.login_alias||data.account.username))||HOME_ACCOUNT.login_alias||HOME_ACCOUNT.username||'—';
  byId('homeToday').textContent=data.today||todayText();
  byId('homeTitle').textContent=data.is_new_account?'欢迎使用 WeGlow微光系统':'欢迎回来'+(data.school&&data.school.school_name?'，'+data.school.school_name:'');
  renderSteps(data);renderNext(data);renderTodos(data);renderRecent(data);
  showMessage(Array.isArray(data.errors)&&data.errors.length?'部分数据暂时无法读取，相关步骤标为「需处理」，请稍后刷新页面。':'');
}
async function load(){
  byId('homeToday').textContent=todayText();
  byId('homeAccount').textContent=HOME_ACCOUNT.login_alias||HOME_ACCOUNT.username||'读取中';
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),20000);
  try{
    const response=await fetch('/api/v1/demo2/home/summary',{credentials:'same-origin',cache:'no-store',signal:controller.signal,headers:{Accept:'application/json'}});
    if(response.status===401){location.assign('/demo2/login');return;}
    const data=await response.json().catch(()=>null);
    if(!response.ok||!data||!data.home){throw new Error(data&&data.error&&data.error.message||'首页数据读取失败，请刷新页面重试。');}
    render(data.home);
  }catch(error){
    showMessage(error.name==='AbortError'?'读取超时，请刷新页面重试。':error instanceof TypeError?'网络连接失败，请检查网络后刷新页面。':error.message);
    byId('loopProgress').textContent='进度暂未读取';byId('loopSteps').innerHTML='';
  }finally{clearTimeout(timer);}
}
load();
</script></body></html>'''


# Upload-page hint: one line pointing at the next loop step computed above.
# The script carries a data attribute so the Node harnesses that eval bare
# ``<script>`` blocks of the upload page do not run (or stub) this request.
UPLOAD_NEXT_STEP_BANNER = r'''<div class="rx-next-step" id="nextStepBanner" role="status" hidden><span class="rx-next-step-copy"><strong id="nextStepTitle">下一步</strong><span id="nextStepDetail"></span></span><a class="rx-btn rx-btn-primary" id="nextStepAction" href="/demo2/home">去完成</a><a class="rx-btn rx-btn-text" href="/demo2/home">查看首页</a><button class="rx-btn rx-btn-text" id="nextStepClose" type="button" aria-label="关闭下一步提示">关闭</button></div>
<style data-rx-next-step>.rx-next-step{display:flex;flex-wrap:wrap;align-items:center;gap:8px 12px;margin:0 0 14px;padding:10px 14px;border:1px solid #b9cff0;border-left:3px solid var(--rx-primary,#1f5fbf);border-radius:6px;background:var(--rx-primary-soft,#eaf2fd)}.rx-next-step[hidden]{display:none}.rx-next-step-copy{flex:1 1 260px;min-width:0;display:flex;flex-wrap:wrap;gap:4px 10px;align-items:baseline}.rx-next-step-copy strong{color:var(--rx-primary-hover,#174a96)}.rx-next-step-copy span{color:var(--rx-text,#26364a);font-size:13px}.rx-next-step .rx-btn{min-height:36px;font-size:13px}</style>
<script data-rx-next-step>
(function(){
  'use strict';
  var KEY='rx_next_step_dismissed';
  var banner=document.getElementById('nextStepBanner'); if(!banner) return;
  var dismissed=false; try{ dismissed=sessionStorage.getItem(KEY)==='1'; }catch(e){}
  if(dismissed) return;
  document.getElementById('nextStepClose').addEventListener('click',function(){
    banner.hidden=true; try{ sessionStorage.setItem(KEY,'1'); }catch(e){}
  });
  fetch('/api/v1/demo2/home/summary',{credentials:'same-origin',cache:'no-store',headers:{Accept:'application/json'}})
    .then(function(r){ return r.ok?r.json():null; })
    .then(function(data){
      var next=data&&data.home&&data.home.next_step; if(!next) return;
      var href=next.action&&typeof next.action.href==='string'&&next.action.href.indexOf('/demo2/')===0?next.action.href:'/demo2/home';
      document.getElementById('nextStepTitle').textContent='下一步：'+next.title;
      document.getElementById('nextStepDetail').textContent=next.detail||'';
      var action=document.getElementById('nextStepAction'); action.textContent=(next.action&&next.action.label)||'去完成'; action.href=href;
      banner.hidden=false;
    })
    .catch(function(){ try{ console.warn('[rx-next-step] summary unavailable'); }catch(e){} });
})();
</script>'''
