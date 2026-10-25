"""Upload one authorized local recording to the local pilot and verify its evidence."""

from __future__ import annotations

import argparse
import base64
import http.cookiejar
import json
import math
import os
import time
import urllib.request
import urllib.error
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHUNK_BYTES = 4 * 1024 * 1024


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8791)
    parser.add_argument("--course-index", type=int, default=0)
    parser.add_argument("--course-id", default="media-validation-20260908")
    args = parser.parse_args()
    password = os.environ.get("REHAB_ACCEPTANCE_PASSWORD", "")
    if not password:
        raise SystemExit("Set REHAB_ACCEPTANCE_PASSWORD for the existing local t1 account.")
    config = json.loads((ROOT / "data/processed/seewo_demo2/session_config.json").read_text(encoding="utf-8"))
    course = config["courses"][args.course_index]
    source = Path(course["student_video"])
    size = source.stat().st_size
    base = f"http://127.0.0.1:{args.port}"
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def api(path: str, payload: dict | None = None):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(base + "/api/v1/demo2" + path, data=body, headers={"Content-Type": "application/json"})
        try:
            with opener.open(request, timeout=180) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            detail = json.loads(exc.read().decode("utf-8"))
            raise RuntimeError(f"HTTP {exc.code}: {detail}") from None

    api("/auth/login", {"username": "t1", "password": password, "role": "school_uploader"})
    del password
    existing = api("/upload/workspace?course_id=" + args.course_id)["workspace"]["tasks"]
    if existing:
        task_id = existing[0]["task_id"]
        print("Reusing the existing private acceptance task.", flush=True)
    else:
        task = api("/upload/tasks", {
            "course_id": args.course_id, "course_name": course["course_name"] + "（原片处理验证）",
            "session_id": args.course_id, "filename": "authorized-classroom-recording.mp4",
            "uploader_name": "Local authorized acceptance",
            "byte_size": size, "total_chunks": math.ceil(size / CHUNK_BYTES),
            "channel_id": "channel_1", "mime_type": "video/mp4",
            "security_confirmed": True, "allow_company_archive": False,
        })["task"]
        task_id = task["task_id"]
        print(f"Uploading locally: {size} bytes, {math.ceil(size / CHUNK_BYTES)} chunks", flush=True)
        with source.open("rb") as handle:
            for index in range(math.ceil(size / CHUNK_BYTES)):
                block = handle.read(CHUNK_BYTES)
                api("/upload/chunks", {"task_id": task_id, "course_id": args.course_id,
                    "chunk_index": index, "content_base64": base64.b64encode(block).decode("ascii")})
                if index % 25 == 0:
                    print(f"Uploaded chunk {index + 1}", flush=True)
    start = time.monotonic()
    previous = None
    while time.monotonic() - start < 1800:
        payload = api("/upload/task?id=" + task_id)
        task = payload["task"]
        status = (task["analysis_status"], task.get("processing_stage"), task.get("processing_progress"))
        if status != previous:
            print(status, flush=True)
            previous = status
        if task["analysis_status"] == "failed":
            raise RuntimeError(str(task.get("processing_error")))
        if task["analysis_status"] == "evidence_ready":
            result = payload["result"]
            break
        time.sleep(5)
    else:
        raise TimeoutError("Acceptance task has not completed within 30 minutes; it remains in the local queue.")
    segments = result["segments"]
    duration = result["media"]["duration_sec"]
    assert segments and segments[0]["start_sec"] == 0
    assert abs(segments[-1]["end_sec"] - duration) < .01
    assert all(abs(a["end_sec"] - b["start_sec"]) < .01 for a, b in zip(segments, segments[1:]))
    checks = {}
    for asset in ("source", "audio"):
        if asset == "audio" and not result["media"]["has_audio"]:
            continue
        request = urllib.request.Request(base + f"/api/v1/demo2/upload/media?id={task_id}&asset={asset}", headers={"Range": "bytes=0-127"})
        with opener.open(request, timeout=20) as response:
            assert response.status == 206
            checks[asset] = {"status": response.status, "bytes": len(response.read()), "content_type": response.headers["Content-Type"]}
    summary = {
        "task_id": task_id, "source_bytes": size, "media": result["media"],
        "summary": result["summary"], "checks": checks,
        "wait_seconds": round(time.monotonic() - start, 2),
        "local_url": base + "/demo2/video?id=" + task_id,
        "scope": "Local technical media processing, not validated student learning assessment",
    }
    output = ROOT / ".runtime" / "media_real_acceptance_20260908.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
