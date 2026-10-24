from __future__ import annotations

import base64
import errno
import hashlib
import http.client
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest

from src.rehab_affect import scenario_lab_server as server
from src.rehab_affect import student_record_store as module


CHUNK = module.MAX_VIDEO_CHUNK_BYTES


@pytest.fixture()
def uploads(tmp_path, monkeypatch):
    monkeypatch.setenv("REHAB_DEMO2_ACCOUNT_PASSWORD_PREFIX", "UploadTest-")
    store = module.Demo2StudentRecordStore(tmp_path / "db.sqlite3", tmp_path / "documents")
    accounts, tokens = {}, {}
    for name in ("school_uploader_01", "school_uploader_02", "company_admin"):
        account = store.authenticate_account(name, "UploadTest-" + name)
        accounts[name] = account
        tokens[name] = store.create_account_session(account)["token"]
    return store, accounts, tokens


def create(uploads, size=CHUNK + 3, **extra):
    store, accounts, _ = uploads
    return store.create_video_task({
        "account_id": accounts["school_uploader_01"]["account_id"], "channel_id": "channel_1",
        "session_id": "synthetic", "course_id": "synthetic", "course_name": "Synthetic",
        "uploader_name": "Test", "filename": "synthetic.mp4", "byte_size": size,
        "total_chunks": (size + CHUNK - 1) // CHUNK,
        **extra,
    })


def raw_task(store, task):
    with store._connect() as connection:
        return dict(connection.execute("SELECT * FROM video_analysis_tasks WHERE task_id=?", (task["task_id"],)).fetchone())


def append(uploads, task, index, data):
    store, _, tokens = uploads
    return store.append_video_chunk({
        "task_id": task["task_id"], "course_id": "synthetic", "chunk_index": index,
        "account_session_token": tokens["school_uploader_01"],
    }, chunk=data)


def resume_payload(task, blocks=()):
    return {"task_id": task["task_id"], "course_id": "synthetic", "byte_size": task["byte_size"],
            "filename": "synthetic.mp4", "chunk_sha256": [hashlib.sha256(block).hexdigest() for block in blocks]}


def resume(uploads, task, blocks=(), **changes):
    store, _, tokens = uploads
    return store.resume_video_upload(tokens["school_uploader_01"], {**resume_payload(task, blocks), **changes})


def test_replay_and_final_response_loss_do_not_requeue(uploads):
    store, _, _ = uploads
    task = create(uploads)
    first = append(uploads, task, 0, b"a" * CHUNK)
    path = Path(raw_task(store, task)["file_path"] + ".part")
    modified = path.stat().st_mtime_ns
    assert append(uploads, task, 0, b"a" * CHUNK) == first
    assert path.stat().st_mtime_ns == modified
    with pytest.raises(module.VideoUploadError) as error:
        append(uploads, task, 0, b"b" * CHUNK)
    assert error.value.code == "chunk_replay_mismatch"
    completed = append(uploads, task, 1, b"end")
    assert completed["upload_status"] == "completed"
    key = raw_task(store, task)["processing_key"]
    for expected in ("queued", "processing", "evidence_ready"):
        if expected == "processing":
            store.claim_next_video_analysis()
        if expected == "evidence_ready":
            store.finish_video_analysis(task["task_id"], {"version": "synthetic", "content": {}})
        replay = append(uploads, task, 1, b"end")
        assert replay["analysis_status"] == expected
        assert raw_task(store, task)["processing_key"] == key
        assert replay["received_bytes"] == CHUNK + 3
    with store._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM audit_logs WHERE action='complete' AND object_id=?", (task["task_id"],)).fetchone()[0] == 1
    assert Path(raw_task(store, task)["file_path"]).read_bytes() == b"a" * CHUNK + b"end"


@pytest.mark.parametrize("index,data", [(1, b"end"), (-1, b"x"), (True, b"x"), (0.5, b"x"),
                                         (0, b"short"), (2, b"x"), (0, b"x" * (CHUNK + 1))],
                         ids=["future", "negative", "boolean", "float", "short", "outside", "oversize"])
def test_invalid_order_types_and_lengths_do_not_advance(uploads, index, data):
    task = create(uploads)
    with pytest.raises(ValueError):
        append(uploads, task, index, data)
    assert raw_task(uploads[0], task)["received_bytes"] == 0


def test_wrong_final_length_rejected(uploads):
    task = create(uploads)
    append(uploads, task, 0, b"a" * CHUNK)
    with pytest.raises(module.VideoUploadError):
        append(uploads, task, 1, b"no")
    assert raw_task(uploads[0], task)["next_chunk_index"] == 1


def test_resume_checks_every_confirmed_chunk_without_returning_hashes(uploads):
    task = create(uploads, 2 * CHUNK + 3)
    assert resume(uploads, task)["next_chunk_index"] == 0
    for index, block in enumerate((b"a" * CHUNK, b"b" * CHUNK)):
        append(uploads, task, index, block)
    result = resume(uploads, task, (b"a" * CHUNK, b"b" * CHUNK))
    assert result["received_bytes"] == 2 * CHUNK
    assert "chunk_sha256" not in result and "file_path" not in result
    for blocks in ((), (b"a" * CHUNK,), (b"c" * CHUNK, b"b" * CHUNK), (b"a" * CHUNK, b"c" * CHUNK)):
        with pytest.raises(module.VideoUploadError):
            resume(uploads, task, blocks)
    for changes in ({"filename": "wrong.mp4"}, {"byte_size": 12}, {"chunk_sha256": ["bad"]}, {"byte_size": True}):
        with pytest.raises(ValueError):
            resume(uploads, task, (b"a" * CHUNK, b"b" * CHUNK), **changes)
    append(uploads, task, 2, b"end")
    with pytest.raises(module.VideoUploadError) as error:
        resume(uploads, task, (b"a" * CHUNK, b"b" * CHUNK))
    assert error.value.code == "upload_not_active"


@pytest.mark.parametrize("name", ["school_uploader_02", "company_admin"])
def test_other_owner_cannot_resume_or_append(uploads, name):
    store, accounts, tokens = uploads
    task = create(uploads, 3)
    with pytest.raises(module.VideoUploadError) as error:
        store.resume_video_upload(tokens[name], resume_payload(task))
    assert error.value.status == 403
    with pytest.raises(ValueError):
        store.append_video_chunk({"task_id": task["task_id"], "course_id": "synthetic", "chunk_index": 0,
                                  "account_id": accounts[name]["account_id"]}, chunk=b"end")


@pytest.mark.parametrize("mutation", ["course", "channel", "scope", "cancelled", "expired"])
def test_changed_scope_and_inactive_tasks_reject_resume_and_append(uploads, mutation):
    store, _, _ = uploads
    task = create(uploads, 3)
    with store._connect() as connection:
        field, value = {
            "course": ("course_id", "other"), "channel": ("channel_id", "channel_2"),
            "scope": ("school_context_json", json.dumps({"city": "different", "district": "different", "school_name": "synthetic"})),
            "cancelled": ("upload_status", "cancelled"), "expired": ("expires_at", "2000-01-01T00:00:00+00:00"),
        }[mutation]
        connection.execute(f"UPDATE video_analysis_tasks SET {field}=? WHERE task_id=?", (value, task["task_id"]))
    with pytest.raises(ValueError):
        resume(uploads, task)
    with pytest.raises(ValueError):
        append(uploads, task, 0, b"end")


@pytest.mark.parametrize("renamed", [False, True])
def test_recovery_truncates_only_uncommitted_tail(uploads, renamed):
    store, _, _ = uploads
    task = create(uploads)
    append(uploads, task, 0, b"a" * CHUNK)
    final = Path(raw_task(store, task)["file_path"])
    part = Path(str(final) + ".part")
    with part.open("ab") as handle:
        handle.write(b"old")
    if renamed:
        part.replace(final)
    assert resume(uploads, task, (b"a" * CHUNK,))["next_chunk_index"] == 1
    append(uploads, task, 1, b"end")
    assert final.read_bytes() == b"a" * CHUNK + b"end"


def test_short_or_changed_disk_prefix_never_accepted(uploads):
    store, _, _ = uploads
    task = create(uploads)
    append(uploads, task, 0, b"a" * CHUNK)
    part = Path(raw_task(store, task)["file_path"] + ".part")
    part.write_bytes(b"b" * CHUNK)
    with pytest.raises(module.VideoUploadError):
        resume(uploads, task, (b"a" * CHUNK,))
    part.write_bytes(b"short")
    for operation in (lambda: resume(uploads, task, (b"a" * CHUNK,)), lambda: append(uploads, task, 1, b"end")):
        with pytest.raises(module.VideoUploadError):
            operation()
    assert part.read_bytes() == b"short"


def test_capacity_reserves_only_unallocated_active_bytes(uploads, monkeypatch):
    store, _, _ = uploads
    task = create(uploads)
    append(uploads, task, 0, b"a" * CHUNK)
    # Only the remaining three bytes are reserved, not the allocated 4 MiB.
    free = module.VIDEO_CREATE_RESERVE_BYTES + 3 + 3
    monkeypatch.setattr(module.shutil, "disk_usage", lambda _: SimpleNamespace(free=free))
    create(uploads, 3)
    before = list(store.video_task_dir.rglob("*.part"))
    with pytest.raises(module.VideoUploadError) as error:
        create(uploads, 1)
    assert error.value.status == 507
    assert list(store.video_task_dir.rglob("*.part")) == before
    append(uploads, task, 1, b"end")
    # Completed task has no reservation, its allocation is already reflected in free.
    create(uploads, 3)


def test_low_disk_append_and_fsync_failure_preserve_committed_offset(uploads, monkeypatch):
    store, _, _ = uploads
    task = create(uploads)
    part = Path(raw_task(store, task)["file_path"] + ".part")
    with monkeypatch.context() as patch:
        patch.setattr(module.shutil, "disk_usage", lambda _: SimpleNamespace(free=module.VIDEO_APPEND_RESERVE_BYTES))
        with pytest.raises(module.VideoUploadError) as error:
            append(uploads, task, 0, b"a" * CHUNK)
        assert error.value.status == 507 and part.stat().st_size == 0
    def full(_fd):
        raise OSError(errno.ENOSPC, "synthetic disk full")
    with monkeypatch.context() as patch:
        patch.setattr(module.os, "fsync", full)
        with pytest.raises(module.VideoUploadError) as error:
            append(uploads, task, 0, b"a" * CHUNK)
        assert error.value.status == 507
    assert raw_task(store, task)["received_bytes"] == 0
    assert part.stat().st_size == 0
    assert append(uploads, task, 0, b"a" * CHUNK)["received_bytes"] == CHUNK


def test_two_store_instances_serialize_duplicate_chunks(uploads):
    store, accounts, tokens = uploads
    second = module.Demo2StudentRecordStore(store.db_path, store.upload_dir)
    task = create(uploads)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(append, value, task, 0, b"a" * CHUNK)
                   for value in (uploads, (second, accounts, tokens))]
        assert [future.result()["received_bytes"] for future in futures] == [CHUNK, CHUNK]
    assert Path(raw_task(store, task)["file_path"] + ".part").stat().st_size == CHUNK


def test_sqlite_full_after_final_rename_rolls_back_and_recovers(uploads, monkeypatch):
    store, _, _ = uploads
    task = create(uploads)
    append(uploads, task, 0, b"a" * CHUNK)
    def full(*_args, **_kwargs):
        error = sqlite3.OperationalError("synthetic database full")
        error.sqlite_errorcode = sqlite3.SQLITE_FULL
        raise error
    with monkeypatch.context() as patch:
        patch.setattr(store, "_audit", full)
        with pytest.raises(module.VideoUploadError) as error:
            append(uploads, task, 1, b"end")
        assert error.value.status == 507
    row = raw_task(store, task)
    assert row["received_bytes"] == CHUNK and row["upload_status"] == "uploading"
    assert Path(row["file_path"]).exists()
    assert resume(uploads, task, (b"a" * CHUNK,))["next_chunk_index"] == 1
    assert append(uploads, task, 1, b"end")["upload_status"] == "completed"
    assert Path(row["file_path"]).read_bytes() == b"a" * CHUNK + b"end"


def test_new_upload_limits_are_server_owned_and_legacy_resume_still_works(uploads, monkeypatch):
    store, _, tokens = uploads
    monkeypatch.setattr(module.shutil, "disk_usage", lambda _: SimpleNamespace(free=20 * 1024**3))
    assert module.MAX_VIDEO_BYTES == 5 * 1024**3
    assert module.MAX_NEW_VIDEO_BYTES == 1024**3
    assert store.account_upload_workspace(tokens["school_uploader_01"], "synthetic")["max_video_bytes"] == 1024**3
    assert store.video_channels()["max_video_bytes"] == 1024**3
    task = create(uploads, module.MAX_NEW_VIDEO_BYTES, processing_config={"upload_max_duration_sec": 99999})
    assert task["processing_config"]["upload_max_duration_sec"] == 3600
    assert create(uploads, 702231347)["byte_size"] == 702231347
    with pytest.raises(ValueError):
        create(uploads, module.MAX_NEW_VIDEO_BYTES + 1)
    with store._connect() as connection:
        connection.execute("UPDATE video_analysis_tasks SET byte_size=?, total_chunks=?, processing_config_json='{}' WHERE task_id=?",
                           (module.MAX_VIDEO_BYTES, module.MAX_VIDEO_BYTES // CHUNK, task["task_id"]))
    legacy = {**task, "byte_size": module.MAX_VIDEO_BYTES}
    assert resume(uploads, legacy)["received_bytes"] == 0
    append(uploads, legacy, 0, b"a" * CHUNK)
    assert resume(uploads, legacy, (b"a" * CHUNK,))["received_bytes"] == CHUNK
    assert raw_task(store, task)["processing_config_json"] == "{}"


@pytest.fixture()
def upload_server(uploads, tmp_path, monkeypatch):
    monkeypatch.setattr(server, "get_demo2_student_store", lambda: uploads[0])
    monkeypatch.setattr(server, "load_seewo_demo2", lambda: {"students": []})
    handler = server.create_handler(scenario_dir=tmp_path, model_path=tmp_path / "unused", policy_name="rule")
    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd.server_port
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(5)


def post(port, token, path, body, **headers):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        connection.request("POST", "/api/v1/demo2/upload/" + path, body=body,
                           headers={"Cookie": "rehab_demo2_session=" + token, "Content-Type": "application/octet-stream", **headers})
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        connection.close()


def test_http_binary_legacy_and_resume_contract(upload_server, uploads):
    task = create(uploads)
    token = uploads[2]["school_uploader_01"]
    query = urlencode({"task_id": task["task_id"], "course_id": "synthetic", "chunk_index": 0})
    path = "chunks?" + query
    status, response = post(upload_server, token, path, b"a" * CHUNK)
    assert status == 200 and response["task"]["next_chunk_index"] == 1
    assert post(upload_server, token, path, b"a" * CHUNK)[0] == 200
    assert post(upload_server, token, path, b"b" * CHUNK)[0] == 409
    status, response = post(upload_server, token, "resume", json.dumps(resume_payload(task, (b"a" * CHUNK,))), **{"Content-Type": "application/json"})
    assert status == 200 and response["task"]["received_bytes"] == CHUNK
    payload = {"task_id": task["task_id"], "course_id": "synthetic", "chunk_index": 1,
               "content_base64": base64.b64encode(b"end").decode()}
    assert post(upload_server, token, "chunks", json.dumps(payload), **{"Content-Type": "application/json"})[0] == 200
    assert post(upload_server, token, "chunks", json.dumps(payload), **{"Content-Type": "application/json"})[0] == 200


@pytest.mark.parametrize("name,expected", [("", 401), ("school_uploader_02", 403), ("company_admin", 403)])
def test_http_owner_enforced_for_binary_and_resume(upload_server, uploads, name, expected):
    task = create(uploads, 3)
    token = uploads[2].get(name, "")
    path = "chunks?" + urlencode({"task_id": task["task_id"], "course_id": "synthetic", "chunk_index": 0})
    assert post(upload_server, token, path, b"end")[0] == expected
    assert post(upload_server, token, "resume", json.dumps(resume_payload(task)), **{"Content-Type": "application/json"})[0] == expected


@pytest.mark.parametrize("headers,expected", [({"Origin": "https://other.invalid"}, 403),
    ({"Origin": "null"}, 403), ({"Sec-Fetch-Site": "cross-site"}, 403),
    ({"Content-Encoding": "gzip"}, 415), ({"Content-Type": "text/plain"}, 400),
    ({"Transfer-Encoding": "chunked"}, 400), ({"Content-Length": str(CHUNK + 1)}, 413)])
def test_http_rejects_csrf_encoding_and_framing(upload_server, uploads, headers, expected):
    task = create(uploads, 3)
    path = "chunks?" + urlencode({"task_id": task["task_id"], "course_id": "synthetic", "chunk_index": 0})
    assert post(upload_server, uploads[2]["school_uploader_01"], path, b"end", **headers)[0] == expected
    assert raw_task(uploads[0], task)["received_bytes"] == 0


def test_http_resume_zero_and_bounded_json(upload_server, uploads):
    task = create(uploads, 3)
    token = uploads[2]["school_uploader_01"]
    headers = {"Content-Type": "application/json"}
    assert post(upload_server, token, "resume", json.dumps(resume_payload(task)), **headers)[0] == 200
    assert post(upload_server, token, "resume", '{"task_id":"a","task_id":"b"}', **headers)[0] == 400
    assert post(upload_server, token, "resume", b"{}", **{**headers, "Content-Length": str(128 * 1024 + 1)})[0] == 413
