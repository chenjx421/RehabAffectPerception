"""Structured debug log for exact-frame identity confirmation.

Each line is one JSON object written to ``identity_debug_YYYYMMDD.jsonl`` beside
the store's data directory (or ``REHAB_DEMO2_IDENTITY_DEBUG_LOG_DIR``). Only
task IDs, frame keys / positions, role categories and result codes are kept;
student names, roster text, revocation reasons and coordinates never reach the
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

DEBUG_LOG_DIR_ENV = "REHAB_DEMO2_IDENTITY_DEBUG_LOG_DIR"
DEBUG_LOGGER = logging.getLogger("rehab_affect.identity_flow")

# Server-authoritative operations plus the client-reported page actions.
OPERATIONS = frozenset({
    "identity_confirm",
    "identity_revoke",
    "identity_detect",
    "manual_box",
    "redetect",
    "frame_advance",
})
CLIENT_OPERATIONS = frozenset({"manual_box", "redetect", "identity_confirm", "frame_advance"})
ROLES = frozenset({"student", "teacher", "unknown"})
BOX_SOURCES = frozenset({"candidate", "manual", "coordinates", "track", "none"})
_ID_FIELDS = ("task_id", "frame_key", "binding_id", "account_id", "code", "box_source", "source")
_INT_FIELDS = ("frame_index", "frame_total", "candidate_count", "http_status", "next_frame_index")
_BOOL_FIELDS = ("overlap_confirmed", "available", "cached")
_LOCK = threading.Lock()


def identity_log_dir(store: Any) -> Path:
    configured = os.getenv(DEBUG_LOG_DIR_ENV, "").strip()
    if configured:
        return Path(configured)
    return log_dir_for_store(store)


def _clean_id(value: Any) -> str:
    text = str(value)
    return text if re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", text) else "<invalid>"


def identity_debug_event(store: Any, operation: str, result: str, **fields: Any) -> dict[str, Any]:
    """Write one structured line; a logging failure never blocks the identity flow."""
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
            entry[key] = value if isinstance(value, int) and not isinstance(value, bool) else "<invalid>"
        elif key in _BOOL_FIELDS:
            entry[key] = value if isinstance(value, bool) else "<invalid>"
    line = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
    DEBUG_LOGGER.debug(line)
    try:
        folder = identity_log_dir(store)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"identity_debug_{entry['ts'][:10].replace('-', '')}.jsonl"
        with _LOCK, path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except (OSError, TypeError, ValueError):
        DEBUG_LOGGER.warning("identity debug log write failed")
    return entry
