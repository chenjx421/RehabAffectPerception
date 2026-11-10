"""Structured debug log for login and registration-entry checks.

Each line is one JSON object written to ``auth_debug_YYYYMMDD.jsonl`` beside
the store's data directory (or ``REHAB_DEMO2_AUTH_DEBUG_LOG_DIR``). Lines carry
the timestamp, operation, requested login role, failure code and a short digest
of the source IP. Passwords are never passed in; usernames are reduced to a
masked hint so a mistyped password in the account box or a full phone number
never reaches disk.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import os
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from .demo2_ui_kit import BRAND_VERSION
from .demo2_upload_debug import log_dir_for_store

DEBUG_LOG_DIR_ENV = "REHAB_DEMO2_AUTH_DEBUG_LOG_DIR"
DEBUG_LOGGER = logging.getLogger("rehab_affect.auth_flow")

OPERATIONS = frozenset({"login_success", "login_failure", "register_config_check", "login_page_render"})
_ID_FIELDS = ("login_role", "account_role", "account_id", "code", "agreement_version", "page_brand_version")
_INT_FIELDS = ("http_status", "duration_ms")
_BOOL_FIELDS = ("sms_available", "payment_available", "agreement_current")
_LOCK = threading.Lock()


def auth_log_dir(store: Any) -> Path:
    configured = os.getenv(DEBUG_LOG_DIR_ENV, "").strip()
    if configured:
        return Path(configured)
    return log_dir_for_store(store)


def source_digest(address: Any) -> str:
    """Return ``<scope>:<12 hex>`` so repeated sources can be correlated without the raw IP."""
    text = str(address or "").strip()
    try:
        parsed = ipaddress.ip_address(text)
    except ValueError:
        return "unknown"
    scope = ("loopback" if parsed.is_loopback else "private" if parsed.is_private else "public")
    digest = hashlib.sha256(f"rehab-auth-source:{parsed.compressed}".encode()).hexdigest()[:12]
    return f"{scope}:{digest}"


def account_hint(username: Any) -> str:
    """Mask a typed account name; phone numbers keep only the first 3 and last 4 digits."""
    text = str(username or "").strip()
    if not text:
        return ""
    if re.fullmatch(r"\+?\d{7,20}", text):
        digits = text.lstrip("+")
        return f"{digits[:3]}****{digits[-4:]}"
    if len(text) <= 2:
        return text if re.fullmatch(r"[A-Za-z0-9_.-]+", text) else "*" * len(text)
    head = text[:2] if re.fullmatch(r"[A-Za-z0-9_.-]{2}", text[:2]) else "**"
    return f"{head}***(len={min(len(text), 999)})"


def _clean_id(value: Any) -> str:
    text = str(value)
    return text if re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", text) else "<invalid>"


def auth_debug_event(store: Any, operation: str, result: str, **fields: Any) -> dict[str, Any]:
    """Write one structured line; a logging failure never blocks the request."""
    entry: dict[str, Any] = {
        "ts": datetime.now().astimezone().isoformat(timespec="milliseconds"),
        "operation": operation if operation in OPERATIONS else "<invalid>",
        "result": _clean_id(result),
        # Server-side brand of the running code; page_brand_version (when sent)
        # is what the browser's possibly cached page reported.
        "brand_version": BRAND_VERSION,
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
        elif key == "source":
            entry[key] = source_digest(value)
        elif key == "account_hint":
            entry[key] = account_hint(value)
    line = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
    DEBUG_LOGGER.debug(line)
    try:
        folder = auth_log_dir(store)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"auth_debug_{entry['ts'][:10].replace('-', '')}.jsonl"
        with _LOCK, path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except (OSError, TypeError, ValueError):
        DEBUG_LOGGER.warning("auth debug log write failed")
    return entry
