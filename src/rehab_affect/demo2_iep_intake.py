"""IEP Word/PDF intake: system summary → teacher confirmation → dossier version → classroom reference.

The parse service (``demo2_document_store``) keeps the uploaded IEP sealed for
24 hours. This module turns its candidates into a short, itemized classroom
support summary (goals, support methods, strategies, precautions, assessment),
drops every item that carries diagnosis wording, ID numbers, phone numbers or
addresses, and — once the teacher has kept/deleted/edited the items and pressed
「确认摘要」 — writes them into the encrypted student dossier as an
``document_type='iep'`` version and links that version to the classroom task.

Item pages and categories always come from the server-side regeneration of the
summary; the browser only chooses which items to keep and may edit their text.
The ``iep_debug_YYYYMMDD.jsonl`` log keeps operation, short codes, counts and
result codes only — never summary text, names or sensitive values.
"""
from __future__ import annotations

import json
import logging
import os
import re
import secrets
import threading
import time
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .demo2_document_parser import DocumentError, clean_text, sensitive_types, SENSITIVE_LABELS
from .demo2_dossier_store import MAX_FILE_BYTES, MAX_RETENTION_DAYS, DossierError, short_code

DEBUG_LOG_DIR_ENV = "REHAB_DEMO2_IEP_DEBUG_LOG_DIR"
DEBUG_LOGGER = logging.getLogger("rehab_affect.iep_intake")
OPERATIONS = frozenset({
    "iep_upload", "iep_summary_generate", "iep_summary_confirm", "iep_manual_supplement",
    "iep_required_rejected", "iep_reference_create", "iep_reuse_existing", "iep_status",
    "iep_document_create", "iep_commit",
})
MAX_ITEMS = 40
MAX_ITEM_CHARS = 300
MAX_MANUAL_CHARS = 1000
MAX_SUMMARY_FIELD_CHARS = 2000
REQUIRED_MESSAGE = "请上传 IEP 文件或填写 IEP 支持摘要"
DEFAULT_SOURCE_REF = "教师上传的 IEP 文件（课堂分析页确认摘要）"
MANUAL_SOURCE_REF = "教师填写的 IEP 支持摘要（课堂分析页）"

# (category, label, dossier summary field) in display order.
CATEGORIES: tuple[tuple[str, str, str], ...] = (
    ("long_term_goals", "长期目标", "learning_goals"),
    ("short_term_goals", "短期目标", "learning_goals"),
    ("support_needs", "支持方式", "support_methods"),
    ("teaching_strategies", "教学策略", "support_methods"),
    ("precautions", "注意事项", "safety_notes"),
    ("assessment_methods", "评估方式", "learning_goals"),
)
CATEGORY_LABELS = {key: label for key, label, _ in CATEGORIES}
CATEGORY_FIELDS = {key: field for key, _, field in CATEGORIES}
_CATEGORY_ORDER = {key: index for index, (key, _, _) in enumerate(CATEGORIES)}
_PRECAUTION_LABEL = re.compile(r"^\s*(课堂注意事项|安全注意事项|特别注意事项|注意事项|特别注意|安全提示|注意要点|安全事项)\s*[:：]?\s*(.*)$")
_KEY_LABEL = re.compile(r"^[^：:\s]{1,12}[：:]")
_LIST_MARKER = re.compile(r"^\s*(?:[0-9０-９]{1,2}[.、．)）]|[（(][0-9０-９一二三四五六七八九十]{1,3}[)）]|[一二三四五六七八九十]{1,3}[、.．]|[•·●○■□▪◆◇\-—*])\s*")
_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
_PARSE_ID = re.compile(r"dp-[0-9a-f]{32}")
_ITEM_ID = re.compile(r"s[0-9]{2}")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_LOCK = threading.Lock()


class IepIntakeError(ValueError):
    def __init__(self, status: int, code: str, message: str, field: str | None = None):
        super().__init__(message)
        self.status, self.code, self.message, self.field = status, code, message, field


# ---------------------------------------------------------------------------
# debug log
# ---------------------------------------------------------------------------

def iep_log_dir(records: Any) -> Path:
    configured = os.getenv(DEBUG_LOG_DIR_ENV, "").strip()
    if configured:
        return Path(configured)
    return Path(os.path.abspath(Path(records.upload_dir).parent / "logs"))


def _token(value: Any) -> str:
    text = str(value)
    return text if re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", text) else "<invalid>"


_SHORT_FIELDS = {"student_id": "student_short", "document_id": "document_short", "parse_id": "parse_short",
                 "task_id": "task_short", "reference_id": "reference_short", "supersedes_id": "supersedes_short",
                 "authorization_id": "authorization_short"}
_COUNT_FIELDS = ("item_count", "kept_count", "deleted_count", "edited_count", "excluded_sensitive_count",
                 "manual_length", "page_count", "version", "http_status", "candidate_count", "withdrawn_count")
_TOKEN_FIELDS = ("code", "mode", "status", "file_type", "origin", "storage_mode", "reason")


def iep_debug_event(records: Any, operation: str, result: str, **fields: Any) -> dict[str, Any]:
    """One JSON line in ``iep_debug_YYYYMMDD.jsonl``; IDs appear only as 8-character short codes."""
    entry: dict[str, Any] = {
        "ts": datetime.now().astimezone().isoformat(timespec="milliseconds"),
        "operation": operation if operation in OPERATIONS else "<invalid>",
        "result": _token(result),
    }
    for key, value in fields.items():
        if value is None or value == "":
            continue
        if key in _SHORT_FIELDS:
            text = str(value)
            entry[_SHORT_FIELDS[key]] = short_code(text) if _ID.fullmatch(text) else "<invalid>"
        elif key in _COUNT_FIELDS:
            entry[key] = value if isinstance(value, int) and not isinstance(value, bool) else "<invalid>"
        elif key in _TOKEN_FIELDS:
            entry[key] = _token(value)
        elif key == "duration_ms" and isinstance(value, (int, float)) and not isinstance(value, bool):
            entry[key] = round(float(value), 1)
        elif key == "original_saved":
            entry[key] = bool(value)
        elif key == "categories" and isinstance(value, dict):
            entry[key] = {k: v for k, v in value.items() if k in CATEGORY_LABELS and isinstance(v, int)}
        elif key == "sensitive_types" and isinstance(value, (list, tuple)):
            entry[key] = sorted({_token(v) for v in value})[:8]
    line = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
    DEBUG_LOGGER.info(line)
    try:
        folder = iep_log_dir(records)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"iep_debug_{entry['ts'][:10].replace('-', '')}.jsonl"
        with _LOCK, path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except (OSError, TypeError, ValueError):
        DEBUG_LOGGER.warning("iep debug log write failed")
    return entry


# ---------------------------------------------------------------------------
# summary generation (pure)
# ---------------------------------------------------------------------------

def _normal(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", unicodedata.normalize("NFKC", text or "")).casefold()


def _strip_marker(text: str) -> str:
    # PDF bullets often survive as private-use glyphs (e.g. U+F0B7) in front of the list text.
    text = "".join(ch for ch in (text or "") if unicodedata.category(ch) not in {"Co", "Cn"}).strip()
    stripped = _LIST_MARKER.sub("", text, count=1).strip()
    return stripped or (text or "").strip()


def _location(block_or_source: dict[str, Any]) -> tuple[int | None, int | None]:
    page = block_or_source.get("page")
    paragraph = block_or_source.get("paragraph_index")
    return (page if isinstance(page, int) and not isinstance(page, bool) and page > 0 else None,
            paragraph if isinstance(paragraph, int) and not isinstance(paragraph, bool) else None)


def _precaution_entries(blocks: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    """Precautions are not a parser field: read 「注意事项」 labels and the list that follows them."""
    found: list[tuple[str, dict[str, Any]]] = []
    active = False
    for block in blocks:
        kind = block.get("kind")
        if kind in {"header", "footer"}:
            continue
        if kind == "table":
            active = False
            rows: dict[int, dict[int, str]] = {}
            for cell in block.get("cells") or []:
                rows.setdefault(cell["row"], {})[cell["col"]] = cell["text"]
            header = rows.get(1, {})
            columns = [col for col, text in header.items() if _PRECAUTION_LABEL.match(text or "")
                       and not _PRECAUTION_LABEL.match(text or "").group(2)]
            for row_number, row in rows.items():
                if row_number == 1:
                    continue
                for col in columns:
                    if row.get(col):
                        found.append((row[col], block))
            for row in rows.values():
                ordered = [row[col] for col in sorted(row)]
                for index, text in enumerate(ordered[:-1]):
                    match = _PRECAUTION_LABEL.match(text or "")
                    if match and not match.group(2) and ordered[index + 1]:
                        found.append((ordered[index + 1], block))
            continue
        text = str(block.get("text") or "")
        match = _PRECAUTION_LABEL.match(unicodedata.normalize("NFKC", text))
        if match:
            value = match.group(2).strip()
            if value:
                found.append((value, block))
                active = kind != "heading"
            else:
                active = True
            continue
        if not active:
            continue
        if kind == "heading" or _KEY_LABEL.match(unicodedata.normalize("NFKC", text)):
            active = False
            continue
        found.append((text, block))
    return found


def _split_sentences(text: str) -> list[str]:
    parts = [part.strip() for part in re.split(r"[；;\n]+", text or "") if part.strip()]
    return parts or ([text.strip()] if (text or "").strip() else [])


def build_iep_summary(parse_result: dict[str, Any]) -> dict[str, Any]:
    """Itemized classroom-support summary from one IEP parse result (no I/O)."""
    candidates = [c for c in parse_result.get("candidates") or [] if isinstance(c, dict)]
    blocks = [b for b in parse_result.get("blocks") or [] if isinstance(b, dict)]
    names = sorted({clean_text(c.get("value")) for c in candidates
                    if c.get("field") == "student_name" and len(clean_text(c.get("value"))) >= 2}, key=len, reverse=True)
    raw: list[tuple[str, str, dict[str, Any]]] = []
    for candidate in candidates:
        field = candidate.get("field")
        if field not in CATEGORY_LABELS or candidate.get("same_goal_as"):
            continue
        source = candidate.get("source") or {}
        raw.append((field, str(candidate.get("value") or ""), source))
    for text, block in _precaution_entries(blocks):
        raw.append(("precautions", text, block))
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    excluded = 0
    excluded_types: set[str] = set()
    for category, value, source in raw:
        for sentence in _split_sentences(value):
            text = _strip_marker(clean_text(sentence))
            for name in names:
                text = text.replace(name, "该生")
            text = text.strip(" ，,。")
            if len(_normal(text)) < 2:
                continue
            kinds = sensitive_types(text)
            if kinds:
                excluded += 1
                excluded_types.update(kinds)
                continue
            key = category + ":" + _normal(text)
            if key in seen:
                continue
            seen.add(key)
            page, paragraph = _location(source)
            items.append({"category": category, "category_label": CATEGORY_LABELS[category],
                          "text": text[:MAX_ITEM_CHARS], "page": page, "paragraph_index": paragraph})
    items.sort(key=lambda item: (_CATEGORY_ORDER[item["category"]], item["page"] or 10 ** 6,
                                 item["paragraph_index"] or 10 ** 6))
    truncated = max(0, len(items) - MAX_ITEMS)
    items = items[:MAX_ITEMS]
    for index, item in enumerate(items, start=1):
        item["item_id"] = f"s{index:02d}"
        item.pop("paragraph_index", None)
    counts = {key: sum(item["category"] == key for item in items) for key in CATEGORY_LABELS}
    status = parse_result.get("status") or "parsed"
    notice = parse_result.get("notice") or ""
    if not items:
        notice = (notice + "；" if notice else "") + "未从文件中筛查到可用于课堂支持的目标、支持方式或策略，请在「人工补充」中填写"
    return {
        "items": items,
        "item_count": len(items),
        "category_counts": counts,
        "excluded_sensitive_count": excluded,
        "excluded_sensitive_labels": sorted({SENSITIVE_LABELS.get(kind, "个人信息") for kind in excluded_types}),
        "truncated_count": truncated,
        "page_count": parse_result.get("page_count") or 0,
        "page_count_estimated": bool(parse_result.get("page_count_estimated")),
        "file_type": parse_result.get("file_type") or "",
        "parse_status": status,
        "manual_entry_required": bool(parse_result.get("manual_entry_required")) or not items,
        "notice": notice,
        "categories": [{"category": key, "label": label} for key, label, _ in CATEGORIES],
    }


MANUAL_PREFIX_RE = re.compile(r"^\s*(?:IEP\s*)?教师补充\s*[:：]\s*")


def manual_supplement_body(manual: Any) -> str:
    """Teacher supplement text without a typed-in 「教师补充：」 label (renderers add the label once)."""
    return MANUAL_PREFIX_RE.sub("", str(manual or "")).strip()


def summary_text_fields(items: list[dict[str, Any]], manual: str) -> dict[str, str]:
    """Map confirmed items onto the dossier's four teacher-confirmed summary fields."""
    lines: dict[str, list[str]] = {"learning_goals": [], "support_methods": [], "safety_notes": [],
                                   "professional_conclusion": []}
    for item in items:
        page = f"（第 {item['page']} 页）" if item.get("page") else ""
        lines[CATEGORY_FIELDS[item["category"]]].append(f"{CATEGORY_LABELS[item['category']]}：{item['text']}{page}")
    if manual:
        lines["support_methods"].append("教师补充：" + manual_supplement_body(manual))
    result = {}
    for key, values in lines.items():
        text = "\n".join(values)
        if len(text) > MAX_SUMMARY_FIELD_CHARS:
            raise IepIntakeError(400, "iep_summary_too_long",
                                 "确认的摘要条目过多（单类超过 2000 字），请删除或精简部分条目后再确认", "iepItems")
        result[key] = text
    return result


def _check_text(value: Any, limit: int, field: str, label: str) -> str:
    if not isinstance(value, str) or len(value) > limit or any(
            unicodedata.category(ch) in {"Cc", "Cf", "Cs"} and ch not in "\n\r\t" for ch in value):
        raise IepIntakeError(400, "invalid_iep_field", f"{label}格式无效或超过 {limit} 字", field)
    text = value.strip()
    kinds = sensitive_types(text)
    if kinds:
        labels = "、".join(sorted({SENSITIVE_LABELS.get(kind, "个人信息") for kind in kinds}))
        raise IepIntakeError(400, "iep_summary_sensitive",
                             f"{label}含有{labels}，课堂支持摘要不能写入诊断原文、身份证号、电话或住址", field)
    return text


def _date_value(value: Any, field: str, label: str) -> date:
    if not isinstance(value, str) or not _DATE.fullmatch(value):
        raise IepIntakeError(400, "invalid_iep_field", f"{label}须为 YYYY-MM-DD", field)
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise IepIntakeError(400, "invalid_iep_field", f"{label}无效", field) from None


def _today() -> date:
    return datetime.now().astimezone().date()


def summary_present(iep: Any) -> bool:
    """Server-side「必填」rule: confirmed system items, a teacher supplement, or an existing IEP version."""
    if not isinstance(iep, dict):
        return False
    if iep.get("mode") == "existing":
        return isinstance(iep.get("document_id"), str) and bool(iep["document_id"].strip())
    items = iep.get("items")
    kept = isinstance(items, list) and any(isinstance(item, dict) and str(item.get("text") or "").strip()
                                          for item in items)
    manual = isinstance(iep.get("manual_supplement"), str) and bool(iep["manual_supplement"].strip())
    return kept or manual


# ---------------------------------------------------------------------------
# service
# ---------------------------------------------------------------------------

class IepIntakeService:
    """Glue between the parse staging store, the dossier store and the simple lesson archive."""

    def __init__(self, records: Any, dossier: Any, documents: Any):
        self.records = records
        self.dossier = dossier
        self.documents = documents
        with records._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS demo2_iep_intakes (
                intake_id TEXT PRIMARY KEY, owner_account_id TEXT NOT NULL, student_id TEXT NOT NULL,
                parse_id TEXT NOT NULL, document_id TEXT NOT NULL, created_at TEXT NOT NULL,
                UNIQUE(owner_account_id, student_id, parse_id))""")

    # -- helpers ----------------------------------------------------------
    def log(self, operation: str, result: str, **fields: Any) -> dict[str, Any]:
        return iep_debug_event(self.records, operation, result, **fields)

    def _account_id(self, token: str) -> str:
        account = self.records.account_from_session(token)
        if account.get("role") != "school_uploader":
            raise IepIntakeError(403, "forbidden", "只有学校教师账号可以录入 IEP")
        return account["account_id"]

    def _summary_for(self, account_id: str, parse_id: Any) -> dict[str, Any]:
        if not isinstance(parse_id, str) or not _PARSE_ID.fullmatch(parse_id):
            raise IepIntakeError(400, "invalid_parse_id", "IEP 文件解析编号无效，请重新上传文件", "iepFile")
        try:
            parsed = self.documents.get(account_id, parse_id)
        except DocumentError as exc:
            raise IepIntakeError(exc.status, exc.code, exc.message, "iepFile") from None
        if parsed.get("purpose") != "iep":
            raise IepIntakeError(400, "parse_purpose_mismatch", "该文件不是按 IEP 用途上传的，请重新选择 IEP 文件", "iepFile")
        return build_iep_summary(parsed)

    # -- API: summary -----------------------------------------------------
    def generate_summary(self, token: str, payload: Any) -> dict[str, Any]:
        started = time.monotonic()
        account_id = self._account_id(token)
        if not isinstance(payload, dict) or set(payload) != {"parse_id"}:
            raise IepIntakeError(400, "invalid_request", "请提交 IEP 文件解析编号")
        try:
            summary = self._summary_for(account_id, payload["parse_id"])
        except IepIntakeError as exc:
            self.log("iep_summary_generate", "rejected", parse_id=payload.get("parse_id"), code=exc.code,
                     http_status=exc.status)
            raise
        self.log("iep_summary_generate", "ok", parse_id=payload["parse_id"], item_count=summary["item_count"],
                 excluded_sensitive_count=summary["excluded_sensitive_count"], page_count=summary["page_count"],
                 file_type=summary["file_type"], status=summary["parse_status"], categories=summary["category_counts"],
                 duration_ms=(time.monotonic() - started) * 1000)
        return dict(summary, parse_id=payload["parse_id"], status="pending_confirmation")

    # -- API: student status ----------------------------------------------
    def student_status(self, token: str, student_id: str) -> dict[str, Any]:
        self._account_id(token)
        workspace = self.dossier.student_workspace(token, student_id)
        auth = workspace.get("authorization")
        active = bool(auth and auth.get("status") == "active" and auth.get("valid_until", "") > _today().isoformat())
        context = self.dossier.iep_context(token, student_id) if active else {"status": "unavailable", "candidates": [],
                                                                             "iep": None, "iep_document_id": ""}
        current = None
        if context.get("status") == "available" and context.get("iep"):
            iep = context["iep"]
            current = {key: iep.get(key) for key in ("document_id", "version", "document_date", "retain_until", "family_id")}
            current["has_file"] = bool(iep.get("has_file"))
        candidates = [{key: item.get(key) for key in ("document_id", "version", "document_date", "retain_until", "family_id")}
                      for item in context.get("candidates") or []]
        result = {
            "student_id": student_id,
            "authorization": ({"active": True, "storage_mode": auth["storage_mode"], "valid_until": auth["valid_until"]}
                              if active else {"active": False, "storage_mode": "", "valid_until": ""}),
            "iep_status": context.get("status") if active else "no_authorization",
            "current": current,
            "candidates": candidates,
            "max_retention_days": MAX_RETENTION_DAYS,
        }
        self.log("iep_status", result["iep_status"], student_id=student_id,
                 document_id=current["document_id"] if current else None,
                 version=current["version"] if current else None, candidate_count=len(candidates))
        return result

    # -- API: commit ------------------------------------------------------
    def _validated_items(self, account_id: str, iep: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any] | None, int, int]:
        parse_id = iep.get("parse_id") or ""
        submitted = iep.get("items")
        if not parse_id:
            if submitted:
                raise IepIntakeError(400, "invalid_iep_items", "系统摘要条目缺少对应的 IEP 文件，请重新上传", "iepFile")
            return [], None, 0, 0
        summary = self._summary_for(account_id, parse_id)
        generated = {item["item_id"]: item for item in summary["items"]}
        if not isinstance(submitted, list) or len(submitted) > MAX_ITEMS:
            raise IepIntakeError(400, "invalid_iep_items", "摘要条目格式无效，请刷新后重新确认", "iepItems")
        kept, used, edited = [], set(), 0
        for entry in submitted:
            if not isinstance(entry, dict) or set(entry) - {"item_id", "text"} or not isinstance(entry.get("item_id"), str):
                raise IepIntakeError(400, "invalid_iep_items", "摘要条目格式无效，请刷新后重新确认", "iepItems")
            item_id = entry["item_id"]
            if not _ITEM_ID.fullmatch(item_id) or item_id not in generated or item_id in used:
                raise IepIntakeError(400, "invalid_iep_items", "摘要条目与系统筛查结果不一致，请重新生成摘要", "iepItems")
            used.add(item_id)
            text = _check_text(entry.get("text", ""), MAX_ITEM_CHARS, "iepItems", "摘要条目")
            if not text:
                continue
            base = generated[item_id]
            if text != base["text"]:
                edited += 1
            kept.append({"item_id": item_id, "category": base["category"], "category_label": base["category_label"],
                         "text": text, "page": base["page"], "edited": text != base["text"]})
        deleted = len(generated) - len(kept)
        return kept, summary, deleted, edited

    def _existing_reference(self, token: str, task_id: str, student_id: str, document_id: str) -> dict[str, Any] | None:
        workspace = self.dossier.task_workspace(token, task_id)
        for ref in workspace["references"]:
            if (ref["student_id"] == student_id and not ref["withdrawn"] and ref["available"]
                    and any(v["document_id"] == document_id for v in ref["document_versions"])):
                return {"reference": ref, "frame_revision": workspace["task"]["frame_revision"], "workspace": workspace}
        return {"reference": None, "frame_revision": workspace["task"]["frame_revision"], "workspace": workspace}

    def _link_task(self, token: str, task_id: str, student_id: str, document_id: str) -> dict[str, Any]:
        found = self._existing_reference(token, task_id, student_id, document_id)
        if found["reference"] is not None:
            ref = found["reference"]
            self.log("iep_reference_create", "reused", task_id=task_id, student_id=student_id,
                     document_id=document_id, reference_id=ref["reference_id"])
            return ref
        # One current IEP reference per student and lesson: older IEP references of this lesson are withdrawn
        # (history stays) so analysis never sees two current IEP families and turns ambiguous.
        withdrawn = 0
        for ref in found["workspace"]["references"]:
            if (ref["student_id"] == student_id and not ref["withdrawn"]
                    and any(doc.get("document_type") == "iep" for doc in ref["documents"])):
                self.dossier.withdraw_reference(token, {"reference_id": ref["reference_id"], "confirmed": True})
                withdrawn += 1
        try:
            ref = self.dossier.create_reference(token, {"task_id": task_id, "student_id": student_id,
                                                        "frame_revision": found["frame_revision"],
                                                        "document_ids": [document_id], "confirmed": True})
        except DossierError as exc:
            self.log("iep_reference_create", "rejected", task_id=task_id, student_id=student_id,
                     document_id=document_id, code=exc.code, http_status=exc.status)
            raise
        self.log("iep_reference_create", "created", task_id=task_id, student_id=student_id, document_id=document_id,
                 reference_id=ref["reference_id"], withdrawn_count=withdrawn, status=ref["status"])
        return ref

    def _authorization(self, token: str, student_id: str, iep: dict[str, Any], wants_original: bool) -> dict[str, Any]:
        workspace = self.dossier.student_workspace(token, student_id)
        auth = workspace.get("authorization")
        if auth and auth.get("status") == "active" and auth.get("valid_until", "") > _today().isoformat():
            return auth
        request = iep.get("authorization")
        if not isinstance(request, dict):
            raise IepIntakeError(409, "iep_authorization_required",
                                 "该学生还没有有效的资料授权，请在「资料授权」中填写授权依据和有效期", "iepAuthReference")
        if set(request) - {"reference", "valid_until", "allow_original", "confirmed"} or request.get("confirmed") is not True:
            raise IepIntakeError(400, "iep_authorization_confirmation_required",
                                 "请勾选「已核实本学生 IEP 资料的实际授权」", "iepAuthConfirmed")
        reference = request.get("reference")
        if not isinstance(reference, str) or not reference.strip():
            raise IepIntakeError(400, "iep_authorization_reference_required", "请填写授权依据", "iepAuthReference")
        until = _date_value(request.get("valid_until"), "iepAuthUntil", "授权有效期")
        if not _today() < until <= _today() + timedelta(days=MAX_RETENTION_DAYS):
            raise IepIntakeError(400, "invalid_retention", f"授权有效期须为未来日期且不超过 {MAX_RETENTION_DAYS} 天", "iepAuthUntil")
        allow_original = request.get("allow_original", True) is not False and wants_original
        return self.dossier.save_authorization(token, {
            "student_id": student_id, "reference": reference.strip()[:500],
            "storage_mode": "original_and_summary" if allow_original else "summary_only",
            "valid_until": until.isoformat(), "confirmed": True})

    def commit(self, token: str, student_id: str, iep: Any, *, task_id: str = "", origin: str = "simple_result") -> dict[str, Any]:
        """Persist the teacher-confirmed IEP summary; returns ids for the stable chain."""
        started = time.monotonic()
        account_id = self._account_id(token)
        if not summary_present(iep):
            self.log("iep_required_rejected", "rejected", student_id=student_id, task_id=task_id or None,
                     origin=origin, code="iep_summary_required", http_status=400)
            raise IepIntakeError(400, "iep_summary_required", REQUIRED_MESSAGE, "iepSummary")
        allowed = {"mode", "parse_id", "items", "manual_supplement", "confirmed", "document_id", "supersedes_id",
                   "document_date", "retain_until", "source_ref", "authorization"}
        if set(iep) - allowed or iep.get("mode") not in {"new", "existing"}:
            raise IepIntakeError(400, "invalid_iep_request", "IEP 摘要字段无效，请刷新后重试", "iepSummary")
        manual = _check_text(iep.get("manual_supplement", ""), MAX_MANUAL_CHARS, "iepManual", "人工补充")
        if manual:
            self.log("iep_manual_supplement", "ok", student_id=student_id, task_id=task_id or None,
                     manual_length=len(manual), origin=origin)
        if iep["mode"] == "existing":
            document_id = iep["document_id"].strip()
            status = self.student_status(token, student_id)
            allowed_ids = ({status["current"]["document_id"]} if status["current"] else set()) | {
                c["document_id"] for c in status["candidates"]}
            if document_id not in allowed_ids:
                self.log("iep_reuse_existing", "rejected", student_id=student_id, document_id=document_id,
                         code="iep_document_not_current", http_status=409)
                raise IepIntakeError(409, "iep_document_not_current",
                                     "所选 IEP 版本已不可用或不是该学生当前有效的 IEP，请刷新后重新选择", "iepExisting")
            version = next((c["version"] for c in ([status["current"]] if status["current"] else []) + status["candidates"]
                            if c["document_id"] == document_id), None)
            self.log("iep_reuse_existing", "ok", student_id=student_id, document_id=document_id, version=version,
                     task_id=task_id or None)
            reference = self._link_task(token, task_id, student_id, document_id) if task_id else None
            self.log("iep_commit", "ok", mode="existing", student_id=student_id, document_id=document_id,
                     reference_id=reference["reference_id"] if reference else None, origin=origin,
                     duration_ms=(time.monotonic() - started) * 1000)
            return {"mode": "existing", "document_id": document_id, "version": version,
                    "reference_id": reference["reference_id"] if reference else "", "item_count": 0,
                    "manual_supplement": manual, "original_saved": None, "created": False}
        if iep.get("parse_id") and iep.get("confirmed") is not True:
            raise IepIntakeError(400, "iep_summary_unconfirmed", "请先点击「确认摘要」再保存", "iepConfirm")
        try:
            kept, summary, deleted, edited = self._validated_items(account_id, iep)
        except IepIntakeError as exc:
            self.log("iep_summary_confirm", "rejected", student_id=student_id, parse_id=iep.get("parse_id") or None,
                     code=exc.code, http_status=exc.status)
            raise
        if not kept and not manual:
            self.log("iep_required_rejected", "rejected", student_id=student_id, task_id=task_id or None,
                     origin=origin, code="iep_summary_required", http_status=400)
            raise IepIntakeError(400, "iep_summary_required", REQUIRED_MESSAGE, "iepSummary")
        parse_id = iep.get("parse_id") or ""
        self.log("iep_summary_confirm", "ok", student_id=student_id, parse_id=parse_id or None,
                 item_count=len(kept) + deleted, kept_count=len(kept), deleted_count=deleted, edited_count=edited,
                 manual_length=len(manual))
        text_fields = summary_text_fields(kept, manual)
        # Idempotent retry: the same confirmed file for the same student is one dossier version.
        if parse_id:
            with self.records._connect() as db:
                previous = db.execute("""SELECT document_id FROM demo2_iep_intakes
                    WHERE owner_account_id=? AND student_id=? AND parse_id=?""", (account_id, student_id, parse_id)).fetchone()
            if previous is not None:
                state = self.student_status(token, student_id)
                live = {c["document_id"] for c in state["candidates"]} | (
                    {state["current"]["document_id"]} if state["current"] else set())
                if previous[0] in live:
                    reference = self._link_task(token, task_id, student_id, previous[0]) if task_id else None
                    self.log("iep_commit", "reused", mode="new", student_id=student_id, document_id=previous[0],
                             reference_id=reference["reference_id"] if reference else None, origin=origin)
                    return {"mode": "new", "document_id": previous[0], "version": None,
                            "reference_id": reference["reference_id"] if reference else "", "item_count": len(kept),
                            "manual_supplement": manual, "original_saved": None, "created": False}
        auth = self._authorization(token, student_id, iep, wants_original=bool(parse_id))
        today = _today()
        document_date = _date_value(iep.get("document_date") or today.isoformat(), "iepDocumentDate", "资料日期")
        if document_date > today:
            raise IepIntakeError(400, "invalid_document_date", "资料日期不能晚于今天", "iepDocumentDate")
        retain_until = _date_value(iep.get("retain_until") or auth["valid_until"], "iepRetainUntil", "资料保存至")
        if retain_until > date.fromisoformat(auth["valid_until"]):
            retain_until = date.fromisoformat(auth["valid_until"])
        source_ref = iep.get("source_ref") or (DEFAULT_SOURCE_REF if parse_id else MANUAL_SOURCE_REF)
        source_ref = _check_text(source_ref, 200, "iepSourceRef", "资料来源") or DEFAULT_SOURCE_REF
        supersedes_id = iep.get("supersedes_id") or ""
        if supersedes_id and (not isinstance(supersedes_id, str) or not _ID.fullmatch(supersedes_id)):
            raise IepIntakeError(400, "invalid_iep_field", "要替换的 IEP 版本编号无效", "iepExisting")
        original = None
        original_reason = "no_file"
        if parse_id and auth["storage_mode"] == "original_and_summary":
            try:
                file_type, data = self.documents.read_original(account_id, parse_id)
            except DocumentError as exc:
                raise IepIntakeError(exc.status, exc.code, exc.message, "iepFile") from None
            if len(data) > MAX_FILE_BYTES:
                original_reason = "original_too_large"
            else:
                mime = {"pdf": "application/pdf", "doc": "application/msword",
                        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}[file_type]
                original = (data, f"IEP-{document_date.isoformat()}.{file_type}", mime)
                original_reason = "saved"
        elif parse_id:
            original_reason = "summary_only_authorization"
        intake_meta = {"items": [{k: item[k] for k in ("item_id", "category", "category_label", "text", "page", "edited")}
                                 for item in kept],
                       "manual_supplement": manual, "file_type": summary["file_type"] if summary else "",
                       "page_count": summary["page_count"] if summary else 0,
                       "excluded_sensitive_count": summary["excluded_sensitive_count"] if summary else 0,
                       "confirmed_at": datetime.now().astimezone().isoformat(timespec="seconds"), "origin": origin}
        try:
            document = self.dossier.create_iep_intake_document(token, {
                "student_id": student_id, "authorization_id": auth["authorization_id"], "document_type": "iep",
                "document_date": document_date.isoformat(), "source_ref": source_ref,
                "retain_until": retain_until.isoformat(), "summary": text_fields, "filename": "", "content_base64": "",
                "supersedes_id": supersedes_id}, original=original, intake=intake_meta)
        except DossierError as exc:
            self.log("iep_document_create", "rejected", student_id=student_id, parse_id=parse_id or None,
                     code=exc.code, http_status=exc.status)
            raise
        if parse_id:
            with self.records._connect() as db:
                db.execute("INSERT OR REPLACE INTO demo2_iep_intakes VALUES (?,?,?,?,?,?)",
                           ("iin-" + secrets.token_hex(12), account_id, student_id, parse_id, document["document_id"],
                            datetime.now().astimezone().isoformat(timespec="seconds")))
        self.log("iep_document_create", "created", student_id=student_id, document_id=document["document_id"],
                 supersedes_id=supersedes_id or None, version=document["version"], parse_id=parse_id or None,
                 kept_count=len(kept), manual_length=len(manual), original_saved=original is not None,
                 reason=original_reason, storage_mode=auth["storage_mode"])
        reference = self._link_task(token, task_id, student_id, document["document_id"]) if task_id else None
        self.log("iep_commit", "ok", mode="new", student_id=student_id, document_id=document["document_id"],
                 reference_id=reference["reference_id"] if reference else None, origin=origin,
                 duration_ms=(time.monotonic() - started) * 1000)
        return {"mode": "new", "document_id": document["document_id"], "version": document["version"],
                "reference_id": reference["reference_id"] if reference else "", "item_count": len(kept),
                "manual_supplement": manual, "original_saved": original is not None, "original_reason": original_reason,
                "created": True}
