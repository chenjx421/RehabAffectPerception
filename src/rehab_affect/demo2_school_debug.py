"""Structured debug log for school directory search, selection and review.

Each line is one JSON object in ``school_debug_YYYYMMDD.jsonl`` under the
store's ``<data>/logs`` directory (or ``REHAB_DEMO2_SCHOOL_DEBUG_LOG_DIR``).
Lines carry the timestamp, operation, region codes, result counts, duration and
result status. Search text, school names and manual entries are never written:
only the query length and whether it looked like pinyin initials.
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

DEBUG_LOG_DIR_ENV = "REHAB_DEMO2_SCHOOL_DEBUG_LOG_DIR"
DEBUG_LOGGER = logging.getLogger("rehab_affect.school_flow")

OPERATIONS = frozenset({
    "school_search", "school_regions", "school_select", "school_manual_submit",
    "school_review", "school_review_list", "directory_import",
})
_ID_FIELDS = ("account_id", "code", "province_code", "city_code", "district_code", "region_parent",
              "school_type", "selection_source", "school_code", "decision", "source_id", "review_status")
_INT_FIELDS = ("http_status", "duration_ms", "result_count", "total", "page", "query_length",
               "received", "inserted", "updated", "duplicates", "provinces", "pending_count")
_BOOL_FIELDS = ("query_initials", "context_changed", "dry_run")
_LOCK = threading.Lock()


def school_log_dir(store: Any = None) -> Path:
    configured = os.getenv(DEBUG_LOG_DIR_ENV, "").strip()
    if configured:
        return Path(configured)
    return log_dir_for_store(store)


def _clean_id(value: Any) -> str:
    text = str(value)
    return text if re.fullmatch(r"[A-Za-z0-9_.:\-一-鿿]{1,160}", text) else "<invalid>"


def school_debug_event(store: Any, operation: str, result: str, **fields: Any) -> dict[str, Any]:
    """Write one line; a logging failure never blocks the request."""
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
            entry[key] = value if isinstance(value, int) and not isinstance(value, bool) else "<invalid>"
        elif key in _BOOL_FIELDS:
            entry[key] = value if isinstance(value, bool) else "<invalid>"
    line = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
    DEBUG_LOGGER.debug(line)
    try:
        folder = school_log_dir(store)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"school_debug_{entry['ts'][:10].replace('-', '')}.jsonl"
        with _LOCK, path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except (OSError, TypeError, ValueError):
        DEBUG_LOGGER.warning("school debug log write failed")
    return entry
