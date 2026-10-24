from __future__ import annotations

import base64
import http.client
import io
import json
import threading
import wave
from pathlib import Path

import pytest

from src.rehab_affect import scenario_lab_server as server
from src.rehab_affect.student_record_store import Demo2StudentRecordStore


@pytest.fixture()
def media_server(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("REHAB_DEMO2_ACCOUNT_PASSWORD_PREFIX", "MediaApi-")
    store = Demo2StudentRecordStore(tmp_path / "db.sqlite3", tmp_path / "documents")
    sessions, accounts = {}, {}
    for name in ("school_uploader_01", "school_uploader_02", "company_admin"):
        account = store.authenticate_account(name, "MediaApi-" + name)
        accounts[name] = account
        sessions[name] = "rehab_demo2_session=" + store.create_account_session(account)["token"]
    task = store.create_video_task({
        "account_id": accounts["school_uploader_01"]["account_id"],
        "channel_id": "channel_1", "session_id": "media-api", "course_id": "media-api",
        "course_name": "Media test", "uploader_name": "Test", "filename": "clip.mp4",
        "byte_size": 10, "total_chunks": 1,
    })
    store.append_video_chunk({"task_id": task["task_id"], "chunk_index": 0, "content_base64": base64.b64encode(b"0123456789").decode()})
    monkeypatch.setattr(server, "get_demo2_student_store", lambda: store)
    monkeypatch.setattr(server, "load_seewo_demo2", lambda: {"students": []})
    handler = server.create_handler(scenario_dir=tmp_path, model_path=tmp_path / "unused", policy_name="rule")
    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd.server_port, store, task["task_id"], sessions
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(5)


def request(port, path, cookie="", *, method="GET", payload=None, range_header=None):
    headers = {"Cookie": cookie, "Content-Type": "application/json"}
    if range_header is not None:
        headers["Range"] = range_header
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        connection.request(method, path, body=json.dumps(payload) if payload else None, headers=headers)
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def test_protected_video_page_and_task_ownership(media_server):
    port, _, task_id, cookies = media_server
    assert request(port, "/demo2/video?id=" + task_id)[0] == 302
    assert request(port, "/demo2/video?id=" + task_id, cookies["school_uploader_01"])[0] == 200
    path = "/api/v1/demo2/upload/task?id=" + task_id
    assert request(port, path)[0] == 401
    assert request(port, path, cookies["school_uploader_02"])[0] == 404
    for name in ("school_uploader_01", "company_admin"):
        status, _, body = request(port, path, cookies[name])
        assert status == 200
        payload = json.loads(body)
        assert payload["task"]["analysis_status"] == "queued"
        assert payload["result"] is None
        assert "file_path" not in payload["task"]


@pytest.mark.parametrize("range_header,expected,body", [
    (None, 200, b"0123456789"), ("bytes=2-5", 206, b"2345"),
    ("bytes=7-", 206, b"789"), ("bytes=-3", 206, b"789"),
    ("bytes=0-999", 206, b"0123456789"), ("bytes=99-", 416, b""),
    ("bytes=3-2", 416, b""), ("bytes=-0", 416, b""),
    ("bytes=1-2,4-5", 416, b""), ("not-a-range", 416, b""),
])
def test_authenticated_media_range_streaming(media_server, range_header, expected, body):
    port, _, task_id, cookies = media_server
    status, headers, data = request(port, "/api/v1/demo2/upload/media?id=" + task_id,
                                    cookies["school_uploader_01"], range_header=range_header)
    assert status == expected
    assert data == body
    assert "no-store" in headers["Cache-Control"]
    assert headers["Content-Length"] == str(len(data))
    if expected == 206:
        assert headers["Content-Range"].endswith("/10")


def test_media_audio_and_retry_never_bypass_owner(media_server):
    port, store, task_id, cookies = media_server
    for suffix in ("", "&asset=audio", "&asset=../../db.sqlite3"):
        path = "/api/v1/demo2/upload/media?id=" + task_id + suffix
        assert request(port, path)[0] == 401
        assert request(port, path, cookies["school_uploader_02"])[0] == 404
    assert request(port, "/api/v1/demo2/upload/media?id=" + task_id + "&asset=../../db.sqlite3", cookies["company_admin"])[0] == 404
    store.claim_next_video_analysis()
    store.fail_video_analysis(task_id, "test_error", "Test error")
    path = "/api/v1/demo2/upload/tasks/retry"
    assert request(port, path, method="POST", payload={"task_id": task_id})[0] == 401
    status, _, denied = request(port, path, cookies["school_uploader_02"], method="POST", payload={"task_id": task_id})
    assert status == 403
    assert json.loads(denied)["error"]["code"] == "task_forbidden"
    with store._connect() as connection:
        assert connection.execute(
            "SELECT analysis_status, attempt_count FROM video_analysis_tasks WHERE task_id=?", (task_id,)
        ).fetchone()[:] == ("failed", 1)
    status, _, raw = request(port, path, cookies["school_uploader_01"], method="POST", payload={"task_id": task_id})
    assert status == 202
    assert json.loads(raw)["task"]["analysis_status"] == "queued"
    status, _, raw = request(port, path, cookies["school_uploader_01"], method="POST", payload={"task_id": task_id})
    assert status == 409
    assert json.loads(raw)["error"]["code"] == "task_not_retryable"


def test_queued_and_processing_downloads_are_conflicts_until_explicit_finish(media_server):
    port, store, task_id, cookies = media_server
    urls = (
        f"/api/v1/demo2/upload/result?id={task_id}",
        f"/api/seewo_demo2/video_result_download?id={task_id}",
    )
    for stage in ("queued", "processing"):
        if stage == "processing":
            assert store.claim_next_video_analysis()["task_id"] == task_id
        for url in urls:
            for name in ("school_uploader_01", "company_admin"):
                status, _, body = request(port, url, cookies[name])
                assert status == 409
                assert json.loads(body)["error"]["code"] == "result_not_ready"
    result = {"task_id": task_id, "analysis_version": "qa_contract_v1", "content": {"test_only": True}}
    store.finish_video_analysis(task_id, result)
    for url in urls:
        status, headers, body = request(port, url, cookies["school_uploader_01"])
        assert status == 200
        assert json.loads(body) == result
        assert "attachment" in headers["Content-Disposition"]
        assert request(port, url, cookies["school_uploader_02"])[0] == 403


def test_completed_audio_uses_processor_relative_artifact_and_stays_protected(media_server):
    """Regression for real processors writing analysis/task/media_*/audio.wav."""
    port, store, task_id, cookies = media_server
    claimed = store.claim_next_video_analysis()
    audio = io.BytesIO()
    with wave.open(audio, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x01\x00" * 160)
    raw_audio = audio.getvalue()
    relative = "media_qa_run/audio.wav"
    audio_path = Path(claimed["analysis_dir"]) / relative
    audio_path.parent.mkdir()
    audio_path.write_bytes(raw_audio)
    store.finish_video_analysis(task_id, {
        "task_id": task_id, "analysis_version": "qa_relative_artifact_v1",
        "media": {"has_audio": True}, "segments": [], "artifacts": {"audio": relative},
    })
    path = f"/api/v1/demo2/upload/media?id={task_id}&asset=audio"
    assert request(port, path)[0] == 401
    assert request(port, path, cookies["school_uploader_02"])[0] == 404
    for name in ("school_uploader_01", "company_admin"):
        status, headers, body = request(port, path, cookies[name])
        assert status == 200
        assert headers["Content-Type"] == "audio/wav"
        assert "no-store" in headers["Cache-Control"]
        assert body == raw_audio
        status, headers, body = request(port, path, cookies[name], range_header="bytes=44-59")
        assert status == 206
        assert body == raw_audio[44:60]
        assert headers["Content-Range"] == f"bytes 44-59/{len(raw_audio)}"


def test_expired_source_and_audio_are_not_served(media_server):
    port, store, task_id, cookies = media_server
    with store._connect() as connection:
        connection.execute("UPDATE video_analysis_tasks SET expires_at='2000-01-01T00:00:00+00:00' WHERE task_id=?", (task_id,))
    for name in ("school_uploader_01", "company_admin"):
        for asset in ("source", "audio"):
            assert request(port, f"/api/v1/demo2/upload/media?id={task_id}&asset={asset}", cookies[name])[0] == 404
