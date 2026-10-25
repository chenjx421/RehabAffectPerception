"""Small, source-backed directory; entries are not tenant or teacher identities.

Integration contract:
* GET school/context adds ``directory=school_directory()``, ``details`` from a
  separate metadata table, ``selection_enabled=True`` only after the guarded
  POST is installed, and ``context_change_allowed`` from an owner roster check.
* POST school/context with selection_source calls prepare_school_selection in the
  SAME write
  transaction that reads the session owner's context and checks their roster.
  Persist only result['context'] in school_contexts; persist result['details']
  separately. Never add metadata keys to _school_context_for_account.
* Also guard payloads WITHOUT selection_source; otherwise they bypass protection.
  Map SchoolSelectionError.status/code to the existing API error envelope.
* No role, account/channel binding, roster scope, or historical task snapshot is
  changed here. A blocked school change needs a separately authorized, audited
  administrator migration, not a rewritten name or a shared directory ID.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any
import unicodedata


CONTEXT_LIMITS = {"city": 80, "district": 80, "school_name": 200}
SOURCE_URL = "https://www.shqp.gov.cn/edu/eduzwgk/lm/jy/zs/cz/20260407/1368257.html"
SOURCE_TITLE = "2026年青浦区初中学区划分一览表"
SOURCE_PUBLISHED_ON = "2026-04-07"
SOURCE_CHECKED_ON = "2026-10-16"
SPECIAL_SOURCE_URL = "https://cms.qpedu.cn/jpgjyjgylb/176182.htm"

# Names transcribed exactly from the school-name column, not expanded aliases.
# These local directory keys are NOT government school codes or tenant IDs.
_SCHOOLS = (
    ("sh-qp-dongfang", "上海市青浦区东方中学"),
    ("sh-qp-yucai", "上海市青浦区豫才中学"),
    ("sh-qp-shiyan", "上海市青浦区实验中学"),
    ("sh-qp-xujing", "上海市青浦区徐泾中学"),
)


class SchoolSelectionError(ValueError):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


def school_directory() -> dict[str, Any]:
    """Return detached public data; never fetch remotely during a user request."""
    special_school = {
        "directory_id": "sh-qp-fudu", "province": "上海市", "city": "上海市",
        "district": "青浦区", "school_name": "青浦区辅读学校", "school_type": "特殊学校",
        "street": "朱家角镇", "address": "上海市青浦区朱家角镇西井街77号",
        "address_status": "public_source", "source_status": "public_source",
        "source_url": SPECIAL_SOURCE_URL, "source_title": "青浦区教育机构一览表",
        "source_published_on": "2022-10-27", "source_checked_on": SOURCE_CHECKED_ON,
        "source_note": "2022年公开资料，学校名称与地址现状待复核；非完整特殊教育学校名录。",
    }
    return {
        "entries": [special_school, *[
            {"directory_id": key, "province": "上海市", "city": "上海市",
             "district": "青浦区", "school_name": name, "school_type": "初中",
             "street": None, "address": None, "address_status": "pending",
             "source_status": "public_source", "source_url": SOURCE_URL,
             "source_title": SOURCE_TITLE, "source_published_on": SOURCE_PUBLISHED_ON,
             "source_checked_on": SOURCE_CHECKED_ON, "source_note": "地址未收录，待补充。"}
            for key, name in _SCHOOLS
        ]],
        "coverage": {
            "kind": "limited", "complete": False, "entry_count": len(_SCHOOLS) + 1,
            "special_education_complete": False,
            "label": "仅收录青浦区辅读学校及部分初中，非全区、全国或完整特殊教育学校名录。",
            "notice": "公开资料不代表教师身份认证或学校数据访问授权；历史资料的现状待复核。",
        },
        "regions": [{"province": "上海市", "city": "上海市", "district": "青浦区"}],
    }


def _text(value: Any, field: str, limit: int) -> str:
    if not isinstance(value, str) or any(unicodedata.category(c).startswith("C") for c in value):
        raise SchoolSelectionError("invalid_school_selection", f"{field}必须为不含控制字符的文本")
    value = value.strip()
    if not value or len(value) > limit:
        raise SchoolSelectionError("invalid_school_selection", f"{field}不能为空且最多{limit}个字符")
    return value


def _context(value: Any) -> dict[str, str]:
    """Validate a stored/snapshot context without normalizing its scope identity."""
    if not isinstance(value, dict) or set(value) - set(CONTEXT_LIMITS):
        raise SchoolSelectionError("invalid_school_context", "学校信息格式无效，请刷新页面")
    context = {key: value.get(key, "") for key in CONTEXT_LIMITS}
    for key, raw in context.items():
        if not isinstance(raw, str) or len(raw) > CONTEXT_LIMITS[key] or any(
            unicodedata.category(c).startswith("C") for c in raw
        ):
            raise SchoolSelectionError("invalid_school_context", "学校信息格式无效，请联系管理员")
    return context


def normalize_school_selection(payload: Any) -> dict[str, Any]:
    """Normalize selection only, NOT authorization or permission to persist.

    directory: {selection_source: 'directory', directory_id: local key}
    other: {selection_source: 'other', province, city, district, school_name,
            street (required, max 80), address (required, max 300)}
    existing: {selection_source: 'existing', city, district, school_name}

    Client-supplied provenance/verification/tenant keys are rejected. 'existing'
    preserves the three fields byte-for-byte and must pass prepare's comparison.
    """
    if not isinstance(payload, dict):
        raise SchoolSelectionError("invalid_school_selection", "请选择学校或填写其他学校")
    mode = payload.get("selection_source")
    expected = {
        "directory": {"selection_source", "directory_id"},
        "other": {"selection_source", "province", "street", "address", *CONTEXT_LIMITS},
        "existing": {"selection_source", *CONTEXT_LIMITS},
    }
    if not isinstance(mode, str) or mode not in expected or set(payload) != expected[mode]:
        raise SchoolSelectionError("invalid_school_selection", "学校选择字段无效")
    details = {"selection_source": mode, "directory_id": None, "province": None,
               "street": None, "address": None, "address_status": "pending",
               "source_note": None,
               "source_status": "pending", "source_url": None, "source_title": None,
               "source_published_on": None, "source_checked_on": None}
    if mode == "directory":
        entry = next((row for row in school_directory()["entries"]
                      if row["directory_id"] == payload["directory_id"]), None)
        if entry is None:
            raise SchoolSelectionError("unknown_school_entry", "学校条目不存在，请重新选择")
        context = {key: entry[key] for key in CONTEXT_LIMITS}
        details.update({key: entry[key] for key in details if key in entry})
    elif mode == "other":
        context = {key: _text(payload[key], key, limit) for key, limit in CONTEXT_LIMITS.items()}
        details["province"] = _text(payload["province"], "province", 80)
        details["street"] = _text(payload["street"], "street", 80)
        details["address"] = _text(payload["address"], "address", 300)
    else:
        context = _context({key: payload[key] for key in CONTEXT_LIMITS})
        if not all(value.strip() for value in context.values()):
            raise SchoolSelectionError("invalid_school_selection", "现有学校信息不完整")
    return {"context": context, "details": details}


def prepare_school_selection(
    payload: Any, *, current_context: dict[str, str], has_existing_students: bool
) -> dict[str, Any]:
    """Pure guard. Caller supplies trusted owner state in the write transaction.

    Wire payload = normalize payload + expected_context + confirmed: true.
    Compare-and-save must be atomic, including the owner-wide roster check (not
    merely the current scope). Keep existing details when source is 'existing'.
    """
    if not isinstance(payload, dict) or payload.get("confirmed") is not True:
        raise SchoolSelectionError("school_confirmation_required", "请明确确认学校信息")
    if type(has_existing_students) is not bool:
        raise SchoolSelectionError("school_scope_unavailable", "无法核验名册归属，请稍后重试", 503)
    current = _context(current_context)
    if "expected_context" not in payload or _context(payload["expected_context"]) != current:
        raise SchoolSelectionError("school_context_changed", "学校信息已变化，请刷新后重新确认", 409)
    result = normalize_school_selection({key: value for key, value in payload.items()
                                         if key not in {"expected_context", "confirmed"}})
    changed = current != result["context"]
    if result["details"]["selection_source"] == "existing" and changed:
        raise SchoolSelectionError("school_context_changed", "现有学校信息不一致，请刷新页面", 409)
    if changed and has_existing_students:
        raise SchoolSelectionError(
            "school_migration_required", "该账号已有学生名册，更换学校需管理员迁移；现有名册和历史任务保持不变。", 409
        )
    return {**deepcopy(result), "context_changed": changed}
