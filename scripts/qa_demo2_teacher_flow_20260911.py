"""Disposable teacher-flow QA: real stores/HTTP, explicitly unavailable AI.

No production ports or databases are accepted. Browser runs are opt-in, use one
headless-shell 1243 instance, and receive fixture credentials only through stdin.
The inherited fixture uses synthetic JPEGs and stub source video, not real media.
"""

from __future__ import annotations

import argparse
import copy
import http.client
import json
import os
import secrets
import subprocess
import tempfile
import threading
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode, urlsplit
from uuid import uuid4

from scripts.qa_demo2_identity_20260910 import _private_server_module, isolated_identity_server
from src.rehab_affect.demo2_identity_store import Demo2IdentityStore
from src.rehab_affect.demo2_membership_store import Demo2MembershipStore
from src.rehab_affect.student_record_store import Demo2StudentRecordStore


API = "/api/v1/demo2/identity"
CHANNELS = "/api/v1/demo2/admin/channels"
FORBIDDEN_PORTS = {8792, 8796}
BOX = {"x": 0.10, "y": 0.20, "width": 0.25, "height": 0.50}
PARTIAL_BOX = {**BOX, "x": 0.12, "y": 0.22}


def request(env, path, *, method="GET", payload=None, user="t1", headers=None, port=None):
    port = env.port if port is None else port
    if port in FORBIDDEN_PORTS or port not in env.allowed_ports:
        raise ValueError("Only this fixture's ephemeral loopback listeners may be used")
    parsed = urlsplit(path)
    if parsed.scheme or parsed.netloc or not path.startswith("/") or path.startswith("//"):
        raise ValueError("Only local relative request targets are allowed")
    outgoing = {"Host": f"127.0.0.1:{port}", "Connection": "close", "Content-Type": "application/json"}
    if user is not None:
        outgoing["Cookie"] = "rehab_demo2_session=" + env.tokens[user]
    outgoing.update(headers or {})
    body = b"" if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    outgoing["Content-Length"] = str(len(body))
    wire = (f"{method} {path} HTTP/1.1\r\n" +
            "".join(f"{key}: {value}\r\n" for key, value in outgoing.items()) + "\r\n").encode("ascii") + body
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
    try:
        connection.connect()
        connection.sock.sendall(wire)
        response = http.client.HTTPResponse(connection.sock, method=method)
        response.begin()
        data = response.read()
        received = {key.lower(): value for key, value in response.getheaders()}
        parsed_body = json.loads(data) if data and "application/json" in received.get("content-type", "") else data
        return response.status, received, parsed_body
    finally:
        connection.close()


def workspace(env, *, user="t1"):
    status, _, body = request(env, API + "/workspace?" + urlencode({"task_id": env.task_ids["t1"]}), user=user)
    assert status == 200 and body["ok"] is True
    return body["workspace"]


def binding_payload(env, *, student=0, box=None, **extra):
    current = workspace(env)
    return {"task_id": env.task_ids["t1"], "frame_key": current["frames"][0]["frame_key"],
            "frame_revision": current["frame_revision"], "role": "student",
            "student_id": env.students["t1"][student]["student_id"], "bbox": dict(box or BOX), **extra}


def save_manual(env, **options):
    payload = binding_payload(env, **options)
    status, _, body = request(env, API + "/bindings", method="POST", payload=payload)
    assert status == 200 and body["ok"] is True, body
    return body["binding"]


def channels(env, **options):
    status, _, body = request(env, CHANNELS, user="admin", **options)
    assert status == 200 and body["ok"] is True, body
    assert isinstance(body["channels"], list)
    return body["channels"]


def channel_payload(env, *, channel_id="channel_1", **changes):
    current = next(item for item in channels(env) if item["channel_id"] == channel_id)
    return {"channel_id": channel_id, "expected_version": current["version"],
            **{key: current[key] for key in ("channel_name", "owner_label", "status", "course_upload_limit")},
            **changes}


def upload_payload(*, course_id=None, channel_id="channel_1"):
    return {"channel_id": channel_id, "course_id": course_id or "teacher-flow-" + uuid4().hex[:8],
            "course_name": "Synthetic QA course", "session_id": "qa-" + uuid4().hex[:8],
            "uploader_name": "Synthetic QA uploader", "filename": "qa-reservation.mp4",
            "mime_type": "video/mp4", "byte_size": 8, "total_chunks": 1, "security_confirmed": True,
            "allow_company_archive": False}


def history_snapshot(env):
    with env.records._connect() as connection:
        return {table: sorted((tuple(row) for row in connection.execute("SELECT * FROM " + table)), key=repr)
                for table in ("video_analysis_tasks", "demo2_identity_students", "demo2_identity_bindings")}


def _disable_detection(env):
    original_import = env.server.importlib.import_module

    def detect(path):
        if not Path(path).resolve().is_relative_to(env.root.resolve()):
            raise ValueError("Detector fixture may only access its own synthetic frames")
        env.detect_calls.append(Path(path))
        return {"available": False, "faces": [], "model": "qa-unavailable-detector", "fixture_only": True,
                "reason": "qa_detector_unavailable; manual_confirmation_required"}

    detector = SimpleNamespace(detect_faces=detect, MODEL_NAME="qa-unavailable-detector")

    def fixture_import(name, package=None):
        if name == ".demo2_face_detection":
            return detector
        if name == env.tracking_module_name and env.tracking_stub is not None:
            return env.tracking_stub
        return original_import(name, package)

    env.server.importlib = SimpleNamespace(import_module=fixture_import)


def enable_tracking_stub(env):
    """Stub only the engine; seed authorization, output validation and rates stay real."""
    env.tracking_module_name = ".demo2_roi_tracking"
    env.clock = SimpleNamespace(now=1000.0)
    original_time = env.server.time
    env.server.time = SimpleNamespace(**{key: getattr(original_time, key) for key in dir(original_time)
                                        if not key.startswith("__")})
    env.server.time.monotonic = lambda: env.clock.now
    env.track_override = None

    class TrackingError(ValueError):
        pass

    def track_frames(frames, bbox):
        assert 1 <= len(frames) <= 6
        assert all(Path(frame["path"]).resolve().is_relative_to(env.root.resolve()) for frame in frames)
        assert all(0 <= frame["time_sec"] - frames[0]["time_sec"] <= 5 for frame in frames)
        env.track_calls.append(copy.deepcopy(frames))
        if env.on_track:
            env.on_track()
        if env.track_override is not None:
            return copy.deepcopy(env.track_override)
        return {"status": "completed", "reason": "synthetic_fixture_only", "points": [
            {"frame_key": frame["frame_key"], "time_sec": frame["time_sec"], "bbox": dict(bbox),
             "status": "seed" if index == 0 else "suggested", "quality": 1.0 if index == 0 else .8,
             "reason": "synthetic_fixture_only"} for index, frame in enumerate(frames)]}

    env.tracking_stub = SimpleNamespace(track_frames=track_frames, TrackingError=TrackingError)


def extend_synthetic_manifest(env, *, count=9):
    """Expand only fixture samples to test window selection, never decoding video."""
    assert 2 <= count <= 20
    with env.records._connect() as connection:
        row = connection.execute("SELECT * FROM video_analysis_tasks WHERE task_id=?",
                                 (env.task_ids["t1"],)).fetchone()
        result = json.loads(row["processing_result_json"])
        current = workspace(env)
        first = env.identity.frame_file(env.tokens["t1"], env.task_ids["t1"], "s0_f0",
                                         current["frame_revision"])[0]
        assert first.resolve().is_relative_to(env.root.resolve())
        picture = first.read_bytes()
        sample = result["segments"][0]["visual"]["samples"][0]
        samples = []
        for index in range(count):
            file = first.with_name(f"frame_{index:06d}.jpg")
            if not file.exists():
                file.write_bytes(picture)
            value = {**sample, "timestamp_sec": index}
            if "image_path" in value:
                value["image_path"] = result["artifacts"]["frames"] + f"/frame_{index:06d}.jpg"
            samples.append(value)
        result["media"]["duration_sec"] = count
        result["summary"]["sampled_frames"] = count
        result["segments"][0]["end_sec"] = count
        result["segments"][0]["visual"]["samples"] = samples
        result["segments"][0]["visual"]["sampled_frames"] = count
        connection.execute("UPDATE video_analysis_tasks SET processing_result_json=? WHERE task_id=?",
                           (json.dumps(result), env.task_ids["t1"]))


@contextmanager
def teacher_flow_server(root):
    """Reopen closes the old listener, then loads fresh stores and a new handler."""
    root = Path(root).resolve()
    original_stack = ExitStack()
    active_close = original_stack.close
    try:
        env = original_stack.enter_context(isolated_identity_server(root, seed_students=True))
        if not env.root.resolve().is_relative_to(root) or env.port in FORBIDDEN_PORTS:
            raise RuntimeError("Invalid isolated fixture root/listener")
        env.allowed_ports = {env.port}
        env.detect_calls = []
        env.tracking_module_name = None
        env.tracking_stub = None
        env.track_calls = []
        env.on_track = None
        _disable_detection(env)

        def reopen():
            nonlocal active_close
            old_port = env.port
            active_close()
            active_close = lambda: None
            env.allowed_ports.discard(old_port)
            records = Demo2StudentRecordStore(env.records.db_path, env.root / "documents")
            identity = Demo2IdentityStore(records)
            membership = Demo2MembershipStore(records, sms_sender=lambda *args: None)
            server = _private_server_module()
            server.get_demo2_student_store = lambda: records
            server.load_seewo_demo2 = lambda *args, **kwargs: {"students": [], "courses": [], "qa_fixture_only": True}
            server.load_seewo_student_demo = server.load_seewo_demo2
            server.SEEWO_STUDENT_DEMO_OUTPUT_DIR = env.root / "unused_legacy_assets"
            server.SEEWO_DEMO2_OUTPUT_DIR = env.root / "unused_demo2_assets"
            env.records, env.identity, env.membership, env.server = records, identity, membership, server
            _disable_detection(env)
            handler = server.create_handler(scenario_dir=env.root, model_path=env.root / "unused.json",
                                            policy_name="rule", membership_store=membership, identity_store=identity)
            httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
            if httpd.server_port in FORBIDDEN_PORTS:
                httpd.server_close()
                raise RuntimeError("Refusing a production port")
            thread = threading.Thread(target=lambda: httpd.serve_forever(poll_interval=.03), daemon=True)
            thread.start()
            env.port = httpd.server_port
            env.allowed_ports.add(env.port)

            def close():
                httpd.shutdown()
                httpd.server_close()
                thread.join(5)
                if thread.is_alive():
                    raise RuntimeError("Reopened fixture listener did not close")

            active_close = close

        env.reopen = reopen
        yield env
    finally:
        active_close()


@contextmanager
def isolated_gateway(env):
    from src.rehab_affect import demo2_manager_gateway as gateway

    invite = secrets.token_urlsafe(36)
    proxy = gateway.make_server({"invite_secret": invite, "cookie_secret": secrets.token_urlsafe(36),
        "expires_at": int(time.time()) + 600, "upstream_port": env.port, "listen_port": 0}, host="127.0.0.1", port=0)
    if proxy.server_port in FORBIDDEN_PORTS:
        proxy.server_close()
        raise RuntimeError("Refusing a production gateway port")
    thread = threading.Thread(target=lambda: proxy.serve_forever(poll_interval=.03), daemon=True)
    thread.start()
    env.allowed_ports.add(proxy.server_port)
    try:
        yield SimpleNamespace(port=proxy.server_port, invite=invite, origin=f"http://127.0.0.1:{proxy.server_port}")
    finally:
        env.allowed_ports.discard(proxy.server_port)
        proxy.shutdown()
        proxy.server_close()
        thread.join(5)
        if thread.is_alive():
            raise RuntimeError("Isolated gateway did not close")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", action="store_true", help="Explicitly run the isolated manual-save E2E")
    parser.add_argument("--node", default="node")
    args = parser.parse_args()
    if not args.browser:
        parser.error("Use pytest for HTTP contracts; --browser is required to launch Chromium")
    output = Path(tempfile.mkdtemp(prefix="qa_teacher_flow_browser_"))
    with tempfile.TemporaryDirectory(prefix="qa_tf_") as root:
        with teacher_flow_server(root) as env:
            config = {"isolated": True, "base": f"http://127.0.0.1:{env.port}", "guard": env.guard,
                      "task_id": env.task_ids["t1"], "token": env.tokens["t1"],
                      "student_id": env.students["t1"][0]["student_id"], "output": str(output)}
            completed = subprocess.run([args.node, str(Path(__file__).with_suffix(".js"))],
                input=json.dumps(config), encoding="utf-8", capture_output=True, timeout=120, env=os.environ.copy())
            # Never relay Node/Playwright call logs: they may contain fixture auth.
            print(json.dumps({"browser_exit_code": completed.returncode, "output": str(output)}))
            if completed.returncode:
                return completed.returncode
            before = workspace(env)
            env.reopen()
            after = workspace(env)
            assert before["bindings"] == after["bindings"] and before["students"] == after["students"]
            report_path = output / "teacher_flow.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report.update(reopened_db_bindings_preserved=True, binding_count=len(after["bindings"]))
            report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            print(json.dumps({"reopened_db_bindings_preserved": True, "binding_count": len(after["bindings"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
