"""Structured debug log for the teacher upload -> processing -> result flow.

Each line is one JSON object written to ``upload_debug_YYYYMMDD.jsonl``.
Only identifiers, enums, sizes, durations and stable error codes are kept;
filenames, course names, teacher names and decoder text never reach the log.
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


DEBUG_LOG_DIR_ENV = "REHAB_DEMO2_UPLOAD_DEBUG_LOG_DIR"
DEBUG_LOGGER = logging.getLogger("rehab_affect.upload_flow")

OPERATIONS = frozenset({
    "upload_start",
    "upload_rejected",
    "upload_chunk",
    "upload_complete",
    "upload_resume",
    "processing_start",
    "processing_complete",
    "processing_failed",
    "media_tools_check",
    "result_redirect",
    "result_page_open",
})
_ID_FIELDS = ("task_id", "channel_id", "account_id", "course_id")
_TOKEN_FIELDS = ("code", "upload_status", "analysis_status", "channel_status", "stage", "role",
                 "ffmpeg_source", "ffprobe_source")
_INT_FIELDS = ("byte_size", "received_bytes", "chunk_index", "chunk_bytes", "total_chunks",
               "next_chunk_index", "verified_chunks", "http_status", "progress")
_FLOAT_FIELDS = ("duration_ms",)
_LOCK = threading.Lock()


def debug_log_dir(base: str | os.PathLike[str] | None = None) -> Path:
    configured = os.getenv(DEBUG_LOG_DIR_ENV, "").strip()
    if configured:
        return Path(configured)
    if base is not None:
        return Path(os.path.abspath(base))
    return Path(os.path.abspath(Path.cwd() / ".runtime" / "logs"))


def log_dir_for_store(store: Any) -> Path:
    """Place logs beside the store's data directories (``<data>/logs``)."""
    for attribute in ("video_task_dir", "upload_dir"):
        value = getattr(store, attribute, None)
        if isinstance(value, (str, os.PathLike)) and str(value):
            return debug_log_dir(Path(value).parent / "logs")
    return debug_log_dir()


def _clean(key: str, value: Any) -> Any:
    if value is None:
        return None
    if key in _ID_FIELDS or key in _TOKEN_FIELDS:
        text = str(value)
        return text if re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", text) else "<invalid>"
    if key in _INT_FIELDS:
        return value if isinstance(value, int) and not isinstance(value, bool) else "<invalid>"
    if key in _FLOAT_FIELDS:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return round(float(value), 1)
        return "<invalid>"
    if key == "tools_available":
        return bool(value)
    return None


def upload_debug_event(store: Any, operation: str, result: str, **fields: Any) -> dict[str, Any]:
    """Write one structured line; a logging failure never blocks the upload or worker."""
    entry: dict[str, Any] = {
        "ts": datetime.now().astimezone().isoformat(timespec="milliseconds"),
        "operation": operation if operation in OPERATIONS else "<invalid>",
        "result": _clean("code", result),
    }
    for key, value in fields.items():
        cleaned = _clean(key, value)
        if cleaned is not None:
            entry[key] = cleaned
    line = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
    DEBUG_LOGGER.debug(line)
    try:
        folder = log_dir_for_store(store)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"upload_debug_{entry['ts'][:10].replace('-', '')}.jsonl"
        with _LOCK, path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except (OSError, TypeError, ValueError):
        DEBUG_LOGGER.warning("upload debug log write failed")
    return entry


def task_fields(task: Any) -> dict[str, Any]:
    """Pick the loggable identifiers and sizes from a public or raw task row."""
    if not isinstance(task, dict):
        return {}
    picked: dict[str, Any] = {}
    for key in ("task_id", "channel_id", "account_id", "course_id", "upload_status", "analysis_status",
                "byte_size", "received_bytes", "total_chunks", "next_chunk_index"):
        if task.get(key) not in (None, ""):
            picked[key] = task[key]
    return picked
