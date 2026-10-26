"""Structured debug log for teacher measurement records and composite scoring.

Each line is one JSON object written to ``measurement_debug_YYYYMMDD.jsonl``
beside the store's data directory (or ``REHAB_DEMO2_MEASUREMENT_DEBUG_LOG_DIR``).
Only stable IDs, dimension scores, counts, review flags and the scoring result
are kept; student names, criterion text and evidence text never reach the log.
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

DEBUG_LOG_DIR_ENV = "REHAB_DEMO2_MEASUREMENT_DEBUG_LOG_DIR"
DEBUG_LOGGER = logging.getLogger("rehab_affect.measurement_flow")

OPERATIONS = frozenset({
    "measurement_create",
    "measurement_update",
    "measurement_review",
    "measurement_withdraw",
    "measurement_rejected",
    "score_compute",
})
_DIMENSIONS = ("accuracy", "independence", "consistency", "transfer")
_ID_FIELDS = ("record_id", "student_id", "account_id", "task_id", "code", "rubric_version")
_INT_FIELDS = ("version", "observed", "opportunities")
_LOCK = threading.Lock()


def measurement_log_dir(store: Any) -> Path:
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


def _clean_scores(scores: Any) -> dict[str, Any]:
    source = scores if isinstance(scores, dict) else {}
    return {name: _clean_number(source.get(name)) for name in _DIMENSIONS}


def measurement_debug_event(store: Any, operation: str, result: str, **fields: Any) -> dict[str, Any]:
    """Write one structured line; a logging failure never blocks saving a record."""
    entry: dict[str, Any] = {
        "ts": datetime.now().astimezone().isoformat(timespec="milliseconds"),
        "operation": operation if operation in OPERATIONS else "<invalid>",
        "result": _clean_id(result),
    }
    for key, value in fields.items():
        if value is None and key not in {"score", "previous_reviewed"}:
            continue
        if key in _ID_FIELDS:
            entry[key] = _clean_id(value)
        elif key in _INT_FIELDS:
            entry[key] = value if isinstance(value, int) and not isinstance(value, bool) else "<invalid>"
        elif key == "scores":
            entry[key] = _clean_scores(value)
        elif key == "score":
            entry[key] = _clean_number(value)
        elif key in {"reviewed", "previous_reviewed"}:
            entry[key] = value if isinstance(value, bool) or value is None else "<invalid>"
        elif key == "evidence_status":
            entry[key] = value if value in {"证据充分", "证据不足"} else "<invalid>"
        elif key == "evidence_reasons":
            entry[key] = [str(item)[:120] for item in value] if isinstance(value, list) else []
        elif key == "formula":
            entry[key] = str(value)[:240]
    line = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
    DEBUG_LOGGER.debug(line)
    try:
        folder = measurement_log_dir(store)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"measurement_debug_{entry['ts'][:10].replace('-', '')}.jsonl"
        with _LOCK, path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except (OSError, TypeError, ValueError):
        DEBUG_LOGGER.warning("measurement debug log write failed")
    return entry


def score_formula(scores: dict[str, Any], weights: dict[str, float]) -> str:
    """Human-readable weighted formula, e.g. ``8×0.35 + 7×0.30 + ...``; empty dims show 空."""
    parts = []
    for name in _DIMENSIONS:
        value = scores.get(name) if isinstance(scores, dict) else None
        parts.append(f"{'空' if value is None else value}×{weights[name]:.2f}")
    return " + ".join(parts)
