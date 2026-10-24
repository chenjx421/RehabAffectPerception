"""Isolated identity QA fixtures and an automatically closed Edge harness.

Import ``isolated_identity_server(tmp_path)`` from API tests, or execute with
``python -m scripts.qa_demo2_identity_20260910`` once the identity UI is ready.
All students, pictures and video bytes are fixtures. This does not validate face
recognition or video decoding. No existing database, fixed port, worker, SMS
provider or payment provider is used. Credentials only cross a child stdin pipe.
"""

from __future__ import annotations

import argparse
import base64
import copy
import importlib
import importlib.util
import inspect
import json
import os
import secrets
import subprocess
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import uuid4

from src.rehab_affect.demo2_identity_store import Demo2IdentityStore
from src.rehab_affect.demo2_membership_store import AGREEMENT_VERSION, Demo2MembershipStore
from src.rehab_affect.student_record_store import Demo2StudentRecordStore


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHOOL = {"city": "虚构测试市", "district": "隔离测试区", "school_name": "身份QA虚拟学校（非真实学校）"}
FIXTURE_BOXES = (
    {"x": 0.15, "y": 0.2, "width": 0.2, "height": 0.6},
    {"x": 0.65, "y": 0.2, "width": 0.2, "height": 0.6},
)


def _private_server_module():
    """Do not patch canonical server globals, sys.modules, or os.environ."""
    source = REPO_ROOT / "src" / "rehab_affect" / "scenario_lab_server.py"
    spec = importlib.util.spec_from_file_location(
        "src.rehab_affect._identity_qa_server_" + uuid4().hex, source
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load the isolated server source")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_synthetic_frames(directory: Path, label: str) -> tuple[list[dict], str]:
    from PIL import Image, ImageDraw

    relative_directory = "media_qa_" + uuid4().hex[:12] + "/frames"
    frames = directory / relative_directory
    frames.mkdir(parents=True, exist_ok=True)
    samples = []
    for index in range(2):
        picture = Image.new("RGB", (640, 360), (240, 244, 248))
        draw = ImageDraw.Draw(picture)
        draw.text((12, 12), f"SYNTHETIC QA ONLY - {label} - frame {index}", fill=(30, 40, 50))
        for number, color in enumerate(((60, 110, 180), (175, 95, 65))):
            left = 96 + 320 * number
            draw.ellipse((left + 30, 75, left + 95, 140), fill=color)
            draw.rectangle((left + 15, 150, left + 113, 285), fill=color)
            draw.text((left + 15, 304), f"shape {number + 1}", fill=(30, 40, 50))
        relative = f"{relative_directory}/frame_{index:06d}.jpg"
        picture.save(directory / relative, format="JPEG", quality=90)
        samples.append({"timestamp_sec": index, "image_path": relative,
                        "brightness": 180, "sharpness": 12, "scene_motion": None})
    return samples, relative_directory


@contextmanager
def isolated_identity_server(root: Path, *, seed_students: bool = False, raw_manifest: bool = False):
    """Yield a fresh real-store HTTP fixture; always close its listener/thread.

    ``root`` is a caller-owned temporary directory. A fresh random child is
    created exclusively and left for that caller to clean up/inspect. Exposed
    tokens are raw session tokens, not Cookie strings. Rosters start empty.
    Explicit ``seed_students=True`` supplies two equal names/distinct IDs to t1.
    ``raw_manifest=True`` bypasses publication sanitization ONLY for separately
    labelled API security tests; never use it for real-pipeline/Edge acceptance.
    ``refresh_revision(task_id)`` returns the replacement revision string.
    """
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    fixture_root = root / ("iq-" + uuid4().hex[:12])
    fixture_root.mkdir(exist_ok=False)
    records = Demo2StudentRecordStore(fixture_root / "identity_qa.sqlite3", fixture_root / "documents")
    aliases = ("t1", "t2", "t3", "t4", "admin")
    users = {alias: "IdentityQA-" + secrets.token_hex(10) for alias in aliases}
    records.set_seeded_pilot_passwords(records.db_path, users)
    accounts = {alias: records.authenticate_account(alias, users[alias]) for alias in aliases}
    tokens = {alias: records.create_account_session(account)["token"] for alias, account in accounts.items()}
    usernames = {alias: alias for alias in aliases}

    # A local in-memory OTP sink, not a production SMS provider or fake paid user.
    messages = {}
    membership = Demo2MembershipStore(records, sms_sender=lambda phone, code: messages.__setitem__(phone, code))
    usernames["member"] = "13900009101"
    users["member"] = "IdentityQAMember" + secrets.token_hex(10)
    membership.request_code(usernames["member"], "identity-qa-local")
    accounts["member"] = membership.register({
        "phone": usernames["member"], "code": messages.pop(usernames["member"]),
        "password": users["member"], "accepted": True, "agreement_version": AGREEMENT_VERSION,
    }, "identity-qa-local")
    tokens["member"] = records.create_account_session(accounts["member"])["token"]
    for alias in ("t1", "t2", "t3", "t4"):
        records.save_account_school_context(tokens[alias], dict(SCHOOL))
    identity = Demo2IdentityStore(records)
    students = {}
    if seed_students:
        students = {"t1": [], "t2": []}
        for alias, codes in (("t1", ("QA-001", "QA-002")), ("t2", ("QA-OTHER",))):
            for code in codes:
                students[alias].append(identity.create_student(tokens[alias], {
                    "display_name": "虚构同名学生", "student_code": code,
                    "class_name": "QA虚拟班", "note": "仅隔离测试夹具，不是真实学生或人脸身份",
                }))

    task_ids, results = {}, {}

    def publish(task_id, alias):
        claim = records.claim_next_video_analysis()
        if claim is None or claim["task_id"] != task_id:
            raise RuntimeError("Expected the isolated fixture's next queued task")
        samples, frames_directory = _write_synthetic_frames(Path(claim["analysis_dir"]), alias)
        result = {
            # This is the actual persisted v1.1 artifact naming/grid contract,
            # while provenance explicitly discloses synthetic fixture content.
            "task_id": task_id, "analysis_version": "demo2_media_evidence_v1.1",
            "analysis_status": "evidence_ready", "source_sha256": claim["sha256"],
            "sampling": {"fps": 1, "window_sec": 20},
            "artifacts": {"frames": frames_directory, "audio": None},
            "media": {"duration_sec": 2.0, "width": 640, "height": 360, "fps": 1,
                      "has_audio": False, "audio_status": "absent"},
            "summary": {"segment_count": 1, "sampled_frames": 2, "decoded_frames": 0,
                        "transcription_performed": False},
            "segments": [{"start_sec": 0.0, "end_sec": 2.0, "review_status": "unreviewed",
                          "visual": {"samples": samples, "sampled_frames": 2,
                                     "mean_motion": 0.0, "mean_brightness": 180, "mean_sharpness": 12},
                          "audio": {"available": False}}],
            "provenance": {"fixture_only": True, "network_used": False,
                           "source_video_is_stub": True, "face_recognition_performed": False,
                           "qa_revision": uuid4().hex},
            "limitations": ["QA合成静态帧与stub源视频；无解码、检测或身份识别能力证明。"],
        }
        records.finish_video_analysis(task_id, result)
        results[task_id] = result
        if raw_manifest:
            # Explicit, opt-in raw-manifest fixture for auth/validation tests.
            # Default fixtures and the CLI never repair production publication.
            with records._connect() as connection:
                connection.execute("UPDATE video_analysis_tasks SET processing_result_json=? WHERE task_id=?",
                                   (json.dumps(result, ensure_ascii=False, sort_keys=True), task_id))
        return identity.workspace(tokens[alias], task_id)["frame_revision"]

    for index, alias in enumerate(("t1", "t2"), start=1):
        content = f"IDENTITY QA STUB VIDEO ONLY / {alias} / {uuid4().hex}".encode("ascii")
        task = records.create_video_task({
            "account_session_token": tokens[alias], "account_id": accounts[alias]["account_id"],
            "channel_id": f"channel_{index}", "session_id": f"identity-qa-{alias}",
            "course_id": f"identity-qa-{alias}", "course_name": "身份QA虚构课堂",
            "uploader_name": "QA fixture", "filename": f"{alias}_explicit_stub.mp4",
            "mime_type": "video/mp4", "byte_size": len(content), "total_chunks": 1,
        })
        task_id = task_ids[alias] = task["task_id"]
        records.append_video_chunk({"account_session_token": tokens[alias], "task_id": task_id,
                                    "chunk_index": 0, "content_base64": base64.b64encode(content).decode("ascii")})
        publish(task_id, alias)

    revision_lock = threading.Lock()

    def refresh_revision(task_id):
        if task_id not in task_ids.values():
            raise ValueError("Only a task owned by this QA fixture may be republished")
        alias = next(name for name, value in task_ids.items() if value == task_id)
        with revision_lock:
            # Test-only reprocessing trigger; publication uses the real claim/
            # finish APIs and never changes a business implementation or DB.
            with records._connect() as connection:
                connection.execute("UPDATE video_analysis_tasks SET analysis_status='queued' WHERE task_id=?", (task_id,))
            return publish(task_id, alias)

    server = _private_server_module()
    real_import_module = importlib.import_module

    def fixture_detect_faces(frame_path):
        if not Path(frame_path).resolve().is_relative_to(fixture_root):
            raise RuntimeError("The position-only fixture cannot read non-fixture frames")
        return {"available": True, "model": "qa-position-only-stub", "fixture_only": True,
                "faces": [{"candidate_id": f"qa-candidate-{index + 1}", "bbox": dict(box), "score": 0.99}
                          for index, box in enumerate(FIXTURE_BOXES)],
                "recognition_performed": False}

    def isolated_import(name, package=None):
        if name == ".demo2_face_detection":
            return SimpleNamespace(detect_faces=fixture_detect_faces)
        return real_import_module(name, package)

    # Redirect only this private server's detector import. Real route guards,
    # per-account rate budgets and concurrency gates remain unchanged.
    server.importlib = SimpleNamespace(import_module=isolated_import)
    server.get_demo2_student_store = lambda: records
    server.load_seewo_demo2 = lambda *args, **kwargs: {"students": [], "courses": [], "qa_fixture_only": True}
    server.load_seewo_student_demo = server.load_seewo_demo2
    server.SEEWO_STUDENT_DEMO_OUTPUT_DIR = fixture_root / "unused_legacy_assets"
    server.SEEWO_DEMO2_OUTPUT_DIR = fixture_root / "unused_demo2_assets"
    kwargs = {"scenario_dir": fixture_root, "model_path": fixture_root / "unused-model.json",
              "policy_name": "rule", "membership_store": membership}
    if "identity_store" in inspect.signature(server.create_handler).parameters:
        kwargs["identity_store"] = identity
    handler = server.create_handler(**kwargs)
    guard = secrets.token_urlsafe(24)

    class IsolatedHandler(handler):
        def do_GET(self):
            if urlsplit(self.path).path == "/__identity_qa__/health":
                if not secrets.compare_digest(self.headers.get("X-Identity-QA", ""), guard):
                    self.send_error(404)
                    return
                body = b'{"isolated_identity_qa":true,"source_video_is_stub":true}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            super().do_GET()

        def do_POST(self):
            if urlsplit(self.path).path != "/__identity_qa__/control":
                super().do_POST()
                return
            if not secrets.compare_digest(self.headers.get("X-Identity-QA", ""), guard):
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 1024:
                    raise ValueError("Invalid QA control size")
                payload = json.loads(self.rfile.read(length))
                if (not isinstance(payload, dict) or set(payload) != {"action", "task_id"}
                        or payload["task_id"] not in task_ids.values()
                        or payload["action"] not in {"refresh_revision", "expire"}):
                    raise ValueError("Only fixture revision/expiry controls are allowed")
                if payload["action"] == "refresh_revision":
                    result = {"frame_revision": refresh_revision(payload["task_id"])}
                else:
                    with records._connect() as connection:
                        connection.execute("UPDATE video_analysis_tasks SET expires_at=? WHERE task_id=?",
                                           ("2000-01-01T00:00:00+00:00", payload["task_id"]))
                    result = {"expired": True}
                body = json.dumps(result).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (ValueError, TypeError):
                self.send_error(400, "Invalid isolated QA control")

        def log_message(self, format, *args):
            # No requests, tokens or student fixture contents in shared logs.
            pass

    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), IsolatedHandler)
    thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    env = SimpleNamespace(port=httpd.server_port, root=fixture_root, records=records,
                          identity=identity, membership=membership, task_ids=task_ids,
                          users=users, usernames=usernames, accounts=accounts, tokens=tokens,
                          students=students, results=results, refresh_revision=refresh_revision,
                          detection_fixture=copy.deepcopy(FIXTURE_BOXES), guard=guard, server=server,
                          raw_manifest=raw_manifest)
    try:
        yield env
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
        if thread.is_alive():
            raise RuntimeError("Isolated identity server did not shut down")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", default="node")
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "output" / "playwright" / "identity_20260910")
    parser.add_argument("--school-repair-only", action="store_true",
                        help="Only the 320px empty task-school repair / order / expiry follow-up")
    args = parser.parse_args()
    output = args.output.resolve() / datetime.now().strftime("run_%Y%m%d_%H%M%S_%f")
    output.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix="rehab-identity-qa-") as temporary:
        with isolated_identity_server(Path(temporary)) as env:
            if args.school_repair_only:
                # Simulate exactly one historical task with an all-empty school
                # snapshot. No binding or existing/production task is altered.
                with env.records._connect() as connection:
                    assert connection.execute("SELECT COUNT(*) FROM demo2_identity_bindings WHERE task_id=?",
                                              (env.task_ids["t1"],)).fetchone()[0] == 0
                    connection.execute("UPDATE video_analysis_tasks SET school_context_json=? WHERE task_id=?",
                                       (json.dumps({key: "" for key in SCHOOL}), env.task_ids["t1"]))
                env.students["t1"] = [env.identity.create_student(env.tokens["t1"], {
                    "display_name": "虚构补验学生", "student_code": "QA-REPAIR-01",
                    "class_name": "QA补验班", "note": "仅本次临时学校归属修复测试",
                })]
            config = {"isolated": True, "base": f"http://127.0.0.1:{env.port}", "guard": env.guard,
                      "users": env.users, "usernames": env.usernames, "task_ids": env.task_ids,
                      "students": env.students, "output": str(output), "source_video_is_stub": True,
                      "school_repair_only": args.school_repair_only, "school_context": dict(SCHOOL)}
            child_env = dict(os.environ)
            child_env.setdefault("NODE_PATH", str(Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules"))
            result = subprocess.run([args.node, str(Path(__file__).with_suffix(".js"))],
                                    input=json.dumps(config, ensure_ascii=False), text=True, encoding="utf-8",
                                    cwd=REPO_ROOT, env=child_env, timeout=240, check=False)
    print(json.dumps({"exit_code": result.returncode, "output": str(output),
                      "isolated_server_closed": True, "fixture_only": True}, ensure_ascii=False))
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
