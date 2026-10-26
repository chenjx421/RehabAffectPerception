"""Structured debug log for company-admin backend operations.

Each line is one JSON object written to ``admin_debug_YYYYMMDD.jsonl`` beside
the store's data directory (or ``REHAB_DEMO2_ADMIN_DEBUG_LOG_DIR``). The log
records the timestamp, operation, admin account, task/report IDs, counts and
result status. Search text, file names, report bodies, student names and
session tokens never reach the log.
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

DEBUG_LOG_DIR_ENV = "REHAB_DEMO2_ADMIN_DEBUG_LOG_DIR"
DEBUG_LOGGER = logging.getLogger("rehab_affect.admin_flow")

OPERATIONS = frozenset({
    "admin_refresh",
    "admin_task_query",
    "admin_report_view",
    "admin_report_download",
    "admin_video_view",
    "admin_video_download",
    "admin_result_download",
    "admin_analysis_guide",
    "admin_analysis_open",
    "admin_analysis_denied",
})
_ID_FIELDS = ("admin_account", "account_id", "task_id", "report_id", "course_id", "channel_id",
              "status", "code", "fmt", "asset", "role", "analysis_status", "upload_status", "filter_status")
_INT_FIELDS = ("http_status", "account_count", "channel_count", "task_total", "storage_bytes",
               "result_count", "report_count", "page", "total", "query_length", "byte_size")
_LOCK = threading.Lock()


def admin_log_dir(store: Any) -> Path:
    configured = os.getenv(DEBUG_LOG_DIR_ENV, "").strip()
    if configured:
        return Path(configured)
    return log_dir_for_store(store)


def _clean_id(value: Any) -> str:
    text = str(value)
    return text if re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", text) else "<invalid>"


def _clean_int(value: Any) -> Any:
    return value if isinstance(value, int) and not isinstance(value, bool) else "<invalid>"


def admin_debug_event(store: Any, operation: str, result: str, **fields: Any) -> dict[str, Any]:
    """Write one structured line; a logging failure never blocks the request."""
    entry: dict[str, Any] = {
        "ts": datetime.now().astimezone().isoformat(timespec="milliseconds"),
        "operation": operation if operation in OPERATIONS else "<invalid>",
        "result": _clean_id(result),
    }
    for key, value in fields.items():
        if value is None or value == "":
            continue
        if key in _ID_FIELDS:
            entry[key] = _clean_id(value)
        elif key in _INT_FIELDS:
            entry[key] = _clean_int(value)
        elif key in {"has_query", "classroom_data_read"}:
            entry[key] = value if isinstance(value, bool) else "<invalid>"
        elif key == "message":
            entry[key] = str(value)[:160]
    line = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
    DEBUG_LOGGER.debug(line)
    try:
        folder = admin_log_dir(store)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"admin_debug_{entry['ts'][:10].replace('-', '')}.jsonl"
        with _LOCK, path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except (OSError, TypeError, ValueError):
        DEBUG_LOGGER.warning("admin debug log write failed")
    return entry
