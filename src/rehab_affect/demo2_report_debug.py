"""Structured debug log for classroom report snapshots.

Each line is one JSON object written to ``report_debug_YYYYMMDD.jsonl`` beside
the store's data directory (or ``REHAB_DEMO2_REPORT_DEBUG_LOG_DIR``). Only
stable IDs, version fingerprints, roles, counts and result status are kept;
report text, student names, IEP summaries and session tokens never reach the
log.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from .demo2_upload_debug import log_dir_for_store

DEBUG_LOG_DIR_ENV = "REHAB_DEMO2_REPORT_DEBUG_LOG_DIR"
DEBUG_LOGGER = logging.getLogger("rehab_affect.report_flow")

OPERATIONS = frozenset({
    "report_generate",
    "report_view",
    "report_list",
    "report_download",
    "report_stale_check",
    "report_admin_redact",
    "report_rejected",
})
ROLES = frozenset({"teacher", "company_admin", "unknown"})
_ID_FIELDS = ("report_id", "content_report_id", "task_id", "course_id", "evaluation_id",
              "account_id", "frame_revision", "version_fingerprint", "status", "code", "fmt")
_INT_FIELDS = ("character_count", "section_count", "student_count", "record_count",
               "evaluation_count", "reviewed_count", "scored_count", "pending_count",
               "removed_count", "report_count", "page")
_LIST_FIELDS = ("evaluation_ids", "evaluation_versions", "record_versions",
                "stale_reasons", "removed_fields")
_LOCK = threading.Lock()


def report_log_dir(store: Any) -> Path:
    configured = os.getenv(DEBUG_LOG_DIR_ENV, "").strip()
    if configured:
        return Path(configured)
    return log_dir_for_store(store)


def _clean_id(value: Any) -> str:
    text = str(value)
    return text if re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", text) else "<invalid>"


def _clean_int(value: Any) -> Any:
    return value if isinstance(value, int) and not isinstance(value, bool) else "<invalid>"


def report_debug_event(store: Any, operation: str, result: str, **fields: Any) -> dict[str, Any]:
    """Write one structured line; a logging failure never blocks a report."""
    entry: dict[str, Any] = {
        "ts": datetime.now().astimezone().isoformat(timespec="milliseconds"),
        "operation": operation if operation in OPERATIONS else "<invalid>",
        "result": _clean_id(result),
    }
    for key, value in fields.items():
        if value is None or value == "":
            continue
        if key == "role":
            entry[key] = value if value in ROLES else "<invalid>"
        elif key in _ID_FIELDS:
            entry[key] = _clean_id(value)
        elif key in _INT_FIELDS:
            entry[key] = _clean_int(value)
        elif key in _LIST_FIELDS:
            entry[key] = ([_clean_id(item) for item in value][:50]
                          if isinstance(value, (list, tuple)) else [])
        elif key in {"ready", "stale"}:
            entry[key] = value if isinstance(value, bool) else "<invalid>"
        elif key == "message":
            entry[key] = str(value)[:160]
    line = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
    DEBUG_LOGGER.debug(line)
    try:
        folder = report_log_dir(store)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"report_debug_{entry['ts'][:10].replace('-', '')}.jsonl"
        with _LOCK, path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except (OSError, TypeError, ValueError):
        DEBUG_LOGGER.warning("report debug log write failed")
    return entry
