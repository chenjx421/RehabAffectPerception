"""Structured debug log for classroom dual-track evaluations.

Each line is one JSON object written to ``evaluation_debug_YYYYMMDD.jsonl``
beside the store's data directory (or ``REHAB_DEMO2_EVALUATION_DEBUG_LOG_DIR``).
Only stable IDs, template/rule versions, track scores, deltas and result status
are kept; goal text, evidence, reasons and rater names never reach the log.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from .demo2_upload_debug import log_dir_for_store

DEBUG_LOG_DIR_ENV = "REHAB_DEMO2_EVALUATION_DEBUG_LOG_DIR"
DEBUG_LOGGER = logging.getLogger("rehab_affect.evaluation_flow")

OPERATIONS = frozenset({
    "evaluation_create",
    "evaluation_save",
    "evaluation_lock",
    "evaluation_review",
    "evaluation_withdraw",
    "evaluation_rejected",
    "dual_track_compute",
})
_ID_FIELDS = ("evaluation_id", "record_id", "account_id", "task_id", "video_task_id", "course_id",
              "template_id", "subject_id", "weight_policy", "rule_version", "status", "code", "phase")
_SCORE_FIELDS = ("school_score", "enhanced_score", "evidence_delta", "weight_delta", "total_delta")
_INT_FIELDS = ("version", "scored_items", "total_items")
_LOCK = threading.Lock()


def evaluation_log_dir(store: Any) -> Path:
    configured = os.getenv(DEBUG_LOG_DIR_ENV, "").strip()
    if configured:
        return Path(configured)
    return log_dir_for_store(store)


def _clean_id(value: Any) -> str:
    text = str(value)
    return text if re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", text) else "<invalid>"


def _clean_number(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return "<invalid>"
    return value


def result_fields(result: dict[str, Any] | None) -> dict[str, Any]:
    """Pick the log-safe numbers of an ``evaluate`` result."""
    if not isinstance(result, dict):
        return {}
    school = result.get("school") or {}
    enhanced = result.get("enhanced") or {}
    comparison = result.get("comparison") or {}
    coverage = enhanced.get("coverage") or school.get("coverage") or {}
    return dict(
        rule_version=result.get("rule_version"),
        template_id=result.get("template_id"),
        status=result.get("status"),
        school_score=school.get("score_10"),
        enhanced_score=enhanced.get("score_10"),
        evidence_delta=comparison.get("evidence_delta"),
        weight_delta=comparison.get("weight_delta"),
        total_delta=comparison.get("total_delta"),
        scored_items=coverage.get("scored"),
        total_items=coverage.get("total"),
        weight_policy=(result.get("weight_policy") or {}).get("mode"),
    )


def evaluation_debug_event(store: Any, operation: str, result: str, **fields: Any) -> dict[str, Any]:
    """Write one structured line; a logging failure never blocks saving a record."""
    entry: dict[str, Any] = {
        "ts": datetime.now().astimezone().isoformat(timespec="milliseconds"),
        "operation": operation if operation in OPERATIONS else "<invalid>",
        "result": _clean_id(result),
    }
    for key, value in fields.items():
        if key in _SCORE_FIELDS:
            entry[key] = _clean_number(value)
            continue
        if value is None or value == "":
            continue
        if key in _ID_FIELDS:
            entry[key] = _clean_id(value)
        elif key in _INT_FIELDS:
            entry[key] = value if isinstance(value, int) and not isinstance(value, bool) else "<invalid>"
        elif key in {"reviewed", "locked"}:
            entry[key] = value if isinstance(value, bool) else "<invalid>"
        elif key == "locked_fields":
            entry[key] = [_clean_id(item) for item in value] if isinstance(value, (list, tuple)) else []
        elif key == "message":
            entry[key] = str(value)[:160]
    line = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
    DEBUG_LOGGER.debug(line)
    try:
        folder = evaluation_log_dir(store)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"evaluation_debug_{entry['ts'][:10].replace('-', '')}.jsonl"
        with _LOCK, path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except (OSError, TypeError, ValueError):
        DEBUG_LOGGER.warning("evaluation debug log write failed")
    return entry
