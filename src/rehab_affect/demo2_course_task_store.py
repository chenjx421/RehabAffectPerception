"""Course-task documents (教案/课程任务 Word/PDF): confirmed goals, versions and links.

A teacher uploads the lesson's task document through the document-parse
service (purpose=course_task), reviews the recognised goals in a confirmation
drawer and saves them here. Every confirmation of the same course creates a new
immutable version; earlier versions stay readable because evaluations and
report snapshots cite ``course_task_doc_id`` + ``version``.

The original file is re-sealed with the document vault; goals are plain JSON
(validated: no roster names, no ID/phone/address numbers). The debug log never
contains goal text, file names or notes.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import secrets
import threading
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from .classroom_rubric import TEMPLATES
from .demo2_document_parser import sensitive_types
from .demo2_upload_debug import log_dir_for_store

DEBUG_LOG_DIR_ENV = "REHAB_DEMO2_COURSE_TASK_DEBUG_LOG_DIR"
DEBUG_LOGGER = logging.getLogger("rehab_affect.course_task_flow")
OPERATIONS = frozenset({
    "course_task_upload", "course_task_confirm", "course_task_version", "course_task_link_evaluation",
    "course_task_link_report", "course_task_read", "course_task_download", "course_task_rejected",
})
DOC_ID_PATTERN = re.compile(r"ctd-[0-9a-f]{32}")
GOAL_CODE_PATTERN = re.compile(r"G-\d{2,3}")
MAX_GOALS = 50
MAX_NOTES = 300
DIMENSIONS = {
    "goals": "目标适配与分层要求",
    "content": "内容设计与教学组织",
    "process": "过程支持与目标达成",
    "teacher": "教师表达与响应调节",
    "outcomes": "学习效果",
}
DEFAULT_DIMENSION = "process"
_DIMENSION_HINTS = (
    ("goals", ("分层", "差异", "个别化", "起点", "不同层次")),
    ("teacher", ("教师示范", "教师语言", "指令清晰", "板书", "演示")),
    ("content", ("教学内容", "知识点", "教学环节", "组织", "重点", "难点")),
    ("outcomes", ("习惯", "情意", "兴趣")),
)
_BLOCKED_SENSITIVE = {"id_card": "身份证号", "phone": "联系电话", "address": "详细住址"}
_LOCK = threading.Lock()
_TOKEN_FIELDS = ("operation_source", "account_id", "course_id", "course_task_doc_short", "previous_doc_short",
                 "parse_short", "task_id", "evaluation_id", "report_short", "code", "status", "role", "fmt")
_INT_FIELDS = ("version", "previous_version", "goal_count", "note_count", "other_count", "http_status",
               "byte_size", "linked_goal_count")


class CourseTaskError(Exception):
    def __init__(self, status: int, code: str, message: str, field: str | None = None):
        super().__init__(message)
        self.status, self.code, self.message, self.field = status, code, message, field


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def short_doc_id(doc_id: Any) -> str:
    text = str(doc_id or "")
    return text[4:12] if DOC_ID_PATTERN.fullmatch(text) else ""


def course_task_log_dir(store: Any) -> Path:
    configured = os.getenv(DEBUG_LOG_DIR_ENV, "").strip()
    if configured:
        return Path(configured)
    return log_dir_for_store(store)


def _token(value: Any) -> str:
    text = str(value)
    return text if re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", text) else "<invalid>"


def course_task_debug_event(store: Any, operation: str, result: str, **fields: Any) -> dict[str, Any]:
    """One JSON line in ``course_task_debug_YYYYMMDD.jsonl``; never blocks a request."""
    entry: dict[str, Any] = {
        "ts": datetime.now().astimezone().isoformat(timespec="milliseconds"),
        "operation": operation if operation in OPERATIONS else "<invalid>",
        "result": _token(result),
    }
    doc_id = fields.pop("course_task_doc_id", None)
    if doc_id:
        fields["course_task_doc_short"] = short_doc_id(doc_id) or "<invalid>"
    previous = fields.pop("previous_doc_id", None)
    if previous:
        fields["previous_doc_short"] = short_doc_id(previous) or "<invalid>"
    parse_id = fields.pop("parse_id", None)
    if parse_id:
        fields["parse_short"] = str(parse_id)[3:11] if str(parse_id).startswith("dp-") else "<invalid>"
    report_id = fields.pop("report_id", None)
    if report_id:
        fields["report_short"] = str(report_id)[:8]
    for key, value in fields.items():
        if value is None or value == "":
            continue
        if key in _TOKEN_FIELDS:
            entry[key] = _token(value)
        elif key in _INT_FIELDS:
            entry[key] = value if isinstance(value, int) and not isinstance(value, bool) else "<invalid>"
        elif key == "goal_codes" and isinstance(value, (list, tuple)):
            entry[key] = [code for code in value if isinstance(code, str) and GOAL_CODE_PATTERN.fullmatch(code)][:MAX_GOALS]
    line = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
    DEBUG_LOGGER.debug(line)
    try:
        folder = course_task_log_dir(store)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"course_task_debug_{entry['ts'][:10].replace('-', '')}.jsonl"
        with _LOCK, path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except (OSError, TypeError, ValueError):
        DEBUG_LOGGER.warning("course task debug log write failed")
    return entry


# ---------------------------------------------------------------------------
# schema and read helpers usable from other stores (no vault needed)
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS demo2_course_task_documents (
    course_task_doc_id TEXT PRIMARY KEY,
    school_id TEXT NOT NULL DEFAULT '',
    scope_key TEXT NOT NULL DEFAULT '',
    course_id TEXT NOT NULL,
    owner_account_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    status TEXT NOT NULL,
    original_path TEXT NOT NULL,
    original_extension TEXT NOT NULL,
    original_sha256 TEXT NOT NULL,
    byte_size INTEGER NOT NULL,
    parse_id TEXT NOT NULL,
    course_name TEXT NOT NULL DEFAULT '',
    lesson_date TEXT NOT NULL DEFAULT '',
    goal_count INTEGER NOT NULL,
    goals_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    confirmed_at TEXT,
    superseded_at TEXT,
    confirmed_by TEXT NOT NULL DEFAULT '',
    UNIQUE(owner_account_id, course_id, version)
);
CREATE INDEX IF NOT EXISTS idx_demo2_course_task_course
    ON demo2_course_task_documents(owner_account_id, course_id, status);
"""


def ensure_schema(connection) -> None:
    connection.executescript(SCHEMA)


def _table_exists(connection) -> bool:
    return connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                              "AND name='demo2_course_task_documents'").fetchone() is not None


def public_document(row: Any, *, admin: bool = False) -> dict[str, Any]:
    row = dict(row)
    content = json.loads(row.get("goals_json") or "{}")
    goals = content.get("goals") if isinstance(content.get("goals"), list) else []
    result = {
        "course_task_doc_id": row["course_task_doc_id"],
        "course_task_doc_short": short_doc_id(row["course_task_doc_id"]),
        "school_id": row.get("school_id") or "",
        "course_id": row["course_id"],
        "owner_account_id": row["owner_account_id"],
        "version": int(row["version"]),
        "status": row["status"],
        "status_label": {"confirmed": "已确认", "superseded": "已被新版本替代"}.get(row["status"], row["status"]),
        "course_name": row.get("course_name") or "",
        "lesson_date": row.get("lesson_date") or "",
        "goal_count": int(row.get("goal_count") or 0),
        "goals": goals,
        "original_extension": row.get("original_extension") or "",
        "byte_size": int(row.get("byte_size") or 0),
        "original_sha256": row.get("original_sha256") or "",
        "created_at": row.get("created_at") or "",
        "confirmed_at": row.get("confirmed_at") or "",
        "superseded_at": row.get("superseded_at") or "",
        "parse_status": content.get("parse_status") or "",
        "page_count": content.get("page_count") or 0,
    }
    if admin:
        # Company admins audit the original and the goal summary only; teacher
        # notes from the document body stay teacher-side.
        result.pop("owner_account_id", None)
        result["notes"] = []
        result["note_count"] = len(content.get("notes") or [])
    else:
        result["notes"] = content.get("notes") if isinstance(content.get("notes"), list) else []
        result["note_count"] = len(result["notes"])
    return result


def current_for_course(connection, owner_account_id: str, course_id: str) -> dict[str, Any] | None:
    """Latest confirmed version of one course for one owner, or None."""
    if not course_id or not _table_exists(connection):
        return None
    row = connection.execute(
        "SELECT * FROM demo2_course_task_documents WHERE owner_account_id=? AND course_id=? AND status='confirmed' "
        "ORDER BY version DESC LIMIT 1", (owner_account_id, course_id)).fetchone()
    return public_document(row) if row else None


def document_by_id(connection, doc_id: str) -> dict[str, Any] | None:
    if not isinstance(doc_id, str) or not DOC_ID_PATTERN.fullmatch(doc_id) or not _table_exists(connection):
        return None
    row = connection.execute("SELECT * FROM demo2_course_task_documents WHERE course_task_doc_id=?",
                             (doc_id,)).fetchone()
    return dict(row) if row else None


def course_task_stale_reasons(connection, owner_account_id: str, course_id: str, reference: Any) -> list[str]:
    """Report snapshots expire once their course-task version is replaced."""
    if not _table_exists(connection):
        return []
    current = current_for_course(connection, owner_account_id, course_id)
    cited = reference if isinstance(reference, dict) else {}
    cited_id = str(cited.get("course_task_doc_id") or "")
    if not cited_id:
        return [f"course_task_added:{current['course_task_doc_id']}"] if current else []
    if current is None:
        return [f"course_task_changed:{cited_id}"]
    if current["course_task_doc_id"] != cited_id or current["version"] != cited.get("version"):
        return [f"course_task_changed:{cited_id}"]
    return []


def dimension_items(template_id: str, dimension: str) -> list[dict[str, Any]]:
    template = TEMPLATES.get(template_id)
    if not template:
        return []
    items = [item for item in template["items"] if item["category_id"] == dimension]
    if not items:
        items = [item for item in template["items"] if item["category_id"] == DEFAULT_DIMENSION]
    return items


def evaluation_goal_basis(goals: list[dict[str, Any]], template_id: str, rows: list[dict[str, Any]],
                          enhanced_available: bool) -> list[dict[str, Any]]:
    """Per-goal system-track basis from the scored rubric items; scores are not recomputed."""
    by_id = {row.get("id"): row for row in rows if isinstance(row, dict)}
    basis: list[dict[str, Any]] = []
    for goal in goals:
        dimension = goal.get("rubric_dimension") or DEFAULT_DIMENSION
        items = dimension_items(template_id, dimension)
        entries, parts = [], []
        for item in items:
            row = by_id.get(item["id"], {})
            school = row.get("school_score")
            enhanced = row.get("enhanced_score") if enhanced_available else None
            evidence = str(row.get("evidence") or "").strip()
            entries.append({"id": item["id"], "label": item["label"], "school_score": school,
                            "enhanced_score": enhanced, "has_evidence": bool(evidence)})
            score = enhanced if enhanced is not None else school
            score_text = "未评分" if score is None else f"{score:g}分"
            track = "增强分" if enhanced is not None else "学校分"
            part = f"第{item['id'][1:]}项「{item['label'][:16]}」{track}{score_text}"
            if evidence:
                part += f"（证据：{evidence[:40]}{'…' if len(evidence) > 40 else ''}）"
            parts.append(part)
        scored = [e for e in entries if (e["enhanced_score"] if enhanced_available else e["school_score"]) is not None]
        text = (f"{goal.get('goal_code')} 对应「{DIMENSIONS.get(dimension, dimension)}」：" + "；".join(parts) + "。"
                if parts else f"{goal.get('goal_code')} 在当前模板中没有对应评分条目。")
        if not enhanced_available and parts:
            text += "该模板没有增强轨，按学校评分列出依据。"
        if goal.get("pass_criteria"):
            text += f"通过标准：{str(goal['pass_criteria'])[:80]}。"
        basis.append({"goal_code": goal.get("goal_code"), "rubric_dimension": dimension,
                      "dimension_label": DIMENSIONS.get(dimension, dimension),
                      "item_ids": [e["id"] for e in entries], "items": entries,
                      "scored_item_count": len(scored), "has_evidence": any(e["has_evidence"] for e in entries),
                      "basis_text": text})
    return basis


def _normalized_goal_key(value: Any) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip().upper()


def build_course_task_section(course_task: dict[str, Any], records: list[dict[str, Any]],
                              evaluations: list[dict[str, Any]] = ()) -> dict[str, Any]:
    """Goal-by-goal achievement from the task's teacher records (by goal code)."""
    goals_out, lines = [], []
    linked_evaluations = [e for e in evaluations
                          if e.get("course_task_doc_id") == course_task["course_task_doc_id"]]
    basis_by_code: dict[str, str] = {}
    for evaluation in linked_evaluations:
        for item in evaluation.get("course_task_goal_basis") or []:
            if isinstance(item, dict) and item.get("goal_code") and item.get("basis_text"):
                basis_by_code.setdefault(item["goal_code"], item["basis_text"])
    for goal in course_task.get("goals", []):
        code = goal.get("goal_code", "")
        related = [r for r in records if _normalized_goal_key(r.get("goal_id")) == _normalized_goal_key(code)]
        current = [r for r in related if r.get("evidence_status", "current") == "current"]
        reviewed = [r for r in current if r.get("reviewed")]
        passed = [r for r in reviewed if (r.get("assessment") or {}).get("passed") is True]
        not_passed = [r for r in reviewed if (r.get("assessment") or {}).get("passed") is False]
        segments = [{"record_id": r.get("record_id"), "student_id": r.get("student_id"),
                     "start_sec": r.get("start_sec"), "end_sec": r.get("end_sec"), "reviewed": bool(r.get("reviewed"))}
                    for r in related if r.get("start_sec") is not None and r.get("end_sec") is not None]
        if not related:
            status, label = "no_evidence", "暂无关联记录"
        elif not reviewed:
            status, label = "pending", "待教师复核"
        elif passed and not not_passed:
            status, label = "achieved", "已达成（按已复核记录）"
        elif passed:
            status, label = "partial", "部分达成"
        else:
            status, label = "not_yet", "尚未达成或证据不足"
        goals_out.append({**{k: goal.get(k, "") for k in ("goal_code", "description", "pass_criteria",
                                                          "measurement_conditions", "rubric_dimension")},
                          "dimension_label": DIMENSIONS.get(goal.get("rubric_dimension"), ""),
                          "record_count": len(related), "reviewed_count": len(reviewed),
                          "passed_count": len(passed), "segments": segments,
                          "achievement_status": status, "achievement_label": label,
                          "evaluation_basis": basis_by_code.get(code, "")})
        text = f"{code}「{str(goal.get('description', ''))[:60]}」：{label}"
        text += f"，关联观察 {len(related)} 条、已复核 {len(reviewed)} 条、达到通过标准 {len(passed)} 条"
        if goal.get("pass_criteria"):
            text += f"；通过标准为“{str(goal['pass_criteria'])[:60]}”"
        if segments:
            spans = "、".join(f"{s['start_sec']:g}–{s['end_sec']:g}秒" for s in segments[:4])
            text += f"；相关片段 {spans}"
        if basis_by_code.get(code):
            text += f"；课堂评价依据：{basis_by_code[code][:120]}"
        lines.append(text + "。")
    intro = (f"本课课程任务文档 {course_task['course_task_doc_id']}（版本 {course_task['version']}）"
             f"共确认 {len(goals_out)} 个目标。达成情况只按教师在本视频中按目标编号保存的复核记录统计，"
             "未记录的目标保持空缺，不按未达成处理，也不代表全班覆盖。")
    text = intro + "".join(lines)
    return {"section": {"title": "本课任务目标与达成情况", "text": text, "source": "course_task"},
            "reference": {"course_task_doc_id": course_task["course_task_doc_id"], "version": course_task["version"],
                          "course_id": course_task["course_id"], "goal_count": len(goals_out),
                          "linked_evaluation_ids": [e.get("evaluation_id", "") for e in linked_evaluations],
                          "goals": goals_out}}


def attach_to_workspace(records_store: Any, account: dict[str, Any], workspace: dict[str, Any],
                        evaluations: Any = ()) -> None:
    """Add the confirmed course task, per-goal segment tags and the report chapter."""
    course_id = str(workspace.get("course_id") or "")
    with records_store._connect() as connection:
        current = current_for_course(connection, account["account_id"], course_id)
    if current is None:
        workspace["course_task"] = None
        return
    built = build_course_task_section(current, workspace.get("records") or [], list(evaluations or []))
    workspace["course_task"] = {**{k: current[k] for k in ("course_task_doc_id", "course_task_doc_short", "version",
                                                         "course_name", "lesson_date", "goal_count", "confirmed_at")},
                                "goals": built["reference"]["goals"]}
    report = workspace.get("report")
    if isinstance(report, dict) and isinstance(report.get("sections"), list):
        sections = [s for s in report["sections"] if s.get("source") != "course_task"]
        sections.append(built["section"])
        report["sections"] = sections
        report["course_task"] = built["reference"]
        report["character_count"] = sum(len(s.get("text", "")) for s in sections)
        if "full_text" in report:
            report["full_text"] = "\n\n".join(s["title"] + "\n" + s["text"] for s in sections)


# ---------------------------------------------------------------------------
# draft building from a parse result
# ---------------------------------------------------------------------------

def _iso_date(value: str) -> str:
    match = re.search(r"(\d{4})\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})", unicodedata.normalize("NFKC", value or ""))
    if not match:
        return ""
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3))).isoformat()
    except ValueError:
        return ""


def suggest_dimension(*texts: str) -> str:
    joined = "".join(texts)
    for dimension, words in _DIMENSION_HINTS:
        if any(word in joined for word in words):
            return dimension
    return DEFAULT_DIMENSION


def build_draft(parse: dict[str, Any]) -> dict[str, Any]:
    candidates = parse.get("candidates") or []
    by_id = {c["candidate_id"]: c for c in candidates}

    def first(field: str) -> str:
        return next((c["value"] for c in candidates if c["field"] == field), "")

    used: set[str] = set()
    ungrouped = {field: [c for c in candidates if c["field"] == field and not any(
        g.get("goal_candidate_id") != c["candidate_id"] and c["candidate_id"] in g.get("detail_candidate_ids", [])
        for g in parse.get("goals") or [])] for field in ("pass_criteria", "measurement_conditions", "evaluation_criteria")}
    goals: list[dict[str, Any]] = []
    for index, summary in enumerate([g for g in parse.get("goals") or [] if g.get("field") == "course_goals"], start=1):
        goal = by_id.get(summary.get("goal_candidate_id"))
        if goal is None:
            continue
        used.add(goal["candidate_id"])
        details: dict[str, list[str]] = {"pass_criteria": [], "measurement_conditions": [], "evaluation_criteria": []}
        for candidate_id in summary.get("detail_candidate_ids") or []:
            detail = by_id.get(candidate_id)
            if detail is None:
                continue
            if detail["field"] in details:
                details[detail["field"]].append(detail["value"])
                used.add(candidate_id)
            elif detail["field"] == "course_goals":
                used.add(candidate_id)
        goals.append({
            "goal_code": f"G-{index:02d}",
            "description": goal["value"],
            "pass_criteria": "；".join(dict.fromkeys(details["pass_criteria"])),
            "measurement_conditions": "；".join(dict.fromkeys(details["measurement_conditions"])),
            "evaluation_criteria": "；".join(dict.fromkeys(details["evaluation_criteria"])),
            "rubric_dimension": suggest_dimension(goal["value"], *details["evaluation_criteria"]),
            "source": {k: goal["source"].get(k) for k in ("page", "paragraph_index", "kind", "cell_id")},
            "confidence": goal.get("confidence"),
        })
    # Document-level conditions/criteria without a goal group apply to every goal lacking its own.
    for field in ("measurement_conditions", "pass_criteria"):
        shared = [c for c in ungrouped[field] if c["candidate_id"] not in used and not c.get("group")]
        if shared:
            text = "；".join(dict.fromkeys(c["value"] for c in shared))
            applied = False
            for goal in goals:
                if not goal[field]:
                    goal[field] = text
                    applied = True
            if applied or not goals:
                used.update(c["candidate_id"] for c in shared)
    for field in ("course_name", "lesson_date"):
        for c in candidates:
            if c["field"] == field:
                used.add(c["candidate_id"])
                break
    for c in candidates:
        if c["field"] == "course_goals" and c.get("same_goal_as"):
            used.add(c["candidate_id"])
    other: list[dict[str, Any]] = []
    for c in candidates:
        if c["candidate_id"] in used:
            continue
        other.append({"other_id": f"f-{c['candidate_id']}", "kind": "field", "label": c["label"],
                      "text": f"{c['label']}：{c['value']}", "page": c["source"].get("page"),
                      "sensitive": bool(c.get("sensitive")), "sensitive_labels": c.get("sensitive_labels") or []})
    for index, block in enumerate(parse.get("other_content") or [], start=1):
        other.append({"other_id": f"b-{index:04d}", "kind": "table_cell" if block.get("cell_id") else "paragraph",
                      "label": "", "text": block.get("text", ""), "page": block.get("page"),
                      "sensitive": bool(block.get("sensitive")),
                      "sensitive_labels": [{"id_card": "身份证号", "phone": "联系电话", "address": "详细住址",
                                            "diagnosis": "诊断/病历信息"}.get(k, "个人信息")
                                           for k in block.get("sensitive_types") or []]})
    return {
        "parse_id": parse["parse_id"],
        "parse_status": parse.get("status", ""),
        "notice": parse.get("notice", ""),
        "manual_entry_required": bool(parse.get("manual_entry_required")),
        "page_count": parse.get("page_count", 0),
        "expires_at": parse.get("expires_at", ""),
        "course_name": first("course_name"),
        "lesson_date": _iso_date(first("lesson_date")),
        "lesson_date_text": first("lesson_date"),
        "goals": goals,
        "other_content": other,
        "dimensions": [{"id": k, "label": v} for k, v in DIMENSIONS.items()],
        "coverage": parse.get("coverage", {}),
    }


# ---------------------------------------------------------------------------
# store
# ---------------------------------------------------------------------------

class Demo2CourseTaskStore:
    def __init__(self, records: Any, documents: Any):
        self.records = records
        self.documents = documents
        self.upload_dir = records.upload_dir
        self.root = Path(documents.root) / "course_tasks"
        with records._connect() as db:
            ensure_schema(db)

    # -- auth ---------------------------------------------------------------
    def _account(self, token: str, *, roles=("school_uploader",)) -> dict[str, Any]:
        try:
            account = self.records.account_from_session(token)
        except ValueError:
            raise CourseTaskError(401, "authentication_required", "请重新登录") from None
        if account.get("role") not in roles:
            raise CourseTaskError(403, "course_task_forbidden", "当前账号无权访问课程任务文档")
        return account

    def _reject(self, error: CourseTaskError, account: dict[str, Any] | None, operation: str, **fields: Any):
        course_task_debug_event(self, "course_task_rejected", operation, account_id=(account or {}).get("account_id"),
                                code=error.code, http_status=error.status, **fields)
        return error

    def _school(self, db, account) -> tuple[str, str]:
        from .demo2_identity_store import Demo2IdentityStore
        from .evaluation_report_contract import school_id_from_context
        context = Demo2IdentityStore._context(self.records._school_context_for_account(db, account["account_id"]),
                                              required=False)
        return school_id_from_context(context), Demo2IdentityStore._scope(account["account_id"], context)

    # -- validation ---------------------------------------------------------
    @staticmethod
    def _text(value: Any, field: str, *, limit: int, required: bool = False, label: str = "") -> str:
        if value is None:
            value = ""
        if not isinstance(value, str) or len(value) > limit or any(
                unicodedata.category(c) in {"Cc", "Cf", "Cs"} and c not in "\n\r\t" for c in value):
            raise CourseTaskError(400, "invalid_field", f"{label or '字段'}过长（最多 {limit} 字）或包含无效字符", field)
        value = value.strip()
        if required and not value:
            raise CourseTaskError(400, "required_field", f"请填写{label or '必填字段'}", field)
        return value

    @staticmethod
    def _course_id(value: Any) -> str:
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > 120 or any(
                unicodedata.category(c).startswith("C") for c in value):
            raise CourseTaskError(400, "invalid_course_id", "课程批次号无效（1~120 个字符）", "course_id")
        return value.strip()

    def _roster_names(self, db, account) -> list[str]:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='demo2_identity_students'").fetchone():
            return []
        names = []
        for row in db.execute("SELECT display_name FROM demo2_identity_students WHERE owner_account_id=?",
                              (account["account_id"],)):
            name = unicodedata.normalize("NFKC", str(row[0] or "")).strip().casefold()
            if len(name) >= 2:
                names.append(name)
        return names

    @staticmethod
    def _check_text(text: str, field: str, names: list[str], label: str) -> None:
        folded = unicodedata.normalize("NFKC", text).casefold()
        if any(name in folded for name in names):
            raise CourseTaskError(400, "goal_contains_student_name",
                                  f"{label}不应填写学生姓名，请改用能力分层或支持方式描述", field)
        blocked = [_BLOCKED_SENSITIVE[k] for k in sensitive_types(text) if k in _BLOCKED_SENSITIVE]
        if blocked:
            raise CourseTaskError(400, "course_task_sensitive_content",
                                  f"{label}包含{('、'.join(dict.fromkeys(blocked)))}，请删除个人信息后再保存", field)

    def _normalize(self, db, account, payload: Any) -> dict[str, Any]:
        allowed = {"parse_id", "course_id", "course_name", "lesson_date", "goals", "notes", "expected_version"}
        if not isinstance(payload, dict) or set(payload) - allowed or not {"parse_id", "course_id", "goals"} <= set(payload):
            raise CourseTaskError(400, "invalid_payload", "请提交解析编号、课程批次号与确认后的目标")
        course_id = self._course_id(payload["course_id"])
        course_name = self._text(payload.get("course_name"), "course_name", limit=200, label="课程名称")
        lesson_date = self._text(payload.get("lesson_date"), "lesson_date", limit=10, label="上课日期")
        if lesson_date:
            try:
                if date.fromisoformat(lesson_date).isoformat() != lesson_date:
                    raise ValueError
            except ValueError:
                raise CourseTaskError(400, "invalid_date", "上课日期格式应为 YYYY-MM-DD", "lesson_date") from None
        expected = payload.get("expected_version", None)
        if expected is not None and (type(expected) is not int or expected < 0):
            raise CourseTaskError(400, "invalid_version", "课程任务版本无效", "expected_version")
        goals_in = payload["goals"]
        if not isinstance(goals_in, list) or not goals_in:
            raise CourseTaskError(400, "goals_required", "请至少保留一个课程任务目标", "goals")
        if len(goals_in) > MAX_GOALS:
            raise CourseTaskError(400, "too_many_goals", f"课程任务目标最多 {MAX_GOALS} 个", "goals")
        names = self._roster_names(db, account)
        self._check_text(course_name, "course_name", names, "课程名称")
        goals, codes = [], set()
        goal_keys = {"goal_code", "description", "pass_criteria", "measurement_conditions", "evaluation_criteria",
                     "rubric_dimension", "source", "confidence"}
        for index, item in enumerate(goals_in):
            prefix = f"goals.{index}."
            if not isinstance(item, dict) or set(item) - goal_keys:
                raise CourseTaskError(400, "invalid_goal", f"第 {index + 1} 个目标字段无效", f"goals.{index}")
            code = self._text(item.get("goal_code"), prefix + "goal_code", limit=8, required=True, label="目标编号")
            if not GOAL_CODE_PATTERN.fullmatch(code):
                raise CourseTaskError(400, "invalid_goal_code", "目标编号格式应为 G-01", prefix + "goal_code")
            if code in codes:
                raise CourseTaskError(400, "duplicate_goal_code", f"目标编号 {code} 重复", prefix + "goal_code")
            codes.add(code)
            goal = {"goal_code": code}
            for key, label, limit, required in (("description", "目标描述", 1000, True),
                                                ("pass_criteria", "通过标准", 1000, False),
                                                ("measurement_conditions", "测量条件", 1000, False),
                                                ("evaluation_criteria", "评价标准", 1000, False)):
                goal[key] = self._text(item.get(key), prefix + key, limit=limit, required=required, label=f"{code} {label}")
                self._check_text(goal[key], prefix + key, names, f"{code} 的{label}")
            dimension = item.get("rubric_dimension") or DEFAULT_DIMENSION
            if dimension not in DIMENSIONS:
                raise CourseTaskError(400, "invalid_dimension", "评分维度建议无效", prefix + "rubric_dimension")
            goal["rubric_dimension"] = dimension
            source = item.get("source")
            if isinstance(source, dict):
                goal["source"] = {k: source.get(k) for k in ("page", "paragraph_index", "kind", "cell_id")
                                  if isinstance(source.get(k), (int, str)) and len(str(source.get(k))) <= 40}
            else:
                goal["source"] = {"manual": True}
            goals.append(goal)
        notes_in = payload.get("notes", [])
        if not isinstance(notes_in, list) or len(notes_in) > MAX_NOTES:
            raise CourseTaskError(400, "invalid_notes", f"备注最多 {MAX_NOTES} 条", "notes")
        notes = []
        for index, note in enumerate(notes_in):
            text = self._text(note.get("text") if isinstance(note, dict) else note, f"notes.{index}",
                              limit=2000, required=True, label="备注")
            self._check_text(text, f"notes.{index}", names, "备注")
            notes.append({"text": text})
        return {"parse_id": payload["parse_id"], "course_id": course_id, "course_name": course_name,
                "lesson_date": lesson_date, "goals": goals, "notes": notes, "expected_version": expected}

    # -- sealing ------------------------------------------------------------
    def _original_path(self, doc_id: str) -> Path:
        return self.root / f"{doc_id}.sealed"

    def _write_original(self, doc_id: str, data: bytes) -> None:
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        sealed = self.documents._seal(data)
        target = self._original_path(doc_id)
        temporary = self.root / f".{doc_id}.{secrets.token_hex(4)}.tmp"
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

    # -- API ----------------------------------------------------------------
    def draft(self, token: str, payload: Any) -> dict[str, Any]:
        """Structured goals proposed from one course_task parse result (nothing is saved)."""
        from .demo2_document_parser import DocumentError
        account = self._account(token)
        if not isinstance(payload, dict) or set(payload) != {"parse_id"} or not isinstance(payload["parse_id"], str):
            raise self._reject(CourseTaskError(400, "invalid_payload", "请提供文件解析编号 parse_id"), account,
                               "course_task_upload")
        try:
            parse = self.documents.get(account["account_id"], payload["parse_id"])
        except DocumentError as exc:
            raise self._reject(CourseTaskError(exc.status, exc.code, exc.message), account, "course_task_upload",
                               parse_id=payload["parse_id"]) from None
        if parse.get("purpose") != "course_task":
            raise self._reject(CourseTaskError(400, "invalid_purpose", "该文件不是课程任务文档，请按课程任务重新上传"),
                               account, "course_task_upload", parse_id=payload["parse_id"])
        draft = build_draft(parse)
        course_task_debug_event(self, "course_task_upload", parse.get("status") or "parsed",
                                account_id=account["account_id"], parse_id=parse["parse_id"],
                                goal_count=len(draft["goals"]), other_count=len(draft["other_content"]),
                                byte_size=parse.get("byte_size") if isinstance(parse.get("byte_size"), int) else None,
                                goal_codes=[g["goal_code"] for g in draft["goals"]])
        return draft

    def confirm(self, token: str, payload: Any) -> dict[str, Any]:
        from .demo2_document_parser import DocumentError
        account = self._account(token)
        course_id = payload.get("course_id") if isinstance(payload, dict) and isinstance(payload.get("course_id"), str) else None
        try:
            with self.records._connect() as db:
                data = self._normalize(db, account, payload)
        except CourseTaskError as exc:
            raise self._reject(exc, account, "course_task_confirm", course_id=course_id) from None
        try:
            extension, original = self.documents.read_original(account["account_id"], data["parse_id"])
            parse = self.documents.get(account["account_id"], data["parse_id"])
        except DocumentError as exc:
            raise self._reject(CourseTaskError(exc.status, exc.code, exc.message), account, "course_task_confirm",
                               course_id=course_id, parse_id=data["parse_id"]) from None
        if parse.get("purpose") != "course_task":
            raise self._reject(CourseTaskError(400, "invalid_purpose", "该文件不是课程任务文档，请按课程任务重新上传"),
                               account, "course_task_confirm", course_id=course_id)
        extension = "." + str(extension or "").lstrip(".").lower()
        doc_id = "ctd-" + secrets.token_hex(16)
        try:
            self._write_original(doc_id, original)
        except Exception:
            DEBUG_LOGGER.exception("course task original sealing failed")
            raise self._reject(CourseTaskError(503, "document_vault_unavailable", "资料加密服务暂不可用，课程任务未保存"),
                               account, "course_task_confirm", course_id=course_id) from None
        now = _now()
        content = {"goals": data["goals"], "notes": data["notes"], "parse_status": parse.get("status", ""),
                   "page_count": parse.get("page_count", 0)}
        try:
            with self.records._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                school_id, scope = self._school(db, account)
                previous = db.execute(
                    "SELECT course_task_doc_id, version FROM demo2_course_task_documents "
                    "WHERE owner_account_id=? AND course_id=? AND status='confirmed' ORDER BY version DESC LIMIT 1",
                    (account["account_id"], data["course_id"])).fetchone()
                top = db.execute("SELECT COALESCE(MAX(version),0) FROM demo2_course_task_documents "
                                 "WHERE owner_account_id=? AND course_id=?",
                                 (account["account_id"], data["course_id"])).fetchone()[0]
                current_version = previous["version"] if previous else 0
                if data["expected_version"] is not None and data["expected_version"] != current_version:
                    raise CourseTaskError(409, "course_task_version_conflict",
                                          "该课程的课程任务已被更新，请刷新后重新核对再保存", "expected_version")
                version = int(top) + 1
                if previous:
                    db.execute("UPDATE demo2_course_task_documents SET status='superseded', superseded_at=? "
                               "WHERE owner_account_id=? AND course_id=? AND status='confirmed'",
                               (now, account["account_id"], data["course_id"]))
                db.execute(
                    "INSERT INTO demo2_course_task_documents (course_task_doc_id, school_id, scope_key, course_id, "
                    "owner_account_id, version, status, original_path, original_extension, original_sha256, byte_size, "
                    "parse_id, course_name, lesson_date, goal_count, goals_json, created_at, confirmed_at, confirmed_by) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (doc_id, school_id, scope, data["course_id"], account["account_id"], version, "confirmed",
                     f"course_tasks/{doc_id}.sealed", extension, hashlib.sha256(original).hexdigest(), len(original),
                     data["parse_id"], data["course_name"], data["lesson_date"], len(data["goals"]),
                     json.dumps(content, ensure_ascii=False, separators=(",", ":")), now, now,
                     account.get("username") or ""))
                self.records._audit(db, account.get("username") or account["account_id"], "course_task_confirmed",
                                    "demo2_course_task", doc_id, {"course_id": data["course_id"], "version": version,
                                                                  "goal_count": len(data["goals"])})
                row = db.execute("SELECT * FROM demo2_course_task_documents WHERE course_task_doc_id=?",
                                 (doc_id,)).fetchone()
        except CourseTaskError as exc:
            self._remove_original(doc_id)
            raise self._reject(exc, account, "course_task_confirm", course_id=data["course_id"]) from None
        except Exception:
            self._remove_original(doc_id)
            raise
        result = public_document(row)
        course_task_debug_event(self, "course_task_confirm", "confirmed", account_id=account["account_id"],
                                course_id=data["course_id"], course_task_doc_id=doc_id, version=version,
                                goal_count=len(data["goals"]), note_count=len(data["notes"]),
                                parse_id=data["parse_id"], goal_codes=[g["goal_code"] for g in data["goals"]])
        if previous:
            course_task_debug_event(self, "course_task_version", "superseded", account_id=account["account_id"],
                                    course_id=data["course_id"], course_task_doc_id=doc_id, version=version,
                                    previous_doc_id=previous["course_task_doc_id"],
                                    previous_version=int(previous["version"]), goal_count=len(data["goals"]))
        return result

    def _remove_original(self, doc_id: str) -> None:
        try:
            self._original_path(doc_id).unlink()
        except OSError:
            pass

    def for_course(self, token: str, course_id: str | None) -> dict[str, Any]:
        account = self._account(token)
        with self.records._connect() as db:
            if course_id:
                course_id = self._course_id(course_id)
                rows = db.execute("SELECT * FROM demo2_course_task_documents WHERE owner_account_id=? AND course_id=? "
                                  "ORDER BY version DESC LIMIT 100", (account["account_id"], course_id)).fetchall()
                versions = [public_document(r) for r in rows]
                current = next((v for v in versions if v["status"] == "confirmed"), None)
                return {"course_id": course_id, "current": current,
                        "versions": [{k: v[k] for k in ("course_task_doc_id", "course_task_doc_short", "version", "status",
                                                        "status_label", "goal_count", "confirmed_at", "superseded_at")}
                                     for v in versions],
                        "dimensions": [{"id": k, "label": v} for k, v in DIMENSIONS.items()]}
            rows = db.execute("SELECT * FROM demo2_course_task_documents WHERE owner_account_id=? AND status='confirmed' "
                              "ORDER BY confirmed_at DESC LIMIT 100", (account["account_id"],)).fetchall()
        return {"course_tasks": [public_document(r) for r in rows],
                "dimensions": [{"id": k, "label": v} for k, v in DIMENSIONS.items()]}

    def _owned(self, token: str, doc_id: Any, operation: str) -> tuple[dict[str, Any], dict[str, Any], bool]:
        account = self._account(token, roles=("school_uploader", "company_admin"))
        admin = account.get("role") == "company_admin"
        if not isinstance(doc_id, str) or not DOC_ID_PATTERN.fullmatch(doc_id):
            raise self._reject(CourseTaskError(400, "invalid_course_task_id", "课程任务编号格式无效"), account, operation)
        with self.records._connect() as db:
            row = document_by_id(db, doc_id)
        if row is None:
            raise self._reject(CourseTaskError(404, "course_task_not_found", "课程任务文档不存在"), account, operation,
                               course_task_doc_id=doc_id)
        if not admin and row["owner_account_id"] != account["account_id"]:
            raise self._reject(CourseTaskError(403, "course_task_forbidden", "当前账号无权访问该课程任务文档"),
                               account, operation, course_task_doc_id=doc_id)
        return account, row, admin

    def document(self, token: str, doc_id: Any) -> dict[str, Any]:
        account, row, admin = self._owned(token, doc_id, "course_task_read")
        course_task_debug_event(self, "course_task_read", "ok", account_id=account["account_id"],
                                course_id=row["course_id"], course_task_doc_id=row["course_task_doc_id"],
                                version=int(row["version"]), goal_count=int(row["goal_count"]),
                                role="company_admin" if admin else "teacher")
        return public_document(row, admin=admin)

    def original(self, token: str, doc_id: Any) -> tuple[bytes, str, str]:
        account, row, admin = self._owned(token, doc_id, "course_task_download")
        try:
            data = self.documents._open(self._original_path(row["course_task_doc_id"]).read_bytes())
        except Exception:
            raise self._reject(CourseTaskError(503, "document_vault_unavailable", "课程任务原件暂不可下载"), account,
                               "course_task_download", course_task_doc_id=row["course_task_doc_id"]) from None
        extension = "." + str(row["original_extension"] or "").lstrip(".").lower()
        if extension not in {".pdf", ".docx", ".doc"}:
            extension = ".pdf"
        mime = {".pdf": "application/pdf", ".doc": "application/msword",
                ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}[extension]
        safe_course = re.sub(r"[^A-Za-z0-9_.-]", "_", row["course_id"])[:60] or "course"
        filename = f"课程任务_{safe_course}_v{row['version']}{extension}"
        course_task_debug_event(self, "course_task_download", "ok", account_id=account["account_id"],
                                course_id=row["course_id"], course_task_doc_id=row["course_task_doc_id"],
                                version=int(row["version"]), byte_size=len(data), fmt=extension.lstrip("."),
                                role="company_admin" if admin else "teacher")
        return data, filename, mime

    def summary_markdown(self, token: str, doc_id: Any) -> tuple[str, str]:
        account, row, admin = self._owned(token, doc_id, "course_task_download")
        doc = public_document(row, admin=admin)
        lines = [f"# 课程任务目标摘要（版本 {doc['version']}）", "",
                 f"课程任务编号：{doc['course_task_doc_id']}", f"课程批次号：{doc['course_id']}",
                 f"课程名称：{doc['course_name'] or '未填写'} · 上课日期：{doc['lesson_date'] or '未填写'}",
                 f"状态：{doc['status_label']} · 确认时间：{doc['confirmed_at']}", ""]
        for goal in doc["goals"]:
            lines += [f"## {goal.get('goal_code')} {goal.get('description', '')}", "",
                      f"- 通过标准：{goal.get('pass_criteria') or '未填写'}",
                      f"- 测量条件：{goal.get('measurement_conditions') or '未填写'}",
                      f"- 评价标准：{goal.get('evaluation_criteria') or '未填写'}",
                      f"- 对应评分维度：{DIMENSIONS.get(goal.get('rubric_dimension'), '未填写')}", ""]
        if not admin and doc["notes"]:
            lines += ["## 其他内容与备注", ""] + [f"- {note.get('text', '')}" for note in doc["notes"]] + [""]
        lines.append("本摘要只含课程任务目标，不含学生个人资料或 IEP 内容。")
        course_task_debug_event(self, "course_task_download", "ok", account_id=account["account_id"],
                                course_id=row["course_id"], course_task_doc_id=row["course_task_doc_id"],
                                version=int(row["version"]), goal_count=int(row["goal_count"]), fmt="md",
                                role="company_admin" if admin else "teacher")
        return "\n".join(lines), f"课程任务目标摘要_v{row['version']}.md"

    def admin_for_tasks(self, token: str, tasks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """{task_id: current course-task summary} for the company task query (goal summary only)."""
        self._account(token, roles=("company_admin",))
        result: dict[str, dict[str, Any]] = {}
        with self.records._connect() as db:
            for task in tasks:
                account_id, course_id = task.get("account_id"), task.get("course_id")
                if not account_id or not course_id:
                    continue
                current = current_for_course(db, account_id, course_id)
                if current:
                    result[task["task_id"]] = {k: current[k] for k in (
                        "course_task_doc_id", "course_task_doc_short", "version", "goal_count", "confirmed_at",
                        "original_extension")}
        return result


def summary_for_upload(records: Any, account_id: str, course_id: str) -> dict[str, Any] | None:
    """Compact status for the upload workspace card (no notes)."""
    with records._connect() as db:
        if not course_id or not _table_exists(db):
            return None
        current = current_for_course(db, account_id, course_id)
        count = db.execute("SELECT COUNT(*) FROM demo2_course_task_documents WHERE owner_account_id=? AND course_id=?",
                           (account_id, course_id)).fetchone()[0]
    if not current:
        return None
    return {**{k: current[k] for k in ("course_task_doc_id", "course_task_doc_short", "version", "goal_count",
                                       "course_name", "lesson_date", "confirmed_at", "original_extension")},
            "goals": [{k: g.get(k, "") for k in ("goal_code", "description")} for g in current["goals"]],
            "version_count": int(count)}
