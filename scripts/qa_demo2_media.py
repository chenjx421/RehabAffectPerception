"""Real HTTP/SQLite/FFmpeg/Edge acceptance using synthetic media only.

Run with PYTHONPATH=src, PYTHONUTF8=1, and the local Playwright NODE_PATH.
No fixed port or business database is used. Every run retains its own evidence.
"""

from __future__ import annotations

import base64
import hashlib
import http.client
import json
import os
import subprocess
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

from src.rehab_affect import scenario_lab_server as server
from src.rehab_affect.demo2_media_worker import VideoAnalysisWorker
from src.rehab_affect.student_record_store import Demo2StudentRecordStore


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / "playwright" / "media_20260908"
CHUNK_BYTES = 4 * 1024 * 1024
PASSWORDS = {**{f"t{i}": f"MediaQA0{i}" for i in range(1, 5)}, "admin": "MediaQAAdmin1"}


def source_hashes() -> dict[str, str]:
    return {
        name: hashlib.sha256((ROOT / "src" / "rehab_affect" / name).read_bytes()).hexdigest()
        for name in ("scenario_lab_server.py", "student_record_store.py", "demo2_media_worker.py",
                     "demo2_media_analysis.py", "demo2_video_review.py", "demo2_portal.py")
    }


def main() -> int:
    output = OUTPUT / datetime.now().strftime("run_%Y%m%d_%H%M%S_%f")
    output.mkdir(parents=True)
    report = {"synthetic_only": True, "source_hashes_before": source_hashes(), "checks": []}
    checks = report["checks"]

    def check(name, ok, evidence=None):
        item = {"name": name, "ok": bool(ok), "evidence": evidence}
        checks.append(item)
        print(json.dumps(item, ensure_ascii=False), flush=True)
        return bool(ok)

    httpd = None
    worker = None
    browser_process = None
    try:
        import imageio_ffmpeg

        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        ffprobe = str(ROOT / ".tools" / "ffprobe.exe")
        assert Path(ffmpeg).is_file() and Path(ffprobe).is_file(), "Local FFmpeg/ffprobe required"
        os.environ["REHAB_FFMPEG"] = ffmpeg
        os.environ["REHAB_FFPROBE"] = ffprobe
        fixture = output / "synthetic_46s.mp4"
        command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-n",
                   "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25",
                   "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
                   "-t", "46", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                   "-b:v", "1200k", "-minrate", "1200k", "-maxrate", "1200k", "-bufsize", "2400k",
                   "-x264-params", "nal-hrd=cbr", "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(fixture)]
        subprocess.run(command, check=True, timeout=120, capture_output=True)
        video = fixture.read_bytes()
        check("synthetic_fixture_multichunk", len(video) > CHUNK_BYTES,
              {"bytes": len(video), "duration_sec": 46, "video": "testsrc2", "audio": "440Hz sine"})
        report["fixture_sha256"] = hashlib.sha256(video).hexdigest()

        store = Demo2StudentRecordStore(output / "qa.sqlite3", output / "documents")
        store.set_seeded_pilot_passwords(store.db_path, PASSWORDS)
        server.get_demo2_student_store = lambda: store
        server.load_seewo_demo2 = lambda force=False: {"students": []}
        handler = server.create_handler(scenario_dir=output, model_path=output / "unused.json", policy_name="rule")
        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        server_thread.start()
        report["isolated_port"] = httpd.server_port

        def request(path, *, cookie="", method="GET", payload=None, headers=None):
            head = {"Content-Type": "application/json", **(headers or {})}
            if cookie:
                head["Cookie"] = cookie
            connection = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=30)
            try:
                connection.request(method, path, json.dumps(payload).encode() if payload is not None else None, head)
                response = connection.getresponse()
                raw = response.read()
                response_headers = {k.lower(): v for k, v in response.getheaders()}
                body = json.loads(raw) if raw and "application/json" in response_headers.get("content-type", "") else raw
                return response.status, response_headers, body
            finally:
                connection.close()

        status, _, body = request("/api/v1/demo2/auth/login", method="POST", payload={"username": "t1", "password": "wrong"})
        check("wrong_password", status == 401 and body["error"]["code"] == "invalid_credentials", status)
        cookies = {}
        for username, password in PASSWORDS.items():
            status, headers, body = request("/api/v1/demo2/auth/login", method="POST", payload={"username": username, "password": password})
            assert status == 200, body
            cookies[username] = headers["set-cookie"].split(";", 1)[0]
            check("login_" + username, "password_hash" not in json.dumps(body), {"status": status, "role": body["account"]["role"]})
        for i in range(1, 5):
            status, _, body = request("/api/v1/demo2/upload/workspace?course_id=media-qa", cookie=cookies[f"t{i}"])
            check(f"channel_isolation_t{i}", status == 200 and body["workspace"]["channel"]["channel_id"] == f"channel_{i}")

        payload = {"security_confirmed": True, "session_id": "media-qa", "course_id": "media-qa",
                   "course_name": "QA 合成录像（46秒，无学校资料）", "uploader_name": "QA synthetic",
                   "channel_id": "channel_1", "filename": fixture.name, "mime_type": "video/mp4",
                   "byte_size": len(video), "total_chunks": (len(video) + CHUNK_BYTES - 1) // CHUNK_BYTES}
        status, _, body = request("/api/v1/demo2/upload/tasks", method="POST", cookie=cookies["t1"], payload=payload)
        assert status == 200, body
        task_id = body["task"]["task_id"]
        report["task_id"] = task_id
        chunk_url = "/api/v1/demo2/upload/chunks"
        bad_chunk = {"task_id": task_id, "course_id": "media-qa", "chunk_index": 1, "content_base64": "YQ=="}
        status, _, body = request(chunk_url, method="POST", cookie=cookies["t1"], payload=bad_chunk)
        check("out_of_order_chunk_rejected", status == 400, {"status": status, "body": body})
        status, _, body = request(chunk_url, method="POST", cookie=cookies["t2"], payload={**bad_chunk, "chunk_index": 0})
        check("cross_account_chunk_rejected", status == 403 and body["error"]["code"] == "task_forbidden", status)
        for index, start in enumerate(range(0, len(video), CHUNK_BYTES)):
            chunk = {"task_id": task_id, "course_id": "media-qa", "chunk_index": index,
                     "content_base64": base64.b64encode(video[start:start + CHUNK_BYTES]).decode()}
            status, _, body = request(chunk_url, method="POST", cookie=cookies["t1"], payload=chunk)
            assert status == 200, body
            check(f"chunk_{index}_uploaded", body["task"]["next_chunk_index"] == index + 1,
                  {k: body["task"].get(k) for k in ("upload_status", "analysis_status", "progress_percent", "next_chunk_index")})
        check("upload_queued_with_matching_hash", body["task"]["analysis_status"] == "queued" and
              body["task"]["sha256"] == report["fixture_sha256"])
        task_url = f"/api/v1/demo2/upload/task?id={task_id}"
        media_url = f"/api/v1/demo2/upload/media?id={task_id}"
        result_url = f"/api/v1/demo2/upload/result?id={task_id}"
        for path in (task_url, media_url, result_url):
            status, _, _ = request(path)
            check("unauth_" + path.split("?")[0].rsplit("/", 1)[1], status == 401, status)
        for path, expected in ((task_url, 404), (media_url, 404), (result_url, 403)):
            status, _, _ = request(path, cookie=cookies["t2"])
            check("cross_account_" + path.split("?")[0].rsplit("/", 1)[1], status == expected, status)
        status, _, body = request(result_url, cookie=cookies["t1"])
        check("queued_download_409", status == 409 and body["error"]["code"] == "result_not_ready", status)
        status, headers, body = request(media_url, cookie=cookies["t1"], headers={"Range": "bytes=100-999"})
        check("source_range_exact_bytes", status == 206 and body == video[100:1000] and "no-store" in headers.get("cache-control", ""),
              {"status": status, "content_range": headers.get("content-range")})
        status, _, _ = request(media_url + "&asset=../../qa.sqlite3", cookie=cookies["admin"])
        check("asset_traversal_rejected", status == 404, status)

        # A genuine worker dependency failure, followed by the UI retry of the
        # same intact media. No fake processor or fabricated result is installed.
        os.environ["REHAB_FFPROBE"] = str(output / "deliberately_missing_ffprobe.exe")
        worker = VideoAnalysisWorker(store, poll_seconds=.05)
        assert worker.start(), "isolated worker failed to start"
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            _, _, body = request(task_url, cookie=cookies["t1"])
            if body["task"]["analysis_status"] in {"failed", "evidence_ready"}:
                break
            time.sleep(.1)
        worker.stop()
        os.environ["REHAB_FFPROBE"] = ffprobe
        check("real_dependency_failure", body["task"]["analysis_status"] == "failed" and
              body["task"].get("processing_error", {}).get("code") == "missing_dependency",
              {k: body["task"].get(k) for k in ("analysis_status", "processing_error", "attempt_count")})
        for name, cookie, expected in (("unauth", "", 401), ("other_account", cookies["t2"], 403)):
            status, _, denied = request("/api/v1/demo2/upload/tasks/retry", cookie=cookie, method="POST", payload={"task_id": task_id})
            check(f"retry_{name}_rejected", status == expected, {"status": status, "body": denied})
        _, _, after_denials = request(task_url, cookie=cookies["t1"])
        check("unauthorized_retry_no_side_effects", after_denials["task"]["analysis_status"] == "failed" and after_denials["task"]["attempt_count"] == 1)
        worker = VideoAnalysisWorker(store, poll_seconds=.05)
        env = dict(os.environ, DEMO2_MEDIA_URL=f"http://127.0.0.1:{httpd.server_port}",
                   DEMO2_MEDIA_TASK=task_id, DEMO2_MEDIA_OUTPUT=str(output), DEMO2_MEDIA_SHA256=report["fixture_sha256"])
        env.setdefault("NODE_PATH", "C:/Path/To/Developer/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules")
        browser_process = subprocess.Popen(["node", str(ROOT / "scripts" / "qa_demo2_media.js")], cwd=ROOT, env=env,
                                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8")
        watchdog = threading.Timer(240, browser_process.kill)
        watchdog.start()
        try:
            with (output / "browser.log").open("w", encoding="utf-8") as log:
                for line in browser_process.stdout:
                    print(line, end="", flush=True)
                    log.write(line)
                    log.flush()
                    if '"event":"retry_queued"' in line:
                        check("real_worker_restart", worker.start())
                        second = VideoAnalysisWorker(store)
                        second_started = second.start()
                        check("second_worker_excluded", not second_started)
                        if second_started:
                            second.stop()
            browser_process.wait(timeout=10)
        finally:
            watchdog.cancel()
        check("browser_acceptance", browser_process.returncode == 0, browser_process.returncode)
        worker.stop()
        _, _, final = request(task_url, cookie=cookies["t1"])
        report["final_task"] = final
        check("real_ffmpeg_evidence_ready", final["task"]["analysis_status"] == "evidence_ready" and final["task"]["attempt_count"] == 2,
              {k: final["task"].get(k) for k in ("analysis_status", "processing_stage", "processing_progress", "processing_error", "attempt_count")})
        report["browser_report"] = json.loads((output / "browser_report.json").read_text(encoding="utf-8"))
    except Exception as exc:
        check("harness_completed", False, f"{type(exc).__name__}: {exc}")
        report["traceback"] = traceback.format_exc()
        print(report["traceback"], flush=True)
    finally:
        if browser_process is not None and browser_process.poll() is None:
            browser_process.kill()
            browser_process.wait(timeout=10)
        if worker is not None:
            worker.stop()
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()
        report["source_hashes_after"] = source_hashes()
        report["source_changed_during_run"] = report["source_hashes_before"] != report["source_hashes_after"]
        report["ok"] = bool(checks) and all(item["ok"] for item in checks)
        (output / "qa_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"ok": report["ok"], "report": str(output / "qa_report.json")}, ensure_ascii=False), flush=True)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
