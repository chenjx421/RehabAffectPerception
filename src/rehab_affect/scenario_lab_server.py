from __future__ import annotations

import argparse
import copy
import gzip
import importlib
import inspect
import json
import mimetypes
import math
import os
import re
import sys
import time
import traceback
from collections import OrderedDict, deque
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import BoundedSemaphore, Event, Lock, Thread
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

from .closed_loop import run_closed_loop_scenario
from .sim_runner import (
    DEFAULT_LEARNED_POLICY_PATH,
    DEFAULT_SCENARIO_DIR,
    KinematicClassroomBackend,
    _batch_from_step,
    _context_from_step,
    build_policy,
    load_scenario,
    run_scenario,
)
from .pipeline import RehabAffectPipeline
from .education_demo import (
    list_education_clips,
    render_education_demo_html,
    run_education_demo_json,
)
from .seewo_student_demo import OUTPUT_DIR as SEEWO_STUDENT_DEMO_OUTPUT_DIR
from .seewo_student_demo import load_seewo_student_demo, render_seewo_student_demo_html
from .seewo_multi_student_demo import OUTPUT_DIR as SEEWO_DEMO2_OUTPUT_DIR
from .seewo_multi_student_demo import load_seewo_demo2, render_seewo_demo2_html
from .seewo_long_report import (
    build_long_course_report,
    load_teacher_reviews,
    report_writer_status,
    save_teacher_reviews,
)
from .student_record_store import (
    MAX_VIDEO_CHUNK_BYTES,
    REGISTRATION_WINDOW_SECONDS,
    RegistrationRateLimitError,
    VideoUploadError,
    get_demo2_student_store,
)
from .showcase import render_showcase_html
from .demo2_media_cache import MediaResultCache
from .demo2_upload_debug import task_fields as _upload_task_fields
from .demo2_upload_debug import upload_debug_event
from .demo2_admin_debug import admin_debug_event


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787
MUJOCO_FRAME_DIR = PROJECT_ROOT / "outputs" / "mujoco_frames"
DEMO2_API_PREFIX = "/api/v1/demo2"
DEMO2_SESSION_COOKIE = "rehab_demo2_session"
DEMO2_SESSION_MAX_AGE = 8 * 60 * 60
DEMO2_PUBLIC_ASSET_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
DEMO2_STUDENT_ROLES = frozenset({"school_uploader", "company_admin"})
DEMO2_IDENTITY_API_PREFIX = f"{DEMO2_API_PREFIX}/identity"
DEMO2_IDENTITY_DETECT_MIN_INTERVAL = 2.0
DEMO2_IDENTITY_DETECT_WINDOW = 60.0
DEMO2_IDENTITY_DETECT_LIMIT = 12
DEMO2_IDENTITY_DETECT_CACHE_TTL = 120.0
DEMO2_IDENTITY_PREVIEW_CACHE_TTL = 60.0
DEMO2_DOSSIER_API_PREFIX = f"{DEMO2_API_PREFIX}/dossier"
DEMO2_SUMMARY_API_PREFIX = f"{DEMO2_API_PREFIX}/student-summaries"
DEMO2_DOSSIER_MAX_BODY = 12 * 1024 * 1024
DEMO2_DOSSIER_MAX_FILE = 8 * 1024 * 1024
DEMO2_DOSSIER_CLEANUP_SECONDS = 30.0
DEMO2_LEGACY_PRIVATE_PATHS = frozenset({
    "/api/seewo_demo2/student_record", "/api/seewo_demo2/student_document",
    "/api/seewo_demo2/support_profile", "/api/seewo_demo2/document_download",
    "/api/seewo_demo2/document_delete", "/api/seewo_demo2/storage",
    "/api/seewo_demo2/storage_policy", "/api/seewo_demo2/archive_video_result",
    "/api/seewo_demo2/video_channels", "/api/seewo_demo2_reviews", "/api/seewo_demo2_long_report",
})
DEMO2_DOSSIER_MIMES = {
    ".pdf": "application/pdf", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".txt": "text/plain",
}
DISCONNECTED_PEER_ERRORS = (BrokenPipeError, ConnectionAbortedError, ConnectionResetError)


class Demo2APIError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class _DossierMaintenance:
    """Sweep scoped dossiers and safety events, never legacy data."""

    def __init__(self, cleanup: Any, *, safety_cleanup: Any = None, summary_cleanup: Any = None,
                 interval: float = DEMO2_DOSSIER_CLEANUP_SECONDS):
        if not 0 < interval <= 60:
            raise ValueError("Dossier cleanup interval must be between 0 and 60 seconds")
        self.cleanup = cleanup
        self.safety_cleanup = safety_cleanup
        self.summary_cleanup = summary_cleanup
        self.interval = interval
        self.stopped = Event()
        self.thread = Thread(target=self._run, name="demo2-dossier-retention", daemon=True)

    def _run(self) -> None:
        while not self.stopped.is_set():
            started = time.monotonic()
            for name, cleanup in (("Dossier", self.cleanup), ("Safety", self.safety_cleanup),
                                  ("Student summary", self.summary_cleanup)):
                if not callable(cleanup):
                    continue
                try:
                    report = cleanup()
                    if name == 'Student summary' and isinstance(report, dict):
                        automatic = report.get('automatic_history')
                        errors = automatic.get('errors') if isinstance(automatic, dict) else None
                        if type(errors) is int and errors > 0:
                            print(f'Student summary automatic archive pending retry ({errors}).',
                                  file=sys.stderr, flush=True)
                except Exception:
                    # One repository's failure must not skip the other sweep.
                    # Never log exception text, key state, reference text or paths.
                    print(f"{name} cleanup unavailable; retry scheduled", file=sys.stderr, flush=True)
            self.stopped.wait(max(0, self.interval - (time.monotonic() - started)))

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stopped.set()
        if self.thread.ident is not None:
            self.thread.join()  # Finish the current sweep before closing the service.


def _legacy_dossier_notice() -> str:
    return """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>历史资料待核对</title>
<style>
:root{color-scheme:light;--ink:#17354f;--muted:#526a80;--blue:#155d98;--line:#cee0ef;--paper:#fff}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);
font:16px/1.8 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
main{width:min(100% - 40px,760px);margin:64px auto;padding:0 0 32px;overflow-wrap:anywhere}
h1{font-size:24px;line-height:1.5;font-weight:600;color:var(--blue);margin:0 0 24px;padding-bottom:16px;border-bottom:1px solid var(--line)}
p{margin:0 0 16px;color:var(--muted)}nav{display:flex;flex-wrap:wrap;gap:8px 24px;margin-top:24px}
a{display:inline-flex;align-items:center;min-height:44px;color:var(--blue);text-underline-offset:4px}
a:hover{text-decoration-thickness:2px}a:focus-visible{outline:3px solid var(--blue);outline-offset:4px}
@media(max-width:520px){main{margin:32px auto}h1{font-size:21px}nav{display:grid;gap:8px}}
</style></head><body><main><h1>历史全局案例与资料入口已停用</h1>
<p>旧源码与数据完整保留。由于尚未建立账号、学生与授权之间的对应关系，历史资料暂不在线开放。</p>
<p>旧资料未迁移、未认领给任何账号，也未删除。请先核对正确学生及学校授权，再通过独立学生档案重新导入。仅凭姓名不能关联历史资料。</p>
<nav aria-label="返回平台"><a href="/demo2/students">返回学生名册</a><a href="/demo2/upload">返回上传工作区</a>
<a href="/demo2/admin/dossiers">资料运行统计</a></nav></main></body></html>"""


def _is_retired_legacy_data_path(path: str) -> bool:
    return (path in DEMO2_LEGACY_PRIVATE_PATHS
            or path.startswith("/api/seewo_student_demo")
            or path.startswith("/assets/seewo_demo2/")
            or path.startswith("/assets/seewo_xiaoyudi_demo/"))


def _public_dossier_admin_summary(summary: Any) -> dict[str, Any]:
    """Project only operational fields; never pass through source metadata."""
    totals = ("authorization_count", "active_authorization_count", "document_count", "available_document_count",
              "expired_document_count", "deletion_pending_count", "reference_count", "encrypted_file_bytes")
    channel_fields = ("channel_no", "document_count", "available_document_count", "deletion_pending_count", "encrypted_file_bytes")
    try:
        result = {"totals": {key: summary["totals"][key] for key in totals},
                  "channels": [{key: row[key] for key in channel_fields} for row in summary["channels"]],
                  "policy": {key: summary["policy"][key] for key in ("max_retention_days", "training_allowed", "raw_documents_visible")},
                  "vault": {key: summary["vault"][key] for key in ("available", "mode")}}
        counts = [*result["totals"].values(), *(value for row in result["channels"] for value in row.values())]
        if (any(type(value) is not int or value < 0 for value in counts)
                or result["policy"] != {"max_retention_days": 60, "training_allowed": False, "raw_documents_visible": False}
                or type(result["vault"]["available"]) is not bool
                or not isinstance(result["vault"]["mode"], str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", result["vault"]["mode"])):
            raise ValueError
        return result
    except (KeyError, TypeError, ValueError):
        raise Demo2APIError(503, "dossier_unavailable", "资料统计暂不可用，请稍后重试") from None


def _log_demo2_get_failure(error: Exception) -> None:
    """Local diagnostics only: exception type/OS code and stack locations.

    Do not format exception messages, source lines, frame locals, URLs, cookies
    or bodies: any of those may contain caller data or private media filenames.
    """
    details = [f"Demo2 GET unexpected failure: {type(error).__name__} pid={os.getpid()}"]
    for name in ("errno", "winerror"):
        value = getattr(error, name, None)
        if isinstance(value, int):
            details.append(f"{name}={value}")
    for frame, line in traceback.walk_tb(error.__traceback__):
        details.append(f'  File "{frame.f_code.co_filename}", line {line}, in {frame.f_code.co_name}')
    try:
        print("\n".join(details), file=sys.stderr, flush=True)
    except OSError:
        pass  # Diagnostics must not replace the existing safe API response.


def _account_value(account: Any, key: str, default: Any = "") -> Any:
    if isinstance(account, dict):
        return account.get(key, default)
    return getattr(account, key, default)


def _account_id(account: Any) -> str:
    return str(_account_value(account, "account_id", "")).strip()


def _account_role(account: Any) -> str:
    return str(_account_value(account, "role", "")).strip()


def _public_account(account: Any) -> dict[str, Any]:
    if isinstance(account, dict):
        source = account
    else:
        source = {
            key: getattr(account, key)
            for key in dir(account)
            if not key.startswith("_") and not callable(getattr(account, key))
        }
    blocked_fragments = ("password", "secret", "hash", "session_token")
    return {
        str(key): value
        for key, value in source.items()
        if not any(fragment in str(key).lower() for fragment in blocked_fragments)
    }


def _session_token(session: Any) -> str:
    if isinstance(session, str):
        return session.strip()
    if isinstance(session, dict):
        for key in ("token", "session_token"):
            token = str(session.get(key, "")).strip()
            if token:
                return token
    return ""


def _render_admin_analysis_guide() -> str:
    """Static task-selection guide for admins opening /demo2/analysis bare."""
    return (
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>请选择课堂任务 · RehabAffect</title>"
        "<style>body{margin:0;font-family:'Microsoft YaHei','PingFang SC','Segoe UI',sans-serif;"
        "background:#f3f7fc;color:#102a43}main{max-width:620px;margin:12vh auto;padding:32px;"
        "background:#fff;border:1px solid #d9e3f0;border-radius:10px}h1{margin:0 0 12px;font-size:24px}"
        "p{line-height:1.7;color:#486581}a{display:inline-block;margin-top:8px;padding:9px 16px;"
        "border-radius:6px;background:#1559c7;color:#fff;text-decoration:none}</style></head><body>"
        "<main id='adminAnalysisGuide'><h1>请选择课堂任务</h1>"
        "<p><strong>请从任务记录进入。</strong>公司后台需要从「任务查询」或「近期上传」中的任务记录打开分析页面，"
        "未指定任务时不读取任何课堂数据。</p>"
        "<p><a href='/demo2/admin#taskQueryTitle'>返回公司后台任务查询</a></p></main></body></html>"
    )


def _render_demo2_portal_page(page: str, account: Any | None = None) -> str:
    if page == "help":
        help_page = importlib.import_module(".demo2_help_page", package=__package__)
        return str(help_page.render_help())
    if page in {"dossier", "course-dossier", "admin-dossiers"}:
        dossier = importlib.import_module(".demo2_dossier", package=__package__)
        name = {"dossier": "render_student", "course-dossier": "render_task", "admin-dossiers": "render_admin"}[page]
        return str(getattr(dossier, name)(account))
    if page in {"students", "identity"}:
        identity = importlib.import_module(".demo2_identity", package=__package__)
        return str(getattr(identity, f"render_{page}")(account=account))
    if page == "membership":
        entry = importlib.import_module(".demo2_entry", package=__package__)
        return str(entry.render_membership(account=account))
    portal = importlib.import_module(".demo2_portal", package=__package__)
    renderer_names = {
        "login": ("render_demo2_login_html", "render_login_html", "render_login_page"),
        "upload": ("render_demo2_upload_html", "render_upload_html", "render_upload_page"),
        "admin": ("render_demo2_admin_html", "render_admin_html", "render_admin_page"),
        "register": ("render_demo2_register_html",),
        "privacy": ("render_demo2_privacy_html",),
        "school": ("render_demo2_school_html",),
        "video": ("render_demo2_video_html",),
    }
    for name in renderer_names[page]:
        renderer = getattr(portal, name, None)
        if not callable(renderer):
            continue
        parameters = inspect.signature(renderer).parameters
        if "account" in parameters:
            return str(renderer(account=account))
        return str(renderer())
    raise RuntimeError(f"demo2_portal does not provide a renderer for {page}")


def _bound_channel_ids(account: Any, workspace: Any) -> set[str]:
    channel_ids: set[str] = set()
    singular_keys = (
        "channel_id",
        "bound_channel_id",
        "assigned_channel_id",
        "upload_channel_id",
    )
    plural_keys = ("channel_ids", "allowed_channel_ids")

    def collect(value: Any) -> None:
        if isinstance(value, str):
            if value.strip():
                channel_ids.add(value.strip())
            return
        if isinstance(value, dict):
            for key in singular_keys:
                collect(value.get(key))
            for key in plural_keys:
                collect(value.get(key))
            for key in ("channel", "upload_channel", "channels", "upload_channels", "allowed_channels"):
                collect(value.get(key))
            return
        if isinstance(value, (list, tuple, set)):
            for item in value:
                collect(item)

    collect(account)
    collect(workspace)
    return channel_ids


def _workspace_has_task(workspace: Any, task_id: str, account_id: str) -> bool:
    if isinstance(workspace, dict):
        if str(workspace.get("task_id", "")).strip() == task_id:
            owner = str(workspace.get("account_id", "")).strip()
            return not owner or owner == account_id
        return any(_workspace_has_task(value, task_id, account_id) for value in workspace.values())
    if isinstance(workspace, (list, tuple)):
        return any(_workspace_has_task(value, task_id, account_id) for value in workspace)
    return False


def _workspace_quota_exhausted(workspace: Any) -> bool:
    if not isinstance(workspace, dict):
        return False
    quota = workspace.get("quota")
    if not isinstance(quota, dict):
        quota = workspace
    try:
        if "remaining_slots" in quota:
            return int(quota["remaining_slots"]) <= 0
        if "used_slots" in quota and "max_slots" in quota:
            return int(quota["used_slots"]) >= int(quota["max_slots"])
    except (TypeError, ValueError):
        return False
    return False


def _is_quota_error(error: Exception) -> bool:
    message = str(error).lower()
    return any(marker in message for marker in ("quota", "名额已满", "上传名额", "配额"))


def _is_protected_legacy_demo2_path(path: str) -> bool:
    # Demo1 also contains original classroom media; membership must not expose
    # those older URLs as a side door around the Demo2 authorization checks.
    return (
        path.startswith("/api/seewo_student_demo")
        or path.startswith("/api/seewo_demo2")
        or path.startswith("/assets/seewo_demo2/")
        or path.startswith("/assets/seewo_xiaoyudi_demo/")
    )


def _remove_physical_paths(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            normalized = str(key).lower()
            if (
                normalized in {"location", "path"}
                or normalized.endswith("_path")
                or normalized.endswith("_dir")
                or normalized.endswith("_location")
            ):
                continue
            cleaned[key] = _remove_physical_paths(item)
        return cleaned
    if isinstance(value, list):
        return [_remove_physical_paths(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_remove_physical_paths(item) for item in value)
    return value


def _channels_for_account(payload: dict[str, Any], account: Any) -> dict[str, Any]:
    """Keep legacy channel responses inside the signed-in account boundary."""
    if _account_role(account) != "school_uploader":
        return payload
    bound_channel_id = str(_account_value(account, "bound_channel_id", "")).strip()
    filtered = dict(payload)
    filtered["channels"] = [
        channel
        for channel in payload.get("channels", [])
        if str(channel.get("channel_id", "")).strip() == bound_channel_id
    ]
    filtered["mode"] = "当前账号的独立上传通道"
    return filtered


def list_scenarios(scenario_dir: Path = DEFAULT_SCENARIO_DIR) -> list[dict[str, Any]]:
    scenarios = []
    for path in sorted(scenario_dir.glob("*.json")):
        scenario = load_scenario(path)
        scenarios.append(
            {
                "scenario_id": scenario.get("scenario_id"),
                "task": scenario.get("task"),
                "description": scenario.get("description"),
                "step_count": len(scenario.get("steps", [])),
                "path": str(path),
            }
        )
    return scenarios


def mujoco_assets_for_scenario(scenario_id: str, frame_dir: Path = MUJOCO_FRAME_DIR) -> dict[str, Any]:
    frame_paths = sorted(frame_dir.glob(f"{scenario_id}_step_*.png"))
    contact_sheet = frame_dir / f"{scenario_id}_contact_sheet.png"
    return {
        "scenario_id": scenario_id,
        "frames": [
            {
                "step": _step_number_from_frame(path),
                "url": f"/assets/mujoco_frames/{path.name}",
                "path": str(path),
                "exists": path.exists(),
            }
            for path in frame_paths
        ],
        "contact_sheet": {
            "url": f"/assets/mujoco_frames/{contact_sheet.name}",
            "path": str(contact_sheet),
            "exists": contact_sheet.exists(),
        },
    }


def _step_number_from_frame(path: Path) -> int:
    try:
        return int(path.stem.rsplit("_step_", 1)[1])
    except (IndexError, ValueError):
        return -1


def load_scenario_by_id(scenario_id: str, scenario_dir: Path = DEFAULT_SCENARIO_DIR) -> dict[str, Any]:
    for path in sorted(scenario_dir.glob("*.json")):
        scenario = load_scenario(path)
        if scenario.get("scenario_id") == scenario_id:
            return scenario
    raise KeyError(f"Scenario not found: {scenario_id}")


def process_edited_step(
    step: dict[str, Any],
    *,
    policy_name: str = "learned",
    model_path: Path = DEFAULT_LEARNED_POLICY_PATH,
    person_id: str = "student_001",
) -> dict[str, Any]:
    robot_policy = build_policy(policy_name, model_path)
    pipeline = RehabAffectPipeline(
        person_id=person_id,
        smooth_window=1,
        robot_policy=robot_policy,
    )
    context = _context_from_step(step)
    result = pipeline.process_batch(_batch_from_step(step), robot_context=context)
    post_context = KinematicClassroomBackend().apply_action(context, result.robot_action)
    return {
        "step": step.get("step", 0),
        "ground_truth_state": step.get("ground_truth_state"),
        "expected_action_id": step.get("expected_action_id"),
        "observable_cues": step.get("observable_cues", {}),
        "human_state": result.human_state.to_dict(),
        "robot_context": context.to_dict(),
        "robot_action": result.robot_action.to_dict(),
        "post_action_context": post_context.to_dict(),
        "action_match": result.robot_action.action_id == step.get("expected_action_id"),
    }


def process_closed_loop_scenario(
    scenario: dict[str, Any],
    *,
    policy_name: str = "learned",
    model_path: Path = DEFAULT_LEARNED_POLICY_PATH,
    person_id: str = "student_001",
) -> dict[str, Any]:
    return run_closed_loop_scenario(
        scenario,
        backend=KinematicClassroomBackend(),
        robot_policy=build_policy(policy_name, model_path),
        person_id=person_id,
        smooth_window=1,
        include_base_steps=True,
    )


def build_edited_step(base_step: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    step = copy.deepcopy(base_step)
    cues = step.setdefault("observable_cues", {})
    context = step.setdefault("robot_context", {})

    cue_updates = updates.get("observable_cues", {})
    context_updates = updates.get("robot_context", {})
    for key, value in cue_updates.items():
        cues[key] = value
    for key, value in context_updates.items():
        context[key] = value

    for key in ("ground_truth_state", "expected_action_id", "step"):
        if key in updates:
            step[key] = updates[key]
    return step


def create_handler(
    *,
    scenario_dir: Path,
    model_path: Path,
    policy_name: str,
    membership_store: Any | None = None,
    identity_store: Any | None = None,
    channel_admin_store: Any | None = None,
    dossier_store: Any | None = None,
) -> type[BaseHTTPRequestHandler]:
    student_store = get_demo2_student_store()
    membership_lock = Lock()
    identity_lock = Lock()
    channel_admin_lock = Lock()
    dossier_lock = Lock()
    measurement_lock = Lock()
    measurement_store = None
    evaluation_lock = Lock()
    evaluation_store = None
    summary_lock = Lock()
    summary_store = None
    report_lock = Lock()
    report_store = None
    identity_detect_lock = Lock()
    identity_detect_slots = BoundedSemaphore(1)
    identity_detect_attempts: OrderedDict[str, deque[float]] = OrderedDict()
    identity_detect_cache = MediaResultCache(max_entries=128, max_bytes=2 * 1024 * 1024,
                                             ttl=DEMO2_IDENTITY_DETECT_CACHE_TTL)
    identity_preview_cache = MediaResultCache(max_entries=16, max_bytes=64 * 1024 * 1024,
                                              ttl=DEMO2_IDENTITY_PREVIEW_CACHE_TTL)
    identity_preview_slots = BoundedSemaphore(1)
    identity_preview_lock = Lock()
    identity_preview_attempts: OrderedDict[str, deque[float]] = OrderedDict()
    identity_tracking_lock = Lock()
    identity_tracking_slots = BoundedSemaphore(1)
    identity_tracking_attempts: OrderedDict[str, deque[float]] = OrderedDict()

    def dossier_call(method: str, *args: Any) -> Any:
        nonlocal dossier_store
        if dossier_store is None and not callable(getattr(student_store, "_connect", None)):
            raise Demo2APIError(503, "dossier_unavailable", "敏感资料服务暂不可用")
        try:
            backend = importlib.import_module(".demo2_dossier_store", package=__package__)
        except ImportError:
            raise Demo2APIError(503, "dossier_unavailable", "敏感资料服务暂不可用") from None
        try:
            with dossier_lock:
                if dossier_store is None:
                    dossier_store = backend.Demo2DossierStore(student_store, identities=identity_store)
            cleaned = dossier_store.cleanup_expired()
            if method == "cleanup_expired":
                return cleaned
            return getattr(dossier_store, method)(*args)
        except backend.DossierError as exc:
            raise Demo2APIError(exc.status, exc.code, exc.message) from exc
        except Exception:
            raise Demo2APIError(503, "dossier_unavailable", "敏感资料服务暂不可用，请稍后重试") from None

    def sync_demo_students() -> dict[str, Any]:
        demo_payload = load_seewo_demo2()
        student_store.ensure_students(demo_payload.get("students", []))
        return demo_payload

    def summary_call(method: str, *args: Any, **kwargs: Any) -> Any:
        nonlocal summary_store
        try:
            backend = importlib.import_module('.demo2_student_summary_store', package=__package__)
        except ImportError:
            raise Demo2APIError(503, 'summary_unavailable', '学生摘要服务暂不可用，请稍后重试') from None
        try:
            with summary_lock:
                if summary_store is None:
                    summary_store = backend.Demo2StudentSummaryStore(student_store)
            summary_store.cleanup_expired()
            return getattr(summary_store, method)(*args, **kwargs)
        except backend.StudentSummaryError as exc:
            raise Demo2APIError(exc.status, exc.code, exc.message) from None
        except Exception:
            raise Demo2APIError(503, 'summary_unavailable', '学生摘要服务暂不可用，请稍后重试') from None

    def sync_student_history() -> dict[str, Any]:
        try:
            report = summary_call('sync_automatic_history')
            return {'status': 'pending_retry' if report.get('errors') else 'synced', **report}
        except Demo2APIError:
            # The primary write is already committed. Never report it as failed
            # or force a duplicate submission when its archive needs a retry.
            return {'status': 'pending_retry', 'message': '原记录已保存，档案同步稍后自动重试'}

    class ScenarioLabHandler(BaseHTTPRequestHandler):
        server_version = "RehabAffectScenarioLab/0.1"
        _peer_disconnected = False

        @staticmethod
        def cleanup_expired_dossiers() -> Any:
            return dossier_call("cleanup_expired")

        @staticmethod
        def cleanup_expired_safety() -> Any:
            from .demo2_safety import SafetyStore

            return SafetyStore(student_store).cleanup_expired()

        @staticmethod
        def cleanup_expired_student_summaries() -> Any:
            cleanup = summary_call('cleanup_expired')
            return {'cleanup': cleanup, 'automatic_history': summary_call('sync_automatic_history')}

        def handle_one_request(self) -> None:
            try:
                super().handle_one_request()
            except DISCONNECTED_PEER_ERRORS:
                self._peer_disconnected = True
                self.close_connection = True

        def _write_response(self, data: bytes) -> None:
            if self._peer_disconnected:
                return
            try:
                self.wfile.write(data)
            except DISCONNECTED_PEER_ERRORS:
                self._peer_disconnected = True
                self.close_connection = True

        def flush_headers(self) -> None:
            # Header writes can fail before the body when navigation cancels a request.
            if hasattr(self, "_headers_buffer"):
                self._write_response(b"".join(self._headers_buffer))
                self._headers_buffer = []

        def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
            if self._peer_disconnected:
                return
            try:
                super().send_error(code, message, explain)
            except DISCONNECTED_PEER_ERRORS:
                self._peer_disconnected = True
                self.close_connection = True

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path in {
                "/demo2/login", "/demo2/upload", "/demo2/admin", "/demo2/admin/channels", "/demo2/analysis", "/demo2/course-batch", "/demo2/teaching-support",
                "/demo2/register", "/demo2/privacy", "/demo2/help", "/demo2/school",
                "/demo2/video", "/demo2/membership",
                "/demo2/students", "/demo2/identity",
                "/demo2/simple-result",
                "/demo2/dossier", "/demo2/course-dossier", "/demo2/admin/dossiers",
                "/demo2/student-summary", "/demo2/admin/student-summaries",
                "/demo2/measurement", "/demo2/admin/measurements", "/demo2/capture", "/demo2/evaluation", "/demo2/safety",
            }:
                self._handle_demo2_page(parsed.path)
                return
            if parsed.path == DEMO2_API_PREFIX or parsed.path.startswith(f"{DEMO2_API_PREFIX}/"):
                self._handle_demo2_api_get(parsed)
                return
            if parsed.path in {"/seewo_student_demo", "/seewo_student_demo2"} or _is_protected_legacy_demo2_path(parsed.path):
                if not self._guard_legacy_student_access(page=parsed.path in {"/seewo_student_demo", "/seewo_student_demo2"}):
                    return
            try:
                if parsed.path == "/":
                    self._send_html(_render_lab_html())
                elif parsed.path == "/showcase":
                    self._send_html(render_showcase_html())
                elif parsed.path == "/education_demo":
                    self._send_html(render_education_demo_html())
                elif parsed.path == "/seewo_student_demo":
                    self._send_html(render_seewo_student_demo_html())
                elif parsed.path == "/seewo_student_demo2":
                    self._send_html(render_seewo_demo2_html())
                elif parsed.path == "/favicon.ico":
                    self._send_empty(status=204)
                elif parsed.path == "/api/health":
                    self._send_json({"ok": True, "service": "scenario_lab"})
                elif parsed.path == "/api/education_clips":
                    self._send_json({"clips": list_education_clips()})
                elif parsed.path == "/api/education_demo":
                    clip_id = parse_qs(parsed.query).get("clip_id", ["bag_instruction_attention"])[0]
                    self._send_json(run_education_demo_json(clip_id))
                elif parsed.path == "/api/seewo_student_demo":
                    force = parse_qs(parsed.query).get("force", ["0"])[0] in {"1", "true", "yes"}
                    self._send_json(load_seewo_student_demo(force=force))
                elif parsed.path == "/api/seewo_student_demo2":
                    force = parse_qs(parsed.query).get("force", ["0"])[0] in {"1", "true", "yes"}
                    self._send_json(load_seewo_demo2(force=force))
                elif parsed.path == "/api/seewo_demo2_reviews":
                    course_id = parse_qs(parsed.query).get("course_id", [""])[0]
                    self._send_json({"course_id": course_id, "reviews": load_teacher_reviews(course_id)})
                elif parsed.path == "/api/seewo_demo2_report_status":
                    self._send_json(report_writer_status())
                elif parsed.path == "/api/seewo_demo2/student_record":
                    sync_demo_students()
                    student_id = parse_qs(parsed.query).get("student_id", [""])[0]
                    self._send_json(student_store.student_record(student_id))
                elif parsed.path == "/api/seewo_demo2/storage":
                    sync_demo_students()
                    self._send_json(_remove_physical_paths(student_store.storage_summary()))
                elif parsed.path == "/api/seewo_demo2/video_channels":
                    account = self._require_account()
                    self._send_json(_channels_for_account(student_store.video_channels(), account))
                elif parsed.path == "/api/seewo_demo2/document_download":
                    document_id = parse_qs(parsed.query).get("id", [""])[0]
                    file_path, document = student_store.document_for_download(document_id)
                    self._send_download(
                        file_path,
                        filename=document["original_filename"],
                        content_type=document["mime_type"],
                    )
                elif parsed.path == "/api/seewo_demo2/video_result_download":
                    task_id = parse_qs(parsed.query).get("id", [""])[0]
                    result_path, filename = self._account_video_result_for_download(task_id)
                    self._send_download(result_path, filename=filename, content_type="application/json; charset=utf-8")
                elif parsed.path == "/api/scenarios":
                    self._send_json({"scenarios": list_scenarios(scenario_dir)})
                elif parsed.path == "/api/scenario":
                    scenario_id = parse_qs(parsed.query).get("id", [""])[0]
                    self._send_json(load_scenario_by_id(scenario_id, scenario_dir))
                elif parsed.path == "/api/mujoco_assets":
                    scenario_id = parse_qs(parsed.query).get("scenario_id", [""])[0]
                    self._send_json(mujoco_assets_for_scenario(scenario_id))
                elif parsed.path.startswith("/assets/mujoco_frames/"):
                    self._send_mujoco_asset(parsed.path)
                elif parsed.path.startswith("/assets/seewo_xiaoyudi_demo/"):
                    self._send_seewo_demo_asset(parsed.path)
                elif parsed.path.startswith("/assets/seewo_demo2/"):
                    self._send_seewo_demo2_asset(parsed.path)
                else:
                    self.send_error(404, "Not found")
            except Demo2APIError as exc:
                self._send_json_error(exc.status, exc.code, exc.message)
            except Exception as exc:  # pragma: no cover - handler safety
                self._send_json({"error": str(exc)}, status=500)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == DEMO2_API_PREFIX or parsed.path.startswith(f"{DEMO2_API_PREFIX}/"):
                self._handle_demo2_api_post(parsed)
                return
            if _is_protected_legacy_demo2_path(parsed.path):
                legacy_account = self._guard_legacy_student_access()
                if not legacy_account:
                    return
                if (
                    parsed.path == "/api/seewo_demo2/video_chunk"
                    and _account_role(legacy_account) != "school_uploader"
                ):
                    self._send_json_error(
                        403,
                        "forbidden",
                        "This account cannot upload video chunks",
                    )
                    return
            try:
                payload = self._read_json()
                if parsed.path == "/api/process_step":
                    scenario = load_scenario_by_id(payload["scenario_id"], scenario_dir)
                    step = scenario["steps"][int(payload.get("step_index", 0))]
                    edited = build_edited_step(step, payload.get("updates", {}))
                    self._send_json(
                        process_edited_step(
                            edited,
                            policy_name=payload.get("policy", policy_name),
                            model_path=model_path,
                        )
                    )
                elif parsed.path == "/api/run_scenario":
                    scenario = payload.get("scenario")
                    if not isinstance(scenario, dict):
                        scenario = load_scenario_by_id(payload["scenario_id"], scenario_dir)
                    result = run_scenario(
                        scenario,
                        backend=KinematicClassroomBackend(),
                        robot_policy=build_policy(payload.get("policy", policy_name), model_path),
                        include_cues=True,
                        smooth_window=1,
                    )
                    self._send_json(result)
                elif parsed.path == "/api/run_closed_loop":
                    scenario = payload.get("scenario")
                    if not isinstance(scenario, dict):
                        scenario = load_scenario_by_id(payload["scenario_id"], scenario_dir)
                    if "updates" in payload:
                        step_index = int(payload.get("step_index", 0))
                        scenario = copy.deepcopy(scenario)
                        scenario["steps"][step_index] = build_edited_step(
                            scenario["steps"][step_index],
                            payload.get("updates", {}),
                        )
                    self._send_json(
                        process_closed_loop_scenario(
                            scenario,
                            policy_name=payload.get("policy", policy_name),
                            model_path=model_path,
                        )
                    )
                elif parsed.path == "/api/seewo_demo2_reviews":
                    self._require_role(legacy_account, "school_uploader")
                    course_id = str(payload.get("course_id", "")).strip()
                    if not course_id:
                        raise ValueError("course_id is required")
                    saved = save_teacher_reviews(course_id, payload.get("reviews", {}))
                    self._send_json({"ok": True, "course_id": course_id, "reviews": saved})
                elif parsed.path == "/api/seewo_demo2_long_report":
                    self._require_role(legacy_account, "school_uploader")
                    course_id = str(payload.get("course_id", "")).strip()
                    if not course_id:
                        raise ValueError("course_id is required")
                    reviews = payload.get("reviews", {})
                    if isinstance(reviews, dict):
                        reviews = save_teacher_reviews(course_id, reviews)
                    report = build_long_course_report(
                        load_seewo_demo2(),
                        course_id,
                        course_context=payload.get("course_context", {}),
                        reviews=reviews,
                        use_llm=bool(payload.get("use_llm", False)),
                    )
                    self._send_json(report)
                elif parsed.path == "/api/seewo_demo2/student_document":
                    self._require_role(legacy_account, "school_uploader")
                    sync_demo_students()
                    document = student_store.save_document(payload)
                    self._send_json({"ok": True, "document": document})
                elif parsed.path == "/api/seewo_demo2/support_profile":
                    self._require_role(legacy_account, "school_uploader")
                    sync_demo_students()
                    profile = student_store.save_support_profile(payload)
                    self._send_json({"ok": True, "support_profile": profile})
                elif parsed.path == "/api/seewo_demo2/storage_policy":
                    self._require_role(legacy_account, "company_admin")
                    policy = student_store.update_policy(payload)
                    self._send_json({"ok": True, "policy": policy})
                elif parsed.path == "/api/seewo_demo2/document_delete":
                    self._require_role(legacy_account, "company_admin")
                    result = student_store.delete_document(str(payload.get("document_id", "")))
                    self._send_json({"ok": True, **result})
                elif parsed.path == "/api/seewo_demo2/video_task":
                    self._require_role(legacy_account, "school_uploader")
                    task = self._create_account_upload_task(legacy_account, payload)
                    self._send_json({"ok": True, "task": task})
                elif parsed.path == "/api/seewo_demo2/video_chunk":
                    task = self._append_account_upload_chunk(legacy_account, payload)
                    self._send_json({"ok": True, "task": task})
                elif parsed.path == "/api/seewo_demo2/security_acceptance":
                    self._require_role(legacy_account, "school_uploader")
                    if payload.get("security_confirmed") is not True:
                        raise Demo2APIError(
                            400,
                            "security_confirmation_required",
                            "Explicit security confirmation is required",
                        )
                    acceptance_payload = dict(payload)
                    acceptance_payload["confirmed_by"] = str(
                        _account_value(legacy_account, "username", "")
                    ).strip()
                    acceptance = student_store.record_security_acceptance(
                        acceptance_payload,
                        actor=_account_id(legacy_account),
                    )
                    self._send_json({"ok": True, "acceptance": acceptance})
                elif parsed.path == "/api/seewo_demo2/archive_video_result":
                    task_id = str(payload.get("task_id", "")).strip()
                    course_id = str(payload.get("course_id", "")).strip()
                    if _account_role(legacy_account) == "school_uploader":
                        workspace = student_store.account_upload_workspace(
                            self._session_cookie_token(), course_id
                        )
                        if not _workspace_has_task(workspace, task_id, _account_id(legacy_account)):
                            raise Demo2APIError(
                                403,
                                "task_forbidden",
                                "Archive task does not belong to this account",
                            )
                    elif _account_role(legacy_account) != "company_admin":
                        raise Demo2APIError(403, "forbidden", "Account cannot archive results")
                    archive_payload = dict(payload)
                    archive_payload["created_by"] = str(
                        _account_value(legacy_account, "username", _account_id(legacy_account))
                    )
                    resource = student_store.archive_video_result(
                        archive_payload, actor=_account_id(legacy_account)
                    )
                    self._send_json({"ok": True, "resource": resource})
                else:
                    self.send_error(404, "Not found")
            except Demo2APIError as exc:
                self._send_json_error(exc.status, exc.code, exc.message)
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=400)

        def _handle_demo2_page(self, path: str) -> None:
            if path in {"/demo2/dossier", "/demo2/course-dossier", "/demo2/admin/dossiers"}:
                self._handle_dossier_page(path)
                return
            try:
                if path in {"/demo2/login", "/demo2/register", "/demo2/privacy", "/demo2/help"}:
                    self._send_html(_render_demo2_portal_page(path.rsplit("/", 1)[-1]))
                    return

                account = self._current_account()
                if account is None:
                    self._send_redirect("/demo2/login")
                    return
                if path == "/demo2/membership":
                    self._send_html(_render_demo2_portal_page("membership", account))
                    return
                self._require_student_access(account)
                role = _account_role(account)
                if path in {'/demo2/student-summary', '/demo2/admin/student-summaries'}:
                    is_admin = path.startswith('/demo2/admin/')
                    self._require_role(account, 'company_admin' if is_admin else 'school_uploader')
                    renderer = importlib.import_module('.demo2_student_summary_page', package=__package__)
                    render = (renderer.render_admin_student_summaries_html if is_admin
                              else renderer.render_student_summary_html)
                    self._send_text_payload(render(account).encode('utf-8'), content_type='text/html; charset=utf-8',
                                            extra_headers={'Cache-Control': 'no-store, private', 'Pragma': 'no-cache'})
                elif path == '/demo2/safety':
                    self._require_role(account, 'school_uploader')
                    renderer = importlib.import_module('.demo2_safety_page', package=__package__)
                    self._send_text_payload(renderer.HTML.encode('utf-8'), content_type='text/html; charset=utf-8', extra_headers={'Cache-Control':'no-store, private'})
                elif path == '/demo2/evaluation':
                    self._require_role(account, 'school_uploader')
                    renderer = importlib.import_module('.demo2_evaluation', package=__package__)
                    self._send_text_payload(renderer.render_evaluation(account).encode('utf-8'), content_type='text/html; charset=utf-8',
                                            extra_headers={'Cache-Control':'no-store, private'})
                elif path in {"/demo2/measurement", "/demo2/admin/measurements"}:
                    self._require_role(account, "company_admin" if path.startswith('/demo2/admin/') else "school_uploader")
                    renderer = importlib.import_module('.demo2_measurement', package=__package__)
                    self._send_text_payload(renderer.render_measurement(account).encode('utf-8'), content_type='text/html; charset=utf-8',
                                            extra_headers={'Cache-Control':'no-store, private'})
                elif path == "/demo2/capture":
                    self._require_role(account, 'school_uploader')
                    renderer = importlib.import_module('.demo2_capture', package=__package__)
                    self._send_html(renderer.render_capture(account))
                elif path == '/demo2/teaching-support':
                    self._require_role(account,'school_uploader')
                    task_id, = self._identity_query(urlparse(self.path),('task_id',))
                    self._measurement_call('support_workspace',self._session_cookie_token(),task_id)
                    renderer=importlib.import_module('.demo2_support_page',package=__package__)
                    self._send_text_payload(renderer.render_support().encode('utf-8'),content_type='text/html; charset=utf-8',
                        extra_headers={'Cache-Control':'no-store, private'})
                elif path == "/demo2/course-batch":
                    self._require_role(account, 'school_uploader')
                    task_id, = self._identity_query(urlparse(self.path), ('task_id',))
                    self._measurement_call('batch_workspace', self._session_cookie_token(), task_id)
                    renderer = importlib.import_module('.demo2_batch_page', package=__package__)
                    self._send_text_payload(renderer.render_batch_review().encode('utf-8'), content_type='text/html; charset=utf-8',
                                            extra_headers={'Cache-Control':'no-store, private'})
                elif path == "/demo2/analysis":
                    # The company backend may open the legacy classroom
                    # analysis page for inspection; only teachers can create
                    # or change classroom data through the newer routes.
                    parsed_analysis = urlparse(self.path)
                    if _account_role(account) == 'company_admin' and not parsed_analysis.query:
                        self._require_role(account, 'company_admin')
                        # Nothing below this point touches tasks, students or
                        # results: the guide is static apart from the log line.
                        self._admin_log(account, "admin_analysis_guide", "guide_shown",
                                        http_status=200, classroom_data_read=False)
                        self._send_text_payload(_render_admin_analysis_guide().encode('utf-8'),
                            content_type="text/html; charset=utf-8",
                            extra_headers={"Cache-Control": "no-store, private"},
                        )
                        return
                    self._require_role(account, 'school_uploader', 'company_admin')
                    if parsed_analysis.query:
                        task_id, = self._identity_query(parsed_analysis, ('task_id',))
                        try:
                            self._measurement_call('course_workspace', self._session_cookie_token(), task_id)
                        except Demo2APIError as exc:
                            # Missing and foreign tasks share one 403 so the
                            # page never reveals whether a task id exists.
                            if exc.status not in {403, 404}:
                                self._admin_log(account, "admin_analysis_denied", "failed", task_id=task_id,
                                                code=exc.code, http_status=exc.status)
                                raise
                            self._admin_log(account, "admin_analysis_denied", "forbidden", task_id=task_id,
                                            code=exc.code, http_status=403)
                            raise Demo2APIError(403, "task_forbidden", "当前账号无权查看此课堂任务") from None
                        self._admin_log(account, "admin_analysis_open", "ok", task_id=task_id, http_status=200)
                    renderer = importlib.import_module('.demo2_course_page', package=__package__)
                    self._send_text_payload(renderer.render_course_analysis(account).encode("utf-8"), content_type="text/html; charset=utf-8",
                                            extra_headers={"Cache-Control": "no-store, private"})
                elif path == "/demo2/students":
                    self._require_role(account, "school_uploader")
                    self._send_html(_render_demo2_portal_page("students", account))
                elif path == "/demo2/identity":
                    task_id, = self._identity_query(urlparse(self.path), ("task_id",))
                    # A page URL is not an authorization grant. Check the task
                    # before rendering, including company-admin task reads.
                    self._identity_call("workspace", self._session_cookie_token(), task_id)
                    self._send_html(_render_demo2_portal_page("identity", account))
                elif path == "/demo2/simple-result":
                    self._require_role(account, "school_uploader", "company_admin")
                    parsed_result = urlparse(self.path)
                    # The upload page appends from=upload when it redirects
                    # after processing; nothing else may widen the query.
                    redirected = "from=upload" in parsed_result.query.split("&")
                    if redirected:
                        task_id, _ = self._identity_query(parsed_result, ("task_id", "from"))
                    else:
                        task_id, = self._identity_query(parsed_result, ("task_id",))
                    # The simple result page is the default teacher path. It
                    # authorizes the task without requiring roster binding.
                    try:
                        student_store.account_simple_analysis(self._session_cookie_token(), task_id)
                    except ValueError as exc:
                        message = str(exc)
                        if any(marker in message for marker in ("无权", "权限", "其他账号")):
                            mapped = Demo2APIError(403, "task_forbidden", "当前账号无权查看此课堂结果")
                        elif any(marker in message for marker in ("未找到", "不存在")):
                            mapped = Demo2APIError(404, "task_unavailable", "课堂任务不存在或已不可用")
                        else:
                            mapped = Demo2APIError(400, "result_unavailable", message)
                        upload_debug_event(student_store, "result_redirect" if redirected else "result_page_open",
                                           "denied", task_id=task_id, account_id=_account_id(account),
                                           role=_account_role(account), code=mapped.code, http_status=mapped.status)
                        raise mapped from exc
                    task_row: Any = None
                    try:
                        task_row = student_store.account_video_task(self._session_cookie_token(), task_id)
                    except (ValueError, AttributeError):
                        task_row = None
                    upload_debug_event(student_store, "result_redirect" if redirected else "result_page_open", "ok",
                                       role=_account_role(account),
                                       **{"task_id": task_id, "account_id": _account_id(account),
                                          **{key: value for key, value in _upload_task_fields(task_row).items()
                                             if key in {"channel_id", "course_id", "byte_size", "analysis_status"}}})
                    renderer = importlib.import_module(".demo2_simple_result", package=__package__)
                    self._send_text_payload(
                        renderer.render_simple_result().encode("utf-8"),
                        content_type="text/html; charset=utf-8",
                        extra_headers={"Cache-Control": "no-store, private", "Pragma": "no-cache"},
                    )
                elif path in {"/demo2/upload", "/demo2/school"}:
                    if role != "school_uploader":
                        self.send_error(403, "Forbidden")
                        return
                    self._send_html(_render_demo2_portal_page(path.rsplit("/", 1)[-1], account))
                elif path == "/demo2/admin/channels":
                    self._require_role(account, "company_admin")
                    renderer = importlib.import_module(".demo2_channel_admin", package=__package__)
                    self._send_html(renderer.render_channels(account))
                elif path == "/demo2/admin":
                    if role != "company_admin":
                        self.send_error(403, "Forbidden")
                        return
                    self._send_html(_render_demo2_portal_page("admin", account))
                elif path == "/demo2/video":
                    self._send_html(_render_demo2_portal_page("video", account))
                else:
                    self._send_html(render_seewo_demo2_html())
            except Demo2APIError as exc:
                self._send_json_error(exc.status, exc.code, exc.message)
            except Exception:  # pragma: no cover - page handler safety
                self.send_error(500, "Portal unavailable")

        def _handle_demo2_api_get(self, parsed: Any) -> None:
            if parsed.path == DEMO2_SUMMARY_API_PREFIX or parsed.path.startswith(f'{DEMO2_SUMMARY_API_PREFIX}/'):
                self._handle_student_summary_api(parsed)
                return
            if parsed.path == DEMO2_DOSSIER_API_PREFIX or parsed.path.startswith(f"{DEMO2_DOSSIER_API_PREFIX}/"):
                self._handle_dossier_api(parsed)
                return
            try:
                if parsed.path == f"{DEMO2_API_PREFIX}/membership/config":
                    self._send_demo2_json({"ok": True, "config": self._membership_call("public_config")})
                    return
                account = self._require_account()
                if parsed.path == f"{DEMO2_API_PREFIX}/membership":
                    self._send_demo2_json({"ok": True, "membership": self._membership_call("membership", _account_id(account))})
                    return
                if parsed.path == f"{DEMO2_API_PREFIX}/admin/memberships":
                    self._require_role(account, "company_admin")
                    self._send_demo2_json({"ok": True, "summary": self._membership_call("admin_summary")})
                    return
                if parsed.path != f"{DEMO2_API_PREFIX}/auth/me":
                    self._require_student_access(account)
                if parsed.path == DEMO2_IDENTITY_API_PREFIX or parsed.path.startswith(f"{DEMO2_IDENTITY_API_PREFIX}/"):
                    self._handle_identity_api_get(account, parsed)
                    return
                if parsed.path == f"{DEMO2_API_PREFIX}/auth/me":
                    self._send_demo2_json({"ok": True, "account": _public_account(account)})
                elif parsed.path == f"{DEMO2_API_PREFIX}/applicability":
                    task_id, = self._identity_query(parsed, ('task_id',))
                    self._send_demo2_json({'ok':True,'result':self._applicability_call('workspace',self._session_cookie_token(),task_id)})
                elif parsed.path == f"{DEMO2_API_PREFIX}/safety":
                    self._send_demo2_json({'ok':True, 'workspace':self._safety_call('workspace', self._session_cookie_token())})
                elif parsed.path == f"{DEMO2_API_PREFIX}/safety/media":
                    event_id, = self._identity_query(parsed, ('id',))
                    media_path, mime = self._safety_call('media', self._session_cookie_token(), event_id)
                    self._send_media(media_path, content_type=mime)
                elif parsed.path == f"{DEMO2_API_PREFIX}/evaluations":
                    self._send_demo2_json({'ok':True,'workspace':self._evaluation_call('workspace',self._session_cookie_token())})
                elif parsed.path == f"{DEMO2_API_PREFIX}/measurements":
                    self._send_demo2_json({'ok': True, 'workspace': self._measurement_call('workspace', self._session_cookie_token())})
                elif parsed.path == f"{DEMO2_API_PREFIX}/course-analysis":
                    self._require_role(account, 'school_uploader')
                    task_id, = self._identity_query(parsed, ('task_id',))
                    token = self._session_cookie_token()
                    workspace = self._measurement_call('course_workspace', token, task_id)
                    # Persist an idempotent report snapshot so the company
                    # backend can list/download reports by stable report_id.
                    report_saved = None
                    try:
                        report_saved = self._report_call('save_from_workspace', token, workspace)
                    except Demo2APIError as exc:
                        report_saved = {'saved': False, 'code': exc.code, 'message': exc.message}
                    self._send_demo2_json({'ok': True, 'workspace': workspace, 'report_saved': report_saved})
                elif parsed.path == f"{DEMO2_API_PREFIX}/course-analysis/report":
                    self._require_role(account, 'school_uploader')
                    task_id, = self._identity_query(parsed, ('task_id',))
                    report = self._measurement_call('course_report', self._session_cookie_token(), task_id)
                    report_id = report.get('report_id', task_id)
                    self._send_demo2_json(
                        {'ok': True, 'report': report},
                        headers={'Content-Disposition': f'attachment; filename="classroom-report-{report_id}.json"'},
                    )
                elif parsed.path == f'{DEMO2_API_PREFIX}/teaching-support':
                    self._require_role(account,'school_uploader')
                    task_id, = self._identity_query(parsed,('task_id',))
                    self._send_demo2_json({'ok':True,'workspace':self._measurement_call('support_workspace',self._session_cookie_token(),task_id)})
                elif parsed.path == f"{DEMO2_API_PREFIX}/course-batch":
                    self._require_role(account, 'school_uploader')
                    task_id, = self._identity_query(parsed, ('task_id',))
                    self._send_demo2_json({'ok':True, 'workspace':self._measurement_call(
                        'batch_workspace', self._session_cookie_token(), task_id)})
                elif parsed.path == f"{DEMO2_API_PREFIX}/course-analysis/tasks":
                    self._require_role(account, 'school_uploader')
                    self._identity_query(parsed, ())
                    self._send_demo2_json({'ok':True, **self._measurement_call(
                        'course_tasks', self._session_cookie_token())})
                elif parsed.path == f"{DEMO2_API_PREFIX}/admin/measurements":
                    self._send_demo2_json({'ok': True, 'summary': self._measurement_call('admin_summary', self._session_cookie_token())})
                elif parsed.path == f"{DEMO2_API_PREFIX}/school/context":
                    self._require_role(account, "school_uploader")
                    self._send_demo2_json({
                        "ok": True,
                        **student_store.account_school_context(self._session_cookie_token()),
                    })
                elif parsed.path == f"{DEMO2_API_PREFIX}/upload/workspace":
                    self._require_role(account, "school_uploader")
                    course_id = parse_qs(parsed.query).get("course_id", [""])[0]
                    workspace = dict(student_store.account_upload_workspace(
                        self._session_cookie_token(), course_id
                    ))
                    # Legacy acceptances are course-global, not account-scoped.
                    # Even a matching confirmed_by is not proof of ownership or
                    # current authorization; never forward these as user consent.
                    workspace.pop("security_acceptance", None)
                    workspace.pop("latest_security_acceptance", None)
                    # Never expose the legacy global/demo roster to a real
                    # upload workspace, including when school setup is absent.
                    workspace["students"] = []
                    if identity_store is not None or callable(getattr(student_store, "_connect", None)):
                        try:
                            roster = self._identity_call("roster", self._session_cookie_token())
                            workspace["students"] = roster["students"]
                        except Demo2APIError as exc:
                            if exc.code != "school_context_required":
                                raise
                            workspace["roster_error"] = {"code": exc.code, "message": exc.message}
                    self._send_demo2_json({"ok": True, "workspace": workspace})
                elif parsed.path == f"{DEMO2_API_PREFIX}/upload/task":
                    task_id = parse_qs(parsed.query).get("id", [""])[0].strip()
                    if not task_id:
                        raise Demo2APIError(400, "invalid_request", "id is required")
                    try:
                        task = student_store.account_video_task(self._session_cookie_token(), task_id)
                    except ValueError:
                        raise Demo2APIError(404, "task_unavailable", "任务不存在或当前账号无权查看")
                    result = None
                    if task.get("analysis_status") in {"evidence_ready", "completed"}:
                        path, _ = self._account_video_result_for_download(task_id)
                        result = json.loads(path.read_text(encoding="utf-8"))
                    self._send_demo2_json({"ok": True, "task": task, "result": result})
                elif parsed.path == f"{DEMO2_API_PREFIX}/upload/media":
                    query = parse_qs(parsed.query)
                    task_id = query.get("id", [""])[0].strip()
                    if not task_id:
                        raise Demo2APIError(400, "invalid_request", "id is required")
                    asset = query.get("asset", ["source"])[0]
                    as_download = query.get("download", [""])[0] == "1"
                    operation = "admin_video_download" if as_download else "admin_video_view"
                    try:
                        media_path, content_type = student_store.account_video_media(
                            self._session_cookie_token(), task_id, asset=asset,
                        )
                    except ValueError:
                        self._admin_log(account, operation, "unavailable", task_id=task_id, asset=asset,
                                        code="media_unavailable", http_status=404)
                        raise Demo2APIError(404, "media_unavailable", "视频或音轨不可用、已到期，或当前账号无权查看")
                    # Range requests from the player would flood the log;
                    # only the first chunk (or a full download) is recorded.
                    if as_download or not self.headers.get("Range", "").startswith("bytes=") or \
                            self.headers.get("Range", "").startswith("bytes=0-"):
                        self._admin_log(account, operation, "ok", task_id=task_id, asset=asset, http_status=200,
                                        byte_size=media_path.stat().st_size)
                    download_name = None
                    if as_download:
                        suffix = media_path.suffix if re.fullmatch(r"\.[A-Za-z0-9]{1,8}", media_path.suffix) else ""
                        download_name = f"video_{task_id}{suffix}" if asset == "source" else f"audio_{task_id}.wav"
                    self._send_media(media_path, content_type=content_type, download_name=download_name)
                elif parsed.path == f"{DEMO2_API_PREFIX}/upload/result":
                    task_id = parse_qs(parsed.query).get("id", [""])[0].strip()
                    if not task_id:
                        raise Demo2APIError(400, "invalid_request", "id is required")
                    try:
                        result_path, filename = self._account_video_result_for_download(task_id)
                    except Demo2APIError as exc:
                        self._admin_log(account, "admin_result_download", "denied", task_id=task_id,
                                        code=exc.code, http_status=exc.status)
                        raise
                    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
                    self._admin_log(account, "admin_result_download", "ok", task_id=task_id, http_status=200,
                                    byte_size=result_path.stat().st_size)
                    self._send_download(result_path, filename=filename, content_type=content_type)
                elif parsed.path == f"{DEMO2_API_PREFIX}/simple-result":
                    task_id = parse_qs(parsed.query).get("task_id", [""])[0].strip()
                    if not task_id:
                        raise Demo2APIError(400, "invalid_request", "task_id is required")
                    try:
                        payload = student_store.account_simple_analysis(
                            self._session_cookie_token(), task_id
                        )
                    except ValueError as exc:
                        message = str(exc)
                        if any(marker in message for marker in ("无权", "权限", "其他账号")):
                            raise Demo2APIError(403, "task_forbidden", "当前账号无权查看此课堂结果") from exc
                        if any(marker in message for marker in ("未找到", "不存在")):
                            raise Demo2APIError(404, "task_unavailable", "课堂任务不存在或已不可用") from exc
                        raise Demo2APIError(400, "result_unavailable", message) from exc
                    self._send_demo2_json({"ok": True, **payload})
                elif parsed.path == f"{DEMO2_API_PREFIX}/simple-result/frame":
                    query = parse_qs(parsed.query)
                    task_id = query.get("task_id", [""])[0].strip()
                    frame_name = query.get("frame", [""])[0].strip()
                    if not task_id or not frame_name:
                        raise Demo2APIError(400, "invalid_request", "task_id and frame are required")
                    crop_bbox = None
                    crop = query.get("crop", [""])[0].strip()
                    if crop:
                        if crop != "person":
                            raise Demo2APIError(400, "invalid_request", "不支持的截图类型")
                        try:
                            crop_bbox = {key: float(query.get(key, [""])[0])
                                         for key in ("x", "y", "width", "height")}
                        except (KeyError, TypeError, ValueError, OverflowError):
                            raise Demo2APIError(400, "invalid_request", "人物截图框无效") from None
                    try:
                        frame_path, content_type = student_store.account_simple_analysis_frame(
                            self._session_cookie_token(), task_id, frame_name, crop_bbox=crop_bbox,
                            source_preview=query.get("quality", [""])[0] == "source",
                        )
                    except ValueError as exc:
                        message = str(exc)
                        if any(marker in message for marker in ("无权", "权限", "其他账号")):
                            raise Demo2APIError(403, "frame_forbidden", "当前账号无权查看此证据画面") from exc
                        raise Demo2APIError(404, "frame_unavailable", "证据画面不存在或已不可用") from exc
                    self._send_media(frame_path, content_type=content_type)
                elif parsed.path == f"{DEMO2_API_PREFIX}/admin/channels":
                    self._require_role(account, "company_admin")
                    if parsed.query:
                        raise Demo2APIError(400, "invalid_request", "通道管理请求不接受其他查询参数")
                    channels = self._channel_admin_call("list_channels", self._session_cookie_token())
                    self._send_demo2_json({"ok": True, **channels})
                elif parsed.path == f"{DEMO2_API_PREFIX}/admin/summary":
                    self._require_role(account, "company_admin")
                    query = parse_qs(parsed.query, keep_blank_values=True)
                    if set(query) - {"upload_page"}:
                        raise Demo2APIError(400, "invalid_request", "不支持的后台汇总参数")
                    if "upload_page" in query:
                        pages = query["upload_page"]
                        if len(pages) != 1 or not re.fullmatch(r"[1-9][0-9]{0,6}", pages[0]):
                            raise Demo2APIError(400, "invalid_request", "视频记录页码须为正整数")
                        summary = student_store.admin_platform_summary(
                            self._session_cookie_token(), upload_page=int(pages[0]))
                    else:
                        summary = student_store.admin_platform_summary(self._session_cookie_token())
                    storage_bytes = sum(int(item.get("byte_size") or 0) for item in (summary.get("storage") or {}).values()
                                        if isinstance(item, dict))
                    self._admin_log(account, "admin_refresh", "ok", http_status=200,
                                    account_count=len(summary.get("upload_accounts") or []),
                                    channel_count=len(summary.get("channels") or []),
                                    task_total=int((summary.get("task_status") or {}).get("total") or 0),
                                    storage_bytes=storage_bytes,
                                    page=int((summary.get("upload_pagination") or {}).get("page") or 1))
                    self._send_demo2_json({"ok": True, "summary": summary})
                elif parsed.path == f"{DEMO2_API_PREFIX}/admin/tasks":
                    self._require_role(account, "company_admin")
                    try:
                        query = parse_qs(parsed.query, keep_blank_values=True, max_num_fields=6, strict_parsing=bool(parsed.query))
                    except ValueError:
                        raise Demo2APIError(400, "invalid_request", "任务查询参数无效") from None
                    if set(query) - {"q", "status", "page"} or any(len(values) != 1 for values in query.values()):
                        raise Demo2APIError(400, "invalid_request", "任务查询仅支持 q、status、page 参数")
                    keyword = query.get("q", [""])[0]
                    status_filter = query.get("status", [""])[0]
                    page_text = query.get("page", ["1"])[0]
                    if not re.fullmatch(r"[1-9][0-9]{0,6}", page_text):
                        raise Demo2APIError(400, "invalid_request", "任务查询页码须为正整数")
                    try:
                        found = student_store.admin_task_query(
                            self._session_cookie_token(), query=keyword,
                            analysis_status=status_filter, page=int(page_text))
                    except ValueError as exc:
                        self._admin_log(account, "admin_task_query", "rejected", http_status=400,
                                        has_query=bool(keyword.strip()), query_length=len(keyword),
                                        filter_status=status_filter or None, message=str(exc))
                        raise Demo2APIError(400, "invalid_request", str(exc)) from None
                    reports = self._report_call("admin_reports_for_tasks", self._session_cookie_token(),
                                                [item["task_id"] for item in found["tasks"]])
                    for item in found["tasks"]:
                        item["reports"] = reports.get(item["task_id"], [])
                    exact = next((item for item in found["tasks"] if item["task_id"] == keyword.strip()), None)
                    self._admin_log(account, "admin_task_query", "ok", http_status=200,
                                    has_query=bool(keyword.strip()), query_length=len(keyword),
                                    filter_status=status_filter or None,
                                    task_id=exact["task_id"] if exact else None,
                                    analysis_status=exact["analysis_status"] if exact else None,
                                    result_count=len(found["tasks"]),
                                    report_count=sum(len(item["reports"]) for item in found["tasks"]),
                                    total=found["pagination"]["total"], page=found["pagination"]["page"])
                    self._send_demo2_json({"ok": True, **found})
                elif parsed.path == f"{DEMO2_API_PREFIX}/reports":
                    token = self._session_cookie_token()
                    try:
                        query = parse_qs(parsed.query, keep_blank_values=True, max_num_fields=4, strict_parsing=True)
                    except ValueError:
                        raise Demo2APIError(400, "invalid_request", "报告查询参数无效") from None
                    if set(query) == {"task_id"}:
                        task_id = query["task_id"][0]
                        if not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", task_id):
                            raise Demo2APIError(400, "invalid_request", "任务编号格式无效")
                        self._send_demo2_json({"ok": True, **self._report_call("list_for_task", token, task_id)})
                    elif set(query) == {"report_id"}:
                        report_id = query["report_id"][0]
                        if not re.fullmatch(r"[0-9a-f]{32}", report_id):
                            raise Demo2APIError(400, "invalid_request", "报告编号格式无效")
                        try:
                            report = self._report_call("get", token, report_id)
                        except Demo2APIError as exc:
                            self._admin_log(account, "admin_report_view", "denied", report_id=report_id,
                                            task_id=self._report_task_id(account, report_id),
                                            code=exc.code, http_status=exc.status)
                            raise
                        self._admin_log(account, "admin_report_view", "ok", report_id=report_id,
                                        task_id=report.get("task_id"), status=report.get("status"), http_status=200)
                        self._send_demo2_json({"ok": True, "report": report})
                    else:
                        raise Demo2APIError(400, "invalid_request", "请仅提供 task_id 或 report_id 查询参数")
                elif parsed.path == f"{DEMO2_API_PREFIX}/reports/download":
                    token = self._session_cookie_token()
                    try:
                        query = parse_qs(parsed.query, keep_blank_values=True, max_num_fields=4, strict_parsing=True)
                    except ValueError:
                        raise Demo2APIError(400, "invalid_request", "报告下载参数无效") from None
                    if set(query) not in ({"report_id"}, {"report_id", "fmt"}):
                        raise Demo2APIError(400, "invalid_request", "请提供 report_id 及可选下载格式")
                    report_id = query["report_id"][0]
                    fmt = query.get("fmt", ["md"])[0]
                    if not re.fullmatch(r"[0-9a-f]{32}", report_id):
                        raise Demo2APIError(400, "invalid_request", "报告编号格式无效")
                    try:
                        text, filename, content_type = self._report_call("download", token, report_id, fmt=fmt)
                    except Demo2APIError as exc:
                        self._admin_log(account, "admin_report_download", "denied", report_id=report_id,
                                        task_id=self._report_task_id(account, report_id),
                                        fmt=fmt, code=exc.code, http_status=exc.status)
                        raise
                    self._admin_log(account, "admin_report_download", "ok", report_id=report_id, fmt=fmt,
                                    task_id=self._report_task_id(account, report_id),
                                    http_status=200, byte_size=len(text.encode("utf-8")))
                    self._send_text_payload(text.encode("utf-8"), content_type=content_type, extra_headers={
                        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
                        "Cache-Control": "no-store",
                    })
                elif parsed.path == f"{DEMO2_API_PREFIX}/admin/reports":
                    self._require_role(account, "company_admin")
                    query = parse_qs(parsed.query, keep_blank_values=True)
                    if set(query) - {"page"}:
                        raise Demo2APIError(400, "invalid_request", "不支持的后台报告参数")
                    page = 1
                    if "page" in query:
                        if len(query["page"]) != 1 or not re.fullmatch(r"[1-9][0-9]{0,6}", query["page"][0]):
                            raise Demo2APIError(400, "invalid_request", "报告页码须为正整数")
                        page = int(query["page"][0])
                    self._send_demo2_json({"ok": True, **self._report_call("list_admin", self._session_cookie_token(), page=page)})
                else:
                    raise Demo2APIError(404, "not_found", "API route not found")
            except Demo2APIError as exc:
                self._send_json_error(exc.status, exc.code, exc.message)
            except ValueError as exc:
                self._send_json_error(400, "invalid_request", str(exc))
            except Exception as exc:  # handler safety; detailed diagnostics stay local
                _log_demo2_get_failure(exc)
                self._send_json_error(500, "internal_error", "服务器暂时无法处理请求，请稍后重试")

        def _handle_demo2_api_post(self, parsed: Any) -> None:
            if parsed.path == DEMO2_SUMMARY_API_PREFIX or parsed.path.startswith(f'{DEMO2_SUMMARY_API_PREFIX}/'):
                self._handle_student_summary_api(parsed)
                return
            if parsed.path == DEMO2_DOSSIER_API_PREFIX or parsed.path.startswith(f"{DEMO2_DOSSIER_API_PREFIX}/"):
                self._handle_dossier_api(parsed)
                return
            try:
                if parsed.path == f"{DEMO2_API_PREFIX}/auth/login":
                    self._login()
                    return
                if parsed.path == f"{DEMO2_API_PREFIX}/auth/logout":
                    self._logout()
                    return
                if parsed.path == f"{DEMO2_API_PREFIX}/auth/register":
                    payload = self._read_json(max_bytes=8192)
                    if set(payload) != {"phone", "code", "password", "agreement_version", "accepted"}:
                        raise Demo2APIError(400, "invalid_request", "请填写手机号、验证码、密码并确认注册协议")
                    if payload.get("accepted") is not True or payload.get("agreement_version") != "2026-09-09":
                        raise Demo2APIError(400, "agreement_required", "请阅读并明确同意当前版本的注册协议")
                    config = self._membership_call("public_config")
                    if config.get("sms_available") is not True:
                        raise Demo2APIError(503, "sms_not_configured", "短信服务尚未配置，暂时无法完成手机号注册")
                    account = self._membership_call("register", payload, self.client_address[0])
                    # Registration never grants a legacy classroom identity.
                    if _account_role(account) != "registered_member" or not _account_id(account):
                        raise Demo2APIError(500, "invalid_account", "注册账号信息异常，请联系管理员")
                    token = _session_token(student_store.create_account_session(_account_id(account)))
                    if not token:
                        raise Demo2APIError(500, "session_error", "账号已注册，请返回登录页重新登录")
                    self._send_demo2_json({"ok": True, "account": _public_account(account), "next_url": "/demo2/membership"},
                                          headers={"Set-Cookie": self._session_cookie(token)})
                    return
                if parsed.path == f"{DEMO2_API_PREFIX}/auth/sms-code":
                    payload = self._read_json(max_bytes=8192)
                    if set(payload) != {"phone"} or not isinstance(payload.get("phone"), str):
                        raise Demo2APIError(400, "invalid_request", "请填写手机号")
                    result = self._membership_call("request_code", payload.get("phone"), self.client_address[0])
                    self._send_demo2_json({"ok": True, "result": result})
                    return

                account = self._require_account()
                if parsed.path == f"{DEMO2_API_PREFIX}/membership/orders":
                    payload = self._read_json(max_bytes=8192)
                    if set(payload) != {"plan_id"} or not isinstance(payload.get("plan_id"), str) or not payload["plan_id"].strip():
                        raise Demo2APIError(400, "invalid_request", "请选择会员套餐；价格和支付状态由服务端确定")
                    order = self._membership_call("create_order", _account_id(account), payload)
                    self._send_demo2_json({"ok": True, "order": order}, status=201)
                    return
                if parsed.path == f"{DEMO2_API_PREFIX}/simple-result/archive":
                    self._require_role(account, "school_uploader")
                    self._require_json_command()
                    result = student_store.archive_simple_lesson(
                        self._session_cookie_token(), self._read_json(max_bytes=32 * 1024)
                    )
                    self._send_demo2_json({"ok": True, "archive": result})
                    return
                self._require_student_access(account)
                if parsed.path in {f"{DEMO2_API_PREFIX}/upload/chunks", f"{DEMO2_API_PREFIX}/upload/resume"}:
                    self.close_connection = True
                    if _account_role(account) != "school_uploader":
                        self._discard_denied_body()
                    self._require_role(account, "school_uploader")
                    origin = self.headers.get("Origin")
                    if (self.headers.get("Sec-Fetch-Site", "").lower() == "cross-site"
                            or (origin and (urlparse(origin).scheme not in {"http", "https"}
                                            or urlparse(origin).netloc != self.headers.get("Host")))):
                        self._discard_denied_body()
                        raise Demo2APIError(403, "origin_forbidden", "请从平台当前页面提交上传")
                    is_resume = parsed.path.endswith("/resume")
                    binary = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() == "application/octet-stream"
                    started = time.monotonic()
                    log_fields: dict[str, Any] = {"account_id": _account_id(account)}
                    try:
                        if is_resume or not binary:
                            if parsed.query:
                                raise Demo2APIError(400, "invalid_request", "JSON 上传请求不接受查询参数")
                            payload = self._read_upload_body(binary=False, max_bytes=128 * 1024 if is_resume else 6 * 1024 * 1024)
                            if isinstance(payload, dict):
                                log_fields.update(task_id=payload.get("task_id"), course_id=payload.get("course_id"),
                                                  chunk_index=payload.get("chunk_index") if type(payload.get("chunk_index")) is int else None)
                                if is_resume and isinstance(payload.get("chunk_sha256"), list):
                                    log_fields["verified_chunks"] = len(payload["chunk_sha256"])
                            task = (student_store.resume_video_upload(self._session_cookie_token(), payload) if is_resume
                                    else self._append_account_upload_chunk(account, payload))
                        else:
                            try:
                                query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True, max_num_fields=3)
                            except ValueError:
                                raise Demo2APIError(400, "invalid_request", "上传查询参数无效") from None
                            if (set(query) != {"task_id", "course_id", "chunk_index"}
                                    or any(len(values) != 1 or not 1 <= len(values[0]) <= 120 for values in query.values())):
                                raise Demo2APIError(400, "invalid_request", "请提供唯一的 task_id、course_id、chunk_index")
                            payload = {key: values[0] for key, values in query.items()}
                            log_fields.update(task_id=payload["task_id"], course_id=payload["course_id"])
                            if payload["chunk_index"].isdigit():
                                log_fields["chunk_index"] = int(payload["chunk_index"])
                            chunk = self._read_upload_body(binary=True, max_bytes=MAX_VIDEO_CHUNK_BYTES)
                            log_fields["chunk_bytes"] = len(chunk)
                            task = self._append_account_upload_chunk(account, payload, chunk=chunk)
                    except Exception as exc:
                        status = getattr(exc, "status", 400 if isinstance(exc, ValueError) else 500)
                        upload_debug_event(
                            student_store, "upload_resume" if is_resume else "upload_chunk", "failed",
                            code=getattr(exc, "code", "invalid_request" if isinstance(exc, ValueError) else "internal_error"),
                            http_status=status if isinstance(status, int) else None,
                            duration_ms=(time.monotonic() - started) * 1000, **log_fields,
                        )
                        raise
                    duration_ms = (time.monotonic() - started) * 1000
                    log_fields.update(_upload_task_fields(task))
                    upload_debug_event(student_store, "upload_resume" if is_resume else "upload_chunk", "ok",
                                       duration_ms=duration_ms, **log_fields)
                    if not is_resume and isinstance(task, dict) and task.get("upload_status") == "completed":
                        upload_debug_event(student_store, "upload_complete", "queued" if task.get("analysis_status") == "queued"
                                           else "completed", duration_ms=duration_ms, **log_fields)
                    self._send_demo2_json({"ok": True, "task": task})
                    return
                if parsed.path == f'{DEMO2_API_PREFIX}/applicability':
                    self._require_role(account,'school_uploader')
                    self._require_json_command()
                    origin=self.headers.get('Origin')
                    if origin and urlparse(origin).netloc!=self.headers.get('Host'):
                        raise Demo2APIError(403,'origin_forbidden','请从平台当前页面提交')
                    result = self._applicability_call('save', self._session_cookie_token(), self._read_json(max_bytes=16384))
                    self._send_demo2_json({'ok': True, 'result': result, 'archive_sync': sync_student_history()})
                    return
                if parsed.path in {f'{DEMO2_API_PREFIX}/safety/create', f'{DEMO2_API_PREFIX}/safety/update'}:
                    self._require_role(account, 'school_uploader')
                    self._require_json_command()
                    origin = self.headers.get('Origin')
                    if origin and urlparse(origin).netloc != self.headers.get('Host'):
                        raise Demo2APIError(403, 'origin_forbidden', '请从平台当前页面提交')
                    value = self._safety_call(parsed.path.rsplit('/',1)[-1], self._session_cookie_token(), self._read_json(max_bytes=16384))
                    self._send_demo2_json({'ok':True, 'record':value})
                    return
                if parsed.path in {f'{DEMO2_API_PREFIX}/evaluations', f'{DEMO2_API_PREFIX}/evaluations/preview', f'{DEMO2_API_PREFIX}/evaluations/withdraw'}:
                    self._require_role(account, 'school_uploader')
                    self._require_json_command()
                    origin = self.headers.get('Origin')
                    if origin and urlparse(origin).netloc != self.headers.get('Host'):
                        raise Demo2APIError(403,'origin_forbidden','请从平台当前页面提交评价')
                    method = 'preview' if parsed.path.endswith('/preview') else 'withdraw' if parsed.path.endswith('/withdraw') else 'save'
                    value = self._evaluation_call(method,self._session_cookie_token(),self._read_json(max_bytes=160000))
                    self._send_demo2_json({'ok':True,('result' if method=='preview' else 'record'):value})
                    return
                if parsed.path in {f'{DEMO2_API_PREFIX}/measurements', f'{DEMO2_API_PREFIX}/measurements/withdraw', f'{DEMO2_API_PREFIX}/course-batch/confirm', f'{DEMO2_API_PREFIX}/teaching-support/plan'}:
                    self._require_role(account, 'school_uploader')
                    self._require_json_command()
                    origin = self.headers.get('Origin')
                    if origin and urlparse(origin).netloc != self.headers.get('Host'):
                        raise Demo2APIError(403, 'origin_forbidden', '请从平台当前页面提交记录')
                    method = 'save_support_plan' if parsed.path.endswith('/plan') else 'confirm_batch' if parsed.path.endswith('/confirm') else 'withdraw' if parsed.path.endswith('/withdraw') else 'save'
                    record = self._measurement_call(method, self._session_cookie_token(), self._read_json(max_bytes=16384))
                    response = {'ok': True, 'record': record}
                    if method in {'save', 'withdraw', 'confirm_batch'}:
                        response['archive_sync'] = sync_student_history()
                    self._send_demo2_json(response)
                    return
                if parsed.path == f"{DEMO2_API_PREFIX}/admin/channels":
                    self._require_role(account, "company_admin")
                    self._require_json_command()
                    if parsed.query:
                        raise Demo2APIError(400, "invalid_request", "通道管理请求不接受其他查询参数")
                    channel = self._channel_admin_call("update_channel", self._session_cookie_token(), self._read_json(max_bytes=8192))
                    self._send_demo2_json({"ok": True, "channel": channel})
                    return
                if parsed.path == DEMO2_IDENTITY_API_PREFIX or parsed.path.startswith(f"{DEMO2_IDENTITY_API_PREFIX}/"):
                    if _account_role(account) != "school_uploader":
                        self._discard_denied_body()
                    self._require_role(account, "school_uploader")
                    self._handle_identity_api_post(parsed)
                    return
                if parsed.path == f"{DEMO2_API_PREFIX}/school/context":
                    self._require_json_command()
                    origin = self.headers.get("Origin")
                    if origin and urlparse(origin).netloc != self.headers.get("Host"):
                        raise Demo2APIError(403, "origin_forbidden", "请从平台当前页面提交学校信息")
                payload = self._read_json(
                    max_bytes=8192 if parsed.path == f"{DEMO2_API_PREFIX}/school/context" else 15 * 1024 * 1024
                )
                if parsed.path == f"{DEMO2_API_PREFIX}/school/context":
                    self._require_role(account, "school_uploader")
                    from .school_directory import SchoolSelectionError
                    try:
                        saved_context = student_store.save_account_school_context(self._session_cookie_token(), payload)
                    except SchoolSelectionError as exc:
                        raise Demo2APIError(exc.status, exc.code, str(exc)) from None
                    self._send_demo2_json({
                        "ok": True,
                        **saved_context,
                    })
                elif parsed.path == f"{DEMO2_API_PREFIX}/upload/tasks":
                    self._require_role(account, "school_uploader")
                    task = self._create_account_upload_task(account, payload)
                    self._send_demo2_json({"ok": True, "task": task})
                elif parsed.path == f"{DEMO2_API_PREFIX}/upload/tasks/cancel":
                    self._require_role(account, "school_uploader")
                    task = self._cancel_account_upload_task(account, payload)
                    self._send_demo2_json({"ok": True, "task": task})
                elif parsed.path in {
                    f"{DEMO2_API_PREFIX}/upload/tasks/retry",
                    f"{DEMO2_API_PREFIX}/upload/tasks/enqueue",
                }:
                    task = self._account_video_analysis_action(
                        payload, legacy=parsed.path.endswith("/enqueue"),
                    )
                    self._send_demo2_json({"ok": True, "task": task}, status=202)
                else:
                    raise Demo2APIError(404, "not_found", "API route not found")
            except RegistrationRateLimitError as exc:
                self._send_demo2_json(
                    {"ok": False, "error": {"code": "rate_limited", "message": str(exc)}},
                    status=429,
                    headers={"Retry-After": str(REGISTRATION_WINDOW_SECONDS)},
                )
            except Demo2APIError as exc:
                self._send_json_error(exc.status, exc.code, exc.message)
            except VideoUploadError as exc:
                self._send_json_error(exc.status, exc.code, str(exc))
            except (ValueError, json.JSONDecodeError) as exc:
                self._send_json_error(400, "invalid_request", str(exc))
            except Exception:  # pragma: no cover - handler safety
                self._send_json_error(500, "internal_error", "服务器暂时无法处理请求，请稍后重试")

        def _read_upload_body(self, *, binary: bool, max_bytes: int) -> Any:
            lengths = self.headers.get_all("Content-Length", [])
            if (len(lengths) != 1 or not re.fullmatch(r"[0-9]{1,10}", lengths[0])
                    or self.headers.get_all("Transfer-Encoding") or self.headers.get_all("Expect")):
                raise Demo2APIError(400, "invalid_framing", "上传请求长度或传输格式无效")
            length = int(lengths[0])
            if length > max_bytes:
                raise Demo2APIError(413, "body_too_large", "上传请求超过分片或校验大小限制")
            types, encodings = self.headers.get_all("Content-Type", []), self.headers.get_all("Content-Encoding", [])
            expected_type = "application/octet-stream" if binary else "application/json"
            if (len(types) != 1 or types[0].split(";", 1)[0].strip().lower() != expected_type
                    or len(encodings) > 1 or (encodings and encodings[0].strip().lower() != "identity")):
                raise Demo2APIError(415, "unsupported_media_type", "请使用未压缩的二进制分片或 JSON 请求")
            blocks, remaining, deadline = [], length, time.monotonic() + 120
            previous_timeout = self.connection.gettimeout()
            try:
                while remaining:
                    seconds_left = deadline - time.monotonic()
                    if seconds_left <= 0:
                        raise TimeoutError
                    self.connection.settimeout(seconds_left)
                    block = self.rfile.read1(min(65536, remaining))
                    if not block:
                        raise Demo2APIError(400, "invalid_framing", "上传请求不完整，请确认进度后重试")
                    blocks.append(block)
                    remaining -= len(block)
            except TimeoutError:
                raise Demo2APIError(408, "request_timeout", "上传请求超时，请确认进度后重试") from None
            finally:
                self.connection.settimeout(previous_timeout)
            raw = b"".join(blocks)
            if binary:
                return raw

            def unique_object(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError
                    result[key] = value
                return result

            def reject_constant(_value):
                raise ValueError

            try:
                payload = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object, parse_constant=reject_constant)
                if not isinstance(payload, dict):
                    raise ValueError
                return payload
            except (ValueError, UnicodeError, RecursionError):
                raise Demo2APIError(400, "invalid_request", "上传请求须为有效 JSON 对象且不得重复字段") from None

        def _send_dossier_json(
            self, payload: dict[str, Any], status: int = 200, *, headers: dict[str, str] | None = None,
        ) -> None:
            data = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self._send_text_payload(data, content_type="application/json; charset=utf-8", status=status,
                                    extra_headers={**(headers or {}), "Cache-Control": "no-store, private",
                                                   "Pragma": "no-cache", "X-Content-Type-Options": "nosniff"})

        def _dossier_error(self, error: Exception) -> None:
            if isinstance(error, Demo2APIError):
                status, code, message = error.status, error.code, error.message
            else:
                # Never expose decoder exceptions, paths, source content or keys.
                status, code, message = 503, "dossier_unavailable", "敏感资料服务暂不可用，请稍后重试"
            self._send_dossier_json({"ok": False, "error": {"code": code, "message": message}}, status=status)

        @staticmethod
        def _dossier_query(parsed: Any, fields: tuple[str, ...]) -> tuple[str, ...]:
            try:
                query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True, max_num_fields=8)
            except ValueError:
                raise Demo2APIError(400, "invalid_request", "资料请求参数格式无效") from None
            if set(query) != set(fields) or any(len(values) != 1 for values in query.values()):
                raise Demo2APIError(400, "invalid_request", "请仅提交接口约定的资料编号")
            values = tuple(query[field][0] for field in fields)
            if any(not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value) for value in values):
                raise Demo2APIError(400, "invalid_request", "资料编号格式无效")
            return values

        def _dossier_content_length(self) -> int:
            lengths = self.headers.get_all("Content-Length", [])
            if (len(lengths) > 1 or self.headers.get_all("Transfer-Encoding")
                    or self.headers.get_all("Expect")
                    or (self.command == "POST" and not lengths)
                    or (lengths and not re.fullmatch(r"[0-9]{1,10}", lengths[0]))):
                raise Demo2APIError(400, "invalid_framing", "请求长度或传输格式无效")
            length = int(lengths[0]) if lengths else 0
            if length > DEMO2_DOSSIER_MAX_BODY:
                raise Demo2APIError(413, "body_too_large", "资料请求体不能超过 12 MiB")
            if self.command != "POST" and length:
                raise Demo2APIError(400, "invalid_framing", "读取资料请求不能携带请求体")
            return length

        def _read_dossier_json(self) -> dict[str, Any]:
            length = self._dossier_content_length()
            types = self.headers.get_all("Content-Type", [])
            encodings = self.headers.get_all("Content-Encoding", [])
            if (len(types) != 1 or types[0].split(";", 1)[0].strip().lower() != "application/json"
                    or len(encodings) > 1 or (encodings and encodings[0].strip().lower() != "identity")):
                raise Demo2APIError(415, "json_required", "请使用未压缩的 JSON 提交资料操作")
            blocks, remaining, deadline = [], length, time.monotonic() + 30
            connection = getattr(self, "connection", None)
            previous_timeout = connection.gettimeout() if connection is not None else None
            try:
                while remaining:
                    seconds_left = deadline - time.monotonic()
                    if seconds_left <= 0:
                        raise TimeoutError
                    if connection is not None:
                        connection.settimeout(seconds_left)
                    block = self.rfile.read1(min(65536, remaining))
                    if not block:
                        raise Demo2APIError(400, "invalid_framing", "请求体不完整，请刷新确认状态后重试")
                    blocks.append(block)
                    remaining -= len(block)
            except TimeoutError:
                raise Demo2APIError(408, "request_timeout", "资料请求超时，请刷新确认状态后重试") from None
            finally:
                if connection is not None:
                    connection.settimeout(previous_timeout)

            def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
                result: dict[str, Any] = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError
                    result[key] = value
                return result

            def reject_constant(_value: str) -> None:
                raise ValueError

            try:
                payload = json.loads(b"".join(blocks).decode("utf-8"), object_pairs_hook=unique_object,
                                     parse_constant=reject_constant)
                if not isinstance(payload, dict):
                    raise ValueError
                return payload
            except (ValueError, UnicodeError, RecursionError):
                raise Demo2APIError(400, "invalid_request", "资料请求须为有效 JSON 对象，不允许重复字段") from None

        def _send_dossier_document(self, document: Any) -> None:
            try:
                data, filename, content_type = document
                if (not isinstance(data, bytes) or not 0 < len(data) <= DEMO2_DOSSIER_MAX_FILE
                        or not isinstance(filename, str) or not 1 <= len(filename) <= 200
                        or filename != filename.strip()
                        or re.search(r'[<>:"/\\|?*\x00-\x1f\x7f]', filename)):
                    raise ValueError
                mime = DEMO2_DOSSIER_MIMES.get(Path(filename).suffix.lower())
                if not mime or not isinstance(content_type, str) or content_type.split(";", 1)[0].strip().lower() != mime:
                    raise ValueError
            except (TypeError, ValueError):
                raise Demo2APIError(503, "document_unavailable", "原件暂不可下载") from None
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8" if mime == "text/plain" else mime)
            self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(filename, safe='')}")
            self.send_header("Cache-Control", "no-store, private")
            self.send_header("Pragma", "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self._write_response(data)

        def _handle_dossier_page(self, path: str) -> None:
            try:
                account = self._current_account()
                if account is None:
                    self._send_text_payload(b"", status=302, content_type="text/html; charset=utf-8",
                                            extra_headers={"Location": "/demo2/login", "Cache-Control": "no-store, private"})
                    return
                self._require_role(account, "company_admin" if path == "/demo2/admin/dossiers" else "school_uploader")
                parsed = urlparse(self.path)
                self._dossier_content_length()
                if path == "/demo2/admin/dossiers":
                    self._dossier_query(parsed, ())
                    dossier_call("cleanup_expired")
                    page = "admin-dossiers"
                else:
                    student_page = path == "/demo2/dossier"
                    if student_page and not parsed.query:
                        # No student chosen yet: send the teacher back to the
                        # roster instead of failing with a 400 JSON response.
                        self._send_text_payload(b"", status=302, content_type="text/html; charset=utf-8",
                                                extra_headers={"Location": "/demo2/students",
                                                               "Cache-Control": "no-store, private"})
                        return
                    if not student_page and not parsed.query:
                        self._send_text_payload(b"", status=302, content_type="text/html; charset=utf-8",
                                                extra_headers={"Location": "/demo2/upload",
                                                               "Cache-Control": "no-store, private"})
                        return
                    identifier, = self._dossier_query(parsed, ("student_id" if student_page else "task_id",))
                    dossier_call("student_workspace" if student_page else "task_workspace", self._session_cookie_token(), identifier)
                    page = "dossier" if student_page else "course-dossier"
                html = _render_demo2_portal_page(page, _public_account(account))
                self._send_text_payload(html.encode("utf-8"), content_type="text/html; charset=utf-8",
                                        extra_headers={"Cache-Control": "no-store, private", "Pragma": "no-cache",
                                                       "X-Content-Type-Options": "nosniff"})
            except Exception as exc:
                self._dossier_error(exc)

        def _handle_student_summary_api(self, parsed: Any) -> None:
            body_read = False
            try:
                account = self._require_account()
                self._require_student_access(account)
                suffix = parsed.path[len(DEMO2_SUMMARY_API_PREFIX):]
                admin_read = self.command == 'GET' and suffix in {'/admin', '/export'}
                self._require_role(account, 'company_admin' if admin_read else 'school_uploader')
                token = self._session_cookie_token()
                query = parse_qs(parsed.query, keep_blank_values=True)
                if self.command == 'GET':
                    if suffix == '/student':
                        student_id, = self._identity_query(parsed, ('student_id',))
                        work = summary_call('student_workspace', token, student_id)
                    elif suffix == '/admin':
                        if set(query) - {'page', 'query'} or any(len(v) != 1 for v in query.values()):
                            raise Demo2APIError(400, 'invalid_request', '摘要查询参数无效')
                        page = query.get('page', ['1'])[0]
                        if not re.fullmatch(r'[1-9][0-9]{0,6}', page):
                            raise Demo2APIError(400, 'invalid_request', '请提供有效页码')
                        work = summary_call('admin_workspace', token, page=int(page), query=query.get('query', [''])[0])
                    elif suffix == '/export':
                        public_id, = self._identity_query(parsed, ('public_id',))
                        work = summary_call('admin_export', token, public_id)
                        self._send_demo2_json(work, headers={'Content-Disposition': 'attachment; filename="student-summary.json"'})
                        return
                    else:
                        raise Demo2APIError(404, 'not_found', '摘要接口不存在')
                    self._send_demo2_json({'ok': True, 'workspace': work})
                    return
                if parsed.query:
                    raise Demo2APIError(400, 'invalid_request', '摘要保存请求不接受查询参数')
                if self.headers.get('Content-Type', '').split(';', 1)[0].lower() != 'application/json':
                    raise Demo2APIError(415, 'json_required', '请通过平台表单提交')
                origin = self.headers.get('Origin')
                if origin and urlparse(origin).netloc != self.headers.get('Host'):
                    raise Demo2APIError(403, 'origin_forbidden', '请从平台当前页面提交')
                if self.headers.get('Sec-Fetch-Site') == 'cross-site':
                    raise Demo2APIError(403, 'origin_forbidden', '请从平台当前页面提交')
                commands = {'/authorization': ('save_authorization', 'authorization'),
                            '/snapshots': ('save_snapshot', 'snapshot'),
                            '/automatic': ('set_automatic_archiving', 'workspace'),
                            '/authorization/withdraw': ('revoke_authorization', 'result')}
                if suffix not in commands:
                    raise Demo2APIError(404, 'not_found', '摘要接口不存在')
                method, envelope = commands[suffix]
                body_read = True
                payload = self._read_json(max_bytes=32 * 1024)
                result = summary_call(method, token, payload)
                self._send_demo2_json({'ok': True, envelope: result})
            except Demo2APIError as exc:
                if not body_read:
                    self._discard_denied_body()
                self._send_json_error(exc.status, exc.code, exc.message)
            except ValueError:
                if not body_read:
                    self._discard_denied_body()
                self._send_json_error(400, 'invalid_request', '摘要请求格式无效，请刷新后重试')
            except Exception:
                if not body_read:
                    self._discard_denied_body()
                self._send_json_error(503, 'summary_unavailable', '学生摘要服务暂不可用，请稍后重试')

        def _handle_dossier_api(self, parsed: Any) -> None:
            try:
                account = self._require_account()
                suffix = parsed.path[len(DEMO2_DOSSIER_API_PREFIX):]
                admin_read = self.command == "GET" and suffix == "/admin"
                required_role = "company_admin" if admin_read else "school_uploader"
                if _account_role(account) != required_role:
                    self._discard_denied_body()
                self._require_role(account, required_role)
                token = self._session_cookie_token()
                if self.command == "GET":
                    self._dossier_content_length()
                    routes = {
                        "/student": ("student_id", "student_workspace", "workspace"),
                        "/task": ("task_id", "task_workspace", "workspace"),
                        "/document": ("document_id", "document_download", ""),
                        "/reference": ("reference_id", "reference_export", ""),
                        "/iep-context": ("student_id", "iep_context", "iep_context"),
                        "/access": (("student_id", "purpose"), "material_access", "access"),
                        "/analysis-context": ("task_id", "analysis_context", "analysis_context"),
                    }
                    if admin_read:
                        self._dossier_query(parsed, ())
                        summary = _public_dossier_admin_summary(dossier_call("admin_summary", token))
                        self._send_dossier_json({"ok": True, "summary": summary})
                        return
                    if suffix not in routes:
                        raise Demo2APIError(404, "not_found", "资料接口不存在")
                    field, method, envelope = routes[suffix]
                    identifiers = self._dossier_query(parsed, field if isinstance(field, tuple) else (field,))
                    result = dossier_call(method, token, *identifiers)
                    if suffix == "/document":
                        self._send_dossier_document(result)
                    elif suffix == "/reference":
                        if not isinstance(result, dict):
                            raise Demo2APIError(503, "dossier_unavailable", "课堂引用暂不可导出")
                        self._send_dossier_json(result, headers={"Content-Disposition": 'attachment; filename="classroom-reference-record.json"'})
                    else:
                        self._send_dossier_json({"ok": True, envelope: result})
                    return
                if self.command != "POST":
                    raise Demo2APIError(405, "method_not_allowed", "不支持的资料请求方法")
                self._dossier_query(parsed, ())
                commands = {
                    "/authorization": ("save_authorization", "authorization", "student_id reference storage_mode valid_until confirmed"),
                    "/authorization/withdraw": ("withdraw_authorization", "result", "student_id authorization_id confirmed"),
                    "/documents": ("create_document", "document", "student_id authorization_id document_type document_date source_ref retain_until summary filename content_base64 supersedes_id"),
                    "/documents/delete": ("delete_document", "result", "student_id document_id confirmed"),
                    "/references": ("create_reference", "reference", "task_id student_id frame_revision document_ids confirmed"),
                    "/references/withdraw": ("withdraw_reference", "reference", "reference_id confirmed"),
                }
                if suffix not in commands:
                    raise Demo2APIError(404, "not_found", "资料接口不存在")
                method, envelope, fields = commands[suffix]
                payload = self._read_dossier_json()
                if set(payload) != set(fields.split()):
                    raise Demo2APIError(400, "invalid_request", "请仅提交资料接口约定的字段")
                if "confirmed" in fields.split() and payload["confirmed"] is not True:
                    raise Demo2APIError(400, "confirmation_required", "必须由教师显式确认本次操作")
                result = dossier_call(method, token, payload)
                self._send_dossier_json({"ok": True, envelope: result})
            except Exception as exc:
                self._dossier_error(exc)

        def _login(self) -> None:
            payload = self._read_json(max_bytes=8192)
            username = payload.get("username", "")
            password = payload.get("password", "")
            if (not isinstance(username, str) or not isinstance(password, str)
                    or not 1 <= len(username.strip()) <= 120 or not 1 <= len(password) <= 1024):
                raise Demo2APIError(400, "invalid_request", "请填写账号和密码")
            username = username.strip()
            role = payload.get("role")
            if "role" in payload and role not in ("school_uploader", "company_admin"):
                raise Demo2APIError(400, "invalid_request", "请选择用户登录或管理员登录")
            try:
                account = student_store.authenticate_account(username, password)
            except ValueError as exc:
                raise Demo2APIError(401, "invalid_credentials", "账号或密码错误") from exc
            if not account:
                raise Demo2APIError(401, "invalid_credentials", "账号或密码错误")
            allowed_roles = {"school_uploader", "registered_member"} if role == "school_uploader" else {role}
            if role is not None and _account_role(account) not in allowed_roles:
                raise Demo2APIError(403, "role_mismatch", "账号与所选登录身份不匹配")
            account_id = _account_id(account)
            if not account_id:
                raise Demo2APIError(500, "invalid_account", "账号信息不完整，请联系管理员")
            token = _session_token(student_store.create_account_session(account_id))
            if not token:
                raise Demo2APIError(500, "session_error", "暂时无法登录，请稍后重试")
            self._send_demo2_json(
                {"ok": True, "account": _public_account(account),
                 "next_url": ("/demo2/membership" if _account_role(account) == "registered_member" else
                              "/demo2/admin" if _account_role(account) == "company_admin" else "/demo2/school")},
                headers={"Set-Cookie": self._session_cookie(token)},
            )

        def _logout(self) -> None:
            token = self._session_cookie_token()
            if token:
                student_store.revoke_account_session(token)
            self._send_demo2_json(
                {"ok": True},
                headers={"Set-Cookie": self._session_cookie("", max_age=0)},
            )

        def _create_account_upload_task(
            self, account: Any, payload: dict[str, Any]
        ) -> dict[str, Any]:
            token = self._session_cookie_token()
            school_info = student_store.account_school_context(token)
            context = school_info.get("context") if isinstance(school_info, dict) else None
            if (not isinstance(context, dict)
                    or any(not isinstance(context.get(key), str) or not context[key].strip()
                           for key in ("city", "district", "school_name"))):
                raise Demo2APIError(409, "school_context_required", "请先选择并保存学校信息，再上传视频")
            if payload.get("security_confirmed") is not True:
                raise Demo2APIError(
                    400,
                    "security_confirmation_required",
                    "请阅读并明确确认数据安全授权后，再上传视频",
                )
            account_id = _account_id(account)
            course_id = str(payload.get("course_id", "")).strip()
            workspace = student_store.account_upload_workspace(token, course_id)
            channel_id = str(payload.get("channel_id", "")).strip()
            byte_size = payload.get("byte_size") if type(payload.get("byte_size")) is int else None
            log_fields = {"account_id": account_id, "course_id": course_id, "channel_id": channel_id,
                          "byte_size": byte_size}

            def reject(status: int, code: str, message: str) -> Demo2APIError:
                upload_debug_event(student_store, "upload_rejected", "rejected", code=code,
                                   http_status=status, channel_status=(workspace or {}).get("channel_status"),
                                   **log_fields)
                return Demo2APIError(status, code, message)

            if channel_id not in _bound_channel_ids(account, workspace):
                raise reject(403, "channel_forbidden", "当前账号无权使用此上传通道，请选择账号绑定的通道")
            blocked = workspace.get("upload_blocked") if isinstance(workspace, dict) else None
            if isinstance(blocked, dict) and blocked.get("code"):
                # Never fall back to another channel; the teacher must see the pause.
                raise reject(409, str(blocked["code"]), str(blocked.get("message") or "上传通道暂不可用"))
            if _workspace_quota_exhausted(workspace):
                raise reject(409, "quota_exceeded", "该课程上传名额已满，请查看现有任务或联系管理员")
            allow_company_archive = payload.get("allow_company_archive", False)
            if not isinstance(allow_company_archive, bool):
                raise Demo2APIError(
                    400,
                    "invalid_request",
                    "请明确选择是否允许公司归档，该选项须为是或否",
                )
            username = str(_account_value(account, "username", "")).strip()
            acceptance_payload = {
                "security_confirmed": True,
                "confirmed_by": username,
                "course_id": course_id,
                "course_name": str(payload.get("course_name", "")).strip(),
                "allow_company_archive": allow_company_archive,
            }
            if "agreement_version" in payload:
                acceptance_payload["agreement_version"] = payload["agreement_version"]
            student_store.record_security_acceptance(
                acceptance_payload,
                actor=username or account_id,
            )
            task_payload = dict(payload)
            task_payload["account_id"] = account_id
            task_payload["security_confirmed"] = True
            task_payload["confirmed_by"] = username
            task_payload["allow_company_archive"] = allow_company_archive
            started = time.monotonic()
            try:
                task = student_store.create_video_task(task_payload, actor=account_id)
            except ValueError as exc:
                if _is_quota_error(exc):
                    raise reject(
                        409,
                        "quota_exceeded",
                        "该课程上传名额已满，请查看现有任务或联系管理员",
                    ) from exc
                if "已暂停" in str(exc):
                    raise reject(409, "channel_paused",
                                 "账号绑定的上传通道已暂停，暂不能新建上传；请联系管理员恢复通道，系统不会自动切换到其他通道") from exc
                if "通道不存在" in str(exc):
                    raise reject(409, "channel_missing", "账号绑定的上传通道不存在，请联系管理员核对通道配置") from exc
                upload_debug_event(student_store, "upload_start", "failed",
                                   code=getattr(exc, "code", "invalid_request"),
                                   duration_ms=(time.monotonic() - started) * 1000, **log_fields)
                raise
            upload_debug_event(student_store, "upload_start", "created",
                               duration_ms=(time.monotonic() - started) * 1000,
                               **{**log_fields, **_upload_task_fields(task)})
            return task

        def _account_video_analysis_action(
            self, payload: dict[str, Any], *, legacy: bool
        ) -> dict[str, Any]:
            task_id = payload.get("task_id")
            if not isinstance(task_id, str) or not task_id.strip():
                raise Demo2APIError(400, "invalid_request", "task_id is required")
            action = (
                student_store.enqueue_legacy_video_analysis
                if legacy else student_store.retry_account_video_analysis
            )
            try:
                # The repository authorizes the owner/admin and checks live
                # media and allowed states atomically before enqueueing.
                return action(self._session_cookie_token(), task_id.strip())
            except ValueError as exc:
                message = str(exc).lower()
                if any(marker in message for marker in ("会话", "登录", "session")):
                    raise Demo2APIError(401, "authentication_required", "登录已失效，请重新登录") from exc
                if any(marker in message for marker in ("无权", "权限", "其他账号", "forbidden")):
                    raise Demo2APIError(403, "task_forbidden", "当前账号无权处理此任务") from exc
                if any(marker in message for marker in ("到期", "已删除", "expired")):
                    raise Demo2APIError(410, "media_expired", "原视频已到期或已删除，不能重新处理") from exc
                if any(marker in message for marker in ("未找到", "不存在", "not found")):
                    raise Demo2APIError(404, "task_unavailable", "任务或原视频不存在") from exc
                if any(marker in message for marker in ("仅", "尚未", "未完成", "not ready")):
                    code = "task_not_enqueueable" if legacy else "task_not_retryable"
                    hint = "仅历史预检任务可加入处理队列" if legacy else "仅失败任务可重试"
                    raise Demo2APIError(409, code, hint) from exc
                raise Demo2APIError(400, "invalid_request", "无法处理该视频任务，请检查任务状态") from exc

        def _account_video_result_for_download(self, task_id: str) -> tuple[Path, str]:
            try:
                return student_store.account_video_result_for_download(
                    self._session_cookie_token(), task_id
                )
            except ValueError as exc:
                message = str(exc)
                lowered = message.lower()
                if any(
                    marker in lowered
                    for marker in ("无权", "越权", "不属于", "权限", "forbidden", "denied")
                ):
                    raise Demo2APIError(403, "result_forbidden", message) from exc
                if any(marker in lowered for marker in ("未找到", "不存在", "not found")):
                    raise Demo2APIError(404, "result_not_found", message) from exc
                if any(marker in lowered for marker in ("尚无", "尚未", "not ready")):
                    raise Demo2APIError(409, "result_not_ready", message) from exc
                raise

        def _cancel_account_upload_task(
            self, account: Any, payload: dict[str, Any]
        ) -> dict[str, Any]:
            task_id = str(payload.get("task_id", "")).strip()
            if not task_id:
                raise Demo2APIError(400, "invalid_request", "task_id is required")
            try:
                return student_store.cancel_video_task(
                    self._session_cookie_token(), task_id
                )
            except ValueError as exc:
                message = str(exc)
                if any(marker in message for marker in ("无权", "其他账号", "权限")):
                    raise Demo2APIError(403, "task_forbidden", message) from exc
                if any(marker in message for marker in ("未找到", "不存在")):
                    raise Demo2APIError(404, "task_not_found", message) from exc
                if any(marker in message for marker in ("仅可取消", "已经完成", "已结束")):
                    raise Demo2APIError(409, "task_not_cancellable", message) from exc
                raise

        def _append_account_upload_chunk(
            self, account: Any, payload: dict[str, Any], *, chunk: bytes | None = None
        ) -> dict[str, Any]:
            role = _account_role(account)
            if role != "school_uploader":
                raise Demo2APIError(403, "forbidden", "当前账号没有视频上传权限，请使用所属学校上传账号")
            account_id = _account_id(account)
            task_id = str(payload.get("task_id", "")).strip()
            if not task_id:
                raise Demo2APIError(400, "invalid_request", "缺少上传任务编号，请返回课程重新选择任务")
            course_id = str(payload.get("course_id", "")).strip()
            if not course_id:
                raise Demo2APIError(400, "invalid_request", "缺少课程编号，请返回所属课程重试")
            workspace = student_store.account_upload_workspace(
                self._session_cookie_token(), course_id
            )
            if not _workspace_has_task(workspace, task_id, account_id):
                raise Demo2APIError(403, "task_forbidden", "任务不属于当前账号或课程，请返回自己的课程确认")
            chunk_payload = dict(payload)
            chunk_payload["account_id"] = account_id
            chunk_payload["account_session_token"] = self._session_cookie_token()
            if chunk is not None:
                return student_store.append_video_chunk(chunk_payload, actor=account_id, chunk=chunk)
            return student_store.append_video_chunk(chunk_payload, actor=account_id)

        def _report_task_id(self, account: Any, report_id: str) -> str | None:
            """Stable task id of a report, looked up only for admin log lines."""
            if _account_role(account) != "company_admin" or not callable(getattr(student_store, "_connect", None)):
                return None
            try:
                with student_store._connect() as connection:
                    row = connection.execute(
                        "SELECT task_id FROM demo2_reports WHERE report_id = ?", (report_id,)).fetchone()
            except Exception:  # the log line must never break the download
                return None
            return str(row[0]) if row else None

        def _admin_log(self, account: Any, operation: str, result: str, **fields: Any) -> None:
            """Company-admin operations only; teacher traffic keeps its own logs."""
            if _account_role(account) != "company_admin":
                return
            admin_debug_event(student_store, operation, result,
                              admin_account=str(_account_value(account, "username", "")).strip(),
                              account_id=_account_id(account), role="company_admin", **fields)

        @staticmethod
        def _require_role(account: Any, *roles: str) -> None:
            if _account_role(account) not in roles:
                raise Demo2APIError(403, "forbidden", "当前账号无权执行此操作")

        def _require_student_access(self, account: Any) -> None:
            # Membership/payment status is deliberately not an authorization
            # source for any of the existing students, courses or upload channels.
            if _account_role(account) not in DEMO2_STUDENT_ROLES:
                self._discard_denied_body()
                raise Demo2APIError(403, "student_access_forbidden", "当前账号尚未获授权访问课堂及学生资料")

        def _discard_denied_body(self) -> None:
            # Early 401/403 may otherwise reset TCP while the client is still
            # sending its body (notably on Windows), losing the error response.
            # Drain bytes only, never parse or execute a denied request. Bound
            # both size and elapsed time so an unauthenticated peer cannot stall.
            if self.command != "POST" or not hasattr(self, "connection"):
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except (TypeError, ValueError):
                return
            if not 0 < length <= 15 * 1024 * 1024 or self.headers.get("Transfer-Encoding"):
                return
            previous_timeout = self.connection.gettimeout()
            deadline = time.monotonic() + .25
            try:
                while length and time.monotonic() < deadline:
                    self.connection.settimeout(max(.001, deadline - time.monotonic()))
                    chunk = self.rfile.read1(min(length, 65536))
                    if not chunk:
                        break
                    length -= len(chunk)
            except OSError:
                pass
            finally:
                self.connection.settimeout(previous_timeout)

        def _guard_legacy_student_access(self, *, page: bool = False) -> Any | None:
            account = self._current_account()
            if account is None:
                self._discard_denied_body()
                if page:
                    self._send_redirect("/demo2/login")
                else:
                    self._send_json_error(401, "authentication_required", "请先登录后再操作")
                return None
            try:
                self._require_student_access(account)
            except Demo2APIError as exc:
                self._send_json_error(exc.status, exc.code, exc.message)
                return None
            if page:
                self._send_text_payload(_legacy_dossier_notice().encode("utf-8"), content_type="text/html; charset=utf-8",
                                        extra_headers={"Cache-Control": "no-store, private"})
                return None
            if _is_retired_legacy_data_path(urlparse(self.path).path):
                self._discard_denied_body()
                self._send_dossier_json({"ok": False, "error": {"code": "legacy_data_reimport_required",
                    "message": "历史全局资料入口已停用；旧数据未迁移或删除，请核对正确学生及授权后重新导入。"}}, status=410)
                return None
            return account

        def _membership_call(self, method: str, *args: Any) -> Any:
            nonlocal membership_store
            try:
                backend = importlib.import_module(".demo2_membership_store", package=__package__)
            except ImportError as exc:
                raise Demo2APIError(503, "membership_unavailable", "会员服务暂不可用，请稍后重试") from exc
            try:
                with membership_lock:
                    if membership_store is None:
                        membership_store = backend.Demo2MembershipStore(student_store)
                return getattr(membership_store, method)(*args)
            except backend.MembershipError as exc:
                raise Demo2APIError(exc.status, exc.code, exc.message) from exc

        def _identity_call(self, method: str, *args: Any) -> Any:
            nonlocal identity_store
            # Legacy FakeStores must never cause a fallback to the real DB.
            if identity_store is None and not callable(getattr(student_store, "_connect", None)):
                raise Demo2APIError(503, "identity_unavailable", "身份名册服务暂不可用")
            try:
                backend = importlib.import_module(".demo2_identity_store", package=__package__)
            except ImportError as exc:
                raise Demo2APIError(503, "identity_unavailable", "身份名册服务暂不可用") from exc
            try:
                with identity_lock:
                    if identity_store is None:
                        identity_store = backend.Demo2IdentityStore(student_store)
                return getattr(identity_store, method)(*args)
            except backend.IdentityError as exc:
                raise Demo2APIError(exc.status, exc.code, exc.message) from exc

        def _channel_admin_call(self, method: str, *args: Any) -> Any:
            nonlocal channel_admin_store
            if channel_admin_store is None and not callable(getattr(student_store, "_connect", None)):
                raise Demo2APIError(503, "channel_admin_unavailable", "通道设置服务暂不可用")
            try:
                backend = importlib.import_module(".demo2_channel_admin_store", package=__package__)
            except ImportError as exc:
                raise Demo2APIError(503, "channel_admin_unavailable", "通道设置服务暂不可用") from exc
            try:
                with channel_admin_lock:
                    if channel_admin_store is None:
                        channel_admin_store = backend.Demo2ChannelAdminStore(student_store)
                return getattr(channel_admin_store, method)(*args)
            except backend.ChannelAdminError as exc:
                raise Demo2APIError(exc.status, exc.code, exc.message) from exc

        def _require_json_command(self) -> None:
            # No simple cross-origin form/text requests for administrative writes.
            if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
                raise Demo2APIError(415, "json_required", "请使用平台页面提交此操作")

        def _applicability_call(self, method: str, *args: Any) -> Any:
            backend=importlib.import_module('.video_applicability',package=__package__)
            try:
                return getattr(backend.ApplicabilityStore(student_store),method)(*args)
            except backend.IdentityError as exc:
                raise Demo2APIError(exc.status,exc.code,exc.message) from None

        def _safety_call(self, method: str, *args: Any) -> Any:
            backend = importlib.import_module('.demo2_safety', package=__package__)
            identity = importlib.import_module('.demo2_identity_store', package=__package__)
            vault = importlib.import_module('.demo2_dossier_vault', package=__package__)
            try:
                return getattr(backend.SafetyStore(student_store), method)(*args)
            except (backend.MeasurementError, identity.IdentityError) as exc:
                raise Demo2APIError(exc.status, exc.code, exc.message) from None
            except vault.VaultError:
                raise Demo2APIError(503, 'safety_vault_unavailable', '核查资料加密服务暂不可用') from None
            except ValueError:
                raise Demo2APIError(400, 'safety_unavailable', '视频已到期或核查参数无效') from None

        def _evaluation_call(self, method: str, *args: Any) -> Any:
            nonlocal evaluation_store
            backend = importlib.import_module('.demo2_evaluation_store', package=__package__)
            identity = importlib.import_module('.demo2_identity_store', package=__package__)
            try:
                with evaluation_lock:
                    if evaluation_store is None:
                        evaluation_store = backend.Demo2EvaluationStore(student_store)
                return getattr(evaluation_store,method)(*args)
            except (backend.MeasurementError, identity.IdentityError) as exc:
                raise Demo2APIError(exc.status,exc.code,exc.message) from None

        def _measurement_call(self, method: str, *args: Any) -> Any:
            nonlocal measurement_store
            backend = importlib.import_module('.demo2_measurement_store', package=__package__)
            try:
                with measurement_lock:
                    if measurement_store is None:
                        measurement_store = backend.Demo2MeasurementStore(student_store)
                return getattr(measurement_store, method)(*args)
            except (backend.MeasurementError, backend.IdentityError) as exc:
                raise Demo2APIError(exc.status, exc.code, exc.message) from None

        def _report_call(self, method: str, *args: Any, **kwargs: Any) -> Any:
            nonlocal report_store
            backend = importlib.import_module('.demo2_report_store', package=__package__)
            try:
                with report_lock:
                    if report_store is None:
                        report_store = backend.Demo2ReportStore(student_store)
                return getattr(report_store, method)(*args, **kwargs)
            except backend.ReportError as exc:
                raise Demo2APIError(exc.status, exc.code, exc.message) from None

        @staticmethod
        def _identity_query(parsed: Any, fields: tuple[str, ...]) -> tuple[str, ...]:
            try:
                query = parse_qs(parsed.query, keep_blank_values=True, max_num_fields=8, strict_parsing=True)
            except ValueError as exc:
                raise Demo2APIError(400, "invalid_request", "身份请求参数格式无效或数量过多") from exc
            if set(query) != set(fields) or any(len(values) != 1 for values in query.values()):
                raise Demo2APIError(400, "invalid_request", "请仅提交所需任务编号、采样帧和帧版本")
            values = tuple(query[field][0] for field in fields)
            if any(not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value) for value in values):
                raise Demo2APIError(400, "invalid_request", "任务编号、采样帧或帧版本格式无效")
            return values

        def _handle_identity_api_get(self, account: Any, parsed: Any) -> None:
            token = self._session_cookie_token()
            if parsed.path == f"{DEMO2_IDENTITY_API_PREFIX}/roster":
                self._require_role(account, "school_uploader")
                self._identity_query(parsed, ())
                self._send_demo2_json({"ok": True, "roster": self._identity_call("roster", token)})
            elif parsed.path == f"{DEMO2_IDENTITY_API_PREFIX}/workspace":
                task_id, = self._identity_query(parsed, ("task_id",))
                self._send_demo2_json({"ok": True, "workspace": self._identity_call("workspace", token, task_id)})
            elif parsed.path == f"{DEMO2_IDENTITY_API_PREFIX}/export":
                task_id, = self._identity_query(parsed, ("task_id",))
                exported = self._identity_call("export", token, task_id)
                self._send_demo2_json(exported, headers={
                    "Content-Disposition": "attachment; filename=student-identity-bindings.json",
                    "X-Content-Type-Options": "nosniff",
                })
            elif parsed.path in {f"{DEMO2_IDENTITY_API_PREFIX}/frame", f"{DEMO2_IDENTITY_API_PREFIX}/detect"}:
                identifiers = self._identity_query(parsed, ("task_id", "frame_key", "frame_revision"))
                # Every request, including repeated detection requests, goes
                # through ownership, revision and raw-media TTL checks first.
                frame_path, content_type = self._identity_call("frame_file", token, *identifiers)
                if parsed.path.endswith("/frame"):
                    self._send_media(frame_path, content_type=content_type)
                else:
                    detection = self._detect_identity_faces(account, frame_path, identifiers)
                    self._send_demo2_json({"ok": True, "detection": detection})
            elif parsed.path == f"{DEMO2_IDENTITY_API_PREFIX}/preview":
                identifiers = self._identity_query(parsed, ("task_id", "frame_key", "frame_revision"))
                self._send_identity_preview(account, token, identifiers)
            else:
                raise Demo2APIError(404, "not_found", "API route not found")

        def _handle_identity_api_post(self, parsed: Any) -> None:
            if parsed.path == f"{DEMO2_IDENTITY_API_PREFIX}/track":
                self._require_json_command()
                self._identity_query(parsed, ())
                result = self._track_identity_region(self._read_json(max_bytes=8192))
                self._send_demo2_json({"ok": True, "track": result})
                return
            actions = {
                f"{DEMO2_IDENTITY_API_PREFIX}/students": ("create_student", "student"),
                f"{DEMO2_IDENTITY_API_PREFIX}/bindings": ("save_binding", "binding"),
                f"{DEMO2_IDENTITY_API_PREFIX}/bindings/revoke": ("revoke_binding", "binding"),
                f"{DEMO2_IDENTITY_API_PREFIX}/task-school": ("confirm_task_school", "workspace"),
            }
            if parsed.path not in actions:
                raise Demo2APIError(404, "not_found", "API route not found")
            self._identity_query(parsed, ())
            payload = self._read_json(max_bytes=16 * 1024)
            method, field = actions[parsed.path]
            result = self._identity_call(method, self._session_cookie_token(), payload)
            response = {'ok': True, field: result}
            if method in {'save_binding', 'revoke_binding', 'confirm_task_school'}:
                response['archive_sync'] = sync_student_history()
            self._send_demo2_json(response)

        def _track_identity_region(self, payload: dict[str, Any]) -> dict[str, Any]:
            token = self._session_cookie_token()
            seed = self._identity_call("tracking_seed", token, payload)
            stamps = [self._identity_file_stamp(frame["path"]) for frame in seed["frames"]]
            account_id = _account_id(self._require_account())
            now = time.monotonic()
            with identity_tracking_lock:
                attempts = identity_tracking_attempts.get(account_id, deque())
                while attempts and now - attempts[0] >= 60:
                    attempts.popleft()
                if attempts and (now - attempts[-1] < 2 or len(attempts) >= 12):
                    raise Demo2APIError(429, "tracking_rate_limited", "正在核对后续位置，请稍后再试")
                attempts.append(now)
                identity_tracking_attempts[account_id] = attempts
                identity_tracking_attempts.move_to_end(account_id)
                while len(identity_tracking_attempts) > 1024:
                    identity_tracking_attempts.popitem(last=False)
            if not identity_tracking_slots.acquire(blocking=False):
                raise Demo2APIError(429, "tracking_busy", "后续位置正在计算，请稍后再试")
            try:
                try:
                    tracker = importlib.import_module(".demo2_roi_tracking", package=__package__)
                except ImportError as exc:
                    raise Demo2APIError(503, "tracking_unavailable", "位置跟随组件暂不可用，仍可手动切换画面核对") from exc
                try:
                    result = tracker.track_frames(seed["frames"], seed["bbox"])
                except tracker.TrackingError as exc:
                    raise Demo2APIError(422, "tracking_failed", "暂时无法延续此位置，请换一个清楚的时刻手动框选") from exc
                current = self._identity_call("tracking_seed", token, payload)
                if seed != current or stamps != [self._identity_file_stamp(frame["path"]) for frame in current["frames"]]:
                    raise Demo2APIError(409, "tracking_source_changed", "起始确认或采样画面已变化，请刷新后重新核对")
                points = self._validated_track_points(result, seed)
                return {"binding_id": seed["binding_id"], "student_id": seed["student_id"], "display_name": seed["display_name"],
                        "frame_revision": seed["frame_revision"], "scope": "short_window_suggestion", "window_sec": 5,
                        "algorithm": "opencv_lk", "automatic_identity": False, "status": result["status"],
                        "reason": self._tracking_reason(result.get("reason")), "points": points}
            finally:
                identity_tracking_slots.release()

        @staticmethod
        def _validated_track_points(result: Any, seed: dict[str, Any]) -> list[dict[str, Any]]:
            invalid = Demo2APIError(422, "invalid_tracking_result", "后续位置结果无效，请手动切换画面核对")
            if not isinstance(result, dict) or result.get("status") not in {"completed", "lost", "insufficient"}:
                raise invalid
            points = result.get("points")
            if not isinstance(points, list) or not 1 <= len(points) <= len(seed["frames"]):
                raise invalid
            if (result["status"] == "completed" and (len(points) != len(seed["frames"]) or len(points) < 2)
                    or result["status"] == "lost" and (len(points) < 2 or not isinstance(points[-1], dict) or points[-1].get("status") != "lost")
                    or result["status"] == "insufficient" and len(points) != 1):
                raise invalid
            clean = []
            for index, point in enumerate(points):
                frame = seed["frames"][index]
                if (not isinstance(point, dict) or point.get("frame_key") != frame["frame_key"]
                        or point.get("time_sec") != frame["time_sec"] or point.get("status") not in {"seed", "suggested", "lost"}):
                    raise invalid
                if (index == 0 and (point["status"] != "seed" or point.get("bbox") != seed["bbox"])) or (index > 0 and point["status"] == "seed"):
                    raise invalid
                bbox = point.get("bbox")
                quality = point.get("quality")
                if quality is not None and (type(quality) not in {int, float} or not math.isfinite(quality) or not 0 <= quality <= 1):
                    raise invalid
                if point["status"] == "lost":
                    if bbox is not None or index != len(points) - 1 or result["status"] != "lost":
                        raise invalid
                else:
                    if not isinstance(bbox, dict) or set(bbox) != {"x", "y", "width", "height"}:
                        raise invalid
                    if any(type(value) not in {int, float} or not math.isfinite(value) or not 0 <= value <= 1 for value in bbox.values()):
                        raise invalid
                    if bbox["width"] <= 0 or bbox["height"] <= 0 or bbox["x"] + bbox["width"] > 1.0000001 or bbox["y"] + bbox["height"] > 1.0000001:
                        raise invalid
                clean.append({"frame_key": frame["frame_key"], "time_sec": frame["time_sec"], "bbox": bbox,
                              "status": point["status"], "quality": quality, "reason": ScenarioLabHandler._tracking_reason(point.get("reason"))})
            return clean

        @staticmethod
        def _tracking_reason(value: Any) -> str:
            return value if isinstance(value, str) and re.fullmatch(r"[a-z0-9_]{1,80}", value) else "manual_review_required"

        @staticmethod
        def _identity_file_stamp(path: Path) -> tuple:
            stat = path.stat()
            return (str(path), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino)

        def _detect_identity_faces(self, account: Any, frame_path: Path, identifiers: tuple[str, ...]) -> dict[str, Any]:
            try:
                detector = importlib.import_module(".demo2_face_detection", package=__package__)
            except ImportError:
                return {"available": False, "model": "face_detection_yunet_2023mar.onnx", "faces": [],
                        "reason": "detector_unavailable; manual_confirmation_required", "cached": False}
            model_path = getattr(detector, "MODEL_PATH", None)
            try:
                model_stamp = self._identity_file_stamp(model_path) if model_path is not None else None
            except OSError:
                model_stamp = ("unavailable",)
            frame_stamp = self._identity_file_stamp(frame_path)
            cache_key = (_account_id(account), *identifiers, frame_stamp, model_stamp, id(detector.detect_faces))
            cached = identity_detect_cache.get(cache_key)
            if cached is not None:
                cached["cached"] = True
                return cached
            # Key budgets by authenticated account, not caller-controlled IP or
            # session token; logging in again cannot reset the client budget.
            now = time.monotonic()
            account_id = _account_id(account)
            with identity_detect_lock:
                attempts = identity_detect_attempts.get(account_id, deque())
                while attempts and now - attempts[0] >= DEMO2_IDENTITY_DETECT_WINDOW:
                    attempts.popleft()
                if attempts and (now - attempts[-1] < DEMO2_IDENTITY_DETECT_MIN_INTERVAL or len(attempts) >= DEMO2_IDENTITY_DETECT_LIMIT):
                    raise Demo2APIError(429, "detection_rate_limited", "人脸定位请求过于频繁，请稍后重试；仍可手动框选")
                attempts.append(now)
                identity_detect_attempts[account_id] = attempts
                identity_detect_attempts.move_to_end(account_id)
                while len(identity_detect_attempts) > 1024:
                    identity_detect_attempts.popitem(last=False)
            if not identity_detect_slots.acquire(blocking=False):
                raise Demo2APIError(429, "detection_busy", "人脸定位正在处理，请稍后重试；仍可手动框选")
            try:
                result = detector.detect_faces(frame_path)
                current_path, _ = self._identity_call("frame_file", self._session_cookie_token(), *identifiers)
                if current_path != frame_path or self._identity_file_stamp(current_path) != frame_stamp:
                    raise Demo2APIError(409, "frame_source_changed", "采样画面已发生变化，请刷新后重新定位")
                result["cached"] = False
                if result.get("available") is True:
                    identity_detect_cache.put(cache_key, result, size=len(json.dumps(result).encode("utf-8")))
                return result
            finally:
                identity_detect_slots.release()

        def _send_identity_preview(self, account: Any, token: str, identifiers: tuple[str, ...]) -> None:
            source = self._identity_call("preview_source", token, *identifiers)
            source_path = source["source_path"]
            stamp = self._identity_file_stamp(source_path)
            key = (_account_id(account), *identifiers, stamp, source["time_sec"])
            preview = identity_preview_cache.get(key)
            cache_hit = preview is not None
            if not cache_hit:
                account_id, now = _account_id(account), time.monotonic()
                with identity_preview_lock:
                    attempts = identity_preview_attempts.get(account_id, deque())
                    while attempts and now - attempts[0] >= 60:
                        attempts.popleft()
                    if attempts and (now - attempts[-1] < 2 or len(attempts) >= 12):
                        raise Demo2APIError(429, "preview_rate_limited", "高清画面请求较频繁，请稍后再试")
                    attempts.append(now)
                    identity_preview_attempts[account_id] = attempts
                    identity_preview_attempts.move_to_end(account_id)
                    while len(identity_preview_attempts) > 1024:
                        identity_preview_attempts.popitem(last=False)
                if not identity_preview_slots.acquire(blocking=False):
                    raise Demo2APIError(429, "preview_busy", "高清画面正在读取，请稍后再试")
                try:
                    extractor = importlib.import_module(".demo2_frame_preview", package=__package__)
                    try:
                        preview = extractor.extract_preview(source_path, source["time_sec"])
                    except extractor.PreviewError as exc:
                        messages = {
                            "timeout": "高清画面读取超时，请稍后重试或使用视频回看",
                            "missing_dependency": "高清预览组件暂不可用，仍可使用视频回看",
                            "no_frame": "此时段未能读取到画面，请换一个时段查看",
                            "resource_limit": "视频超过高清预览的资源限制，请使用视频回看",
                            "busy": "高清画面正在读取，请稍后再试",
                        }
                        raise Demo2APIError(422, f"preview_{exc.code}",
                                            messages.get(exc.code, "暂时无法读取高清画面，请使用视频回看")) from exc
                    # Recheck expiry, revision and authorization after decoding.
                    current = self._identity_call("preview_source", token, *identifiers)
                    if current != source or self._identity_file_stamp(current["source_path"]) != stamp:
                        raise Demo2APIError(409, "preview_source_changed", "视频已发生变化，请刷新页面后重试")
                    data = preview.get("image_bytes")
                    if not isinstance(data, bytes) or not 0 < len(data) <= 4 * 1024 * 1024:
                        raise Demo2APIError(422, "preview_invalid", "无法读取高清画面，请使用视频回看")
                    identity_preview_cache.put(key, preview, size=len(data))
                finally:
                    identity_preview_slots.release()
            data = preview["image_bytes"]
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Cache-Control", "no-store, private")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Preview-Cache", "hit" if cache_hit else "miss")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self._write_response(data)

        def _require_account(self) -> Any:
            account = self._current_account()
            if account is None:
                self._discard_denied_body()
                raise Demo2APIError(401, "authentication_required", "请先登录后再操作")
            return account

        def _current_account(self) -> Any | None:
            token = self._session_cookie_token()
            if not token:
                return None
            try:
                return student_store.account_from_session(token)
            except ValueError:
                return None

        def _session_cookie_token(self) -> str:
            header = self.headers.get("Cookie", "")
            if not header:
                return ""
            cookie = SimpleCookie()
            try:
                cookie.load(header)
            except ValueError:
                return ""
            morsel = cookie.get(DEMO2_SESSION_COOKIE)
            return morsel.value.strip() if morsel else ""

        @staticmethod
        def _session_cookie(token: str, *, max_age: int = DEMO2_SESSION_MAX_AGE) -> str:
            cookie = SimpleCookie()
            cookie[DEMO2_SESSION_COOKIE] = token
            morsel = cookie[DEMO2_SESSION_COOKIE]
            morsel["httponly"] = True
            morsel["samesite"] = "Lax"
            morsel["path"] = "/"
            morsel["max-age"] = str(max_age)
            return morsel.OutputString()

        def _send_redirect(self, location: str) -> None:
            self.send_response(302)
            self.send_header("Location", location)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _send_json_error(self, status: int, code: str, message: str) -> None:
            error: dict[str, Any] = {"code": code, "message": message}
            if code == "report_stale":
                # Old snapshots are refused, not silently rebuilt: tell the
                # client to regenerate from the current scoring versions.
                error.update({"stale": True, "status_label": "已过期", "action": "regenerate"})
            self._send_demo2_json({"ok": False, "error": error}, status=status)

        def _send_demo2_json(
            self,
            payload: dict[str, Any],
            status: int = 200,
            *,
            headers: dict[str, str] | None = None,
        ) -> None:
            data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            self._send_text_payload(
                data,
                content_type="application/json; charset=utf-8",
                status=status,
                extra_headers={"Cache-Control": "no-store", **(headers or {})},
            )

        def log_message(self, format: str, *args: Any) -> None:
            return None

        def _read_json(self, *, max_bytes: int = 15 * 1024 * 1024) -> dict[str, Any]:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError as exc:
                raise ValueError("请求长度无效，请刷新后重试") from exc
            if not 0 <= length <= max_bytes:
                raise ValueError(f"请求内容过大或长度无效，最多允许 {max_bytes // 1024}KB")
            try:
                raw = self.rfile.read(length).decode("utf-8")
                payload = json.loads(raw or "{}")
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("请求内容格式无效，请刷新后重试") from exc
            if not isinstance(payload, dict):
                raise ValueError("请求内容必须是 JSON 对象")
            return payload

        def _send_html(self, html: str) -> None:
            self._send_text_payload(
                html.encode("utf-8"),
                content_type="text/html; charset=utf-8",
            )

        def _send_text_payload(
            self,
            data: bytes,
            *,
            content_type: str,
            status: int = 200,
            allow_origin: bool = False,
            extra_headers: dict[str, str] | None = None,
        ) -> None:
            accept_encoding = self.headers.get("Accept-Encoding", "").lower()
            use_gzip = "gzip" in accept_encoding and len(data) >= 1024
            payload = gzip.compress(data, compresslevel=5) if use_gzip else data
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Vary", "Accept-Encoding")
            if use_gzip:
                self.send_header("Content-Encoding", "gzip")
            if allow_origin:
                self.send_header("Access-Control-Allow-Origin", "*")
            for name, value in (extra_headers or {}).items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self._write_response(payload)

        def _send_empty(self, status: int = 204) -> None:
            self.send_response(status)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _send_download(self, path: Path, *, filename: str, content_type: str) -> None:
            data = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type or "application/octet-stream")
            self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(filename)}")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self._write_response(data)

        def _send_media(self, path: Path, *, content_type: str, download_name: str | None = None) -> None:
            # Range streaming allows seeking in long classroom recordings without loading GBs into memory.
            with path.open("rb") as media:
                size = os.fstat(media.fileno()).st_size
                start, end = 0, size - 1
                range_header = self.headers.get("Range", "")
                if range_header:
                    match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip())
                    valid = bool(match and (match[1] or match[2]))
                    if valid:
                        if match[1]:
                            start = int(match[1])
                            end = min(int(match[2]), size - 1) if match[2] else size - 1
                        else:
                            suffix = int(match[2])
                            start = max(0, size - suffix)
                            valid = suffix > 0
                        valid = valid and 0 <= start <= end < size
                    if not valid:
                        self.send_response(416)
                        self.send_header("Content-Range", f"bytes */{size}")
                        self.send_header("Content-Length", "0")
                        self.send_header("Cache-Control", "no-store")
                        self.end_headers()
                        return
                self.send_response(206 if range_header else 200)
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", "no-store, private")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Accept-Ranges", "bytes")
                if download_name:
                    self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(download_name)}")
                self.send_header("Content-Length", str(max(0, end - start + 1)))
                if range_header:
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                self.end_headers()
                media.seek(start)
                remaining = end - start + 1
                while remaining > 0 and not self._peer_disconnected:
                    block = media.read(min(256 * 1024, remaining))
                    if not block:
                        break
                    self._write_response(block)
                    remaining -= len(block)

        def _send_mujoco_asset(self, request_path: str) -> None:
            filename = Path(unquote(request_path)).name
            if not filename:
                self.send_error(404, "Not found")
                return
            asset = (MUJOCO_FRAME_DIR / filename).resolve()
            root = MUJOCO_FRAME_DIR.resolve()
            if root not in asset.parents and asset != root:
                self.send_error(403, "Forbidden")
                return
            if not asset.exists() or not asset.is_file():
                self.send_error(404, "Not found")
                return
            content_type = mimetypes.guess_type(asset.name)[0] or "application/octet-stream"
            data = asset.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self._write_response(data)

        def _send_seewo_demo_asset(self, request_path: str) -> None:
            relative = unquote(request_path).split("/assets/seewo_xiaoyudi_demo/", 1)[-1]
            if not relative:
                self.send_error(404, "Not found")
                return
            asset = (SEEWO_STUDENT_DEMO_OUTPUT_DIR / relative).resolve()
            root = SEEWO_STUDENT_DEMO_OUTPUT_DIR.resolve()
            if root not in asset.parents and asset != root:
                self.send_error(403, "Forbidden")
                return
            if not asset.exists() or not asset.is_file():
                self.send_error(404, "Not found")
                return
            data = asset.read_bytes()
            content_type = mimetypes.guess_type(asset.name)[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self._write_response(data)

        def _send_seewo_demo2_asset(self, request_path: str) -> None:
            relative = unquote(request_path).split("/assets/seewo_demo2/", 1)[-1]
            if not relative:
                self.send_error(404, "Not found")
                return
            relative_path = Path(relative)
            if (
                len(relative_path.parts) != 2
                or relative_path.suffix.lower() not in DEMO2_PUBLIC_ASSET_EXTENSIONS
            ):
                self.send_error(404, "Not found")
                return
            asset = (SEEWO_DEMO2_OUTPUT_DIR / relative_path).resolve()
            root = SEEWO_DEMO2_OUTPUT_DIR.resolve()
            if root not in asset.parents and asset != root:
                self.send_error(403, "Forbidden")
                return
            if not asset.exists() or not asset.is_file():
                self.send_error(404, "Not found")
                return
            data = asset.read_bytes()
            content_type = mimetypes.guess_type(asset.name)[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self._write_response(data)

        def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
            data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            self._send_text_payload(
                data,
                content_type="application/json; charset=utf-8",
                status=status,
                allow_origin=True,
            )

    return ScenarioLabHandler


def run_server(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    scenario_dir: Path = DEFAULT_SCENARIO_DIR,
    model_path: Path = DEFAULT_LEARNED_POLICY_PATH,
    policy_name: str = "learned",
) -> ThreadingHTTPServer:
    handler = create_handler(
        scenario_dir=scenario_dir,
        model_path=model_path,
        policy_name=policy_name,
    )
    retention_store = get_demo2_student_store()
    stop_retention = Event()
    try:
        retention_interval = max(
            60,
            int(os.getenv("REHAB_DEMO2_RETENTION_SCAN_SECONDS", "3600")),
        )
    except ValueError:
        retention_interval = 3600

    def retention_worker() -> None:
        while not stop_retention.is_set():
            try:
                retention_store.enforce_raw_media_retention()
            except Exception as exc:  # pragma: no cover - operational guard
                print(f"Retention scan failed: {exc}", flush=True)
            stop_retention.wait(retention_interval)

    retention_thread = Thread(
        target=retention_worker,
        name="demo2-retention",
        daemon=True,
    )
    from .demo2_media_worker import VideoAnalysisWorker

    media_worker = VideoAnalysisWorker(retention_store)
    server = ThreadingHTTPServer((host, port), handler)
    dossier_cleanup = getattr(handler, "cleanup_expired_dossiers", None)
    safety_cleanup = getattr(handler, "cleanup_expired_safety", None)
    summary_cleanup = getattr(handler, "cleanup_expired_student_summaries", None)
    maintenance_options = {"safety_cleanup": safety_cleanup} if callable(safety_cleanup) else {}
    if callable(summary_cleanup):
        maintenance_options['summary_cleanup'] = summary_cleanup
    dossier_maintenance = (_DossierMaintenance(dossier_cleanup, **maintenance_options)
                           if callable(dossier_cleanup) or callable(safety_cleanup) or callable(summary_cleanup) else None)
    try:
        retention_thread.start()
        if dossier_maintenance is not None:
            dossier_maintenance.start()
        if os.getenv("REHAB_DEMO2_MEDIA_WORKER", "1") != "0":
            media_worker.start()
        print(f"Scenario Lab running at http://{host}:{port}", flush=True)
        server.serve_forever()
    finally:
        stop_retention.set()
        try:
            media_worker.stop()
        finally:
            try:
                try:
                    if dossier_maintenance is not None:
                        dossier_maintenance.stop()
                finally:
                    if retention_thread.ident is not None:
                        retention_thread.join(timeout=2)
            finally:
                server.server_close()
    return server


def _render_lab_html() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>RehabAffect Scenario Lab</title>
  <style>
    :root {
      --bg: #f5f7f2;
      --panel: #ffffff;
      --ink: #14201a;
      --muted: #607068;
      --line: #d7dfd1;
      --blue: #2563eb;
      --green: #16783a;
      --amber: #b7791f;
      --red: #c24135;
      --violet: #6d4aff;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: Inter, "Segoe UI", Arial, sans-serif;
      line-height: 1.42;
    }
    header {
      background: #fff;
      border-bottom: 1px solid var(--line);
      padding: 20px 28px 16px;
    }
    h1 {
      margin: 0 0 6px;
      font-size: 26px;
      letter-spacing: 0;
    }
    .subtitle {
      color: var(--muted);
      font-size: 14px;
      max-width: 1080px;
    }
    main {
      display: grid;
      grid-template-columns: 290px minmax(430px, 1fr) 430px;
      gap: 14px;
      padding: 16px;
    }
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      min-width: 0;
      overflow: hidden;
    }
    .panel-head {
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
      font-weight: 700;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
    }
    .body {
      padding: 12px;
      display: grid;
      gap: 12px;
    }
    label {
      color: var(--muted);
      font-size: 12px;
      display: grid;
      gap: 5px;
    }
    select, input, textarea {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 8px 9px;
      font: inherit;
      background: #fff;
      color: var(--ink);
    }
    textarea {
      resize: vertical;
      min-height: 70px;
    }
    .grid2 {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
    }
    .checks {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
    }
    .checks label {
      display: flex;
      align-items: center;
      gap: 7px;
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 8px;
      color: var(--ink);
    }
    .checks input { width: auto; }
    .preset-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
    }
    .preset {
      font-size: 12px;
      padding: 8px;
    }
    button {
      border: 1px solid var(--line);
      border-radius: 7px;
      background: #fff;
      color: var(--ink);
      padding: 9px 11px;
      font: inherit;
      cursor: pointer;
    }
    .primary {
      background: var(--blue);
      color: #fff;
      border-color: var(--blue);
      font-weight: 700;
    }
    .scene {
      border: 1px solid var(--line);
      background: #edf3e9;
      border-radius: 8px;
      min-height: 360px;
      overflow: hidden;
    }
    .scene svg {
      width: 100%;
      min-height: 360px;
      display: block;
    }
    .metrics {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 9px;
    }
    .metric {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px;
      background: #fff;
    }
    .metric .label {
      color: var(--muted);
      font-size: 11px;
    }
    .metric .value {
      font-weight: 700;
      font-size: 18px;
      margin-top: 3px;
      overflow-wrap: anywhere;
    }
    .action {
      border-left: 3px solid var(--violet);
      background: #fbfaff;
      padding: 10px 12px;
      border-radius: 0 7px 7px 0;
      font-size: 12px;
    }
    .trajectory {
      display: grid;
      gap: 8px;
      font-size: 12px;
    }
    .trace-step {
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 8px 9px;
      background: #fff;
    }
    .trace-step strong {
      color: var(--blue);
    }
    pre {
      margin: 0;
      background: #101812;
      color: #e7f5eb;
      padding: 12px;
      border-radius: 7px;
      overflow: auto;
      max-height: 500px;
      font-size: 11px;
    }
    .tabs {
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
    }
    .tab.active {
      border-color: var(--blue);
      color: var(--blue);
    }
    .status {
      font-size: 12px;
      color: var(--muted);
    }
    @media (max-width: 1160px) {
      main { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <header>
    <h1>Scenario Lab</h1>
    <div class="subtitle">本地实时实验台：编辑学生线索和机器人上下文，调用真实 Python pipeline，返回 human_state 与 robot_action。</div>
  </header>
  <main>
    <section class="panel">
      <div class="panel-head">输入</div>
      <div class="body">
        <label>scenario<select id="scenario"></select></label>
        <label>step<select id="step"></select></label>
        <label>speech<textarea id="speech"></textarea></label>
        <div class="grid2">
          <label>face state<select id="faceState"></select></label>
          <label>expected action<select id="expectedAction"></select></label>
        </div>
        <div class="grid2">
          <label>attention<input id="attention" type="number" min="0" max="1" step="0.01"></label>
          <label>movement<input id="movement" type="number" min="0" max="1" step="0.01"></label>
        </div>
        <div class="grid2">
          <label>response delay<input id="delay" type="number" min="0" max="10" step="0.1"></label>
          <label>failure count<input id="failure" type="number" min="0" max="10" step="1"></label>
        </div>
        <div class="grid2">
          <label>robot distance<input id="robotDistance" type="number" min="0.3" max="3" step="0.01"></label>
          <label>obstacle distance<input id="obstacleDistance" type="number" min="0.1" max="3" step="0.01"></label>
        </div>
        <div class="checks">
          <label><input id="robotMoving" type="checkbox">robot moving</label>
          <label><input id="painGuarding" type="checkbox">pain guarding</label>
        </div>
        <div class="preset-grid">
          <button class="preset" data-preset="engaged">engaged</button>
          <button class="preset" data-preset="confused">confused</button>
          <button class="preset" data-preset="pain">pain stop</button>
          <button class="preset" data-preset="refusal">refusal</button>
        </div>
        <button class="primary" id="run">Run Pipeline</button>
        <button id="runLoop">Run Closed Loop</button>
        <div class="status" id="status">ready</div>
      </div>
    </section>
    <section class="panel">
      <div class="panel-head">场景</div>
      <div class="body">
        <div class="scene" id="scene"></div>
        <div class="metrics">
          <div class="metric"><div class="label">human_state</div><div class="value" id="humanState">n/a</div></div>
          <div class="metric"><div class="label">confidence</div><div class="value" id="confidence">n/a</div></div>
          <div class="metric"><div class="label">risk</div><div class="value" id="risk">n/a</div></div>
          <div class="metric"><div class="label">action</div><div class="value" id="action">n/a</div></div>
        </div>
        <div class="action" id="actionBox">No result yet.</div>
        <div class="trajectory" id="trajectory"></div>
      </div>
    </section>
    <section class="panel">
      <div class="panel-head">输出</div>
      <div class="body">
        <div class="tabs">
          <button class="tab active" data-tab="human_state">human_state</button>
          <button class="tab" data-tab="robot_action">robot_action</button>
          <button class="tab" data-tab="post_action_context">post_context</button>
          <button class="tab" data-tab="closed_loop">closed_loop</button>
          <button class="tab" data-tab="full">full</button>
        </div>
        <pre id="json">Run a step.</pre>
      </div>
    </section>
  </main>
  <script>
    const states = ['engaged','confused','fatigued','frustrated','refusing','pain_risk','low_attention','needs_help'];
    const actions = ['continue_and_encourage','repeat_instruction_slowly','reduce_task_load_and_offer_break','pause_and_request_consent','stop_and_check_pain_risk','regain_attention','offer_help'];
    let scenarios = [];
    let currentScenario = null;
    let currentResult = null;
    let currentLoop = null;
    let activeTab = 'human_state';
    const el = (id) => document.getElementById(id);
    const fmt = (value) => typeof value === 'number' ? value.toFixed(2) : String(value ?? 'n/a');

    function fillOptions(select, values) {
      select.innerHTML = values.map((value) => `<option value="${value}">${value}</option>`).join('');
    }

    async function api(path, options = {}) {
      const response = await fetch(path, options);
      const data = await response.json();
      if (!response.ok || data.error) throw new Error(data.error || response.statusText);
      return data;
    }

    async function init() {
      fillOptions(el('faceState'), states);
      fillOptions(el('expectedAction'), actions);
      const payload = await api('/api/scenarios');
      scenarios = payload.scenarios;
      fillOptions(el('scenario'), scenarios.map((item) => item.scenario_id));
      const params = new URLSearchParams(window.location.search);
      const scenarioParam = params.get('scenario');
      const scenarioId = scenarios.some((item) => item.scenario_id === scenarioParam)
        ? scenarioParam
        : scenarios[0].scenario_id;
      el('scenario').value = scenarioId;
      await loadScenario(scenarioId);
      const preset = params.get('preset');
      if (preset) applyPreset(preset);
      if (params.get('loop') === '1') {
        await runClosedLoop();
      } else {
        await runStep();
      }
    }

    async function loadScenario(id) {
      currentScenario = await api('/api/scenario?id=' + encodeURIComponent(id));
      fillOptions(el('step'), currentScenario.steps.map((step, index) => `Step ${index}: ${step.ground_truth_state}`));
      el('step').selectedIndex = 0;
      loadStepIntoForm();
    }

    function loadStepIntoForm() {
      const step = currentScenario.steps[el('step').selectedIndex];
      const cues = step.observable_cues || {};
      const context = step.robot_context || {};
      el('speech').value = cues.speech_text || '';
      el('faceState').value = cues.face_state_hint || step.ground_truth_state || 'engaged';
      el('expectedAction').value = step.expected_action_id || 'continue_and_encourage';
      el('attention').value = cues.attention_score ?? 0.55;
      el('movement').value = cues.movement_speed ?? 0.25;
      el('delay').value = cues.response_delay_sec ?? 0;
      el('failure').value = cues.recent_failure_count ?? 0;
      el('robotDistance').value = context.robot_distance_m ?? 1.0;
      el('obstacleDistance').value = context.obstacle_distance_m ?? 1.0;
      el('robotMoving').checked = Boolean(context.is_robot_moving);
      el('painGuarding').checked = Boolean(cues.pain_guarding);
      renderScene(null);
    }

    function updatesFromForm() {
      return {
        expected_action_id: el('expectedAction').value,
        observable_cues: {
          speech_text: el('speech').value,
          face_state_hint: el('faceState').value,
          attention_score: Number(el('attention').value),
          movement_speed: Number(el('movement').value),
          response_delay_sec: Number(el('delay').value),
          recent_failure_count: Number(el('failure').value),
          pain_guarding: el('painGuarding').checked
        },
        robot_context: {
          robot_distance_m: Number(el('robotDistance').value),
          obstacle_distance_m: Number(el('obstacleDistance').value),
          is_robot_moving: el('robotMoving').checked
        }
      };
    }

    function applyPreset(name) {
      const presets = {
        engaged: {
          speech: '我在看',
          faceState: 'engaged',
          expectedAction: 'continue_and_encourage',
          attention: 0.78,
          movement: 0.24,
          delay: 1,
          failure: 0,
          robotDistance: 1.0,
          obstacleDistance: 0.9,
          robotMoving: true,
          painGuarding: false
        },
        confused: {
          speech: '我不会，可以再说一遍吗',
          faceState: 'confused',
          expectedAction: 'repeat_instruction_slowly',
          attention: 0.52,
          movement: 0.16,
          delay: 4,
          failure: 2,
          robotDistance: 1.1,
          obstacleDistance: 1.2,
          robotMoving: false,
          painGuarding: false
        },
        pain: {
          speech: '我疼，不想动',
          faceState: 'pain_risk',
          expectedAction: 'stop_and_check_pain_risk',
          attention: 0.3,
          movement: 0.05,
          delay: 3,
          failure: 1,
          robotDistance: 0.45,
          obstacleDistance: 0.25,
          robotMoving: true,
          painGuarding: true
        },
        refusal: {
          speech: '我不想做了',
          faceState: 'refusing',
          expectedAction: 'pause_and_request_consent',
          attention: 0.35,
          movement: 0.03,
          delay: 6,
          failure: 3,
          robotDistance: 0.65,
          obstacleDistance: 0.9,
          robotMoving: true,
          painGuarding: false
        }
      };
      const preset = presets[name];
      if (!preset) return;
      el('speech').value = preset.speech;
      el('faceState').value = preset.faceState;
      el('expectedAction').value = preset.expectedAction;
      el('attention').value = preset.attention;
      el('movement').value = preset.movement;
      el('delay').value = preset.delay;
      el('failure').value = preset.failure;
      el('robotDistance').value = preset.robotDistance;
      el('obstacleDistance').value = preset.obstacleDistance;
      el('robotMoving').checked = preset.robotMoving;
      el('painGuarding').checked = preset.painGuarding;
      renderScene(null);
    }

    async function runStep() {
      el('status').textContent = 'running';
      currentResult = await api('/api/process_step', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          scenario_id: el('scenario').value,
          step_index: el('step').selectedIndex,
          policy: 'learned',
          updates: updatesFromForm()
        })
      });
      el('status').textContent = currentResult.action_match ? 'action match' : 'action changed';
      renderResult();
    }

    async function runClosedLoop() {
      el('status').textContent = 'running closed loop';
      currentLoop = await api('/api/run_closed_loop', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          scenario_id: el('scenario').value,
          step_index: el('step').selectedIndex,
          policy: 'learned',
          updates: updatesFromForm()
        })
      });
      const score = currentLoop.aggregate_metrics?.mean_closed_loop_score || currentLoop.metrics?.closed_loop_score;
      el('status').textContent = `closed loop score ${fmt(score)}`;
      renderLoop(currentLoop);
      setActiveTab('closed_loop');
      renderJson();
    }

    function renderResult() {
      const state = currentResult.human_state;
      const action = currentResult.robot_action;
      el('humanState').textContent = state.state;
      el('confidence').textContent = fmt(state.confidence);
      el('risk').textContent = state.risk_level;
      el('action').textContent = action.action_id;
      el('actionBox').innerHTML = `<strong>${action.action_id}</strong><br>speech: ${action.speech_action}<br>motion: ${action.motion_policy}<br>task: ${action.task_adjustment}<br>safety: ${action.safety_action}<br>shield: ${action.metadata?.action_shield || 'none'}`;
      el('trajectory').innerHTML = '';
      renderScene(currentResult);
      renderJson();
    }

    function renderLoop(loop) {
      const metrics = loop.metrics || {};
      const rows = (loop.steps || []).map((step) => {
        const feedback = step.embodied_feedback || {};
        const action = step.robot_action || {};
        return `<div class="trace-step">
          <strong>step ${step.step}</strong>
          ${step.base_ground_truth_state} -> ${step.ground_truth_state} -> ${step.human_state?.state}
          <br>action: ${action.action_id}
          <br>motion: ${action.motion_policy}; outcome: ${feedback.outcome}
        </div>`;
      }).join('');
      el('trajectory').innerHTML = `<div class="action">
        <strong>closed-loop trajectory</strong><br>
        action: ${fmt(metrics.action_match_accuracy * 100)}% |
        recovery: ${metrics.recovery_count ?? 0} |
        risk containment: ${metrics.risk_containment_count ?? 0} |
        safety violations: ${metrics.safety_violation_count ?? 0}
      </div>${rows}`;
      if (loop.steps?.length) {
        const last = loop.steps[loop.steps.length - 1];
        const state = last.human_state || {};
        const action = last.robot_action || {};
        el('humanState').textContent = state.state || 'n/a';
        el('confidence').textContent = fmt(state.confidence);
        el('risk').textContent = state.risk_level || 'n/a';
        el('action').textContent = action.action_id || 'n/a';
        el('actionBox').innerHTML = `<strong>${action.action_id}</strong><br>speech: ${action.speech_action}<br>motion: ${action.motion_policy}<br>task: ${action.task_adjustment}<br>safety: ${action.safety_action}<br>closed-loop score: ${fmt(metrics.closed_loop_score)}`;
        renderScene(last);
      }
    }

    function renderScene(result) {
      const context = result?.robot_context || {
        robot_distance_m: Number(el('robotDistance').value || 1),
        obstacle_distance_m: Number(el('obstacleDistance').value || 1),
        is_robot_moving: el('robotMoving').checked
      };
      const post = result?.post_action_context || context;
      const state = result?.human_state?.state || el('faceState').value;
      const robotX = mapDistance(post.robot_distance_m ?? context.robot_distance_m, 340);
      const obstacleX = mapDistance(context.obstacle_distance_m, 250);
      const studentColor = {engaged:'#16783a', confused:'#b7791f', fatigued:'#b7791f', refusing:'#c24135', pain_risk:'#c24135', low_attention:'#c24135', needs_help:'#2563eb'}[state] || '#657069';
      const robotColor = post.is_robot_moving ? '#6d4aff' : '#2563eb';
      el('scene').innerHTML = `<svg viewBox="0 0 760 430">
        <rect x="22" y="22" width="716" height="386" rx="8" fill="#f7faf4" stroke="#d8dfd1"/>
        <rect x="460" y="268" width="190" height="76" rx="6" fill="#c99e69"/>
        <text x="512" y="312" font-size="18">desk / task</text>
        <rect x="${obstacleX}" y="88" width="58" height="58" rx="6" fill="#e3aa1b"/>
        <text x="${obstacleX - 2}" y="166" font-size="15">obstacle</text>
        <circle cx="505" cy="190" r="42" fill="${studentColor}"/>
        <text x="473" y="197" font-size="16" fill="#fff">student</text>
        <circle cx="650" cy="112" r="34" fill="#16783a"/>
        <text x="624" y="118" font-size="15" fill="#fff">teacher</text>
        <circle cx="${robotX}" cy="202" r="40" fill="${robotColor}"/>
        <text x="${robotX - 25}" y="209" font-size="16" fill="#fff">robot</text>
        <line x1="${robotX + 40}" y1="202" x2="463" y2="193" stroke="#8f9a92" stroke-width="2" stroke-dasharray="7 7"/>
      </svg>`;
    }

    function mapDistance(value, origin) {
      const distance = Number(value ?? 1);
      return Math.max(70, Math.min(430, Math.round(origin - distance * 190)));
    }

    function renderJson() {
      const data = activeTab === 'closed_loop'
        ? currentLoop
        : activeTab === 'full'
          ? currentResult
          : currentResult?.[activeTab];
      el('json').textContent = JSON.stringify(data || {}, null, 2);
    }

    function setActiveTab(name) {
      activeTab = name;
      document.querySelectorAll('.tab').forEach((tab) => {
        tab.classList.toggle('active', tab.dataset.tab === name);
      });
    }

    el('scenario').addEventListener('change', async () => {
      await loadScenario(el('scenario').value);
      await runStep();
    });
    el('step').addEventListener('change', async () => {
      loadStepIntoForm();
      await runStep();
    });
    el('run').addEventListener('click', runStep);
    el('runLoop').addEventListener('click', runClosedLoop);
    document.querySelectorAll('[data-preset]').forEach((button) => {
      button.addEventListener('click', async () => {
        applyPreset(button.dataset.preset);
        await runStep();
      });
    });
    document.querySelectorAll('.tab').forEach((button) => {
      button.addEventListener('click', () => {
        setActiveTab(button.dataset.tab);
        renderJson();
      });
    });
    init().catch((error) => {
      el('status').textContent = error.message;
      el('json').textContent = error.stack || error.message;
    });
  </script>
</body>
</html>
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the local editable Scenario Lab server.")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--scenario-dir", type=Path, default=DEFAULT_SCENARIO_DIR)
    parser.add_argument("--model-path", type=Path, default=DEFAULT_LEARNED_POLICY_PATH)
    parser.add_argument("--policy", choices=("rule", "learned"), default="learned")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    run_server(
        host=args.host,
        port=args.port,
        scenario_dir=args.scenario_dir,
        model_path=args.model_path,
        policy_name=args.policy,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
