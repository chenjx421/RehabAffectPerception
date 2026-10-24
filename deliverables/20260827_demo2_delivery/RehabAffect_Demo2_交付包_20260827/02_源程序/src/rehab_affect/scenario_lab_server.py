from __future__ import annotations

import argparse
import copy
import gzip
import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
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
from .student_record_store import get_demo2_student_store
from .showcase import render_showcase_html


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787
MUJOCO_FRAME_DIR = PROJECT_ROOT / "outputs" / "mujoco_frames"


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
) -> type[BaseHTTPRequestHandler]:
    student_store = get_demo2_student_store()

    def sync_demo_students() -> dict[str, Any]:
        demo_payload = load_seewo_demo2()
        student_store.ensure_students(demo_payload.get("students", []))
        return demo_payload

    class ScenarioLabHandler(BaseHTTPRequestHandler):
        server_version = "RehabAffectScenarioLab/0.1"

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
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
                    self._send_json(student_store.storage_summary())
                elif parsed.path == "/api/seewo_demo2/video_channels":
                    self._send_json(student_store.video_channels())
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
                    result_path, filename = student_store.video_result_for_download(task_id)
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
            except Exception as exc:  # pragma: no cover - handler safety
                self._send_json({"error": str(exc)}, status=500)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
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
                    course_id = str(payload.get("course_id", "")).strip()
                    if not course_id:
                        raise ValueError("course_id is required")
                    saved = save_teacher_reviews(course_id, payload.get("reviews", {}))
                    self._send_json({"ok": True, "course_id": course_id, "reviews": saved})
                elif parsed.path == "/api/seewo_demo2_long_report":
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
                    sync_demo_students()
                    document = student_store.save_document(payload)
                    self._send_json({"ok": True, "document": document})
                elif parsed.path == "/api/seewo_demo2/support_profile":
                    sync_demo_students()
                    profile = student_store.save_support_profile(payload)
                    self._send_json({"ok": True, "support_profile": profile})
                elif parsed.path == "/api/seewo_demo2/storage_policy":
                    policy = student_store.update_policy(payload)
                    self._send_json({"ok": True, "policy": policy})
                elif parsed.path == "/api/seewo_demo2/document_delete":
                    result = student_store.delete_document(str(payload.get("document_id", "")))
                    self._send_json({"ok": True, **result})
                elif parsed.path == "/api/seewo_demo2/video_task":
                    task = student_store.create_video_task(payload)
                    self._send_json({"ok": True, "task": task})
                elif parsed.path == "/api/seewo_demo2/video_chunk":
                    task = student_store.append_video_chunk(payload)
                    self._send_json({"ok": True, "task": task})
                elif parsed.path == "/api/seewo_demo2/security_acceptance":
                    acceptance = student_store.record_security_acceptance(payload)
                    self._send_json({"ok": True, "acceptance": acceptance})
                elif parsed.path == "/api/seewo_demo2/archive_video_result":
                    resource = student_store.archive_video_result(payload)
                    self._send_json({"ok": True, "resource": resource})
                else:
                    self.send_error(404, "Not found")
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=400)

        def log_message(self, format: str, *args: Any) -> None:
            return None

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 15 * 1024 * 1024:
                raise ValueError("请求内容超过 15MB 限制")
            raw = self.rfile.read(length).decode("utf-8")
            return json.loads(raw or "{}")

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
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

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
            self.wfile.write(data)

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
            self.wfile.write(data)

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
            self.wfile.write(data)

        def _send_seewo_demo2_asset(self, request_path: str) -> None:
            relative = unquote(request_path).split("/assets/seewo_demo2/", 1)[-1]
            if not relative:
                self.send_error(404, "Not found")
                return
            asset = (SEEWO_DEMO2_OUTPUT_DIR / relative).resolve()
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
            self.wfile.write(data)

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
    server = ThreadingHTTPServer((host, port), handler)
    print(f"Scenario Lab running at http://{host}:{port}", flush=True)
    server.serve_forever()
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
