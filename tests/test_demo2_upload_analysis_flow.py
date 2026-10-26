"""Teacher upload main line: course info -> upload -> background processing -> task result."""

from __future__ import annotations

import base64
import http.client
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

import pytest

import rehab_affect.scenario_lab_server as server_module
from rehab_affect import demo2_media_analysis as media
from rehab_affect.demo2_media_worker import VideoAnalysisWorker
from rehab_affect.demo2_portal import render_demo2_upload_html
from rehab_affect.demo2_upload_debug import DEBUG_LOG_DIR_ENV
from rehab_affect.student_record_store import Demo2StudentRecordStore


PASSWORD_PREFIX = "UploadFlowTest-"
SCHOOL = {"city": "Synthetic City", "district": "Synthetic District", "school_name": "Synthetic School"}


def _request(port: int, method: str, path: str, payload: Any = None, *, cookie: str = "") -> tuple[int, dict, Any]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if cookie:
        headers["Cookie"] = cookie
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        raw = response.read()
        response_headers = {key.lower(): value for key, value in response.getheaders()}
        if "application/json" in response_headers.get("content-type", ""):
            return response.status, response_headers, json.loads(raw.decode("utf-8"))
        return response.status, response_headers, raw.decode("utf-8")
    finally:
        connection.close()


def _login(port: int, username: str) -> str:
    status, headers, _ = _request(port, "POST", "/api/v1/demo2/auth/login",
                                  {"username": username, "password": PASSWORD_PREFIX + username})
    assert status == 200
    return headers["set-cookie"].split(";", 1)[0]


def _read_log(folder: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for path in sorted(folder.glob("upload_debug_*.jsonl")):
        entries.extend(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    return entries


@pytest.fixture()
def flow(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("REHAB_DEMO2_ACCOUNT_PASSWORD_PREFIX", PASSWORD_PREFIX)
    log_dir = tmp_path / "upload-logs"
    monkeypatch.setenv(DEBUG_LOG_DIR_ENV, str(log_dir))
    store = Demo2StudentRecordStore(tmp_path / "flow.sqlite3", tmp_path / "documents")
    monkeypatch.setattr(server_module, "get_demo2_student_store", lambda: store)
    monkeypatch.setattr(server_module, "load_seewo_demo2", lambda force=False: {"students": []})
    handler = server_module.create_handler(scenario_dir=tmp_path, model_path=tmp_path / "unused.json",
                                           policy_name="rule")
    httpd = server_module.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        port = httpd.server_port
        cookie = _login(port, "school_uploader_01")
        assert _request(port, "POST", "/api/v1/demo2/school/context", SCHOOL, cookie=cookie)[0] == 200
        yield {"port": port, "store": store, "cookie": cookie, "log_dir": log_dir}
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _create_task(flow: dict[str, Any], *, course_id: str = "flow-course", content: bytes = b"synthetic",
                 channel_id: str = "channel_1") -> tuple[int, Any]:
    status, _, body = _request(flow["port"], "POST", "/api/v1/demo2/upload/tasks", {
        "channel_id": channel_id, "uploader_name": "Synthetic Teacher", "course_id": course_id,
        "course_name": "生活语文", "session_id": f"{course_id}-2026-10-26", "filename": "synthetic.mp4",
        "mime_type": "video/mp4", "byte_size": len(content), "total_chunks": 1,
        "security_confirmed": True, "allow_company_archive": False,
    }, cookie=flow["cookie"])
    return status, body


def _upload(flow: dict[str, Any], task_id: str, *, course_id: str = "flow-course", content: bytes = b"synthetic"):
    return _request(flow["port"], "POST", "/api/v1/demo2/upload/chunks", {
        "task_id": task_id, "course_id": course_id, "chunk_index": 0,
        "content_base64": base64.b64encode(content).decode("ascii"),
    }, cookie=flow["cookie"])


def _pause_channel(store: Demo2StudentRecordStore, channel_id: str = "channel_1") -> None:
    with sqlite3.connect(store.db_path) as connection:
        connection.execute("UPDATE video_upload_channels SET status = 'paused' WHERE channel_id = ?", (channel_id,))


def test_upload_page_asks_only_course_name_and_date_and_tracks_background_stage() -> None:
    html = render_demo2_upload_html({"role": "school_uploader", "username": "t1", "bound_channel_id": "channel_1"})
    assert 'id="courseName"' in html and 'id="lessonDate"' in html and 'type="date"' in html
    # Course batch and student focus stay behind advanced mode; the main line is short.
    assert 'class="field advanced-only"><label for="courseId">' in html
    assert 'class="field advanced-only"><label for="studentSelect">' in html
    assert 'id="uploadStages"' in html and "后台处理" in html and "学生状态结果" in html
    assert "'&from=upload'" in html and "/demo2/simple-result?task_id=" in html
    assert 'id="channelPauseAlert"' in html and "（已暂停）" in html
    assert "debugLog('upload_start'" in html and "debugLog('upload_chunk'" in html
    assert "debugLog('upload_resume'" in html and "debugLog('result_redirect'" in html
    assert "debugLog('processing_failed'" in html and "debugLog('processing_start'" in html


def test_full_flow_logs_each_step_and_redirect_lands_on_task_scoped_result(flow) -> None:
    store, port = flow["store"], flow["port"]
    status, body = _create_task(flow)
    assert status == 200
    task_id = body["task"]["task_id"]
    assert body["task"]["channel_id"] == "channel_1"
    status, _, body = _upload(flow, task_id)
    assert status == 200 and body["task"]["upload_status"] == "completed"
    assert body["task"]["analysis_status"] == "queued"

    def processor(task, output_dir, *, progress, stop_event):
        progress(50, "synthetic")
        return {"version": "synthetic-flow-v1", "task_id": task["task_id"], "content": {"synthetic": True}}

    worker = VideoAnalysisWorker(store, processor=processor)
    assert worker.run_once()
    status, _, body = _request(port, "GET", f"/api/v1/demo2/upload/task?id={task_id}", cookie=flow["cookie"])
    assert status == 200 and body["task"]["analysis_status"] == "evidence_ready"

    status, _, page = _request(port, "GET", f"/demo2/simple-result?task_id={task_id}&from=upload",
                               cookie=flow["cookie"])
    assert status == 200 and "<html" in page.lower()
    # Any other extra query parameter is still rejected.
    status, _, _ = _request(port, "GET", f"/demo2/simple-result?task_id={task_id}&from=elsewhere",
                            cookie=flow["cookie"])
    assert status == 400

    entries = _read_log(flow["log_dir"])
    operations = [entry["operation"] for entry in entries]
    for expected in ("upload_start", "upload_chunk", "upload_complete", "processing_start",
                     "processing_complete", "result_redirect"):
        assert expected in operations, (expected, operations)
    for entry in entries:
        assert entry["ts"] and entry["result"]
    start = next(e for e in entries if e["operation"] == "upload_start")
    assert start["task_id"] == task_id and start["channel_id"] == "channel_1"
    assert start["byte_size"] == len(b"synthetic") and isinstance(start["duration_ms"], float)
    chunk = next(e for e in entries if e["operation"] == "upload_chunk")
    assert chunk["result"] == "ok" and chunk["chunk_index"] == 0 and chunk["received_bytes"] == len(b"synthetic")
    done = next(e for e in entries if e["operation"] == "processing_complete")
    assert done["task_id"] == task_id and done["channel_id"] == "channel_1" and "duration_ms" in done
    redirect = next(e for e in entries if e["operation"] == "result_redirect")
    assert redirect["result"] == "ok" and redirect["task_id"] == task_id and redirect["channel_id"] == "channel_1"
    raw = "\n".join(path.read_text(encoding="utf-8") for path in flow["log_dir"].glob("*.jsonl"))
    # No filename, course name or teacher name ever reaches the debug log.
    assert "synthetic.mp4" not in raw and "生活语文" not in raw and "Synthetic Teacher" not in raw


def test_result_api_returns_only_requested_task_and_rejects_other_accounts(flow) -> None:
    store, port = flow["store"], flow["port"]
    first = _create_task(flow, course_id="course-a")[1]["task"]["task_id"]
    second = _create_task(flow, course_id="course-b")[1]["task"]["task_id"]
    status, _, body = _request(port, "GET", f"/api/v1/demo2/simple-result?task_id={first}", cookie=flow["cookie"])
    assert status == 200 and body["task"]["task_id"] == first
    assert second not in json.dumps(body, ensure_ascii=False)

    other = _login(port, "school_uploader_02")
    status, _, body = _request(port, "GET", f"/api/v1/demo2/simple-result?task_id={first}", cookie=other)
    assert status == 403
    status, _, _ = _request(port, "GET", f"/demo2/simple-result?task_id={first}&from=upload", cookie=other)
    assert status in {403, 404}
    denied = [e for e in _read_log(flow["log_dir"]) if e["operation"] == "result_redirect"]
    assert denied and denied[-1]["result"] == "denied" and denied[-1]["task_id"] == first


def test_paused_bound_channel_is_shown_and_blocks_upload_without_switching(flow) -> None:
    store, port = flow["store"], flow["port"]
    _pause_channel(store)
    status, _, body = _request(port, "GET", "/api/v1/demo2/upload/workspace?course_id=paused-course",
                               cookie=flow["cookie"])
    assert status == 200
    workspace = body["workspace"]
    assert workspace["selected_channel_id"] == "channel_1"
    assert workspace["channel"]["channel_id"] == "channel_1" and workspace["channel"]["status"] == "paused"
    assert workspace["channel_status"] == "paused"
    assert workspace["upload_blocked"]["code"] == "channel_paused"
    assert "不会自动切换" in workspace["upload_blocked"]["message"]

    status, body = _create_task(flow, course_id="paused-course")
    assert status == 409 and body["error"]["code"] == "channel_paused"
    # Picking another active channel explicitly is refused too while the binding is paused.
    status, body = _create_task(flow, course_id="paused-course", channel_id="channel_2")
    assert status == 409 and body["error"]["code"] == "channel_paused"
    with sqlite3.connect(store.db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM video_analysis_tasks").fetchone()[0] == 0

    rejected = [e for e in _read_log(flow["log_dir"]) if e["operation"] == "upload_rejected"]
    assert rejected and rejected[-1]["code"] == "channel_paused" and rejected[-1]["http_status"] == 409
    assert rejected[-1]["channel_status"] == "paused"


def test_missing_bound_channel_is_not_replaced_by_first_active_channel(flow) -> None:
    store = flow["store"]
    with sqlite3.connect(store.db_path) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("UPDATE platform_accounts SET bound_channel_id = 'channel_9' "
                           "WHERE username = 'school_uploader_01'")
    token = store.create_account_session(
        store.authenticate_account("school_uploader_01", PASSWORD_PREFIX + "school_uploader_01"))["token"]
    workspace = store.account_upload_workspace(token, "missing-course")
    assert workspace["channel"] is None and workspace["selected_channel_id"] == ""
    assert workspace["upload_blocked"]["code"] == "channel_missing"


def test_unavailable_ffmpeg_fails_task_with_named_reason(flow, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    store = flow["store"]
    task_id = _create_task(flow)[1]["task"]["task_id"]
    assert _upload(flow, task_id)[0] == 200
    monkeypatch.setenv("REHAB_FFMPEG", str(tmp_path / "missing" / "ffmpeg"))
    monkeypatch.setenv("REHAB_FFPROBE", str(tmp_path / "missing" / "ffprobe"))

    status = media.media_tool_status()
    assert status == {"tools_available": False, "missing": ["ffmpeg", "ffprobe"],
                      "ffmpeg_source": "missing", "ffprobe_source": "missing"}

    worker = VideoAnalysisWorker(store)
    assert worker.run_once()
    status, _, body = _request(flow["port"], "GET", f"/api/v1/demo2/upload/task?id={task_id}", cookie=flow["cookie"])
    task = body["task"]
    assert task["analysis_status"] == "failed"
    assert task["processing_error"]["code"] == "missing_dependency"
    assert "ffmpeg" in task["processing_error"]["message"] and str(tmp_path) not in task["processing_error"]["message"]
    failed = [e for e in _read_log(flow["log_dir"]) if e["operation"] == "processing_failed"]
    assert failed and failed[-1]["code"] == "missing_dependency" and failed[-1]["task_id"] == task_id
    assert isinstance(failed[-1]["duration_ms"], float)


def test_configured_tool_path_is_used_and_reported(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake = tmp_path / "ffprobe"
    fake.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setenv("REHAB_FFPROBE", str(fake))
    path, source = media._resolve_tool_with_source("ffprobe")
    assert Path(path) == fake.resolve() and source == "configured"


def test_worker_start_logs_media_tool_check(flow, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("REHAB_FFMPEG", str(tmp_path / "none" / "ffmpeg"))
    monkeypatch.setenv("REHAB_FFPROBE", str(tmp_path / "none" / "ffprobe"))
    worker = VideoAnalysisWorker(flow["store"], poll_seconds=0.05)
    assert worker.start()
    worker.stop(timeout=5)
    checks = [e for e in _read_log(flow["log_dir"]) if e["operation"] == "media_tools_check"]
    assert checks and checks[-1]["result"] == "missing" and checks[-1]["tools_available"] is False
    assert checks[-1]["ffmpeg_source"] == "missing"


def test_chunk_failure_and_resume_are_logged(flow) -> None:
    task_id = _create_task(flow, content=b"abcdef")[1]["task"]["task_id"]
    status, _, body = _request(flow["port"], "POST", "/api/v1/demo2/upload/chunks", {
        "task_id": task_id, "course_id": "flow-course", "chunk_index": 3,
        "content_base64": base64.b64encode(b"abcdef").decode("ascii"),
    }, cookie=flow["cookie"])
    assert status == 409
    status, _, body = _request(flow["port"], "POST", "/api/v1/demo2/upload/resume", {
        "task_id": task_id, "course_id": "flow-course", "byte_size": 6, "filename": "synthetic.mp4",
        "chunk_sha256": [],
    }, cookie=flow["cookie"])
    assert status == 200 and body["task"]["task_id"] == task_id
    entries = _read_log(flow["log_dir"])
    failed_chunk = [e for e in entries if e["operation"] == "upload_chunk" and e["result"] == "failed"]
    assert failed_chunk and failed_chunk[-1]["http_status"] == 409 and failed_chunk[-1]["task_id"] == task_id
    resume = [e for e in entries if e["operation"] == "upload_resume" and e["result"] == "ok"]
    assert resume and resume[-1]["task_id"] == task_id and resume[-1]["verified_chunks"] == 0
    assert resume[-1]["channel_id"] == "channel_1" and resume[-1]["byte_size"] == 6
