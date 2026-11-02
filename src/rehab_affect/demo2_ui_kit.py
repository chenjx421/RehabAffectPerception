"""Shared Demo2 interface kit: design tokens, components, navigation, formatting.

Every Demo2 page imports its look from here instead of copying CSS:

* ``UI_KIT_CSS`` – design tokens (``--rx-*``) plus button, card, KPI, status
  badge, form field, disclosure, empty state, toast, skeleton, step and
  navigation styles. All class names use the ``rx-`` prefix so they never
  collide with the legacy page styles that tests still assert on.
* ``UI_KIT_SCRIPT`` – a ``<script data-rx-kit>`` block exposing ``window.RxUI``
  (formatters, toast, copy) and the progressive enhancements: menu toggle,
  short-ID copy buttons, ISO time / byte rendering. It is tagged with an
  attribute so the Node harnesses that eval ``<script>`` blocks skip it.
* ``teacher_header`` / ``admin_header`` / ``header_for`` – the single top
  navigation for teacher pages and the company backend.
* ``format_bytes`` / ``format_time`` / ``relative_time`` / ``short_id_html`` /
  ``status_badge`` – server-side counterparts of the JS helpers.

Pages are still rendered (and mostly cached) at import time; nothing here keeps
per-request state. Rendering problems (unknown status code, unformattable
value) are logged as WARNING to ``rehab_affect.ui_kit`` and, when
``REHAB_DEMO2_UI_DEBUG_LOG_DIR`` is set, to ``ui_debug_YYYYMMDD.jsonl``. The log
records only the page, component, input *type* and the fallback shown – never
the value itself, so student names or document text cannot leak into it.
"""

from __future__ import annotations

import html
import json
import logging
import math
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

UI_DEBUG_LOG_DIR_ENV = "REHAB_DEMO2_UI_DEBUG_LOG_DIR"
UI_LOGGER = logging.getLogger("rehab_affect.ui_kit")
_LOG_LOCK = threading.Lock()

# The teacher home page (/demo2/home) shows the classroom-loop progress; the
# post-login landing page is chosen separately and stays unchanged.
TEACHER_HOME_URL = "/demo2/home"

# User-visible brand. Package/logger/env names (rehab_affect, REHAB_*) stay
# unchanged on purpose; only the presentation layer carries the brand.
BRAND_NAME = "WeGlow"
BRAND_FULL_NAME = "WeGlow微光系统"
BRAND_TAGLINE = "课堂学习分析"
# Bumped whenever user-visible brand assets change; written to page meta and
# auth logs so stale cached pages can be told apart from the current brand.
BRAND_VERSION = "weglow-20261031"
_TITLE_SEPARATORS = (" · ", " — ", " - ")
_LEGACY_BRAND_MARKERS = ("RehabAffect", "课堂学习分析平台", "云图智航", "学校内测平台")
_HEAD_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S)


def brand_title(page_name: str) -> str:
    """Return ``WeGlow微光系统 · <页面名>`` for any (possibly legacy) title."""
    name = str(page_name or "").strip()
    if name.startswith(BRAND_FULL_NAME):
        return name
    for separator in _TITLE_SEPARATORS:
        if separator in name:
            head, tail = name.split(separator, 1)
            if any(marker in tail for marker in _LEGACY_BRAND_MARKERS):
                name = head.strip()
                break
    if any(marker == name for marker in _LEGACY_BRAND_MARKERS):
        name = ""
    return f"{BRAND_FULL_NAME} · {name}" if name else BRAND_FULL_NAME


def brand_document_title(document_html: str) -> str:
    """Rewrite the head ``<title>`` of a standalone page into the brand format."""
    head_end = document_html.find("</head>")
    match = _HEAD_TITLE_RE.search(document_html)
    if match is None or (head_end != -1 and match.start() > head_end):
        return document_html
    branded = html.escape(brand_title(html.unescape(match.group(1))), quote=False)
    return document_html[:match.start(1)] + branded + document_html[match.end(1):]

# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------


def _input_type(value: Any) -> str:
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "bool"
    return type(value).__name__


def ui_warning(page: str, component: str, value: Any, fallback: str, reason: str = "") -> dict[str, Any]:
    """Log a degraded render. Only metadata about ``value`` is recorded."""
    entry: dict[str, Any] = {
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        "level": "WARNING",
        "page": str(page or "unknown")[:80],
        "component": str(component or "unknown")[:80],
        "input_type": _input_type(value),
        "input_length": len(value) if isinstance(value, (str, bytes)) else None,
        "fallback": str(fallback)[:80],
    }
    if reason:
        entry["reason"] = str(reason)[:120]
    UI_LOGGER.warning(json.dumps(entry, ensure_ascii=False, separators=(",", ":")))
    configured = os.getenv(UI_DEBUG_LOG_DIR_ENV, "").strip()
    if configured:
        try:
            directory = Path(configured)
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / f"ui_debug_{datetime.now():%Y%m%d}.jsonl"
            with _LOG_LOCK, path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            UI_LOGGER.debug("ui debug log directory not writable")
    return entry


# Browser-reported API failures (see ``UI_FEEDBACK_JS``). The endpoint is
# reachable without a session because 401s are exactly what it must record, so
# every field is validated against a strict shape and the process keeps a small
# rate budget. Request bodies, query strings and server messages never arrive
# here: the client only sends the path, method, status and error code.
CLIENT_ERROR_PATH = "/api/v1/demo2/ui/client-error"
CLIENT_ERROR_KINDS = frozenset({"http_error", "network_error", "timeout"})
_CLIENT_ERROR_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"})
_CLIENT_ERROR_FIELDS = frozenset({"client_ts", "page", "api_path", "method", "status", "error_code", "kind"})
_CLIENT_PATH_RE = re.compile(r"^/api/[A-Za-z0-9_./-]{1,150}$")
_CLIENT_PAGE_RE = re.compile(r"^[A-Za-z0-9_./-]{1,80}$")
_CLIENT_CODE_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
_CLIENT_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|[+-]\d{2}:\d{2})$")
_CLIENT_BUDGET = {"window_start": 0.0, "count": 0}
CLIENT_ERROR_BUDGET_PER_MINUTE = 120


class ClientErrorRejected(ValueError):
    """The reported client error did not match the allowed shape."""


def _client_budget_ok(now: float) -> bool:
    with _LOG_LOCK:
        if now - _CLIENT_BUDGET["window_start"] >= 60:
            _CLIENT_BUDGET["window_start"] = now
            _CLIENT_BUDGET["count"] = 0
        if _CLIENT_BUDGET["count"] >= CLIENT_ERROR_BUDGET_PER_MINUTE:
            return False
        _CLIENT_BUDGET["count"] += 1
        return True


def ui_client_error(payload: Any, *, now: float | None = None) -> dict[str, Any] | None:
    """Validate and log one browser-side API failure.

    Returns the logged entry, ``None`` when the per-minute budget is spent, and
    raises :class:`ClientErrorRejected` for anything outside the allowed shape
    (unknown keys, query strings, free text) so nothing identifying is stored.
    """
    if not isinstance(payload, dict) or not set(payload) <= _CLIENT_ERROR_FIELDS:
        raise ClientErrorRejected("unexpected_fields")
    api_path = payload.get("api_path")
    if not isinstance(api_path, str) or not _CLIENT_PATH_RE.match(api_path) or ".." in api_path:
        raise ClientErrorRejected("invalid_api_path")
    method = str(payload.get("method") or "GET").upper()
    if method not in _CLIENT_ERROR_METHODS:
        raise ClientErrorRejected("invalid_method")
    status = payload.get("status")
    if isinstance(status, bool) or not isinstance(status, int) or not 0 <= status <= 599:
        raise ClientErrorRejected("invalid_status")
    kind = payload.get("kind") or "http_error"
    if kind not in CLIENT_ERROR_KINDS:
        raise ClientErrorRejected("invalid_kind")
    code = payload.get("error_code") or ""
    if code and (not isinstance(code, str) or not _CLIENT_CODE_RE.match(code)):
        raise ClientErrorRejected("invalid_error_code")
    page = payload.get("page") or "unknown"
    if not isinstance(page, str) or not _CLIENT_PAGE_RE.match(page):
        raise ClientErrorRejected("invalid_page")
    client_ts = payload.get("client_ts") or ""
    if client_ts and (not isinstance(client_ts, str) or not _CLIENT_TS_RE.match(client_ts)):
        raise ClientErrorRejected("invalid_client_ts")
    if not _client_budget_ok(time.monotonic() if now is None else now):
        return None
    entry: dict[str, Any] = {
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        "level": "WARNING",
        "component": "api_error",
        "page": page,
        "api_path": api_path,
        "method": method,
        "status": status,
        "error_code": code,
        "kind": kind,
        "client_ts": client_ts,
    }
    UI_LOGGER.warning(json.dumps(entry, ensure_ascii=False, separators=(",", ":")))
    configured = os.getenv(UI_DEBUG_LOG_DIR_ENV, "").strip()
    if configured:
        try:
            directory = Path(configured)
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / f"ui_debug_{datetime.now():%Y%m%d}.jsonl"
            with _LOG_LOCK, path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            UI_LOGGER.debug("ui debug log directory not writable")
    return entry


# Back/forward button events (see ``RxNav`` in UI_KIT_JS). Same shape rules as
# the client-error channel: page *path* only (no query/hash), a fixed event and
# result vocabulary, and nothing typed into forms.
NAV_EVENT_PATH = "/api/v1/demo2/ui/nav-event"
NAV_EVENTS = frozenset({"nav_back", "nav_forward", "nav_blocked", "nav_home_fallback"})
NAV_RESULTS = frozenset({"ok", "same_page", "cancelled", "confirmed", "disabled", "redirected"})
NAV_TRIGGERS = frozenset({"button", "shortcut"})
NAV_DIRECTIONS = frozenset({"back", "forward"})
_NAV_EVENT_FIELDS = frozenset({"client_ts", "page", "event", "result", "trigger", "direction", "index", "depth"})
_NAV_PAGE_RE = re.compile(r"^/[A-Za-z0-9_./-]{0,120}$")
_NAV_BUDGET = {"window_start": 0.0, "count": 0}
NAV_EVENT_BUDGET_PER_MINUTE = 240


def _nav_budget_ok(now: float) -> bool:
    with _LOG_LOCK:
        if now - _NAV_BUDGET["window_start"] >= 60:
            _NAV_BUDGET["window_start"] = now
            _NAV_BUDGET["count"] = 0
        if _NAV_BUDGET["count"] >= NAV_EVENT_BUDGET_PER_MINUTE:
            return False
        _NAV_BUDGET["count"] += 1
        return True


def _nav_int(payload: dict[str, Any], key: str) -> int | None:
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 999:
        raise ClientErrorRejected(f"invalid_{key}")
    return value


def ui_nav_event(payload: Any, *, now: float | None = None) -> dict[str, Any] | None:
    """Validate and log one back/forward navigation event from the header buttons.

    Returns the logged entry, ``None`` when the per-minute budget is spent, and
    raises :class:`ClientErrorRejected` for unknown fields or values.
    """
    if not isinstance(payload, dict) or not set(payload) <= _NAV_EVENT_FIELDS:
        raise ClientErrorRejected("unexpected_fields")
    event = payload.get("event")
    if event not in NAV_EVENTS:
        raise ClientErrorRejected("invalid_event")
    result = payload.get("result") or "ok"
    if result not in NAV_RESULTS:
        raise ClientErrorRejected("invalid_result")
    trigger = payload.get("trigger") or "button"
    if trigger not in NAV_TRIGGERS:
        raise ClientErrorRejected("invalid_trigger")
    direction = payload.get("direction") or ("forward" if event == "nav_forward" else "back")
    if direction not in NAV_DIRECTIONS:
        raise ClientErrorRejected("invalid_direction")
    page = payload.get("page")
    if not isinstance(page, str) or not _NAV_PAGE_RE.match(page) or ".." in page:
        raise ClientErrorRejected("invalid_page")
    client_ts = payload.get("client_ts") or ""
    if client_ts and (not isinstance(client_ts, str) or not _CLIENT_TS_RE.match(client_ts)):
        raise ClientErrorRejected("invalid_client_ts")
    index = _nav_int(payload, "index")
    depth = _nav_int(payload, "depth")
    if not _nav_budget_ok(time.monotonic() if now is None else now):
        return None
    entry: dict[str, Any] = {
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        "level": "INFO",
        "component": "page_nav",
        "operation": event,
        "result": result,
        "trigger": trigger,
        "direction": direction,
        "page": page,
        "index": index,
        "depth": depth,
        "client_ts": client_ts,
    }
    UI_LOGGER.info(json.dumps(entry, ensure_ascii=False, separators=(",", ":")))
    configured = os.getenv(UI_DEBUG_LOG_DIR_ENV, "").strip()
    if configured:
        try:
            directory = Path(configured)
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / f"ui_debug_{datetime.now():%Y%m%d}.jsonl"
            with _LOG_LOCK, path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            UI_LOGGER.debug("ui debug log directory not writable")
    return entry


# --------------------------------------------------------------------------
# Status vocabulary
# --------------------------------------------------------------------------

# One Chinese name per lifecycle state; the many backend codes fold into them.
STATUS_LABELS: dict[str, tuple[str, str]] = {
    "uploading": ("上传中", "info"),
    "queued": ("排队中", "neutral"),
    "pending": ("排队中", "neutral"),
    "uploaded_pending_worker": ("排队中", "neutral"),
    "waiting": ("排队中", "neutral"),
    "processing": ("分析中", "info"),
    "analyzing": ("分析中", "info"),
    "running": ("分析中", "info"),
    "evidence_ready": ("证据已就绪", "success"),
    "ready": ("证据已就绪", "success"),
    "needs_review": ("待复核", "warning"),
    "pending_review": ("待复核", "warning"),
    "draft": ("待复核", "warning"),
    "reviewed": ("已复核", "success"),
    "confirmed": ("已复核", "success"),
    "failed": ("失败", "danger"),
    "error": ("失败", "danger"),
    "processing_failed": ("失败", "danger"),
    "stale": ("已过期", "muted"),
    "expired": ("已过期", "muted"),
    "report_stale": ("已过期", "muted"),
    "completed": ("已完成", "success"),
    "cancelled": ("已取消", "muted"),
    "canceled": ("已取消", "muted"),
    "active": ("启用", "success"),
    "paused": ("已暂停", "warning"),
}
CANONICAL_STATUS_NAMES = ("上传中", "排队中", "分析中", "证据已就绪", "待复核", "已复核", "失败", "已过期")
UNKNOWN_STATUS_LABEL = "未知状态"


def status_label(code: Any, *, page: str = "unknown") -> tuple[str, str]:
    key = str(code or "").strip().lower()
    if key in STATUS_LABELS:
        return STATUS_LABELS[key]
    ui_warning(page, "status_badge", code, UNKNOWN_STATUS_LABEL, "unknown_status_code")
    return UNKNOWN_STATUS_LABEL, "neutral"


def status_badge(code: Any, *, page: str = "unknown") -> str:
    label, tone = status_label(code, page=page)
    return f'<span class="rx-badge rx-badge-{tone}" data-rx-status-code="{_attr(code)}">{_text(label)}</span>'


# --------------------------------------------------------------------------
# Formatting
# --------------------------------------------------------------------------

_BYTE_UNITS = ("B", "KB", "MB", "GB", "TB")


def format_bytes(value: Any, *, page: str = "unknown") -> str:
    try:
        number = float(value)
        if isinstance(value, bool) or not math.isfinite(number) or number < 0:
            raise ValueError("not a non-negative finite number")
    except (TypeError, ValueError) as exc:
        ui_warning(page, "format_bytes", value, "—", type(exc).__name__)
        return "—"
    unit = 0
    while number >= 1024 and unit < len(_BYTE_UNITS) - 1:
        number /= 1024
        unit += 1
    if unit == 0:
        return f"{int(number)} B"
    return f"{number:.2f} {_BYTE_UNITS[unit]}" if unit >= 3 else f"{number:.1f} {_BYTE_UNITS[unit]}"


def _parse_time(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        parsed = datetime.fromtimestamp(float(value), tz=timezone.utc)
    elif isinstance(value, str) and value.strip():
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
    else:
        raise ValueError("empty or unsupported time value")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone()


def format_time(value: Any, *, page: str = "unknown") -> str:
    try:
        return _parse_time(value).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError, OverflowError, OSError) as exc:
        ui_warning(page, "format_time", value, "时间未返回", type(exc).__name__)
        return "时间未返回"


def relative_time(value: Any, *, now: datetime | None = None, page: str = "unknown") -> str:
    try:
        moment = _parse_time(value)
    except (TypeError, ValueError, OverflowError, OSError) as exc:
        ui_warning(page, "relative_time", value, "时间未返回", type(exc).__name__)
        return "时间未返回"
    current = (now or datetime.now(timezone.utc)).astimezone()
    seconds = int((current - moment).total_seconds())
    future = seconds < 0
    seconds = abs(seconds)
    if seconds < 45:
        return "刚刚"
    for size, unit in ((86400 * 365, "年"), (86400 * 30, "个月"), (86400, "天"), (3600, "小时"), (60, "分钟")):
        if seconds >= size:
            amount = max(1, round(seconds / size))
            return f"{amount} {unit}后" if future else f"{amount} {unit}前"
    return "刚刚"


def short_id(value: Any) -> str:
    text = str(value or "")
    body = re.sub(r"^[A-Za-z]{1,16}[-_](?=[0-9A-Fa-f])", "", text)
    return (body or text)[:8]


def short_id_html(value: Any, *, label: str = "编号", page: str = "unknown") -> str:
    text = str(value or "").strip()
    if not text:
        ui_warning(page, "short_id", value, "未返回", "empty_identifier")
        return '<span class="rx-id rx-id-empty">未返回</span>'
    return (
        f'<span class="rx-id" data-rx-full="{_attr(text)}" title="{_attr(text)}">'
        f'<code class="rx-id-code">{_text(short_id(text))}</code>'
        f'<button class="rx-copy" type="button" data-rx-copy="{_attr(text)}" '
        f'aria-label="复制完整{_attr(label)}">复制完整编号</button></span>'
    )


# --------------------------------------------------------------------------
# Components
# --------------------------------------------------------------------------


def _text(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=False)


def _attr(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _id_attr(element_id: str | None) -> str:
    return f' id="{_attr(element_id)}"' if element_id else ""


ICONS: dict[str, str] = {
    "menu": '<path d="M4 6h16M4 12h16M4 18h16"/>',
    "close": '<path d="M6 6l12 12M18 6 6 18"/>',
    "logout": '<path d="M10 17l5-5-5-5M15 12H3"/><path d="M14 3h5a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-5"/>',
    "inbox": '<path d="M3 13h5l2 3h4l2-3h5"/><path d="M5 5h14l2 8v6H3v-6Z"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.5"/>',
    "check": '<path d="m5 12 4 4 10-10"/>',
    "alert": '<path d="M12 4 2.8 20h18.4Z"/><path d="M12 10v4M12 17v.5"/>',
    "upload": '<path d="M12 16V4M7 9l5-5 5 5M4 20h16"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    "settings": '<path d="M21 4h-7M10 4H3M21 12h-9M8 12H3M21 20h-5M12 20H3M14 2v4M8 10v4M16 18v4"/>',
    "book": ('<path d="M3 5.5A2.5 2.5 0 0 1 5.5 3H10a2 2 0 0 1 2 2v16a3 3 0 0 0-3-3H3Z"/>'
             '<path d="M21 5.5A2.5 2.5 0 0 0 18.5 3H14a2 2 0 0 0-2 2v16a3 3 0 0 1 3-3h6Z"/>'
             '<path d="m16 9 1.4 1.4L20 7.8"/>'),
    "back": '<path d="M19 12H5M11 18l-6-6 6-6"/>',
    "forward": '<path d="M5 12h14M13 6l6 6-6 6"/>',
    "glow": ('<circle cx="12" cy="12" r="3.4" fill="currentColor" fill-opacity=".28"/>'
             '<path d="M12 2.8v2.6M12 18.6v2.6M2.8 12h2.6M18.6 12h2.6"/>'
             '<path d="m5.6 5.6 1.8 1.8M16.6 16.6l1.8 1.8M5.6 18.4l1.8-1.8M16.6 7.4l1.8-1.8"/>'),
}


def icon(name: str, *, css_class: str = "rx-icon") -> str:
    body = ICONS.get(name)
    if body is None:
        ui_warning("ui_kit", "icon", name, "info", "unknown_icon")
        body = ICONS["info"]
    return (f'<svg class="{css_class}" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            f'stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">{body}</svg>')


_BUTTON_VARIANTS = {"primary", "secondary", "danger", "text"}


def button(label: str, *, variant: str = "primary", element_id: str | None = None, href: str | None = None,
           disabled: bool = False, loading: bool = False, aria_label: str | None = None,
           icon_name: str | None = None, button_type: str = "button", page: str = "unknown") -> str:
    if variant not in _BUTTON_VARIANTS:
        ui_warning(page, "button", variant, "secondary", "unknown_variant")
        variant = "secondary"
    classes = f"rx-btn rx-btn-{variant}" + (" is-loading" if loading else "")
    inner = (icon(icon_name) if icon_name else "") + f"<span>{_text(label)}</span>"
    aria = f' aria-label="{_attr(aria_label)}"' if aria_label else ""
    busy = ' aria-busy="true"' if loading else ""
    if href and not disabled:
        return f'<a class="{classes}" href="{_attr(href)}"{_id_attr(element_id)}{aria}>{inner}</a>'
    state = " disabled" if disabled or loading else ""
    return f'<button class="{classes}" type="{_attr(button_type)}"{_id_attr(element_id)}{aria}{busy}{state}>{inner}</button>'


def card(body: str, *, title: str | None = None, subtitle: str | None = None, actions: str = "",
         element_id: str | None = None) -> str:
    head = ""
    if title or actions:
        head = (f'<div class="rx-card-head"><div><h2 class="rx-card-title">{_text(title or "")}</h2>'
                + (f'<p class="rx-card-sub">{_text(subtitle)}</p>' if subtitle else "")
                + f'</div>{actions}</div>')
    return f'<section class="rx-card"{_id_attr(element_id)}>{head}<div class="rx-card-body">{body}</div></section>'


def kpi(label: str, value: Any, *, hint: str = "", value_id: str | None = None, tone: str = "",
        delta_id: str | None = None) -> str:
    """KPI tile; ``delta_id`` adds a slot pages fill with 「较上次刷新」 changes."""
    tone_class = f" rx-kpi-{tone}" if tone in {"success", "warning", "danger", "info"} else ""
    delta = (f'<small class="rx-kpi-delta"{_id_attr(delta_id)} aria-live="polite"></small>' if delta_id else "")
    return (f'<article class="rx-kpi{tone_class}"><span class="rx-kpi-label">{_text(label)}</span>'
            f'<strong class="rx-kpi-value"{_id_attr(value_id)}>{_text(value)}</strong>'
            + (f'<small class="rx-kpi-hint">{_text(hint)}</small>' if hint else "") + delta + "</article>")


def kpi_group(title: str, tiles: Sequence[str], *, description: str = "", element_id: str | None = None) -> str:
    """A titled set of KPI tiles, e.g. 「资料数量」「授权状态」「存储与清理」."""
    desc = f'<p class="rx-kpi-group-desc">{_text(description)}</p>' if description else ""
    return (f'<section class="rx-kpi-group"{_id_attr(element_id)}><div class="rx-kpi-group-head">'
            f'<h3 class="rx-kpi-group-title">{_text(title)}</h3>{desc}</div>'
            f'<div class="rx-kpi-grid">{"".join(tiles)}</div></section>')


def drawer(body: str, *, title: str, element_id: str, title_id: str, subtitle: str = "", close_id: str = "") -> str:
    """Right-side drawer shell; pages toggle ``hidden`` and own the form inside."""
    close = (f'<button class="rx-btn rx-btn-text rx-drawer-close" type="button" id="{_attr(close_id)}" aria-label="关闭">'
             f'{icon("close")}<span>关闭</span></button>' if close_id else "")
    sub = f'<p class="rx-drawer-sub">{_text(subtitle)}</p>' if subtitle else ""
    return (f'<div class="rx-drawer-backdrop" id="{_attr(element_id)}Backdrop" data-rx-drawer-backdrop="{_attr(element_id)}" hidden></div>'
            f'<aside class="rx-drawer" id="{_attr(element_id)}" role="dialog" aria-modal="false" '
            f'aria-labelledby="{_attr(title_id)}" hidden><div class="rx-drawer-head"><div>'
            f'<h2 class="rx-drawer-title" id="{_attr(title_id)}" tabindex="-1">{_text(title)}</h2>{sub}</div>{close}</div>'
            f'<div class="rx-drawer-body">{body}</div></aside>')


def form_field(name: str, label: str, control: str, *, required: bool = False, help_text: str = "",
               field_id: str | None = None) -> str:
    """Wrap a control with label, required star, helper text and an error slot.

    ``control`` is the caller's ``<input>``/``<select>``/``<textarea>`` so
    existing ``id`` and ``name`` attributes stay exactly as tests expect.
    """
    target = field_id or name
    star = '<span class="rx-required" aria-hidden="true">*</span><span class="rx-sr">（必填）</span>' if required else ""
    help_html = f'<small class="rx-help" id="{_attr(target)}Help">{_text(help_text)}</small>' if help_text else ""
    return (f'<div class="rx-field" data-rx-field="{_attr(name)}"><label class="rx-label" for="{_attr(target)}">'
            f'{_text(label)}{star}</label>{control}{help_html}'
            f'<p class="rx-error" id="{_attr(target)}Error" role="alert" hidden></p></div>')


def disclosure(title: str, items: Sequence[str] | str, *, open_: bool = False, element_id: str | None = None) -> str:
    """Collapsible 「使用边界与说明」 block; the title stays visible when closed."""
    if isinstance(items, str):
        content = f"<p>{_text(items)}</p>"
    else:
        content = "<ul>" + "".join(f"<li>{_text(item)}</li>" for item in items) + "</ul>"
    return (f'<details class="rx-disclosure"{_id_attr(element_id)}{" open" if open_ else ""}>'
            f'<summary>{icon("info")}<span>{_text(title)}</span></summary><div class="rx-disclosure-body">{content}</div></details>')


def empty_state(reason: str, *, action_label: str = "", action_href: str = "", icon_name: str = "inbox",
                element_id: str | None = None, compact: bool = False) -> str:
    action = button(action_label, variant="primary", href=action_href) if action_label and action_href else ""
    compact_class = " rx-empty-compact" if compact else ""
    return (f'<div class="rx-empty{compact_class}"{_id_attr(element_id)}>{icon(icon_name, css_class="rx-empty-icon")}'
            f'<p>{_text(reason)}</p>{action}</div>')


def skeleton(lines: int = 3) -> str:
    count = max(1, min(int(lines), 12))
    return ('<div class="rx-skeleton" aria-hidden="true">'
            + "".join('<span class="rx-skeleton-line"></span>' for _ in range(count)) + "</div>"
            + '<span class="rx-sr" role="status">正在加载</span>')


def steps(labels: Sequence[str], current: int = 0, *, aria_label: str = "操作步骤",
          element_id: str | None = None) -> str:
    """Numbered step bar. Pages move it with ``RxUI.setStep(element_id, index)``."""
    items = []
    for index, label in enumerate(labels):
        state = "done" if index < current else "current" if index == current else "todo"
        aria = ' aria-current="step"' if state == "current" else ""
        items.append(f'<li class="rx-step rx-step-{state}" data-rx-step="{index}"{aria}><b>{index + 1}</b>'
                     f'<span>{_text(label)}</span></li>')
    return f'<ol class="rx-steps"{_id_attr(element_id)} aria-label="{_attr(aria_label)}">{"".join(items)}</ol>'


def hint(text: str, *, element_id: str, label: str = "") -> str:
    """「？」 toggle that reveals a field's helper text on demand.

    The bubble keeps ``element_id`` so existing ``aria-describedby`` links and
    scripts that rewrite the helper text keep working. It is rendered in the
    normal flow (not absolutely positioned) so it never widens narrow screens.
    """
    name = label or "本项"
    return (f'<button class="rx-hint-toggle" type="button" aria-expanded="false" aria-controls="{_attr(element_id)}" '
            f'aria-label="查看{_attr(name)}说明" title="查看说明">?</button>'
            f'<small class="rx-hint-bubble" id="{_attr(element_id)}" hidden>{_text(text)}</small>')


def toast_region() -> str:
    return '<div class="rx-toast-region" id="rxToastRegion" role="status" aria-live="polite" aria-atomic="true"></div>'


# --------------------------------------------------------------------------
# Navigation
# --------------------------------------------------------------------------

TEACHER_NAV: tuple[tuple[str, str, str, str], ...] = (
    ("home", "首页", TEACHER_HOME_URL, "rxNavHome"),
    ("upload", "上传任务", "/demo2/upload", "rxNavUpload"),
    ("students", "学生名册", "/demo2/students", "studentRosterLink"),
    ("measurement", "学生测量", "/demo2/measurement", "rxNavMeasurement"),
    ("evaluation", "评课", "/demo2/evaluation", "rxNavEvaluation"),
    ("capture", "课堂录制", "/demo2/capture", "rxNavCapture"),
    ("school", "学校信息", "/demo2/school", "rxNavSchool"),
    ("membership", "会员中心", "/demo2/membership", "membershipLink"),
    ("help", "使用帮助", "/demo2/help", "rxNavHelp"),
)

ADMIN_NAV: tuple[tuple[str, str, str, str], ...] = (
    ("overview", "总览", "/demo2/admin", "rxNavAdminOverview"),
    ("tasks", "任务查询", "/demo2/admin#taskQueryTitle", "rxNavAdminTasks"),
    ("channels", "上传通道", "/demo2/admin/channels", "rxNavAdminChannels"),
    ("dossiers", "学生资料运行状态", "/demo2/admin/dossiers", "rxNavAdminDossiers"),
    ("measurements", "测量记录汇总", "/demo2/admin/measurements", "rxNavAdminMeasurements"),
    ("membership", "会员与订单", "/demo2/admin#membershipSummaryTitle", "rxNavAdminMembership"),
)

MEMBER_NAV: tuple[tuple[str, str, str, str], ...] = (
    ("membership", "会员中心", "/demo2/membership", "membershipLink"),
    ("help", "使用帮助", "/demo2/help", "rxNavHelp"),
)


def account_field(account: Any, key: str) -> Any:
    if account is None:
        return None
    if isinstance(account, dict):
        return account.get(key)
    return getattr(account, key, None)


def account_role(account: Any) -> str:
    return str(account_field(account, "role") or "")


def account_label(account: Any) -> str:
    for key in ("login_alias", "username"):
        value = account_field(account, key)
        if value:
            return str(value)
    return ""


def _nav_links(items: Iterable[tuple[str, str, str, str]], active: str, page: str) -> str:
    entries = list(items)
    if active and active not in {key for key, *_ in entries}:
        ui_warning(page, "nav", active, "no_active_item", "unknown_nav_key")
    links = []
    for key, label, href, element_id in entries:
        current = ' aria-current="page"' if key == active else ""
        links.append(f'<a class="rx-nav-link" href="{_attr(href)}" id="{_attr(element_id)}" data-rx-nav-key="{_attr(key)}"{current}>{_text(label)}</a>')
    return "".join(links)


def _header(*, scope: str, nav_label: str, items: Iterable[tuple[str, str, str, str]], active: str,
            brand_href: str, brand_sub: str, account: Any, account_caption: str, account_id: str,
            logout_id: str, logout_bound: bool, extra_actions: str, page: str, brand_id: str = "") -> str:
    label = account_label(account)
    logout_hook = "" if logout_bound else " data-rx-logout"
    fetch_hook = "" if label else ' data-rx-fetch-account'
    return f"""<header class="rx-header" data-rx-scope="{scope}" data-rx-page="{_attr(page)}"{fetch_hook}>
  <div class="rx-header-inner">
    <a class="rx-brand" href="{_attr(brand_href)}"{_id_attr(brand_id)} aria-label="{BRAND_FULL_NAME} {_attr(brand_sub)}首页" data-brand-version="{BRAND_VERSION}">{icon("glow", css_class="rx-brand-icon")}<span class="rx-brand-copy"><strong>{BRAND_NAME}<em>微光系统</em></strong><span>{_text(brand_sub)}</span></span></a>
    {history_buttons(brand_href)}
    <button class="rx-nav-toggle" type="button" aria-expanded="false" aria-controls="rxNavPanel" aria-label="打开导航菜单">{icon("menu")}<span>菜单</span></button>
    <div class="rx-nav-panel" id="rxNavPanel">
      <nav class="rx-nav" aria-label="{_attr(nav_label)}">{_nav_links(items, active, page)}</nav>
      <div class="rx-header-actions">{extra_actions}<span class="rx-account"><span>{_text(account_caption)}</span><strong id="{_attr(account_id)}" data-rx-account>{_text(label or "读取中")}</strong></span><button class="rx-btn rx-btn-text rx-logout" id="{_attr(logout_id)}" type="button" aria-label="退出登录"{logout_hook}>{icon("logout")}<span>退出</span></button></div>
    </div>
  </div>
</header>"""


ROLE_HOME_URLS: dict[str, str] = {
    "teacher": TEACHER_HOME_URL, "admin": "/demo2/admin", "member": "/demo2/membership", "public": "/demo2/login",
}


def history_buttons(home_url: str = TEACHER_HOME_URL) -> str:
    """Back/forward pair placed next to the brand; ``RxNav`` in UI_KIT_JS drives it.

    ``home_url`` is where 后退 lands when this tab has no in-site history
    (page opened from a bookmark or another site).
    """
    return (f'<div class="rx-history" role="group" aria-label="页面前进后退" data-rx-history data-rx-home="{_attr(home_url)}">'
            f'<button class="rx-history-btn" id="rxNavBack" type="button" data-rx-nav="back" aria-label="后退到上一页" '
            f'title="后退到上一页（Alt+←）" aria-keyshortcuts="Alt+ArrowLeft">{icon("back")}<span>后退</span></button>'
            f'<button class="rx-history-btn" id="rxNavForward" type="button" data-rx-nav="forward" aria-label="前进到下一页" '
            f'title="前进到下一页（Alt+→）" aria-keyshortcuts="Alt+ArrowRight">{icon("forward")}<span>前进</span></button>'
            f'</div>')


def teacher_header(active: str, account: Any = None, *, account_id: str = "accountName", brand_id: str = "",
                   brand_sub: str = "教师工作台",
                   logout_id: str = "logoutButton", logout_bound: bool = True, extra_actions: str = "",
                   page: str = "") -> str:
    return _header(scope="teacher", nav_label="教师工作台导航", items=TEACHER_NAV, active=active,
                   brand_href=TEACHER_HOME_URL, brand_sub=brand_sub, account=account,
                   account_caption="登录账号", account_id=account_id, logout_id=logout_id,
                   logout_bound=logout_bound, extra_actions=extra_actions, page=page or active,
                   brand_id=brand_id)


def admin_header(active: str, account: Any = None, *, account_id: str = "accountName", brand_id: str = "",
                 logout_id: str = "logoutButton", logout_bound: bool = True, extra_actions: str = "",
                 page: str = "") -> str:
    return _header(scope="admin", nav_label="公司后台导航", items=ADMIN_NAV, active=active,
                   brand_href="/demo2/admin", brand_sub="公司内测管理后台", account=account,
                   account_caption="公司账号", account_id=account_id, logout_id=logout_id,
                   logout_bound=logout_bound, extra_actions=extra_actions, page=page or active,
                   brand_id=brand_id)


def member_header(active: str, account: Any = None, *, account_id: str = "accountName", brand_id: str = "",
                  logout_id: str = "logoutButton", logout_bound: bool = True, extra_actions: str = "",
                  page: str = "") -> str:
    return _header(scope="member", nav_label="会员导航", items=MEMBER_NAV, active=active,
                   brand_href="/demo2/membership", brand_sub=BRAND_TAGLINE, account=account,
                   account_caption="登录账号", account_id=account_id, logout_id=logout_id,
                   logout_bound=logout_bound, extra_actions=extra_actions, page=page or active,
                   brand_id=brand_id)


def header_for(account: Any, teacher_active: str, *, admin_active: str = "", **kwargs: Any) -> str:
    """Pick the navigation by role so shared pages never show a foreign nav."""
    role = account_role(account)
    if role == "company_admin":
        return admin_header(admin_active, account, page=kwargs.pop("page", "") or teacher_active, **kwargs)
    if role == "registered_member":
        return member_header(teacher_active if teacher_active in {"membership", "help"} else "", account,
                             page=kwargs.pop("page", "") or teacher_active, **kwargs)
    return teacher_header(teacher_active, account, **kwargs)


# --------------------------------------------------------------------------
# CSS
# --------------------------------------------------------------------------

TOKENS_CSS = r"""
:root {
  --rx-primary:#1f5fbf; --rx-primary-hover:#174a96; --rx-primary-soft:#eaf2fd; --rx-primary-pale:#f6f9fe;
  --rx-primary-deep:#123f86; --rx-glow:#4fc3f7; --rx-glow-soft:rgba(79,195,247,.22);
  --rx-ink:#172b4d; --rx-text:#26364a; --rx-muted:#56657a; --rx-line:#d3deea; --rx-line-strong:#a9bfd8;
  --rx-surface:#ffffff; --rx-canvas:#f4f7fb;
  --rx-success:#146c4b; --rx-success-soft:#e8f6ef; --rx-warning:#8a4b06; --rx-warning-soft:#fff5e3;
  --rx-danger:#b42318; --rx-danger-soft:#fdeeec; --rx-neutral:#4d5b6d; --rx-neutral-soft:#eef2f6;
  --rx-focus:#1f5fbf;
  --rx-fs-12:12px; --rx-fs-14:14px; --rx-fs-16:16px; --rx-fs-20:20px; --rx-fs-24:24px; --rx-fs-32:32px;
  --rx-sp-4:4px; --rx-sp-8:8px; --rx-sp-12:12px; --rx-sp-16:16px; --rx-sp-24:24px; --rx-sp-32:32px;
  --rx-radius-sm:4px; --rx-radius:6px; --rx-radius-lg:8px;
  --rx-shadow-sm:0 1px 2px rgba(23,43,77,.06); --rx-shadow:0 8px 24px rgba(23,43,77,.08);
  --rx-header-h:64px;
}
"""

COMPONENT_CSS = r"""
.rx-sr { position:absolute; width:1px; height:1px; padding:0; margin:-1px; overflow:hidden; clip:rect(0,0,0,0); white-space:nowrap; border:0; }
.rx-icon { width:18px; height:18px; flex:none; display:inline-block; }
a:focus-visible,button:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible,summary:focus-visible,[tabindex]:focus-visible { outline:3px solid var(--rx-focus); outline-offset:2px; }
h2[id],h3[id],section[id] { scroll-margin-top:calc(var(--rx-header-h) + 16px); }
.rx-btn { display:inline-flex; align-items:center; justify-content:center; gap:var(--rx-sp-8); min-height:44px; padding:0 var(--rx-sp-16); border:1px solid transparent; border-radius:var(--rx-radius); font:inherit; font-size:var(--rx-fs-14); font-weight:700; line-height:1.2; text-decoration:none; cursor:pointer; transition:background-color .15s ease,border-color .15s ease,color .15s ease; }
.rx-btn-primary { background:var(--rx-primary); border-color:var(--rx-primary); color:#fff; }
.rx-btn-primary:hover { background:var(--rx-primary-hover); border-color:var(--rx-primary-hover); }
.rx-btn-secondary { background:#fff; border-color:var(--rx-line-strong); color:var(--rx-primary-hover); }
.rx-btn-secondary:hover { background:var(--rx-primary-pale); border-color:var(--rx-primary); }
.rx-btn-danger { background:#fff; border-color:#e3a8a1; color:var(--rx-danger); }
.rx-btn-danger:hover { background:var(--rx-danger-soft); border-color:var(--rx-danger); }
.rx-btn-text { background:transparent; color:var(--rx-primary-hover); padding:0 var(--rx-sp-8); }
.rx-btn-text:hover { background:var(--rx-primary-pale); border-color:transparent; }
.rx-btn:disabled,.rx-btn[aria-disabled="true"] { cursor:not-allowed; opacity:.55; }
.rx-btn.is-loading { position:relative; color:transparent !important; pointer-events:none; }
.rx-btn.is-loading::after { content:""; position:absolute; width:16px; height:16px; border:2px solid currentColor; border-color:var(--rx-primary) transparent var(--rx-primary) transparent; border-radius:50%; animation:rx-spin .8s linear infinite; }
.rx-btn-primary.is-loading::after { border-color:#fff transparent #fff transparent; }
@keyframes rx-spin { to { transform:rotate(360deg); } }
.rx-card { min-width:0; background:var(--rx-surface); border:1px solid var(--rx-line); border-radius:var(--rx-radius-lg); box-shadow:var(--rx-shadow-sm); }
.rx-card-head { display:flex; align-items:flex-start; justify-content:space-between; gap:var(--rx-sp-16); padding:var(--rx-sp-16) var(--rx-sp-24); border-bottom:1px solid var(--rx-line); }
.rx-card-title { margin:0; font-size:var(--rx-fs-20); line-height:1.3; color:var(--rx-ink); }
.rx-card-sub { margin:var(--rx-sp-4) 0 0; color:var(--rx-muted); font-size:var(--rx-fs-14); }
.rx-card-body { padding:var(--rx-sp-24); }
.rx-kpi { min-width:0; display:flex; flex-direction:column; gap:var(--rx-sp-4); padding:var(--rx-sp-16); background:var(--rx-surface); border:1px solid var(--rx-line); border-radius:var(--rx-radius-lg); }
.rx-kpi-label { color:var(--rx-muted); font-size:var(--rx-fs-12); }
.rx-kpi-value { color:var(--rx-ink); font-size:var(--rx-fs-24); font-weight:800; line-height:1.2; overflow-wrap:anywhere; font-variant-numeric:tabular-nums; }
.rx-kpi-hint { color:var(--rx-muted); font-size:var(--rx-fs-12); }
.rx-kpi-success .rx-kpi-value { color:var(--rx-success); } .rx-kpi-warning .rx-kpi-value { color:var(--rx-warning); } .rx-kpi-danger .rx-kpi-value { color:var(--rx-danger); } .rx-kpi-info .rx-kpi-value { color:var(--rx-primary); }
.rx-badge { display:inline-flex; align-items:center; gap:var(--rx-sp-4); min-height:24px; padding:2px var(--rx-sp-8); border:1px solid transparent; border-radius:var(--rx-radius-sm); font-size:var(--rx-fs-12); font-weight:700; line-height:1.3; white-space:nowrap; }
.rx-badge-info { background:var(--rx-primary-soft); border-color:#b9cff0; color:#174a96; }
.rx-badge-success { background:var(--rx-success-soft); border-color:#a9d8c2; color:var(--rx-success); }
.rx-badge-warning { background:var(--rx-warning-soft); border-color:#ecc98e; color:var(--rx-warning); }
.rx-badge-danger { background:var(--rx-danger-soft); border-color:#efb7b0; color:var(--rx-danger); }
.rx-badge-neutral,.rx-badge-muted { background:var(--rx-neutral-soft); border-color:#cfd7e1; color:var(--rx-neutral); }
.rx-field { display:flex; flex-direction:column; gap:6px; min-width:0; }
.rx-label { color:var(--rx-ink); font-size:var(--rx-fs-14); font-weight:700; }
.rx-required { margin-left:2px; color:var(--rx-danger); }
.rx-help { color:var(--rx-muted); font-size:var(--rx-fs-12); }
.rx-error { margin:0; color:var(--rx-danger); font-size:var(--rx-fs-12); font-weight:700; }
.rx-field.has-error input,.rx-field.has-error select,.rx-field.has-error textarea { border-color:var(--rx-danger); }
.rx-disclosure { margin:var(--rx-sp-16) 0; border:1px solid var(--rx-line); border-left:3px solid var(--rx-primary); border-radius:var(--rx-radius); background:var(--rx-primary-pale); color:var(--rx-text); }
.rx-disclosure > summary { display:flex; align-items:center; gap:var(--rx-sp-8); min-height:44px; padding:0 var(--rx-sp-16); cursor:pointer; color:var(--rx-ink); font-size:var(--rx-fs-14); font-weight:700; list-style:none; }
.rx-disclosure > summary::-webkit-details-marker { display:none; }
.rx-disclosure > summary::after { content:"展开"; margin-left:auto; color:var(--rx-primary-hover); font-size:var(--rx-fs-12); font-weight:700; }
.rx-disclosure[open] > summary::after { content:"收起"; }
.rx-disclosure-body { padding:0 var(--rx-sp-16) var(--rx-sp-12); font-size:var(--rx-fs-14); }
.rx-disclosure-body ul { margin:0; padding-left:20px; } .rx-disclosure-body li + li { margin-top:var(--rx-sp-4); }
.rx-empty { display:flex; flex-direction:column; align-items:center; gap:var(--rx-sp-12); padding:var(--rx-sp-32) var(--rx-sp-16); border:1px dashed var(--rx-line-strong); border-radius:var(--rx-radius-lg); background:var(--rx-primary-pale); color:var(--rx-muted); text-align:center; }
.rx-empty p { margin:0; color:var(--rx-text); font-size:var(--rx-fs-14); }
.rx-empty-icon { width:32px; height:32px; color:var(--rx-primary); }
.rx-empty-compact { flex-direction:row; justify-content:center; gap:var(--rx-sp-8); padding:var(--rx-sp-16); text-align:left; }
.rx-empty-compact .rx-empty-icon { width:20px; height:20px; color:var(--rx-muted); }
.rx-empty-compact p { color:var(--rx-muted); }
td > .rx-empty { margin:var(--rx-sp-4) 0; }
.rx-kpi-delta { min-height:16px; color:var(--rx-muted); font-size:var(--rx-fs-12); font-variant-numeric:tabular-nums; }
.rx-kpi-delta[data-trend="up"] { color:var(--rx-success); } .rx-kpi-delta[data-trend="down"] { color:var(--rx-warning); }
.rx-kpi-group { min-width:0; padding:var(--rx-sp-16); border:1px solid var(--rx-line); border-radius:var(--rx-radius-lg); background:var(--rx-primary-pale); }
.rx-kpi-group-head { margin-bottom:var(--rx-sp-12); }
.rx-kpi-group-title { margin:0; color:var(--rx-ink); font-size:var(--rx-fs-16); }
.rx-kpi-group-desc { margin:var(--rx-sp-4) 0 0; color:var(--rx-muted); font-size:var(--rx-fs-12); }
.rx-kpi-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); gap:var(--rx-sp-12); }
.rx-drawer-backdrop { position:fixed; inset:0; z-index:150; background:rgba(23,43,77,.32); }
.rx-drawer { position:fixed; top:0; right:0; bottom:0; z-index:160; display:flex; flex-direction:column; width:min(420px,100vw); background:#fff; border-left:1px solid var(--rx-line); box-shadow:-12px 0 32px rgba(23,43,77,.16); animation:rx-drawer-in .18s ease-out; }
.rx-drawer[hidden],.rx-drawer-backdrop[hidden] { display:none !important; }
.rx-drawer-head { display:flex; align-items:flex-start; justify-content:space-between; gap:var(--rx-sp-12); padding:var(--rx-sp-16) var(--rx-sp-24); border-bottom:1px solid var(--rx-line); }
.rx-drawer-title { margin:0; color:var(--rx-ink); font-size:var(--rx-fs-20); }
.rx-drawer-sub { margin:var(--rx-sp-4) 0 0; color:var(--rx-muted); font-size:var(--rx-fs-12); }
.rx-drawer-body { flex:1; min-height:0; overflow:auto; padding:var(--rx-sp-24); }
@keyframes rx-drawer-in { from { transform:translateX(24px); opacity:0; } to { transform:none; opacity:1; } }
.rx-toast-region { position:fixed; right:var(--rx-sp-16); bottom:var(--rx-sp-16); z-index:200; display:flex; flex-direction:column; gap:var(--rx-sp-8); max-width:min(360px,calc(100vw - 32px)); pointer-events:none; }
.rx-toast { padding:var(--rx-sp-12) var(--rx-sp-16); border-radius:var(--rx-radius); background:var(--rx-ink); color:#fff; font-size:var(--rx-fs-14); box-shadow:var(--rx-shadow); pointer-events:auto; animation:rx-toast-in .18s ease-out; }
.rx-toast-success { background:var(--rx-success); } .rx-toast-danger { background:var(--rx-danger); } .rx-toast-warning { background:var(--rx-warning); }
@keyframes rx-toast-in { from { opacity:0; transform:translateY(8px); } to { opacity:1; transform:none; } }
.rx-skeleton { display:grid; gap:var(--rx-sp-8); }
.rx-skeleton-line { display:block; height:14px; border-radius:var(--rx-radius-sm); background:linear-gradient(90deg,#e8eef5 0%,#f4f7fb 50%,#e8eef5 100%); background-size:200% 100%; animation:rx-shimmer 1.2s ease-in-out infinite; }
.rx-skeleton-line:nth-child(3n) { width:60%; } .rx-skeleton-line:nth-child(3n+2) { width:85%; }
@keyframes rx-shimmer { from { background-position:200% 0; } to { background-position:-200% 0; } }
.rx-steps { display:flex; gap:0; margin:var(--rx-sp-16) 0; padding:0; list-style:none; border:1px solid var(--rx-line); border-radius:var(--rx-radius-lg); background:#fff; overflow-x:auto; }
.rx-step { flex:1 1 0; min-width:120px; display:flex; align-items:center; gap:var(--rx-sp-8); padding:var(--rx-sp-12) var(--rx-sp-16); border-right:1px solid var(--rx-line); color:var(--rx-muted); font-size:var(--rx-fs-14); }
.rx-step:last-child { border-right:0; }
.rx-step b { display:inline-flex; align-items:center; justify-content:center; width:24px; height:24px; flex:none; border-radius:50%; background:var(--rx-neutral-soft); color:var(--rx-neutral); font-size:var(--rx-fs-12); }
.rx-step-current { background:var(--rx-primary-soft); color:var(--rx-primary-hover); font-weight:700; }
.rx-step-current b { background:var(--rx-primary); color:#fff; }
.rx-step-done b { background:var(--rx-success-soft); color:var(--rx-success); }
.rx-hint-toggle { display:inline-flex; align-items:center; justify-content:center; width:22px; height:22px; min-height:22px; margin-left:6px; padding:0; border:1px solid var(--rx-line-strong); border-radius:50%; background:#fff; color:var(--rx-primary-hover); font:700 12px/1 "Segoe UI",sans-serif; vertical-align:middle; cursor:pointer; position:relative; }
.rx-hint-toggle::before { content:""; position:absolute; inset:-11px; }
.rx-hint-toggle:hover,.rx-hint-toggle[aria-expanded="true"] { border-color:var(--rx-primary); background:var(--rx-primary-soft); }
.rx-hint-bubble { display:block; position:relative; margin-top:6px; padding:8px 12px; border:1px solid #b9cff0; border-radius:var(--rx-radius); background:var(--rx-primary-pale); color:var(--rx-text); font-size:var(--rx-fs-12); line-height:1.7; overflow-wrap:anywhere; }
.rx-hint-bubble[hidden] { display:none !important; }
.rx-hint-bubble::before { content:""; position:absolute; top:-6px; left:14px; width:10px; height:10px; border-left:1px solid #b9cff0; border-top:1px solid #b9cff0; background:var(--rx-primary-pale); transform:rotate(45deg); }
.rx-id { display:inline-flex; align-items:center; gap:var(--rx-sp-4); max-width:100%; flex-wrap:wrap; vertical-align:middle; }
.rx-id-code { padding:1px 6px; border-radius:var(--rx-radius-sm); background:var(--rx-neutral-soft); color:var(--rx-ink); font-family:"Cascadia Code",SFMono-Regular,Consolas,monospace; font-size:var(--rx-fs-12); white-space:nowrap; flex:none; }
.rx-copy { min-height:28px; padding:2px 8px; border:1px solid var(--rx-line); border-radius:var(--rx-radius-sm); background:#fff; color:var(--rx-primary-hover); font-size:var(--rx-fs-12); font-weight:700; cursor:pointer; white-space:nowrap; }
.rx-copy:hover { border-color:var(--rx-primary); background:var(--rx-primary-pale); }
time[data-rx-formatted] { font-variant-numeric:tabular-nums; }
.rx-tabs { display:flex; flex-wrap:wrap; gap:var(--rx-sp-4); margin:var(--rx-sp-16) 0 var(--rx-sp-24); padding:var(--rx-sp-4); border:1px solid var(--rx-line); border-radius:var(--rx-radius-lg); background:var(--rx-canvas); }
.rx-tab { flex:1 1 auto; display:inline-flex; align-items:center; justify-content:center; gap:var(--rx-sp-8); min-height:44px; padding:0 var(--rx-sp-16); border:1px solid transparent; border-radius:var(--rx-radius); background:transparent; color:var(--rx-muted); font:inherit; font-size:var(--rx-fs-14); font-weight:700; cursor:pointer; }
.rx-tab:hover { color:var(--rx-primary-hover); background:#fff; }
.rx-tab[aria-selected="true"] { background:#fff; border-color:var(--rx-line); color:var(--rx-primary-hover); box-shadow:var(--rx-shadow-sm); }
.rx-tab-count { display:inline-flex; align-items:center; justify-content:center; min-width:22px; height:22px; padding:0 6px; border-radius:var(--rx-radius-lg); background:var(--rx-neutral-soft); color:var(--rx-neutral); font-size:var(--rx-fs-12); font-variant-numeric:tabular-nums; }
.rx-tab[aria-selected="true"] .rx-tab-count { background:var(--rx-primary); color:#fff; }
.rx-avatar { display:inline-flex; align-items:center; justify-content:center; width:40px; height:40px; flex:none; border-radius:50%; background:var(--rx-primary-soft); color:var(--rx-primary-hover); font-size:var(--rx-fs-16); font-weight:800; line-height:1; }
.rx-avatar-lg { width:56px; height:56px; font-size:var(--rx-fs-24); }
.rx-avatar[data-tone="1"] { background:#e8f6ef; color:#146c4b; } .rx-avatar[data-tone="2"] { background:#fff5e3; color:#8a4b06; }
.rx-avatar[data-tone="3"] { background:#f3ecfb; color:#5b3a8c; } .rx-avatar[data-tone="4"] { background:#e7f5f8; color:#0f5e6e; }
.rx-btn-danger-solid { background:var(--rx-danger); border-color:var(--rx-danger); color:#fff; }
.rx-btn-danger-solid:hover { background:#912018; border-color:#912018; }
.rx-notice-region { position:fixed; top:calc(var(--rx-header-h) + 12px); right:var(--rx-sp-16); z-index:190; display:flex; flex-direction:column; gap:var(--rx-sp-8); width:min(420px,calc(100vw - 24px)); pointer-events:none; }
@media (max-width:480px) { .rx-notice-region { right:12px; } }
.rx-notice { display:flex; align-items:flex-start; gap:var(--rx-sp-12); padding:var(--rx-sp-12) var(--rx-sp-16); border:1px solid #efb7b0; border-left:4px solid var(--rx-danger); border-radius:var(--rx-radius-lg); background:#fff; color:var(--rx-text); box-shadow:var(--rx-shadow); font-size:var(--rx-fs-14); line-height:1.6; pointer-events:auto; animation:rx-toast-in .18s ease-out; }
.rx-notice-info { border-color:#b9cff0; border-left-color:var(--rx-primary); }
.rx-notice-warning { border-color:#ecc98e; border-left-color:var(--rx-warning); }
.rx-notice > .rx-icon { margin-top:2px; color:var(--rx-danger); }
.rx-notice-info > .rx-icon { color:var(--rx-primary); } .rx-notice-warning > .rx-icon { color:var(--rx-warning); }
.rx-notice-text { flex:1 1 auto; min-width:0; }
.rx-notice-text strong { display:block; color:var(--rx-ink); font-size:var(--rx-fs-14); }
.rx-notice-text p { margin:2px 0 0; color:var(--rx-muted); font-size:var(--rx-fs-12); }
.rx-notice-code,.rx-error-code { display:inline-block; margin-top:2px; color:var(--rx-muted); font-size:11px; font-weight:400; font-family:"Cascadia Code",SFMono-Regular,Consolas,monospace; overflow-wrap:anywhere; }
.rx-notice-actions { display:flex; flex-wrap:wrap; gap:var(--rx-sp-8); margin-top:var(--rx-sp-8); }
.rx-notice-actions .rx-btn { min-height:36px; padding:0 var(--rx-sp-12); font-size:13px; }
.rx-notice-close { flex:none; width:32px; height:32px; min-height:32px; padding:0; border:0; border-radius:var(--rx-radius); background:transparent; color:var(--rx-muted); font-size:18px; line-height:1; cursor:pointer; }
.rx-notice-close:hover { background:var(--rx-neutral-soft); color:var(--rx-ink); }
.rx-modal-backdrop { position:fixed; inset:0; z-index:300; display:flex; align-items:center; justify-content:center; padding:var(--rx-sp-16); background:rgba(23,43,77,.45); }
.rx-modal-backdrop[hidden] { display:none !important; }
.rx-modal { width:min(480px,100%); max-height:calc(100vh - 32px); overflow:auto; background:#fff; border-radius:var(--rx-radius-lg); box-shadow:0 20px 48px rgba(23,43,77,.28); animation:rx-toast-in .16s ease-out; }
.rx-modal-head { display:flex; align-items:center; gap:var(--rx-sp-12); padding:var(--rx-sp-24) var(--rx-sp-24) var(--rx-sp-8); }
.rx-modal-icon { display:inline-flex; align-items:center; justify-content:center; width:40px; height:40px; flex:none; border-radius:50%; background:var(--rx-danger-soft); color:var(--rx-danger); }
.rx-modal-info .rx-modal-icon { background:var(--rx-primary-soft); color:var(--rx-primary); }
.rx-modal-title { margin:0; color:var(--rx-ink); font-size:var(--rx-fs-20); line-height:1.35; }
.rx-modal-body { padding:0 var(--rx-sp-24); color:var(--rx-text); font-size:var(--rx-fs-14); line-height:1.7; }
.rx-modal-body p { margin:var(--rx-sp-8) 0 0; }
.rx-modal-body ul { margin:var(--rx-sp-8) 0 0; padding-left:20px; color:var(--rx-muted); }
.rx-modal-field { display:flex; flex-direction:column; gap:6px; margin-top:var(--rx-sp-16); }
.rx-modal-field textarea { width:100%; min-height:72px; padding:8px 10px; border:1px solid var(--rx-line-strong); border-radius:var(--rx-radius); font:inherit; font-size:var(--rx-fs-14); resize:vertical; box-sizing:border-box; }
.rx-modal-field textarea[aria-invalid="true"] { border-color:var(--rx-danger); }
.rx-modal-actions { display:flex; justify-content:flex-end; flex-wrap:wrap; gap:var(--rx-sp-8); padding:var(--rx-sp-24); }
.rx-loading-bar { position:fixed; top:0; left:0; right:0; z-index:400; height:3px; overflow:hidden; background:var(--rx-primary-soft); pointer-events:none; }
.rx-loading-bar::after { content:""; position:absolute; top:0; bottom:0; left:-40%; width:40%; background:var(--rx-primary); animation:rx-loading-slide 1.1s ease-in-out infinite; }
.rx-loading-bar[hidden],.rx-loading-pill[hidden] { display:none !important; }
.rx-loading-pill { position:fixed; left:50%; bottom:var(--rx-sp-24); z-index:200; display:inline-flex; align-items:center; gap:var(--rx-sp-8); padding:8px 16px; border:1px solid var(--rx-line); border-radius:var(--rx-radius-lg); background:#fff; color:var(--rx-ink); box-shadow:var(--rx-shadow); font-size:var(--rx-fs-14); transform:translateX(-50%); pointer-events:none; }
.rx-loading-pill::before { content:""; width:14px; height:14px; border:2px solid var(--rx-primary); border-right-color:transparent; border-radius:50%; animation:rx-spin .8s linear infinite; }
@keyframes rx-loading-slide { from { left:-40%; } to { left:100%; } }
@media (prefers-reduced-motion:reduce) { .rx-notice,.rx-modal,.rx-loading-bar::after,.rx-loading-pill::before { animation:none; } }
@media (prefers-reduced-motion:reduce) { .rx-btn.is-loading::after,.rx-skeleton-line,.rx-toast,.rx-drawer { animation:none; } }
"""

NAV_CSS = r"""
header.rx-header { position:sticky; top:0; z-index:60; display:block; height:auto; min-height:0; margin:0; padding:0; gap:0; background:#fff; border-bottom:1px solid var(--rx-line); box-shadow:var(--rx-shadow-sm); font-family:"Segoe UI","Microsoft YaHei","PingFang SC",sans-serif; font-size:14px; line-height:1.5; letter-spacing:0; }
header.rx-header::before { content:""; display:block; height:3px; background:linear-gradient(90deg,var(--rx-primary-deep) 0%,var(--rx-primary) 55%,var(--rx-glow) 100%); }
.rx-header a { text-decoration:none; }
.rx-header svg { display:inline-block; }
.rx-header-inner { width:min(1240px,calc(100% - 32px)); min-height:var(--rx-header-h); margin:0 auto; display:flex; align-items:center; gap:var(--rx-sp-24); }
.rx-brand { display:flex; align-items:center; gap:10px; flex:none; color:var(--rx-ink); text-decoration:none; }
.rx-brand-icon { width:36px; height:36px; padding:6px; border-radius:var(--rx-radius-lg); background:linear-gradient(135deg,var(--rx-primary) 0%,var(--rx-primary-deep) 100%); color:#fff; box-shadow:0 0 0 3px var(--rx-glow-soft),0 4px 12px rgba(31,95,191,.28); }
.rx-brand-copy strong { display:block; font-size:17px; line-height:1.2; color:var(--rx-ink); letter-spacing:.2px; }
.rx-brand-copy strong em { margin-left:4px; font-style:normal; font-weight:700; font-size:14px; color:var(--rx-primary); }
.rx-brand-copy span { display:block; font-size:var(--rx-fs-12); color:var(--rx-muted); }
.rx-history { display:flex; align-items:center; gap:4px; flex:none; }
.rx-history-btn { display:inline-flex; align-items:center; gap:4px; min-height:36px; padding:0 10px; border:1px solid var(--rx-line); border-radius:var(--rx-radius); background:var(--rx-primary-pale); color:var(--rx-primary); font:inherit; font-size:13px; font-weight:600; cursor:pointer; white-space:nowrap; transition:background .15s,border-color .15s; }
.rx-history-btn:hover:not(:disabled) { background:var(--rx-primary-soft); border-color:var(--rx-line-strong); }
.rx-history-btn:focus-visible { outline:2px solid var(--rx-focus); outline-offset:2px; }
.rx-history-btn:disabled,.rx-history-btn[aria-disabled="true"] { cursor:not-allowed; color:#8a97a8; background:#f3f5f8; border-color:var(--rx-line); }
.rx-history-btn .rx-icon { width:16px; height:16px; }
.rx-history-btn[data-rx-fallback="home"] { border-style:dashed; }
.rx-nav-toggle { display:none; margin-left:auto; align-items:center; gap:6px; min-height:44px; padding:0 12px; border:1px solid var(--rx-line-strong); border-radius:var(--rx-radius); background:#fff; color:var(--rx-ink); font:inherit; font-size:var(--rx-fs-14); font-weight:700; cursor:pointer; }
.rx-nav-panel { flex:1 1 auto; min-width:0; display:flex; align-items:center; gap:var(--rx-sp-16); }
.rx-nav { display:flex; align-items:stretch; gap:2px; min-width:0; flex-wrap:nowrap; }
.rx-nav-link { display:inline-flex; align-items:center; min-height:var(--rx-header-h); padding:0 10px; border-bottom:3px solid transparent; color:var(--rx-text); font-size:var(--rx-fs-14); text-decoration:none; white-space:nowrap; }
.rx-nav-link:hover { color:var(--rx-primary); background:var(--rx-primary-pale); }
.rx-nav-link[aria-current="page"] { color:var(--rx-primary); border-bottom-color:var(--rx-primary); font-weight:700; }
.rx-header-actions { margin-left:auto; display:flex; align-items:center; gap:var(--rx-sp-8); flex:none; }
.rx-header-actions .button { min-height:40px; }
.rx-account { display:flex; flex-direction:column; min-width:0; max-width:180px; padding:4px 10px; border-left:2px solid var(--rx-primary); background:var(--rx-primary-pale); line-height:1.3; }
.rx-account > span { color:var(--rx-muted); font-size:11px; }
.rx-account > strong { color:var(--rx-ink); font-size:13px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.rx-logout { min-height:40px; }
.rx-logout .rx-icon { width:16px; height:16px; }
@media (min-width:1181px) and (max-width:1360px) {
  .rx-header-inner { gap:var(--rx-sp-12); }
  .rx-nav-panel { gap:var(--rx-sp-8); }
  .rx-nav-link { padding:0 6px; }
}
@media (max-width:1180px) {
  .rx-nav-toggle { display:inline-flex; }
  .rx-nav-panel { display:none; position:absolute; left:0; right:0; top:100%; flex-direction:column; align-items:stretch; gap:0; padding:var(--rx-sp-8) var(--rx-sp-16) var(--rx-sp-16); background:#fff; border-bottom:1px solid var(--rx-line); box-shadow:var(--rx-shadow); max-height:calc(100vh - var(--rx-header-h)); overflow-y:auto; }
  .rx-header.is-open .rx-nav-panel { display:flex; }
  .rx-nav { flex-direction:column; gap:0; }
  .rx-nav-link { min-height:44px; padding:0 var(--rx-sp-12); border-bottom:0; border-left:3px solid transparent; }
  .rx-nav-link[aria-current="page"] { border-left-color:var(--rx-primary); background:var(--rx-primary-soft); }
  .rx-header-actions { margin:var(--rx-sp-8) 0 0; padding-top:var(--rx-sp-12); border-top:1px solid var(--rx-line); flex-wrap:wrap; }
  .rx-account { max-width:none; flex:1 1 140px; }
}
/* Wide screens whose header actions crowd the nav: setupHeader adds rx-header-compact and the menu takes over. */
.rx-header.rx-header-compact { position:sticky; }
.rx-header.rx-header-compact .rx-nav-toggle { display:inline-flex; }
.rx-header.rx-header-compact .rx-nav-panel { display:none; position:absolute; left:0; right:0; top:100%; flex-direction:column; align-items:stretch; gap:0; padding:var(--rx-sp-8) var(--rx-sp-16) var(--rx-sp-16); background:#fff; border-bottom:1px solid var(--rx-line); box-shadow:var(--rx-shadow); max-height:calc(100vh - var(--rx-header-h)); overflow-y:auto; }
.rx-header.rx-header-compact.is-open .rx-nav-panel { display:flex; }
.rx-header.rx-header-compact .rx-nav { flex-direction:column; gap:0; }
.rx-header.rx-header-compact .rx-nav-link { min-height:44px; padding:0 var(--rx-sp-12); border-bottom:0; border-left:3px solid transparent; }
.rx-header.rx-header-compact .rx-nav-link[aria-current="page"] { border-left-color:var(--rx-primary); background:var(--rx-primary-soft); }
.rx-header.rx-header-compact .rx-header-actions { margin:var(--rx-sp-8) 0 0; padding-top:var(--rx-sp-12); border-top:1px solid var(--rx-line); flex-wrap:wrap; }
.rx-header.rx-header-compact .rx-account { max-width:none; flex:1 1 140px; }
@media (max-width:640px) { .rx-history-btn span { display:none; } .rx-history-btn { width:40px; padding:0; justify-content:center; } }
.rx-header.rx-history-iconic .rx-history-btn span { display:none; }
.rx-header.rx-history-iconic .rx-history-btn { width:36px; padding:0; justify-content:center; }
.rx-header.rx-history-iconic .rx-header-inner { gap:var(--rx-sp-12); }
@media (max-width:480px) {
  .rx-header-inner { width:calc(100% - 20px); gap:var(--rx-sp-8); }
  .rx-brand-copy span { display:none; }
  .rx-nav-toggle span { display:none; }
  .rx-nav-toggle { width:44px; padding:0; justify-content:center; flex:none; }
  .rx-brand { flex:0 1 auto; min-width:0; }
  .rx-brand-icon { flex:none; }
  .rx-brand-copy { min-width:0; overflow:hidden; }
  .rx-brand-copy strong { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .rx-history { flex:none; }
  .rx-history-btn, .rx-header.rx-history-iconic .rx-history-btn { width:34px; }
}
@media print { .rx-header,.rx-toast-region,.rx-notice-region,.rx-loading-bar,.rx-loading-pill,.rx-modal-backdrop { display:none !important; } }
"""

# 统一「切换学生」条：结果页、身份确认页、课堂分析人物页、学生测量页共用。
SWITCHER_CSS = r"""
.rx-switcher { margin:0 0 var(--rx-sp-16); padding:var(--rx-sp-12) var(--rx-sp-16); background:var(--rx-surface); border:1px solid var(--rx-line); border-radius:var(--rx-radius-lg); }
.rx-switcher[hidden] { display:none !important; }
.rx-switcher-head { display:flex; flex-wrap:wrap; align-items:baseline; gap:var(--rx-sp-4) var(--rx-sp-12); margin-bottom:var(--rx-sp-8); }
.rx-switcher-title { font-size:var(--rx-fs-16); font-weight:800; color:var(--rx-ink); }
.rx-switcher-title::before { content:"⇆"; margin-right:6px; color:var(--rx-primary); }
.rx-switcher-count { color:var(--rx-muted); font-size:var(--rx-fs-12); }
.rx-switcher-note { flex-basis:100%; color:var(--rx-muted); font-size:var(--rx-fs-12); }
.rx-switcher-track { display:flex; gap:var(--rx-sp-12); overflow-x:auto; padding:2px 2px var(--rx-sp-8); scroll-snap-type:x proximity; }
.rx-switch-card { flex:0 0 172px; display:flex; flex-direction:column; align-items:stretch; gap:6px; min-width:0; padding:var(--rx-sp-8); border:1px solid var(--rx-line); border-radius:var(--rx-radius-lg); background:#fff; color:var(--rx-ink); text-align:left; cursor:pointer; font:inherit; scroll-snap-align:start; transition:border-color .15s, box-shadow .15s; }
.rx-switch-card:hover { border-color:#9fbbe6; }
.rx-switch-card:focus-visible { outline:3px solid var(--rx-focus, #8bb4f0); outline-offset:2px; }
.rx-switch-card.is-active { border-color:var(--rx-primary); box-shadow:0 0 0 2px #d6e4fb; background:var(--rx-primary-soft); }
.rx-switch-card.is-excluded { opacity:.72; border-style:dashed; }
.rx-switcher .rx-switch-avatar { display:block; width:100%; aspect-ratio:1/1; border-radius:var(--rx-radius-md, 6px); overflow:hidden; background:#eef3f7; }
.rx-switcher .rx-switch-avatar img { display:block; width:100%; height:100%; max-width:none; object-fit:cover; }
.rx-switch-initial { display:flex; align-items:center; justify-content:center; width:100%; height:100%; font-size:44px; font-weight:800; color:#fff; background:linear-gradient(135deg,#5b8fd8,#1f5fbf); }
.rx-switch-card[data-tone="1"] .rx-switch-initial { background:linear-gradient(135deg,#3fb6a8,#0d7f74); }
.rx-switch-card[data-tone="2"] .rx-switch-initial { background:linear-gradient(135deg,#f0a85a,#c26a12); }
.rx-switch-card[data-tone="3"] .rx-switch-initial { background:linear-gradient(135deg,#9a86e0,#5e4b96); }
.rx-switch-body { display:flex; flex-direction:column; gap:2px; min-width:0; }
.rx-switch-body strong { font-size:var(--rx-fs-16); line-height:1.3; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.rx-switch-body small { color:var(--rx-muted); font-size:var(--rx-fs-12); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.rx-switch-body .rx-badge { align-self:flex-start; margin-top:2px; }
.rx-switcher-low { margin:var(--rx-sp-8) 0 0; padding:var(--rx-sp-8) var(--rx-sp-12); border-left:4px solid var(--rx-warning); background:var(--rx-warning-soft); color:#6b4a0c; font-size:var(--rx-fs-14); border-radius:var(--rx-radius-sm); }
.rx-switcher-low ul { margin:4px 0; padding-left:20px; }
.rx-switcher-low a { color:var(--rx-primary); font-weight:700; text-decoration:underline; }
@media (max-width:640px) { .rx-switch-card { flex-basis:132px; } .rx-switch-initial { font-size:34px; } }
@media print { .rx-switcher { display:none !important; } }
"""

UI_KIT_CSS = TOKENS_CSS + COMPONENT_CSS + NAV_CSS + SWITCHER_CSS


# --------------------------------------------------------------------------
# JavaScript
# --------------------------------------------------------------------------

_STATUS_JSON = json.dumps({key: list(value) for key, value in STATUS_LABELS.items()}, ensure_ascii=False)

UI_KIT_JS = r"""
(function(){
  'use strict';
  if (typeof window === 'undefined' || typeof document === 'undefined' || window.RxUI) return;
  var STATUS = __STATUS__;
  var pageName = function(){ var h=document.querySelector('[data-rx-page]'); return (h&&h.getAttribute('data-rx-page'))||location.pathname; };
  var typeOf = function(v){ return v===null?'none':Array.isArray(v)?'array':typeof v; };
  function warn(component, value, fallback, reason){
    var entry={ts:new Date().toISOString(),level:'WARNING',page:pageName(),component:component,input_type:typeOf(value),
      input_length:typeof value==='string'?value.length:null,fallback:fallback,reason:reason||''};
    try { console.warn('[rx-ui]', JSON.stringify(entry)); } catch (e) {}
    return entry;
  }
  function pad(n){ return String(n).padStart(2,'0'); }
  function parseTime(value){
    if (value===null||value===undefined||value==='') return null;
    var d = value instanceof Date ? value : new Date(typeof value==='number' && value<1e12 ? value*1000 : value);
    return isNaN(d.getTime()) ? null : d;
  }
  function formatTime(value, fallback){
    var d=parseTime(value);
    if (!d) { var shown=fallback||'时间未返回'; if(value!==null&&value!==undefined&&value!=='') warn('format_time',value,shown,'unparseable'); return shown; }
    return d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate())+' '+pad(d.getHours())+':'+pad(d.getMinutes());
  }
  function formatDate(value, fallback){
    var d=parseTime(value);
    if (!d) { var shown=fallback||'日期未返回'; if(value) warn('format_date',value,shown,'unparseable'); return shown; }
    return d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate());
  }
  function relativeTime(value, now){
    var d=parseTime(value);
    if (!d) { warn('relative_time',value,'时间未返回','unparseable'); return '时间未返回'; }
    var diff=Math.round(((now?now.getTime():Date.now())-d.getTime())/1000), future=diff<0; diff=Math.abs(diff);
    if (diff<45) return '刚刚';
    var units=[[31536000,'年'],[2592000,'个月'],[86400,'天'],[3600,'小时'],[60,'分钟']];
    for (var i=0;i<units.length;i++) if (diff>=units[i][0]) { var n=Math.max(1,Math.round(diff/units[i][0])); return n+' '+units[i][1]+(future?'后':'前'); }
    return '刚刚';
  }
  function formatBytes(value){
    var n=Number(value);
    if (value===null||value===undefined||value===''||!isFinite(n)||n<0) { warn('format_bytes',value,'—','not_a_byte_count'); return '—'; }
    var units=['B','KB','MB','GB','TB'], i=0;
    while (n>=1024 && i<units.length-1) { n/=1024; i++; }
    return i===0 ? Math.round(n)+' B' : n.toFixed(i>=3?2:1)+' '+units[i];
  }
  function shortId(value){
    var text=String(value||''); var body=text.replace(/^[A-Za-z]{1,16}[-_](?=[0-9A-Fa-f])/,'');
    return (body||text).slice(0,8);
  }
  function statusLabel(code){
    var key=String(code||'').trim().toLowerCase();
    if (STATUS[key]) return STATUS[key];
    warn('status_badge',code,'未知状态','unknown_status_code'); return ['未知状态','neutral'];
  }
  function esc(v){ return String(v==null?'':v).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];}); }
  function statusBadge(code){ var s=statusLabel(code); return '<span class="rx-badge rx-badge-'+s[1]+'">'+esc(s[0])+'</span>'; }
  function shortIdHtml(value, label){
    var text=String(value||'').trim();
    if (!text) { warn('short_id',value,'未返回','empty_identifier'); return '<span class="rx-id rx-id-empty">未返回</span>'; }
    return '<span class="rx-id" data-rx-full="'+esc(text)+'" title="'+esc(text)+'"><code class="rx-id-code">'+esc(shortId(text))+'</code><button class="rx-copy" type="button" data-rx-copy="'+esc(text)+'" aria-label="复制完整'+esc(label||'编号')+'">复制完整编号</button></span>';
  }
  function region(){
    var r=document.getElementById('rxToastRegion');
    if (!r) { r=document.createElement('div'); r.id='rxToastRegion'; r.className='rx-toast-region'; r.setAttribute('role','status'); r.setAttribute('aria-live','polite'); document.body.appendChild(r); }
    return r;
  }
  function toast(message, tone, ms){
    var el=document.createElement('div'); el.className='rx-toast'+(tone?' rx-toast-'+tone:''); el.textContent=String(message||'');
    region().appendChild(el); setTimeout(function(){ if(el.parentNode) el.parentNode.removeChild(el); }, ms||2400);
    return el;
  }
  function copy(text){
    var done=function(){ toast('已复制','success'); return true; };
    var fallback=function(){
      try { var ta=document.createElement('textarea'); ta.value=text; ta.setAttribute('readonly',''); ta.style.position='fixed'; ta.style.opacity='0';
        document.body.appendChild(ta); ta.select(); var ok=document.execCommand('copy'); document.body.removeChild(ta);
        if (ok) return done(); } catch (e) {}
      warn('copy',text,'copy_failed','clipboard_unavailable'); toast('复制失败，请手动选择编号','danger'); return false;
    };
    if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text).then(done, fallback);
    return Promise.resolve(fallback());
  }
  var ISO=/^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$/;
  var LONG_ID=/^(?:[A-Za-z]{1,16}[-_])?(?:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[0-9a-f]{20,})$/i;
  var LEAF='td,span,small,dd,strong,p,li,code,time,em,b';
  function isLeaf(el){ return el.children.length===0 && !el.closest('.rx-id,script,style,textarea,select,option,[contenteditable],[data-rx-raw]'); }
  function enhance(root){
    root=root||document;
    root.querySelectorAll('[data-rx-time]:not([data-rx-done])').forEach(function(el){ el.setAttribute('data-rx-done','1'); var raw=el.getAttribute('data-rx-time')||el.textContent.trim(); if(!raw) return; el.textContent=formatTime(raw); el.title=relativeTime(raw)+' · '+raw; });
    root.querySelectorAll('[data-rx-bytes]:not([data-rx-done])').forEach(function(el){ el.setAttribute('data-rx-done','1'); el.textContent=formatBytes(el.getAttribute('data-rx-bytes')); });
    root.querySelectorAll('[data-rx-short-id]:not([data-rx-done])').forEach(function(el){ el.setAttribute('data-rx-done','1'); var v=el.getAttribute('data-rx-short-id')||el.textContent.trim(); el.innerHTML=shortIdHtml(v); });
    root.querySelectorAll('button:not([aria-label]):not([aria-labelledby])').forEach(function(btn){
      var t=(btn.textContent||'').trim(); if (t.length>1) return;
      var label=btn.getAttribute('title')||(/^[×✕xX]$/.test(t)?'关闭':'');
      if (label) btn.setAttribute('aria-label',label);
      else if (!btn.hasAttribute('data-rx-warned')) { btn.setAttribute('data-rx-warned','1'); warn('icon_button',t,'unlabeled','missing_aria_label'); }
    });
    root.querySelectorAll(LEAF).forEach(function(el){
      if (el.hasAttribute('data-rx-done') || !isLeaf(el)) return;
      var text=(el.textContent||'').trim(); if (!text || text.length>80) return;
      if (ISO.test(text)) { el.textContent=formatTime(text); el.title=relativeTime(text)+' · '+text; el.setAttribute('data-rx-formatted','time'); }
      else if (LONG_ID.test(text) && (el.classList.contains('mono') || el.tagName==='CODE' || el.closest('td,dd,.mono'))) { el.innerHTML=shortIdHtml(text); }
    });
  }
  var queued=false;
  function schedule(){ if (queued) return; queued=true; (window.requestAnimationFrame||setTimeout)(function(){ queued=false; try { enhance(document); } catch (e) { warn('enhance',null,'skipped',e&&e.message); } }); }
  function setupHeader(){
    var header=document.querySelector('.rx-header'); if (!header) return;
    var toggle=header.querySelector('.rx-nav-toggle');
    var setOpen=function(open){ header.classList.toggle('is-open',open); if(toggle){ toggle.setAttribute('aria-expanded',open?'true':'false'); toggle.setAttribute('aria-label',open?'关闭导航菜单':'打开导航菜单'); } };
    if (toggle) toggle.addEventListener('click',function(){ setOpen(!header.classList.contains('is-open')); });
    var fitNav=function(){
      try {
        var wasOpen=header.classList.contains('is-open');
        header.classList.remove('rx-header-compact'); header.classList.remove('rx-history-iconic');
        var panel=header.querySelector('.rx-nav-panel'), links=header.querySelectorAll('.rx-nav-link'), actions=header.querySelector('.rx-header-actions');
        if (!panel || !links.length || !actions || window.getComputedStyle(panel).display==='none' || window.getComputedStyle(panel).position==='absolute') return;
        var crowded=function(){ return links[links.length-1].getBoundingClientRect().right > actions.getBoundingClientRect().left - 4; };
        if (!crowded()) return;
        // First give the nav the room taken by the 后退/前进 labels, then fall back to the menu.
        if (header.querySelector('.rx-history')) { header.classList.add('rx-history-iconic'); if (!crowded()) return; header.classList.remove('rx-history-iconic'); }
        header.classList.add('rx-header-compact'); if (!wasOpen) setOpen(false);
      } catch (e) { warn('header_fit',null,'skipped',e&&e.message); }
    };
    fitNav();
    window.addEventListener('resize',fitNav);
    var headerActions=header.querySelector('.rx-header-actions');
    if (headerActions && window.MutationObserver) new MutationObserver(fitNav).observe(headerActions,{childList:true,subtree:true,characterData:true,attributes:true,attributeFilter:['hidden','class']});
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(fitNav);
    document.addEventListener('keydown',function(e){ if(e.key==='Escape' && header.classList.contains('is-open')){ setOpen(false); if(toggle) toggle.focus(); } });
    document.addEventListener('click',function(e){ if(header.classList.contains('is-open') && !header.contains(e.target)) setOpen(false); });
    var syncHash=function(){
      var links=header.querySelectorAll('.rx-nav-link'); var path=location.pathname, hash=location.hash; var matched=null;
      links.forEach(function(a){ var u=new URL(a.getAttribute('href'),location.href); if(u.pathname===path && u.hash && u.hash===hash) matched=a; });
      if (!matched) return;
      links.forEach(function(a){ if(a===matched) a.setAttribute('aria-current','page'); else a.removeAttribute('aria-current'); });
    };
    syncHash(); window.addEventListener('hashchange',syncHash);
    header.querySelectorAll('[data-rx-logout]').forEach(function(btn){
      btn.addEventListener('click',function(){
        btn.disabled=true;
        fetch('/api/v1/demo2/auth/logout',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:'{}'})
          .catch(function(){}).then(function(){ location.assign('/demo2/login'); });
      });
    });
    if (header.hasAttribute('data-rx-fetch-account')) {
      fetch('/api/v1/demo2/auth/me',{credentials:'same-origin',headers:{Accept:'application/json'}}).then(function(r){ return r.ok?r.json():null; }).then(function(data){
        var acc=data&&(data.account||data); var name=acc&&(acc.login_alias||acc.username);
        var slot=header.querySelector('[data-rx-account]'); if (slot && name && (slot.textContent==='读取中'||!slot.textContent.trim())) slot.textContent=name;
      }).catch(function(){ warn('account',null,'读取中','account_fetch_failed'); });
    }
  }
  function setHint(btn, open){
    var bubble=document.getElementById(btn.getAttribute('aria-controls')||''); if (!bubble) return;
    bubble.hidden=!open; btn.setAttribute('aria-expanded',open?'true':'false');
  }
  function closeHints(except){ document.querySelectorAll('.rx-hint-toggle[aria-expanded="true"]').forEach(function(b){ if(b!==except) setHint(b,false); }); }
  function setStep(id, index){
    var bar=typeof id==='string'?document.getElementById(id):id; if (!bar) return;
    bar.querySelectorAll('[data-rx-step]').forEach(function(li){
      var i=Number(li.getAttribute('data-rx-step')), state=i<index?'done':i===index?'current':'todo';
      li.className='rx-step rx-step-'+state;
      if (state==='current') li.setAttribute('aria-current','step'); else li.removeAttribute('aria-current');
    });
  }
  document.addEventListener('click',function(e){
    var hintBtn=e.target && e.target.closest ? e.target.closest('.rx-hint-toggle') : null;
    if (hintBtn) { e.preventDefault(); var open=hintBtn.getAttribute('aria-expanded')!=='true'; closeHints(hintBtn); setHint(hintBtn,open); return; }
    if (e.target && e.target.closest && !e.target.closest('.rx-hint-bubble')) closeHints(null);
    var btn=e.target && e.target.closest ? e.target.closest('[data-rx-copy]') : null;
    if (!btn) return; e.preventDefault(); copy(btn.getAttribute('data-rx-copy')||'');
  });
  document.addEventListener('keydown',function(e){
    if (e.key!=='Escape') return; var open=document.querySelector('.rx-hint-toggle[aria-expanded="true"]');
    if (open) { setHint(open,false); open.focus(); }
  });
  window.RxUI={formatTime:formatTime,formatDate:formatDate,relativeTime:relativeTime,formatBytes:formatBytes,shortId:shortId,
    shortIdHtml:shortIdHtml,statusLabel:statusLabel,statusBadge:statusBadge,toast:toast,copy:copy,enhance:enhance,warn:warn,setStep:setStep};
  var start=function(){
    setupHeader(); enhance(document);
    if (window.MutationObserver) new MutationObserver(schedule).observe(document.body,{childList:true,subtree:true,characterData:true});
  };
  if (document.readyState==='loading') document.addEventListener('DOMContentLoaded',start); else start();
})();
""".replace("__STATUS__", _STATUS_JSON)

# Site-wide feedback: every same-origin ``/api/`` fetch passes through one
# wrapper that (1) turns failures into a plain-Chinese notice with the original
# code in small print, (2) reports path/method/status/code – never bodies,
# queries or messages – to CLIENT_ERROR_PATH, (3) shows a loading indicator once
# requests run longer than 800 ms and (4) stashes unsaved form values in
# the opt-in draft store (UI_DRAFT_STORE_SCRIPT) when the session expires so
# they can be restored after login.
# Responses are passed through untouched; status codes and JSON error codes are
# only *read*, never rewritten.
UI_FEEDBACK_JS = r"""
(function(){
  'use strict';
  if (typeof window === 'undefined' || typeof document === 'undefined' || !window.RxUI || window.RxUI.__feedback) return;
  var R=window.RxUI, nativeFetch=typeof window.fetch==='function' ? window.fetch.bind(window) : null;
  // Formatter-only environments (Node harnesses) have no window events; keep the pure helpers there.
  var live=typeof window.addEventListener==='function';
  var LOG_PATH='__LOG_PATH__', LOADING_DELAY=800, DRAFT_TTL=2*3600*1000, DRAFT_PREFIX='rx-draft:';
  var CODE_TEXT={
    report_stale:'报告已过期，请刷新后再下载',
    applicability_required:'请先在分析页确认视频适用性',
    network_error:'网络连接不稳定，请稍后重试',
    timeout:'网络连接不稳定，请求超时，请稍后重试',
    rate_limited:'操作较频繁，请稍后再试',
    json_required:'请从平台页面重新提交此操作',
    origin_forbidden:'请从平台页面重新提交此操作',
    version_conflict:'内容已被其他操作更新，请刷新后再修改',
    stale_version:'内容已被其他操作更新，请刷新后再修改',
    goal_contains_student_name:'本课目标中不能出现学生姓名，请改写后再保存',
    missing_dependency:'服务器缺少视频处理组件，请联系管理员',
    encryption_unavailable:'加密存储暂不可用，请稍后重试；不会改为明文保存'
  };
  var STATUS_TEXT={400:'提交的内容有误，请检查后重试',401:'登录已过期，请重新登录',403:'你没有查看此内容的权限',
    404:'内容不存在或已被删除',405:'当前页面不支持此操作',409:'内容已被更新，请刷新后再操作',410:'内容已到期或被撤回',
    413:'提交的内容过大，请精简后重试',415:'请从平台页面重新提交此操作',422:'提交的内容有误，请检查后重试',
    429:'操作较频繁，请稍后再试',500:'服务器暂时出错，请稍后重试',502:'服务暂时不可用，请稍后重试',
    503:'服务暂时不可用，请稍后重试',504:'服务响应超时，请稍后重试'};
  // Login/registration show their own field errors; a 401 there is a wrong password, not an expired session.
  var QUIET_PATHS=[LOG_PATH,'/api/v1/demo2/ui/nav-event','/api/v1/demo2/help/debug-event','/api/v1/demo2/auth/login','/api/v1/demo2/auth/register','/api/v1/demo2/auth/sms-code','/api/v1/demo2/auth/logout'];
  var NO_LOADING_PATHS=[LOG_PATH,'/api/v1/demo2/ui/nav-event','/api/v1/demo2/help/debug-event','/api/v1/demo2/upload/chunks','/api/seewo_demo2/video_chunk','/api/v1/demo2/upload/tasks/resume','/api/v1/demo2/identity/debug-event','/api/v1/demo2/evaluations/debug-event'];
  var QUIET_PAGES=['/demo2/login','/demo2/register'];
  // Pages that already explain these statuses next to the control: still logged, but no global notice.
  var INLINE_HANDLED={'/api/v1/demo2/identity/detect':[429],'/api/v1/demo2/schools/search':[400,429],'/api/v1/demo2/simple-result/persons':[400,403,404],'/api/v1/demo2/simple-result/person-switch':[400,403,429]};
  function handledInline(path, status){ var list=INLINE_HANDLED[path]; return !!list && list.indexOf(status)>=0; }
  function esc(v){ return String(v==null?'':v).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];}); }
  function hasChinese(text){ return typeof text==='string' && /[\u4e00-\u9fa5]/.test(text); }
  function startsWithAny(path, list){ for (var i=0;i<list.length;i++) if (path===list[i] || path.indexOf(list[i]+'/')===0) return true; return false; }
  function pageName(){ var h=document.querySelector('[data-rx-page]'); var name=(h&&h.getAttribute('data-rx-page'))||location.pathname||'unknown'; return String(name).replace(/[^A-Za-z0-9_./-]/g,'').slice(0,80)||'unknown'; }

  // ---- error vocabulary ------------------------------------------------
  function describeError(status, code, serverMessage){
    status=Number(status)||0; code=String(code||'');
    var text;
    if (status===401) text=STATUS_TEXT[401];
    else if (code && CODE_TEXT[code]) text=CODE_TEXT[code];
    else if (status===403 || status===404) text=STATUS_TEXT[status];
    else if (hasChinese(serverMessage)) text=String(serverMessage).replace(/[。.\s]+$/,'');
    else if (status===0) text=CODE_TEXT.network_error;
    else text=STATUS_TEXT[status]||'操作未成功，请稍后重试';
    var label=code ? (status ? status+' · '+code : code) : (status ? 'HTTP '+status : 'network_error');
    return {text:text, code:code, status:status, label:label, full:text+'（错误码：'+label+'）'};
  }
  function errorText(status, code, serverMessage){ return describeError(status, code, serverMessage).full; }
  function fromError(err){
    if (!err) return describeError(0,'network_error');
    if (err.name==='TimeoutError') return describeError(0,'timeout');
    if (err instanceof TypeError && !err.status) return describeError(0,'network_error');
    return describeError(err.status, err.code, err.message);
  }
  function errorHtml(info){ return esc(info.text)+' <small class="rx-error-code">错误码：'+esc(info.label)+'</small>'; }

  // ---- debug log channel ----------------------------------------------
  var sent={}, sentCount=0;
  function report(entry){
    var line={ts:new Date().toISOString(),page:entry.page,api_path:entry.api_path,method:entry.method,status:entry.status,error_code:entry.error_code,kind:entry.kind};
    try { console.warn('[rx-ui] api_error', JSON.stringify(line)); } catch (e) {}
    var key=[line.api_path,line.method,line.status,line.error_code,line.kind].join('|'), now=Date.now();
    if ((sent[key] && now-sent[key]<5000) || sentCount>=40 || !nativeFetch) return line;
    sent[key]=now; sentCount++;
    var body={client_ts:line.ts,page:line.page,api_path:line.api_path,method:line.method,status:line.status,kind:line.kind};
    if (line.error_code && /^[A-Za-z0-9_.:-]{1,64}$/.test(line.error_code)) body.error_code=line.error_code;
    try { nativeFetch(LOG_PATH,{method:'POST',credentials:'same-origin',keepalive:true,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}).catch(function(){}); } catch (e) {}
    return line;
  }

  // ---- notices ----------------------------------------------------------
  function noticeRegion(){
    var r=document.getElementById('rxNoticeRegion');
    if (!r) { r=document.createElement('div'); r.id='rxNoticeRegion'; r.className='rx-notice-region'; (document.body||document.documentElement).appendChild(r); }
    return r;
  }
  function closeNotice(el){ if (el && el.parentNode) el.parentNode.removeChild(el); }
  function notice(opts){
    opts=opts||{};
    var key=opts.key||'', region=noticeRegion();
    if (key) { var prev=region.querySelector('[data-rx-notice-key="'+key.replace(/["\\]/g,'')+'"]'); if (prev) closeNotice(prev); }
    var tone=opts.tone||'danger', el=document.createElement('div');
    el.className='rx-notice'+(tone==='danger'?'':' rx-notice-'+tone); el.setAttribute('role',tone==='info'?'status':'alert');
    if (key) el.setAttribute('data-rx-notice-key',key);
    el.innerHTML='<svg class="rx-icon" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">'
      +(tone==='info'?'<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.5"/>':'<path d="M12 4 2.8 20h18.4Z"/><path d="M12 10v4M12 17v.5"/>')+'</svg>'
      +'<div class="rx-notice-text"><strong>'+esc(opts.title||'')+'</strong>'
      +(opts.code?'<small class="rx-notice-code">错误码：'+esc(opts.code)+'</small>':'')
      +(opts.detail?'<p>'+esc(opts.detail)+'</p>':'')
      +((opts.actions||[]).length?'<div class="rx-notice-actions"></div>':'')+'</div>'
      +'<button type="button" class="rx-notice-close" aria-label="关闭提示">×</button>';
    el.querySelector('.rx-notice-close').addEventListener('click',function(){ closeNotice(el); });
    var bar=el.querySelector('.rx-notice-actions');
    (opts.actions||[]).forEach(function(a){
      var node=document.createElement(a.href?'a':'button');
      node.className='rx-btn '+(a.primary?'rx-btn-primary':'rx-btn-secondary'); node.textContent=a.label;
      if (a.href) { node.setAttribute('href',a.href); node.setAttribute('data-rx-no-guard',''); if (a.newTab) { node.target='_blank'; node.rel='noopener'; } }
      else node.type='button';
      if (a.id) node.id=a.id;
      if (a.onClick) node.addEventListener('click',function(e){ a.onClick(e, el); });
      bar.appendChild(node);
    });
    region.appendChild(el);
    if (opts.timeout) setTimeout(function(){ closeNotice(el); }, opts.timeout);
    return el;
  }

  // ---- unsaved drafts across an expired session -------------------------
  function draftKey(){ return DRAFT_PREFIX+location.pathname+location.search; }
  function draftFields(){
    var out={}, count=0;
    document.querySelectorAll('input[id],select[id],textarea[id]').forEach(function(el){
      if (el.closest('[data-rx-no-draft],.rx-header,.rx-modal,.rx-notice-region')) return;
      var type=(el.type||'').toLowerCase();
      if (['password','file','hidden','submit','button','reset','image'].indexOf(type)>=0) return;
      // Checkboxes here are confirmations (已核对/已复核/授权确认); a restored draft must never tick them for the teacher.
      if (type==='checkbox') return;
      if (type==='radio') { if (el.checked!==el.defaultChecked) { out[el.id]={c:el.checked}; count++; } return; }
      if (el.tagName==='SELECT') { var changed=Array.prototype.some.call(el.options,function(o){ return o.selected!==o.defaultSelected; }); if (changed) { out[el.id]={v:el.value}; count++; } return; }
      if (el.value!==el.defaultValue && String(el.value).length<=20000) { out[el.id]={v:el.value}; count++; }
    });
    return {fields:out,count:count};
  }
  // Persistence is opt-in: only pages that include UI_DRAFT_STORE_SCRIPT keep drafts in the browser.
  function store(){ return window.RxDraftStore || null; }
  function saveDraft(){
    if (!store()) return 0;
    try {
      var d=draftFields(); if (!d.count) return 0;
      store().set(draftKey(), JSON.stringify({ts:Date.now(),fields:d.fields}));
      return d.count;
    } catch (e) { R.warn('draft',null,'not_saved','session_storage_unavailable'); return 0; }
  }
  function readDraft(){
    try {
      if (!store()) return null;
      var raw=store().get(draftKey()); if (!raw) return null;
      var d=JSON.parse(raw); if (!d || !d.fields || Date.now()-Number(d.ts||0)>DRAFT_TTL) { store().remove(draftKey()); return null; }
      return d;
    } catch (e) { return null; }
  }
  function discardDraft(){ try { if (store()) store().remove(draftKey()); } catch (e) {} }
  function restoreDraft(){
    var d=readDraft(); if (!d) return {restored:0,pending:0};
    var restored=0, left={};
    Object.keys(d.fields).forEach(function(id){
      var el=document.getElementById(id), value=d.fields[id];
      if (!el || el.disabled) { left[id]=value; return; }
      if ('c' in value) el.checked=!!value.c; else el.value=value.v;
      el.dispatchEvent(new Event('input',{bubbles:true})); el.dispatchEvent(new Event('change',{bubbles:true}));
      restored++;
    });
    var pending=Object.keys(left).length;
    try { if (pending) store().set(draftKey(), JSON.stringify({ts:d.ts,fields:left})); else discardDraft(); } catch (e) {}
    return {restored:restored,pending:pending};
  }
  function offerDraft(){
    var d=readDraft(); if (!d) return;
    var n=Object.keys(d.fields).length; if (!n) return;
    notice({key:'draft',tone:'info',title:'找到上次未保存的内容（'+n+' 项）',
      detail:'内容只暂存在本浏览器标签页，关闭标签页后自动清除。若表单还没打开，请先打开对应表单再点「恢复内容」。',
      actions:[{label:'恢复内容',primary:true,id:'rxDraftRestore',onClick:function(e,el){
        var r=restoreDraft();
        if (r.restored) R.toast('已恢复 '+r.restored+' 项未保存内容；核对勾选需重新勾选后再保存','success',4000);
        if (r.pending) { R.toast('还有 '+r.pending+' 项所在的表单尚未打开','warning',4000); return; }
        closeNotice(el);
      }},{label:'不需要，丢弃',id:'rxDraftDiscard',onClick:function(e,el){ discardDraft(); closeNotice(el); }}]});
  }

  // ---- API failure handling -------------------------------------------
  function showApiError(info, ctx){
    if (startsWithAny(location.pathname, QUIET_PAGES)) return;
    if (info.status===401) {
      var saved=(ctx&&ctx.draftSaved)||saveDraft();
      notice({key:'auth',title:info.text,code:info.label,
        detail:saved?'本页已填写的 '+saved+' 项内容已暂存在本浏览器，重新登录后回到本页可以恢复；也可以在新窗口登录后回到这里重新保存。':'请重新登录后继续操作。',
        actions:[{label:'返回登录',href:'/demo2/login',primary:true,id:'rxReloginLink',onClick:function(){ allowLeave=true; }},
                 {label:'在新窗口登录',href:'/demo2/login',newTab:true,id:'rxReloginNewTab'}]});
      return;
    }
    var kept=info.status===0 && ctx && ctx.draftSaved ? '请检查网络后重试；已填写的内容仍保留在页面上，并已暂存在本浏览器，刷新页面后可以恢复。' : '请检查网络后重试；已填写的内容仍保留在页面上。';
    notice({key:'api:'+info.status+':'+info.code,title:info.text,code:info.label,timeout:info.status===0?0:9000,
      detail:info.status===0?kept:(ctx&&ctx.method!=='GET'?'本次操作未生效，已填写的内容仍保留在页面上。':'')});
  }
  function codeFromBody(data){
    if (!data || typeof data!=='object') return '';
    var e=data.error;
    if (e && typeof e==='object' && typeof e.code==='string') return e.code;
    if (typeof e==='string' && /^[a-z][a-z0-9_]{1,63}$/.test(e)) return e;
    if (typeof data.code==='string' && /^[a-z][a-z0-9_]{1,63}$/.test(data.code)) return data.code;
    return '';
  }
  function messageFromBody(data){ var e=data&&data.error; return (e&&typeof e==='object'&&e.message)||data&&data.message||''; }

  // ---- loading indicator ------------------------------------------------
  var inflight=0, loadingTimer=null, loadingBar=null, loadingPill=null;
  function loadingEls(){
    if (!loadingBar) {
      loadingBar=document.createElement('div'); loadingBar.className='rx-loading-bar'; loadingBar.id='rxLoadingBar'; loadingBar.hidden=true; loadingBar.setAttribute('aria-hidden','true');
      loadingPill=document.createElement('div'); loadingPill.className='rx-loading-pill'; loadingPill.id='rxLoadingPill'; loadingPill.hidden=true; loadingPill.setAttribute('role','status'); loadingPill.textContent='正在加载，请稍候…';
      (document.body||document.documentElement).appendChild(loadingBar); (document.body||document.documentElement).appendChild(loadingPill);
    }
  }
  function beginLoading(){
    inflight++;
    if (!loadingTimer) loadingTimer=setTimeout(function(){ loadingTimer=null; if (inflight>0) { loadingEls(); loadingBar.hidden=false; loadingPill.hidden=false; } }, LOADING_DELAY);
  }
  function endLoading(){
    inflight=Math.max(0,inflight-1);
    if (inflight===0) { if (loadingTimer) { clearTimeout(loadingTimer); loadingTimer=null; } if (loadingBar) { loadingBar.hidden=true; loadingPill.hidden=true; } }
  }

  if (nativeFetch && live) {
    window.fetch=function(input, init){
      var raw=typeof input==='string'?input:(input&&input.url)||String(input||''), url;
      try { url=new URL(raw, location.href); } catch (e) { return nativeFetch(input, init); }
      if (url.origin!==location.origin || url.pathname.indexOf('/api/')!==0) return nativeFetch(input, init);
      var path=url.pathname, method=String((init&&init.method)||(input&&input.method)||'GET').toUpperCase();
      var quiet=startsWithAny(path, QUIET_PATHS), showLoading=!startsWithAny(path, NO_LOADING_PATHS);
      if (showLoading) beginLoading();
      var ctx={api_path:path.slice(0,150),method:method,page:pageName()};
      return nativeFetch(input, init).then(function(response){
        if (showLoading) endLoading();
        // A later success means the session is back (e.g. logged in from a new window).
        if (response.ok && !quiet) { var authNotice=document.querySelector('[data-rx-notice-key="auth"]'); if (authNotice) { closeNotice(authNotice); R.toast('已重新连接，可以继续操作','success'); } }
        // A successful write means the stashed draft has been saved for real.
        if (response.ok && !quiet && method!=='GET' && !/\/debug-event$/.test(path)) discardDraft();
        if (!response.ok && !quiet) {
          var status=response.status;
          // Saved before the page sees the 401: some pages redirect to login immediately.
          if (status===401 && !startsWithAny(location.pathname, QUIET_PAGES)) ctx.draftSaved=saveDraft();
          response.clone().json().catch(function(){ return null; }).then(function(data){
            var code=codeFromBody(data), info=describeError(status, code, messageFromBody(data));
            report({page:ctx.page,api_path:ctx.api_path,method:method,status:status,error_code:code,kind:'http_error'});
            if (!handledInline(path, status)) showApiError(info, ctx);
          });
        }
        return response;
      }, function(err){
        if (showLoading) endLoading();
        var aborted=err && err.name==='AbortError';
        if (!quiet && !aborted) {
          var timeout=err && err.name==='TimeoutError', info=describeError(0, timeout?'timeout':'network_error');
          report({page:ctx.page,api_path:ctx.api_path,method:method,status:0,error_code:info.code,kind:timeout?'timeout':'network_error'});
          // A failed write may leave the page asking for a refresh; keep the typed values so the refresh can restore them.
          if (method!=='GET' && !startsWithAny(location.pathname, QUIET_PAGES)) ctx.draftSaved=saveDraft();
          showApiError(info, ctx);
        }
        throw err;
      });
    };
  }
  if (live) window.addEventListener('offline',function(){ notice({key:'offline',title:CODE_TEXT.network_error,code:'offline',detail:'网络已断开，恢复连接前请先不要保存或上传。'}); });
  if (live) window.addEventListener('online',function(){ var el=document.querySelector('[data-rx-notice-key="offline"]'); if (el) closeNotice(el); R.toast('网络已恢复','success'); });

  // ---- confirm dialog ---------------------------------------------------
  var dialogOpen=false;
  function confirmDialog(opts){
    opts=opts||{};
    return new Promise(function(resolve){
      if (dialogOpen) { resolve(opts.input?null:false); return; }
      dialogOpen=true;
      var previous=document.activeElement, danger=opts.tone!=='info';
      var back=document.createElement('div'); back.className='rx-modal-backdrop'; back.id='rxConfirm';
      var items=(opts.consequences||[]).map(function(t){ return '<li>'+esc(t)+'</li>'; }).join('');
      var input=opts.input||null;
      back.innerHTML='<div class="rx-modal'+(danger?'':' rx-modal-info')+'" role="alertdialog" aria-modal="true" aria-labelledby="rxConfirmTitle" aria-describedby="rxConfirmBody">'
        +'<div class="rx-modal-head"><span class="rx-modal-icon"><svg class="rx-icon" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">'
        +(danger?'<path d="M12 4 2.8 20h18.4Z"/><path d="M12 10v4M12 17v.5"/>':'<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.5"/>')+'</svg></span>'
        +'<h2 class="rx-modal-title" id="rxConfirmTitle">'+esc(opts.title||'确认操作')+'</h2></div>'
        +'<div class="rx-modal-body" id="rxConfirmBody"><p>'+esc(opts.message||'')+'</p>'+(items?'<ul>'+items+'</ul>':'')
        +(input?'<div class="rx-modal-field"><label class="rx-label" for="rxConfirmInput">'+esc(input.label||'原因')+(input.required?'<span class="rx-required" aria-hidden="true">*</span>':'')+'</label>'
          +'<textarea id="rxConfirmInput" maxlength="'+(Number(input.maxLength)||500)+'" aria-describedby="rxConfirmInputError"></textarea>'
          +'<p class="rx-error" id="rxConfirmInputError" role="alert" hidden></p></div>':'')
        +'</div><div class="rx-modal-actions"><button type="button" class="rx-btn rx-btn-secondary" id="rxConfirmCancel">'+esc(opts.cancelLabel||'取消')+'</button>'
        +'<button type="button" class="rx-btn '+(danger?'rx-btn-danger-solid':'rx-btn-primary')+'" id="rxConfirmOk">'+esc(opts.confirmLabel||'确认')+'</button></div></div>';
      document.body.appendChild(back);
      var okBtn=back.querySelector('#rxConfirmOk'), cancelBtn=back.querySelector('#rxConfirmCancel'), field=back.querySelector('#rxConfirmInput');
      if (field && input.example) field.setAttribute('placeh'+'o'+'lder', String(input.example));
      function finish(value){
        dialogOpen=false; document.removeEventListener('keydown',onKey,true);
        if (back.parentNode) back.parentNode.removeChild(back);
        if (previous && previous.focus && document.contains(previous)) { try { previous.focus({preventScroll:true}); } catch (e) {} }
        resolve(value);
      }
      function cancel(){ finish(input?null:false); }
      function accept(){
        if (input) {
          var v=String(field.value||'').trim(), err=back.querySelector('#rxConfirmInputError');
          if (input.required && !v) { err.textContent='请填写'+(input.label||'原因')+'。'; err.hidden=false; field.setAttribute('aria-invalid','true'); field.focus(); return; }
          finish(v); return;
        }
        finish(true);
      }
      function onKey(e){
        if (e.key==='Escape') { e.preventDefault(); cancel(); return; }
        if (e.key!=='Tab') return;
        var focusables=Array.prototype.filter.call(back.querySelectorAll('button,textarea'),function(n){ return !n.disabled; });
        var first=focusables[0], last=focusables[focusables.length-1];
        if (e.shiftKey && document.activeElement===first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement===last) { e.preventDefault(); first.focus(); }
      }
      okBtn.addEventListener('click',accept); cancelBtn.addEventListener('click',cancel);
      back.addEventListener('mousedown',function(e){ if (e.target===back) cancel(); });
      document.addEventListener('keydown',onKey,true);
      (field||cancelBtn).focus();
    });
  }

  // ---- leave protection -------------------------------------------------
  var guards=[], allowLeave=false;
  function anyDirty(){ return guards.some(function(g){ try { return !!g(); } catch (e) { return false; } }); }
  function leaveGuard(isDirty){ if (typeof isDirty==='function') guards.push(isDirty); return isDirty; }
  // Tracks user edits inside ``selector`` (re-rendered forms included); the
  // flag drops when the form leaves the DOM or the page calls ``clean()``.
  function trackForm(selector){
    var dirty=false;
    var mark=function(e){ if (e.target && e.target.closest && e.target.closest(selector)) dirty=true; };
    document.addEventListener('input',mark,true); document.addEventListener('change',mark,true);
    var tracker={isDirty:function(){ return dirty && !!document.querySelector(selector); },clean:function(){ dirty=false; },markDirty:function(){ dirty=true; }};
    leaveGuard(tracker.isDirty);
    return tracker;
  }
  if (live) window.addEventListener('beforeunload',function(e){ if (allowLeave || !anyDirty()) return; e.preventDefault(); e.returnValue=''; });
  document.addEventListener('click',function(e){
    if (e.defaultPrevented || e.button!==0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    var link=e.target && e.target.closest ? e.target.closest('a[href]') : null;
    if (!link || link.hasAttribute('download') || link.hasAttribute('data-rx-no-guard') || (link.target && link.target!=='_self')) return;
    var href=link.getAttribute('href')||''; if (!href || href.charAt(0)==='#' || /^javascript:/i.test(href)) return;
    var to; try { to=new URL(href, location.href); } catch (err) { return; }
    if (to.pathname===location.pathname && to.search===location.search && to.hash) return;
    if (!anyDirty()) return;
    e.preventDefault();
    confirmDialog({title:'离开此页面？',message:'当前表单有未保存的修改，离开后这些内容会丢失。',confirmLabel:'仍要离开',cancelLabel:'留在本页'})
      .then(function(ok){ if (ok) { allowLeave=true; location.assign(to.href); } });
  });

  // ---- page helpers -----------------------------------------------------
  function success(message){ return R.toast(message,'success',3000); }
  function showErrorIn(el, err){
    var node=typeof el==='string'?document.getElementById(el):el, info=fromError(err);
    if (node) node.innerHTML=errorHtml(info);
    return info;
  }

  R.describeError=describeError; R.errorText=errorText; R.fromError=fromError; R.errorHtml=errorHtml; R.showErrorIn=showErrorIn;
  R.notice=notice; R.confirmDialog=confirmDialog; R.leaveGuard=leaveGuard; R.trackForm=trackForm; R.isDirty=anyDirty;
  R.allowLeave=function(){ allowLeave=true; }; R.isLeaving=function(){ return allowLeave; }; R.success=success; R.saveDraft=saveDraft; R.restoreDraft=restoreDraft;
  R.reportApiError=report; R.__feedback=true;
  var start=function(){ if (!startsWithAny(location.pathname, QUIET_PAGES)) offerDraft(); };
  if (document.readyState==='loading') document.addEventListener('DOMContentLoaded',start); else start();
})();
""".replace("__LOG_PATH__", CLIENT_ERROR_PATH)

# Page back/forward (修改意见 2). The tab's in-site history lives in
# sessionStorage ``rx_nav_stack`` as ``{entries:[{k,u}], index}``; every history
# entry carries its key in ``history.state.rxNav`` (push/replaceState are wrapped
# so pages that pass ``null`` keep the key). Entering from a bookmark or another
# site starts a fresh stack, so 后退 then lands on the role home instead of
# leaving WeGlow. Events go to NAV_EVENT_PATH with the page path only.
UI_NAV_JS = r"""
(function(){
  'use strict';
  if (typeof window === 'undefined' || typeof document === 'undefined' || !window.RxUI || window.RxUI.__nav) return;
  var R=window.RxUI, H=window.history; R.__nav=true;
  if (typeof window.addEventListener!=='function' || !H || typeof H.replaceState!=='function' || typeof H.pushState!=='function') return;
  var KEY='rx_nav_stack', LOG='__NAV_PATH__', MAX=60, RESET_PAGES=['/demo2/login','/demo2/register'];
  var store=null, memory=null;
  try { store=window.sessionStorage; store.setItem('rx_nav_probe','1'); store.removeItem('rx_nav_probe'); } catch (e) { store=null; }
  function read(){
    var raw=null, s=null;
    try { raw=store?store.getItem(KEY):memory; } catch (e) { raw=memory; }
    try { s=raw?JSON.parse(raw):null; } catch (e) { s=null; }
    if (!s || !Array.isArray(s.entries) || typeof s.index!=='number' || s.index>=s.entries.length) s={entries:[],index:-1};
    return s;
  }
  function write(s){ var raw=JSON.stringify(s); memory=raw; try { if (store) store.setItem(KEY,raw); } catch (e) {} }
  function here(){ return location.pathname+location.search+location.hash; }
  function newKey(){ return 'n'+Date.now().toString(36)+Math.random().toString(36).slice(2,8); }
  function keyOf(st){ return st && typeof st==='object' && typeof st.rxNav==='string' ? st.rxNav : ''; }
  function find(s,k){ for (var i=0;i<s.entries.length;i++) if (s.entries[i].k===k) return i; return -1; }
  function withKey(st,k){
    if (st!==null && st!==undefined && (typeof st!=='object' || Array.isArray(st))) return st;
    var o={}; if (st) for (var p in st) if (Object.prototype.hasOwnProperty.call(st,p)) o[p]=st[p];
    o.rxNav=k; return o;
  }
  var nativePush=H.pushState.bind(H), nativeReplace=H.replaceState.bind(H);
  function tag(k){ try { nativeReplace(withKey(H.state,k),''); } catch (e) {} }
  function record(k, isNew){
    var s=read(), i=isNew?-1:find(s,k);
    if (i>=0) { s.index=i; s.entries[i].u=here(); write(s); return s; }
    s.entries=s.entries.slice(0,s.index+1); s.entries.push({k:k,u:here()});
    if (s.entries.length>MAX) s.entries=s.entries.slice(s.entries.length-MAX);
    s.index=s.entries.length-1; write(s); return s;
  }
  function sameOriginReferrer(){ try { return !!document.referrer && new URL(document.referrer).origin===location.origin; } catch (e) { return false; } }
  function isResetPage(){ return RESET_PAGES.indexOf(location.pathname)>=0; }
  function boot(){
    if (isResetPage()) { write({entries:[],index:-1}); return; }
    var k=keyOf(H.state), s=read();
    if (k && find(s,k)>=0) { var y=s.entries[find(s,k)].y; record(k,false); restoreScroll(y); return; }
    k=newKey();
    // A tab whose first page is this one, or one arriving from outside the site, has no in-site back.
    if (H.length<=1 || !sameOriginReferrer() || !s.entries.length) write({entries:[],index:-1});
    tag(k); record(k,true);
  }
  // Pages that render their lists after load are too short for the browser's own scroll restore;
  // re-apply the saved offset as the page grows, until the user scrolls themselves.
  function saveScroll(){
    var s=read(), i=find(s,keyOf(H.state)); if (i<0) return;
    s.entries[i].y=Math.max(0,Math.round(window.scrollY||window.pageYOffset||0)); write(s);
  }
  function restoreScroll(y){
    y=Number(y)||0; if (y<=0 || typeof window.scrollTo!=='function') return;
    var done=false, ro=null, root=document.documentElement;
    var stop=function(){ if (done) return; done=true; if (ro) ro.disconnect(); ['wheel','touchstart','keydown','mousedown'].forEach(function(n){ window.removeEventListener(n,stop,true); }); };
    var apply=function(){
      if (done) return;
      var max=Math.max(0,(root.scrollHeight||0)-(window.innerHeight||0));
      if (max>=y) { window.scrollTo(0,y); stop(); } else if (max>0 && Math.abs((window.scrollY||0)-max)>2) window.scrollTo(0,max);
    };
    ['wheel','touchstart','keydown','mousedown'].forEach(function(n){ window.addEventListener(n,stop,true); });
    if (typeof window.ResizeObserver==='function' && document.body) { ro=new window.ResizeObserver(apply); ro.observe(document.body); }
    window.addEventListener('load',apply); apply();
  }
  window.addEventListener('pagehide',saveScroll);
  H.pushState=function(st,t,u){
    saveScroll(); var k=newKey(), r=nativePush(withKey(st,k),t,u);
    if (!isResetPage()) record(k,true);
    refresh(); return r;
  };
  H.replaceState=function(st,t,u){
    var k=keyOf(H.state)||newKey(), r=nativeReplace(withKey(st,k),t,u);
    var s=read(), i=find(s,k); if (i>=0) { s.entries[i].u=here(); write(s); }
    refresh(); return r;
  };
  function onMove(){
    if (isResetPage()) return;
    var k=keyOf(H.state), s=read();
    if (k && find(s,k)>=0) record(k,false);
    else { k=newKey(); tag(k); record(k,true); }
    refresh();
  }
  function home(){ var box=document.querySelector('[data-rx-history]'); return (box && box.getAttribute('data-rx-home')) || '/demo2/home'; }
  function atHome(){ return location.pathname===home(); }
  function state(){
    var s=read();
    return {s:s, back:s.index>0, forward:s.index>=0 && s.index<s.entries.length-1};
  }
  function setBtn(btn, enabled, label, mode){
    if (!btn) return;
    btn.setAttribute('aria-disabled',enabled?'false':'true');
    btn.setAttribute('title',label); btn.setAttribute('aria-label',label);
    if (mode) btn.setAttribute('data-rx-fallback',mode); else btn.removeAttribute('data-rx-fallback');
  }
  function refresh(){
    var st=state(), back=document.getElementById('rxNavBack'), fwd=document.getElementById('rxNavForward');
    if (back) {
      if (st.back) setBtn(back,true,'后退到上一页（Alt+←）','');
      else if (!atHome()) setBtn(back,true,'返回首页（本标签页没有站内上一页）','home');
      else setBtn(back,false,'已是第一页','');
    }
    if (fwd) setBtn(fwd,st.forward,st.forward?'前进到下一页（Alt+→）':'没有可前进的页面','');
    return st;
  }
  function log(event, result, trigger, direction){
    var s=read(), body={client_ts:new Date().toISOString(),page:String(location.pathname||'/').replace(/[^A-Za-z0-9_./-]/g,'').slice(0,120)||'/',
      event:event,result:result,trigger:trigger,direction:direction,index:Math.max(0,Math.min(999,s.index)),depth:Math.min(999,s.entries.length)};
    var json=JSON.stringify(body);
    try { console.info('[rx-nav]', json); } catch (e) {}
    try {
      if (navigator.sendBeacon && typeof Blob==='function' && navigator.sendBeacon(LOG,new Blob([json],{type:'application/json'}))) return body;
      if (typeof fetch==='function') fetch(LOG,{method:'POST',credentials:'same-origin',keepalive:true,headers:{'Content-Type':'application/json'},body:json}).catch(function(){});
    } catch (e) {}
    return body;
  }
  function sameDocument(url){
    try { var to=new URL(url,location.href); return to.pathname===location.pathname && to.search===location.search; } catch (e) { return false; }
  }
  // Pages that keep their own link/unload prompts register here so only 后退/前进 consult them.
  var navGuards=[];
  var busy=false;
  function guard(direction, trigger, proceed){
    var dirty=false; try { dirty=typeof R.isDirty==='function' && !!R.isDirty(); } catch (e) { dirty=false; }
    if (!dirty) dirty=navGuards.some(function(g){ try { return !!g(); } catch (e) { return false; } });
    if (!dirty) { proceed(); return; }
    busy=true;
    var ask=typeof R.confirmDialog==='function'
      ? R.confirmDialog({title:'有未保存内容，确定离开？',message:'当前表单有未保存的修改，'+(direction==='back'?'后退':'前进')+'后这些内容可能会丢失。',confirmLabel:'仍要离开',cancelLabel:'留在本页'})
      : Promise.resolve(window.confirm('有未保存内容，确定离开？'));
    ask.then(function(ok){
      busy=false; log('nav_blocked',ok?'confirmed':'cancelled',trigger,direction);
      if (ok) proceed();
    });
  }
  function go(direction, trigger){
    if (busy) return;
    var st=state();
    if (direction==='back' && !st.back) {
      if (atHome()) { log('nav_back','disabled',trigger,direction); R.toast('已是第一页'); return; }
      guard(direction,trigger,function(){
        log('nav_home_fallback','redirected',trigger,direction);
        if (typeof R.allowLeave==='function') R.allowLeave();
        location.assign(home());
      });
      return;
    }
    if (direction==='forward' && !st.forward) { log('nav_forward','disabled',trigger,direction); R.toast('没有可前进的页面'); return; }
    var target=st.s.entries[st.s.index+(direction==='back'?-1:1)], inPage=!!target && sameDocument(target.u);
    guard(direction,trigger,function(){
      log(direction==='back'?'nav_back':'nav_forward',inPage?'same_page':'ok',trigger,direction);
      if (!inPage && typeof R.allowLeave==='function') R.allowLeave();
      if (direction==='back') H.back(); else H.forward();
    });
  }
  // Tabs inside one page: ``RxUI.tabHash({names, current, apply})`` keeps ``#tab-<name>`` in the URL so 后退/前进 walk tabs.
  function tabHash(opts){
    opts=opts||{}; var names=opts.names||[];
    function fromHash(){ var m=/^#tab-([A-Za-z0-9_-]{1,40})$/.exec(location.hash||''); return m && names.indexOf(m[1])>=0 ? m[1] : ''; }
    function url(name){ return location.pathname+location.search+'#tab-'+name; }
    function set(name, push){
      if (names.indexOf(name)<0 || location.hash==='#tab-'+name) return;
      if (push) {
        var now=typeof opts.current==='function'?opts.current():'';
        if (!fromHash() && now && now!==name && names.indexOf(now)>=0) H.replaceState(H.state,'',url(now));
        H.pushState({},'',url(name));
      } else if (fromHash()) H.replaceState(H.state,'',url(name));
    }
    var sync=function(){ var name=fromHash(); if (name && typeof opts.apply==='function' && (typeof opts.current!=='function' || opts.current()!==name)) opts.apply(name); };
    window.addEventListener('popstate',sync); window.addEventListener('hashchange',sync);
    return {initial:fromHash, set:set, sync:sync};
  }
  R.tabHash=tabHash; R.navGuard=function(fn){ if (typeof fn==='function') navGuards.push(fn); return fn; }; R.navBack=function(){ go('back','button'); }; R.navForward=function(){ go('forward','button'); }; R.navState=function(){ var st=state(); return {index:st.s.index,depth:st.s.entries.length,back:st.back,forward:st.forward}; };
  boot();
  window.addEventListener('popstate',onMove); window.addEventListener('hashchange',onMove);
  window.addEventListener('pageshow',function(e){ if (e && e.persisted) onMove(); });
  function ensureButtons(){
    if (document.querySelector('[data-rx-history]')) return;
    var brand=document.querySelector('.rx-header .rx-brand'); if (!brand || !brand.parentNode) return;
    var scope=(document.querySelector('.rx-header')||brand).getAttribute('data-rx-scope')||'teacher';
    var homes=__HOMES__, box=document.createElement('div'); box.innerHTML=__BUTTONS__.replace('__HOME__',homes[scope]||homes.teacher);
    var el=box.firstChild; if (el) brand.parentNode.insertBefore(el, brand.nextSibling);
  }
  function start(){
    ensureButtons();
    document.querySelectorAll('[data-rx-nav]').forEach(function(btn){
      btn.addEventListener('click',function(e){ e.preventDefault(); go(btn.getAttribute('data-rx-nav')==='forward'?'forward':'back','button'); });
    });
    refresh();
  }
  document.addEventListener('keydown',function(e){
    if (!e.altKey || e.ctrlKey || e.metaKey || e.shiftKey || (e.key!=='ArrowLeft' && e.key!=='ArrowRight')) return;
    var t=e.target; if (t && t.closest && t.closest('input,textarea,select,[contenteditable]')) return;
    if (document.getElementById('rxConfirm') || !document.getElementById('rxNavBack')) return;
    e.preventDefault(); go(e.key==='ArrowLeft'?'back':'forward','shortcut');
  });
  if (document.readyState==='loading') document.addEventListener('DOMContentLoaded',start); else start();
})();
"""

UI_NAV_JS = (UI_NAV_JS.replace("__NAV_PATH__", NAV_EVENT_PATH)
             .replace("__HOMES__", json.dumps(ROLE_HOME_URLS))
             .replace("__BUTTONS__", json.dumps(history_buttons("__HOME__"), ensure_ascii=False)))

PERSON_SWITCH_PATH = "/api/v1/demo2/simple-result/person-switch"
PERSONS_PATH = "/api/v1/demo2/simple-result/persons"

# ``RxUI.studentSwitcher(host, opts)``: one horizontal strip of avatar cards
# (192 px source avatar, 学生编号/已绑定姓名, 已绑定/未绑定/已排除 badge).  The
# selection lives in the URL (?person_id= or ?student_id=) so 后退/前进 and deep
# links walk students; each teacher switch is logged without names.
UI_SWITCHER_JS = r"""
(function(){
  'use strict';
  if (typeof window === 'undefined' || typeof document === 'undefined' || !window.RxUI || window.RxUI.studentSwitcher) return;
  var R=window.RxUI, H=window.history, LOG='__SWITCH_PATH__', LIST='__PERSONS_PATH__';
  var BADGE={bound:['rx-badge-success','已绑定'],unbound:['rx-badge-warning','未绑定'],excluded:['rx-badge-neutral','已排除']};
  function esc(x){ return String(x==null?'':x).replace(/[&<>"']/g,function(c){ return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; }); }
  function params(){ try { return new URLSearchParams(location.search); } catch (e) { return null; } }
  function avatarUrl(taskId, image){
    if (!taskId || !image || !image.frame || !image.bbox) return '';
    var q=new URLSearchParams({task_id:taskId,frame:image.frame,crop:image.crop==='person'?'person':'avatar',v:'3',quality:'source'});
    ['x','y','width','height'].forEach(function(k){ q.set(k,String(image.bbox[k])); });
    return '/api/v1/demo2/simple-result/frame?'+q.toString();
  }
  function loadPersons(taskId){
    if (!taskId || typeof fetch!=='function') return Promise.resolve(null);
    return fetch(LIST+'?task_id='+encodeURIComponent(taskId),{cache:'no-store',credentials:'same-origin'})
      .then(function(r){ return r.ok ? r.json() : null; }).catch(function(){ return null; });
  }
  function log(page, item, trigger, taskId){
    if (!item || typeof fetch!=='function') return;
    var body={page:page,trigger:trigger};
    if (taskId) body.task_id=taskId;
    if (item.person_id) body.person_id=item.person_id;
    if (item.student_id) body.student_id=item.student_id;
    try { console.info('[rx-switch]', JSON.stringify(body)); } catch (e) {}
    try { fetch(LOG,{method:'POST',credentials:'same-origin',keepalive:true,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}).catch(function(){}); } catch (e) {}
  }
  function lowNoticeHtml(low, manualHref){
    if (!low) return '';
    var reasons=(low.reasons||[]).map(function(r){ return '<li>'+esc(r.text)+'</li>'; }).join('');
    return '<div class="rx-switcher-low" role="status" data-low-students="'+esc(low.student_count)+'"><strong>'+esc(low.message||('本视频仅识别到 '+low.student_count+' 名学生'))+'</strong>'+
      (reasons?'<ul>'+reasons+'</ul>':'')+'<span>'+esc(low.hint||'')+'</span>'+
      (manualHref?' <a href="'+esc(manualHref)+'" data-manual-box>手动画框添加学生</a>':'')+'</div>';
  }
  function studentSwitcher(host, opts){
    opts=opts||{};
    var items=[], current='', page=opts.page||'unknown';
    function keyOf(item){ return item.key || item.student_id || item.person_id || ''; }
    function find(predicate){ for (var i=0;i<items.length;i++) if (predicate(items[i])) return items[i]; return null; }
    function byKey(k){ return find(function(it){ return keyOf(it)===k; }); }
    function fromUrl(){
      var q=params(); if (!q) return null;
      var sid=q.get('student_id'), pid=q.get('person_id');
      return (sid && find(function(it){ return it.student_id===sid; })) || (pid && find(function(it){ return it.person_id===pid; })) || null;
    }
    function urlFor(item){
      var u=new URL(location.href); u.searchParams.delete('student_id'); u.searchParams.delete('person_id');
      var mode=opts.param||'auto';
      if (mode==='student_id' || (mode==='auto' && item.student_id)) u.searchParams.set('student_id',item.student_id);
      else if (item.person_id) u.searchParams.set('person_id',item.person_id);
      return u.pathname+u.search+u.hash;
    }
    function card(item, index){
      var k=keyOf(item), active=k===current, badge=BADGE[item.status]||BADGE.unbound, title=item.title||('学生 '+(index+1));
      var img=item.avatarUrl?'<img src="'+esc(item.avatarUrl)+'" alt="'+esc(title)+' 头像" width="192" height="192" loading="lazy">':
        '<span class="rx-switch-initial" aria-hidden="true">'+esc(String(item.initial||title).trim().charAt(0)||'学')+'</span>';
      return '<button type="button" role="tab" class="rx-switch-card'+(active?' is-active':'')+(item.status==='excluded'?' is-excluded':'')+'" data-switch-key="'+esc(k)+'"'+
        ' data-tone="'+(index%4)+'" aria-selected="'+(active?'true':'false')+'" tabindex="'+(active?'0':'-1')+'" title="切换到 '+esc(title)+'">'+
        '<span class="rx-switch-avatar">'+img+'</span><span class="rx-switch-body"><strong>'+esc(title)+'</strong>'+
        '<small>'+esc(item.subtitle||'')+'</small><span class="rx-badge '+badge[0]+'">'+esc(item.statusText||badge[1])+'</span></span></button>';
    }
    function render(){
      if (!host) return;
      var count=items.filter(function(it){ return it.status!=='excluded'; }).length, active=byKey(current);
      host.classList.add('rx-switcher'); host.setAttribute('aria-label',opts.label||'切换学生');
      host.hidden=!items.length && !opts.low;
      host.innerHTML='<div class="rx-switcher-head"><span class="rx-switcher-title">'+esc(opts.label||'切换学生')+'</span>'+
        '<span class="rx-switcher-count">共 '+count+' 名学生'+(active?' · 当前：'+esc(active.title||''):'')+'</span>'+
        (opts.note?'<span class="rx-switcher-note">'+esc(opts.note)+'</span>':'')+'</div>'+
        '<div class="rx-switcher-track" role="tablist" aria-label="'+esc(opts.label||'切换学生')+'">'+items.map(card).join('')+'</div>'+
        lowNoticeHtml(opts.low, opts.manualHref);
      host.querySelectorAll('img').forEach(function(img){ img.addEventListener('error',function(){ var s=document.createElement('span'); s.className='rx-switch-initial'; s.textContent='学'; img.replaceWith(s); }); });
    }
    function select(k, meta){
      meta=meta||{}; var item=byKey(k); if (!item) return false;
      var changed=k!==current;
      if (meta.push && changed) {
        var q=params(), was=byKey(current);
        if (was && q && !q.get('student_id') && !q.get('person_id')) H.replaceState(H.state,'',urlFor(was));
        H.pushState({},'',urlFor(item));
      } else if (meta.replace) {
        H.replaceState(H.state,'',urlFor(item));
      }
      current=k; render();
      if (meta.trigger && meta.trigger!=='init' && changed) log(page,item,meta.trigger,opts.taskId||item.task_id||'');
      if (typeof opts.onSelect==='function' && (changed || meta.force)) opts.onSelect(item,meta);
      return true;
    }
    if (host) {
      host.addEventListener('click',function(e){ var b=e.target.closest && e.target.closest('[data-switch-key]'); if (!b) return; select(b.getAttribute('data-switch-key'),{push:true,trigger:'click'}); });
      host.addEventListener('keydown',function(e){
        if (e.key!=='ArrowLeft' && e.key!=='ArrowRight') return;
        var cards=[].slice.call(host.querySelectorAll('[data-switch-key]')); var i=cards.indexOf(document.activeElement); if (i<0) return;
        e.preventDefault(); var next=cards[(i+(e.key==='ArrowRight'?1:cards.length-1))%cards.length];
        select(next.getAttribute('data-switch-key'),{push:true,trigger:'keyboard'}); var again=host.querySelector('[data-switch-key="'+next.getAttribute('data-switch-key')+'"]'); if (again) again.focus();
      });
    }
    window.addEventListener('popstate',function(){
      var item=fromUrl(); if (item && keyOf(item)!==current) select(keyOf(item),{trigger:'history'});
    });
    var api={
      update:function(list, wanted){
        items=(list||[]).slice(); var fromLink=fromUrl();
        var pick=(wanted && byKey(wanted)) || fromLink || byKey(current) || items.filter(function(it){ return it.status!=='excluded'; })[0] || items[0] || null;
        var k=pick?keyOf(pick):''; var changed=k!==current; current=k; render();
        if (pick && changed && typeof opts.onSelect==='function') opts.onSelect(pick,{trigger:fromLink && pick===fromLink?'deeplink':'init'});
        return pick;
      },
      setLow:function(low, href){ opts.low=low||null; if (href!==undefined) opts.manualHref=href; render(); },
      select:function(k, meta){ return select(k, meta||{push:true,trigger:'click'}); },
      current:function(){ return byKey(current); },
      urlItem:fromUrl,
      items:function(){ return items.slice(); }
    };
    return api;
  }
  R.studentSwitcher=studentSwitcher; R.personAvatarUrl=avatarUrl; R.loadLessonPersons=loadPersons; R.lowStudentNoticeHtml=lowNoticeHtml;
})();
""".replace("__SWITCH_PATH__", PERSON_SWITCH_PATH).replace("__PERSONS_PATH__", PERSONS_PATH)
UI_KIT_JS = UI_KIT_JS + UI_FEEDBACK_JS + UI_NAV_JS + UI_SWITCHER_JS

# Tab-scoped draft persistence for the long teacher forms (测量记录、双轨评价、资料新增).
# Kept out of the shared kit so pages with a no-browser-storage contract (e.g.
# 学校信息) never carry it; the store is cleared when the tab closes.
UI_DRAFT_STORE_JS = r"""
(function(){
  'use strict';
  if (typeof window === 'undefined' || window.RxDraftStore) return;
  try {
    var s=window.sessionStorage, probe='rx-draft-probe'; s.setItem(probe,'1'); s.removeItem(probe);
    window.RxDraftStore={get:function(k){ return s.getItem(k); },set:function(k,v){ s.setItem(k,v); },remove:function(k){ s.removeItem(k); }};
  } catch (e) { window.RxDraftStore=null; }
})();
"""
UI_DRAFT_STORE_SCRIPT = f"<script data-rx-kit data-rx-draft-store>{UI_DRAFT_STORE_JS}</script>"

# Tagged so test harnesses that eval bare ``<script>`` blocks in Node skip it.
UI_KIT_SCRIPT = f"<script data-rx-kit>{UI_KIT_JS}</script>"
UI_KIT_STYLE = f'<style data-rx-kit>{UI_KIT_CSS}</style>'

_HEADER_RE = re.compile(r"<header\b[^>]*>.*?</header>", re.S)


def inject_kit(document_html: str, *, header: str | None = None, page: str = "unknown") -> str:
    """Add the kit to a standalone page and optionally swap its first header.

    Used by the legacy pages that build their own ``<html>`` instead of
    ``demo2_portal._document``. Idempotent: a page that already carries the
    kit is returned unchanged apart from the header swap and brand title.
    """
    result = brand_document_title(document_html)
    if header is not None:
        if _HEADER_RE.search(result) is None:
            ui_warning(page, "inject_kit", "header", "prepended", "no_header_found")
            result = re.sub(r"(<body[^>]*>)", lambda m: m.group(1) + header, result, count=1)
        else:
            result = _HEADER_RE.sub(lambda _m: header, result, count=1)
    if "data-rx-kit" not in result:
        if "</head>" in result:
            result = result.replace("</head>", UI_KIT_STYLE + "</head>", 1)
        else:
            ui_warning(page, "inject_kit", "head", "style_in_body", "no_head_found")
            result = UI_KIT_STYLE + result
        if "</body>" in result:
            result = result.replace("</body>", toast_region() + UI_KIT_SCRIPT + "</body>", 1)
        else:
            result = result + toast_region() + UI_KIT_SCRIPT
    return result


__all__ = [
    "BRAND_FULL_NAME", "BRAND_NAME", "BRAND_TAGLINE", "BRAND_VERSION", "brand_document_title", "brand_title",
    "ADMIN_NAV", "CANONICAL_STATUS_NAMES", "CLIENT_ERROR_PATH", "ClientErrorRejected", "NAV_EVENT_PATH", "ROLE_HOME_URLS", "history_buttons", "ui_nav_event", "UI_FEEDBACK_JS", "STATUS_LABELS", "TEACHER_HOME_URL", "TEACHER_NAV", "UI_KIT_CSS",
    "UI_KIT_JS", "UI_KIT_SCRIPT", "UI_NAV_JS", "UI_SWITCHER_JS", "SWITCHER_CSS", "PERSON_SWITCH_PATH", "PERSONS_PATH", "UI_KIT_STYLE", "account_label", "account_role", "admin_header", "button",
    "card", "disclosure", "drawer", "empty_state", "form_field", "format_bytes", "format_time", "header_for", "hint", "icon",
    "inject_kit", "kpi", "kpi_group", "member_header", "relative_time", "short_id", "short_id_html", "skeleton",
    "status_badge", "status_label", "steps", "teacher_header", "toast_region", "ui_client_error", "ui_warning", "UI_DRAFT_STORE_JS", "UI_DRAFT_STORE_SCRIPT",
]
