from __future__ import annotations

import base64
import hashlib
import json
import os
import stat
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from rehab_affect.student_record_store import Demo2StudentRecordStore


@pytest.fixture()
def media_store(tmp_path, monkeypatch):
    monkeypatch.setenv("REHAB_DEMO2_ACCOUNT_PASSWORD_PREFIX", "MediaTest-")
    return Demo2StudentRecordStore(tmp_path / "media.sqlite3", tmp_path / "documents")


def login(store, username="school_uploader_01"):
    account = store.authenticate_account(username, f"MediaTest-{username}")
    return account, store.create_account_session(account)["token"]


def create_task(store, *, config=None, finish_upload=True, content=b"uploaded-bytes"):
    account, token = login(store)
    task = store.create_video_task({
        "account_id": account["account_id"], "account_session_token": token,
        "channel_id": "channel_1", "session_id": "lesson", "uploader_name": "Fixture Teacher",
        "course_id": "media-course", "course_name": "Fixture Course", "filename": "lesson.mp4",
        "byte_size": len(content), "total_chunks": 1, "processing_config": config or {},
    })
    if finish_upload:
        task = store.append_video_chunk({"task_id": task["task_id"], "account_id": account["account_id"],
                                        "chunk_index": 0, "content_base64": base64.b64encode(content).decode("ascii")})
    return task, token


def engine_result(task_id):
    return {"version": "fixture-v1", "task_id": task_id, "content": {"duration_seconds": 3, "segments": []}}


def expire(store, task_id):
    with store._connect() as connection:
        connection.execute("UPDATE video_analysis_tasks SET expires_at = ? WHERE task_id = ?",
                           ((datetime.now().astimezone() - timedelta(seconds=1)).isoformat(), task_id))


def raw_task(store, task_id):
    with store._connect() as connection:
        return dict(connection.execute("SELECT * FROM video_analysis_tasks WHERE task_id = ?", (task_id,)).fetchone())


def test_upload_completion_only_queues_and_hashes(media_store, monkeypatch):
    def forbidden_precheck(*args):
        raise AssertionError("Upload must not invoke the analysis engine")

    monkeypatch.setattr(media_store, "_build_video_precheck", forbidden_precheck)
    task, token = create_task(media_store)
    assert task["upload_status"] == "completed" and task["analysis_status"] == "queued"
    assert task["progress_percent"] == 100 and task["processing_progress"] == 0
    assert task["processing_stage"] == "queued" and task["attempt_count"] == 0
    assert task["processing_error"] is None and task["result_url"] == ""
    assert task["result_download_url"] == ""
    assert task["sha256"] == hashlib.sha256(b"uploaded-bytes").hexdigest()
    assert not (media_store.video_task_dir / "analysis" / task["task_id"]).exists()
    assert not (media_store.video_task_dir / "results").exists()
    assert media_store.account_video_media(token, task["task_id"])[0].read_bytes() == b"uploaded-bytes"
    with pytest.raises(ValueError, match="尚无"):
        media_store.account_video_result_for_download(token, task["task_id"])


def test_lifecycle_persists_config_progress_and_idempotent_result(media_store):
    task, token = create_task(media_store, config={"version": "pipeline-v1", "sample_seconds": 5})
    task_id = task["task_id"]
    claim = media_store.claim_next_video_analysis()
    assert claim["task_id"] == task_id and claim["attempt_count"] == 1
    assert claim["processing_config"] == task["processing_config"]
    assert Path(claim["file_path"]).is_file() and Path(claim["analysis_dir"]).is_dir()
    assert media_store.claim_next_video_analysis() is None
    media_store.update_video_analysis_progress(task_id, "extract_audio", 45)
    assert media_store.update_video_analysis_progress(task_id, "sample_frames", 20)["processing_progress"] == 45
    assert media_store.update_video_analysis_progress(task_id, "writing_result", 100)["processing_progress"] == 99
    audio = Path(claim["analysis_dir"]) / "audio.wav"
    audio.write_bytes(b"fixture-audio")
    with pytest.raises(ValueError, match="尚未"):
        media_store.account_video_media(token, task_id, "audio")
    result = engine_result(task_id)
    result["content"]["source_path"] = claim["file_path"]
    ready = media_store.finish_video_analysis(task_id, result)
    assert ready["analysis_status"] == "evidence_ready" and ready["processing_progress"] == 100
    assert ready["processing_stage"] == "evidence_ready"
    assert ready["result_download_url"].startswith("/api/seewo_demo2/video_result_download")
    assert ready["result_url"] == f"/api/v1/demo2/upload/result?id={task_id}"
    assert ready["review_url"] == f"/demo2/video?id={task_id}"
    assert ready["media_url"].endswith(f"id={task_id}&asset=source")
    path, _ = media_store.account_video_result_for_download(token, task_id)
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored == engine_result(task_id)
    before = path.stat().st_mtime_ns
    assert media_store.finish_video_analysis(task_id, result) == ready
    assert path.stat().st_mtime_ns == before
    assert media_store.account_video_media(token, task_id, "audio") == (audio, "audio/wav")
    reopened = Demo2StudentRecordStore(media_store.db_path, media_store.upload_dir)
    public = reopened.account_video_task(token, task_id)
    assert public == ready
    for key in ("file_path", "result_path", "analysis_dir", "processing_claim_id", "processing_result_json"):
        assert key not in public
    assert str(media_store.video_task_dir) not in json.dumps(public)


def test_claim_is_atomic_and_single_active_across_store_instances(media_store):
    first, _ = create_task(media_store)
    second, _ = create_task(media_store)
    stores = [Demo2StudentRecordStore(media_store.db_path, media_store.upload_dir) for _ in range(6)]
    with ThreadPoolExecutor(max_workers=6) as pool:
        claims = list(pool.map(lambda store: store.claim_next_video_analysis(), stores))
    assert len([claim for claim in claims if claim]) == 1
    winner = next(index for index, claim in enumerate(claims) if claim)
    assert claims[winner]["task_id"] == first["task_id"]
    with pytest.raises(ValueError, match="未领取"):
        media_store.update_video_analysis_progress(first["task_id"], "extract_audio", 10)
    stores[winner].finish_video_analysis(first["task_id"], engine_result(first["task_id"]))
    assert media_store.claim_next_video_analysis()["task_id"] == second["task_id"]


def test_recovery_is_explicit_and_fences_old_worker(media_store):
    task, token = create_task(media_store)
    task_id = task["task_id"]
    claim = media_store.claim_next_video_analysis()
    audio = Path(claim["analysis_dir"]) / "audio.wav"
    audio.write_bytes(b"partial-old-attempt")
    media_store.update_video_analysis_progress(task_id, "extract_audio", 40)
    restarted = Demo2StudentRecordStore(media_store.db_path, media_store.upload_dir)
    assert restarted.account_video_task(token, task_id)["analysis_status"] == "processing"
    assert restarted.claim_next_video_analysis() is None
    assert restarted.recover_interrupted_video_analysis() == {"recovered_count": 1, "recovered_task_ids": [task_id]}
    assert restarted.recover_interrupted_video_analysis()["recovered_count"] == 0
    new_claim = restarted.claim_next_video_analysis()
    assert new_claim["attempt_count"] == 2 and not audio.exists()
    with pytest.raises(ValueError, match="失效"):
        media_store.finish_video_analysis(task_id, engine_result(task_id))
    with pytest.raises(ValueError, match="失效"):
        media_store.fail_video_analysis(task_id, "old_worker", "旧的处理尝试")
    restarted.finish_video_analysis(task_id, engine_result(task_id))


def test_failure_retry_preserves_config_and_increments_attempt_only_on_claim(media_store):
    task, token = create_task(media_store, config={"b": 2, "a": 1})
    task_id = task["task_id"]
    claim = media_store.claim_next_video_analysis()
    failed = media_store.fail_video_analysis(task_id, "decode_failed", "无法读取 D:/private/source.mp4")
    assert failed["analysis_status"] == "failed" and failed["attempt_count"] == 1
    assert failed["processing_error"]["code"] == "decode_failed"
    assert "D:/private" not in json.dumps(failed)
    queued = media_store.retry_account_video_analysis(token, task_id)
    assert queued["attempt_count"] == 1 and queued["processing_error"] is None
    assert queued["processing_config_hash"] == claim["processing_config_hash"]
    assert queued["processing_key"] == claim["processing_key"]
    with pytest.raises(ValueError, match="仅失败"):
        media_store.retry_account_video_analysis(token, task_id)
    assert media_store.claim_next_video_analysis()["attempt_count"] == 2


def test_owner_admin_access_and_no_payload_owner_spoofing(media_store):
    task, owner = create_task(media_store)
    _, other = login(media_store, "school_uploader_02")
    _, admin = login(media_store, "company_admin")
    task_id = task["task_id"]
    for method, args in ((media_store.account_video_task, (other, task_id)),
                         (media_store.account_video_media, (other, task_id)),
                         (media_store.account_video_media, (other, task_id, "audio")),
                         (media_store.retry_account_video_analysis, (other, task_id))):
        with pytest.raises(ValueError, match="无权"):
            method(*args)
    assert media_store.account_video_task(admin, task_id)["account_id"] == task["account_id"]
    assert media_store.account_video_media(admin, task_id)[0].is_file()
    media_store.claim_next_video_analysis()
    media_store.fail_video_analysis(task_id, "fixture_failure", "测试失败")
    assert media_store.retry_account_video_analysis(admin, task_id)["account_id"] == task["account_id"]
    with pytest.raises(ValueError):
        media_store.account_video_media(owner, task_id, "../audio.wav")
    media_store.revoke_account_session(owner)
    with pytest.raises(ValueError, match="会话"):
        media_store.account_video_task(owner, task_id)


@pytest.mark.parametrize("stage,progress", [("../stage", 10), ("extract_audio", -1), ("x", 101), ("x", True), ("x", float("nan"))])
def test_invalid_progress_is_rejected(media_store, stage, progress):
    task, _ = create_task(media_store)
    media_store.claim_next_video_analysis()
    with pytest.raises(ValueError):
        media_store.update_video_analysis_progress(task["task_id"], stage, progress)
    assert raw_task(media_store, task["task_id"])["processing_progress"] == 0


def test_invalid_or_wrong_task_result_does_not_publish_file(media_store):
    task, _ = create_task(media_store)
    media_store.claim_next_video_analysis()
    for result in ({}, {"version": "v1"}, {"version": "v1", "content": {}, "task_id": "another-task"}):
        with pytest.raises(ValueError):
            media_store.finish_video_analysis(task["task_id"], result)
    assert raw_task(media_store, task["task_id"])["analysis_status"] == "processing"
    assert not (media_store.video_task_dir / "results").exists()


def test_expiry_cleans_source_audio_and_artifacts_but_keeps_structured_result(media_store):
    task, token = create_task(media_store)
    task_id = task["task_id"]
    claim = media_store.claim_next_video_analysis()
    directory = Path(claim["analysis_dir"])
    (directory / "audio.wav").write_bytes(b"private-audio")
    (directory / "frames").mkdir()
    (directory / "frames" / "one.jpg").write_bytes(b"private-frame")
    media_store.finish_video_analysis(task_id, engine_result(task_id))
    expire(media_store, task_id)
    for asset in ("source", "audio"):
        with pytest.raises(ValueError, match="到期"):
            media_store.account_video_media(token, task_id, asset)
    assert media_store.account_video_task(token, task_id)["media_url"] == ""
    outcome = media_store.enforce_raw_media_retention()
    assert outcome["deleted_count"] == 1 and outcome["failed"] == []
    assert not Path(claim["file_path"]).exists() and not directory.exists()
    assert media_store.account_video_result_for_download(token, task_id)[0].is_file()
    assert media_store.enforce_raw_media_retention()["deleted_count"] == 0
    directory.mkdir()
    (directory / "audio.wav").write_bytes(b"late-worker-write")
    assert media_store.enforce_raw_media_retention()["deleted_count"] == 1
    assert not directory.exists()


def test_expired_queued_or_active_video_cannot_be_processed(media_store):
    task, token = create_task(media_store)
    task_id = task["task_id"]
    expire(media_store, task_id)
    assert media_store.claim_next_video_analysis() is None
    assert media_store.account_video_task(token, task_id)["analysis_status"] == "failed"
    with pytest.raises(ValueError, match="到期"):
        media_store.retry_account_video_analysis(token, task_id)
    active, _ = create_task(media_store)
    media_store.claim_next_video_analysis()
    expire(media_store, active["task_id"])
    media_store.enforce_raw_media_retention()
    with pytest.raises(ValueError, match="失效"):
        media_store.finish_video_analysis(active["task_id"], engine_result(active["task_id"]))


def test_audio_not_readable_if_source_missing_or_auto_delete_disabled(media_store):
    task, token = create_task(media_store)
    claim = media_store.claim_next_video_analysis()
    audio = Path(claim["analysis_dir"]) / "audio.wav"
    audio.write_bytes(b"audio")
    media_store.finish_video_analysis(task["task_id"], engine_result(task["task_id"]))
    source = Path(claim["file_path"])
    source.unlink()
    with pytest.raises(ValueError, match="原视频不存在"):
        media_store.account_video_media(token, task["task_id"], "audio")
    source.write_bytes(b"uploaded-bytes")
    with media_store._connect() as connection:
        connection.execute("UPDATE retention_policies SET auto_delete = 0 WHERE data_type = 'raw_media'")
    expire(media_store, task["task_id"])
    assert media_store.enforce_raw_media_retention()["auto_delete"] is False
    assert audio.is_file() and source.is_file()
    with pytest.raises(ValueError, match="到期"):
        media_store.account_video_media(token, task["task_id"], "audio")


def test_legacy_precheck_requires_explicit_authorized_enqueue(media_store):
    task, token = create_task(media_store)
    task_id = task["task_id"]
    result_path = media_store.video_task_dir / "results" / f"{task_id}.json"
    result_path.parent.mkdir()
    result_path.write_text('{"legacy":true}', encoding="utf-8")
    with media_store._connect() as connection:
        connection.execute("UPDATE video_analysis_tasks SET analysis_status = 'precheck_complete', result_path = ? WHERE task_id = ?",
                           (str(result_path), task_id))
    reopened = Demo2StudentRecordStore(media_store.db_path, media_store.upload_dir)
    assert reopened.recover_interrupted_video_analysis()["recovered_count"] == 0
    assert reopened.claim_next_video_analysis() is None
    assert reopened.account_video_result_for_download(token, task_id)[0] == result_path
    with pytest.raises(ValueError, match="仅失败"):
        reopened.retry_account_video_analysis(token, task_id)
    _, other = login(reopened, "school_uploader_02")
    with pytest.raises(ValueError, match="无权"):
        reopened.enqueue_legacy_video_analysis(other, task_id)
    assert reopened.enqueue_legacy_video_analysis(token, task_id)["analysis_status"] == "queued"
    with pytest.raises(ValueError, match="尚无"):
        reopened.account_video_result_for_download(token, task_id)
    assert reopened.claim_next_video_analysis()["task_id"] == task_id


def test_retention_rejects_outside_source_and_analysis_directory_links(media_store, tmp_path):
    task, token = create_task(media_store)
    task_id = task["task_id"]
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "audio.wav"
    sentinel.write_bytes(b"do-not-delete")
    with media_store._connect() as connection:
        connection.execute("UPDATE video_analysis_tasks SET file_path = ? WHERE task_id = ?", (str(sentinel), task_id))
    with pytest.raises(ValueError, match="受控"):
        media_store.account_video_media(token, task_id)
    expire(media_store, task_id)
    assert media_store.enforce_raw_media_retention()["failed"] and sentinel.exists()

    linked, linked_token = create_task(media_store)
    claim = media_store.claim_next_video_analysis()
    directory = Path(claim["analysis_dir"])
    directory.rmdir()
    try:
        if os.name == "nt":
            import _winapi
            _winapi.CreateJunction(str(outside), str(directory))
        else:
            directory.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"Cannot create test directory link: {exc}")
    try:
        with pytest.raises(ValueError, match="受控"):
            media_store._video_analysis_dir(linked["task_id"])
        expire(media_store, linked["task_id"])
        assert media_store.enforce_raw_media_retention()["failed"]
        assert sentinel.read_bytes() == b"do-not-delete"
    finally:
        if os.name == "nt":
            directory.rmdir()
        else:
            directory.unlink()


def test_upload_rejects_spoofed_account_and_bad_final_size_without_appending(media_store):
    task, _ = create_task(media_store, finish_upload=False, content=b"ab")
    row = raw_task(media_store, task["task_id"])
    part = Path(f"{row['file_path']}.part")
    for payload in ({"content_base64": "YWI=", "account_id": "forged-owner"}, {"content_base64": "YQ=="}):
        with pytest.raises(ValueError):
            media_store.append_video_chunk({"task_id": task["task_id"], "chunk_index": 0, **payload})
    assert part.read_bytes() == b""
    part.write_bytes(b"uncommitted-data")
    complete = media_store.append_video_chunk({"task_id": task["task_id"], "chunk_index": 0, "content_base64": "YWI="})
    assert complete["sha256"] == hashlib.sha256(b"ab").hexdigest()


def test_config_is_canonical_and_not_shared_between_tasks(media_store):
    first, _ = create_task(media_store, config={"b": 2, "a": 1})
    second, _ = create_task(media_store, config={"a": 1, "b": 2})
    assert first["processing_config_hash"] == second["processing_config_hash"]
    assert first["processing_key"] != second["processing_key"]
    assert raw_task(media_store, first["task_id"])["processing_config_json"] == '{"a":1,"b":2,"upload_max_duration_sec":3600}'


def test_engine_native_evidence_payload_is_saved_without_repackaging(media_store):
    task, token = create_task(media_store)
    media_store.claim_next_video_analysis()
    result = {"task_id": task["task_id"], "analysis_version": "fixture-v1", "analysis_status": "evidence_ready",
              "media": {"duration_sec": 3}, "segments": [], "provenance": {"network_used": False}}
    media_store.finish_video_analysis(task["task_id"], result)
    path, _ = media_store.account_video_result_for_download(token, task["task_id"])
    assert json.loads(path.read_text(encoding="utf-8")) == result


@pytest.mark.parametrize("status,label", [
    ("evidence_ready", "视频证据记录"),
    ("completed", "视频证据记录"),
    ("precheck_complete", "上传预检结果"),
    ("uploaded_pending_worker", "上传预检结果"),
])
def test_result_download_filename_distinguishes_evidence_from_legacy_precheck(media_store, status, label):
    task, token = create_task(media_store)
    task_id = task["task_id"]
    media_store.claim_next_video_analysis()
    media_store.finish_video_analysis(task_id, engine_result(task_id))
    with media_store._connect() as connection:
        connection.execute("UPDATE video_analysis_tasks SET analysis_status = ? WHERE task_id = ?", (status, task_id))
    path, filename = media_store.video_result_for_download(task_id)
    assert path.is_file()
    assert filename == f"lesson_{label}.json"
    assert media_store.account_video_result_for_download(token, task_id) == (path, filename)


def test_audio_uses_persisted_run_manifest_with_owner_and_expiry_checks(media_store):
    task, owner = create_task(media_store)
    task_id = task["task_id"]
    claim = media_store.claim_next_video_analysis()
    directory = Path(claim["analysis_dir"])
    run = directory / "run_fixture"
    run.mkdir()
    audio = run / "audio.wav"
    audio.write_bytes(b"current-audio")
    (directory / "audio.wav").write_bytes(b"obsolete-root-audio")
    result = {"task_id": task_id, "analysis_version": "fixture-v1", "analysis_status": "evidence_ready",
              "media": {"duration_sec": 3}, "segments": [],
              "artifacts": {"audio": "run_fixture/audio.wav", "result": "run_fixture/analysis.json"}}
    media_store.finish_video_analysis(task_id, result)
    reopened = Demo2StudentRecordStore(media_store.db_path, media_store.upload_dir)
    _, admin = login(reopened, "company_admin")
    _, other = login(reopened, "school_uploader_02")
    for token in (owner, admin):
        assert reopened.account_video_media(token, task_id, "audio") == (audio, "audio/wav")
    with pytest.raises(ValueError, match="无权"):
        reopened.account_video_media(other, task_id, "audio")
    result_path, _ = reopened.account_video_result_for_download(owner, task_id)
    assert json.loads(result_path.read_text(encoding="utf-8"))["artifacts"] == result["artifacts"]
    audio.unlink()
    with pytest.raises(ValueError, match="不存在"):
        reopened.account_video_media(owner, task_id, "audio")  # Do not serve the obsolete root file.
    audio.write_bytes(b"current-audio")
    expire(reopened, task_id)
    for token in (owner, admin):
        with pytest.raises(ValueError, match="到期"):
            reopened.account_video_media(token, task_id, "audio")


def test_audio_invalid_or_absent_manifest_never_falls_back(media_store):
    task, token = create_task(media_store)
    task_id = task["task_id"]
    claim = media_store.claim_next_video_analysis()
    root_audio = Path(claim["analysis_dir"]) / "audio.wav"
    root_audio.write_bytes(b"legacy-audio")
    result = engine_result(task_id)
    media_store.finish_video_analysis(task_id, result)
    assert media_store.account_video_media(token, task_id, "audio")[0] == root_audio
    invalid_paths = ["../another_task/audio.wav", "run/../audio.wav", "/tmp/audio.wav",
                     "C:/private/audio.wav", "C:audio.wav", "\\\\server\\share\\audio.wav",
                     "run/other.wav", "run/audio.wav:stream", "run/\x00/audio.wav", "", 42, []]
    invalid_results = [{**result, "artifacts": {"audio": value}} for value in invalid_paths]
    invalid_results.extend([{**result, "artifacts": value} for value in (None, [], {}, {"audio": None})])
    invalid_results.extend([{}, None, []])
    for invalid in invalid_results:
        with media_store._connect() as connection:
            connection.execute("UPDATE video_analysis_tasks SET processing_result_json = ? WHERE task_id = ?",
                               (json.dumps(invalid), task_id))
        with pytest.raises(ValueError, match="清单|不存在音轨"):
            media_store.account_video_media(token, task_id, "audio")
    with media_store._connect() as connection:
        connection.execute("UPDATE video_analysis_tasks SET processing_result_json = ? WHERE task_id = ?",
                           ("not-json", task_id))
    with pytest.raises(ValueError, match="清单"):
        media_store.account_video_media(token, task_id, "audio")


def test_manifest_audio_and_retention_reject_links_before_deleting_any_artifacts(media_store, tmp_path):
    task, token = create_task(media_store)
    task_id = task["task_id"]
    claim = media_store.claim_next_video_analysis()
    directory = Path(claim["analysis_dir"])
    outside = tmp_path / "another_task"
    outside.mkdir()
    sentinel = outside / "audio.wav"
    sentinel.write_bytes(b"other-task-audio")
    frame = directory / "frame.png"
    frame.write_bytes(b"keep-until-entire-tree-valid")
    link = directory / "run_link"
    try:
        if os.name == "nt":
            import _winapi
            _winapi.CreateJunction(str(outside), str(link))
        else:
            link.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"Cannot create test directory link: {exc}")
    try:
        result = {**engine_result(task_id), "artifacts": {"audio": "run_link/audio.wav"}}
        media_store.finish_video_analysis(task_id, result)
        with pytest.raises(ValueError, match="受控"):
            media_store.account_video_media(token, task_id, "audio")
        expire(media_store, task_id)
        outcome = media_store.enforce_raw_media_retention()
        assert outcome["deleted_count"] == 0 and len(outcome["failed"]) == 1
        assert frame.is_file() and Path(claim["file_path"]).is_file()
        assert sentinel.read_bytes() == b"other-task-audio"
    finally:
        if os.name == "nt":
            link.rmdir()
        else:
            link.unlink()
    assert media_store.enforce_raw_media_retention()["deleted_count"] == 1
    assert not directory.exists() and sentinel.is_file()


def test_audio_rejects_nonredirecting_windows_reparse_points(media_store, monkeypatch):
    task, token = create_task(media_store)
    task_id = task["task_id"]
    claim = media_store.claim_next_video_analysis()
    audio = Path(claim["analysis_dir"]) / "audio.wav"
    audio.write_bytes(b"audio")
    media_store.finish_video_analysis(task_id, engine_result(task_id))
    original_lstat = Path.lstat

    def reparse_lstat(path):
        info = original_lstat(path)
        if path == audio:
            return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT)
        return info

    monkeypatch.setattr(Path, "lstat", reparse_lstat)
    with pytest.raises(ValueError, match="受控"):
        media_store.account_video_media(token, task_id, "audio")


def test_retention_removes_all_run_artifacts_and_preserves_downloadable_result(media_store):
    task, token = create_task(media_store)
    task_id = task["task_id"]
    claim = media_store.claim_next_video_analysis()
    directory = Path(claim["analysis_dir"])
    for relative in ("run_1/audio.wav", "run_1/frames/frame.png", "run_1/analysis.json",
                     "run_2/intermediate/clip.mp4", "run_2/frames/frame.jpg", "scratch.tmp"):
        path = directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"derived-sensitive-data")
    source = Path(claim["file_path"])
    part = Path(f"{source}.part")
    part.write_bytes(b"orphan-upload-data")
    result = {**engine_result(task_id), "artifacts": {"audio": "run_1/audio.wav"}}
    media_store.finish_video_analysis(task_id, result)
    result_path, _ = media_store.account_video_result_for_download(token, task_id)
    preserved_result = result_path.read_bytes()
    expire(media_store, task_id)
    outcome = media_store.enforce_raw_media_retention()
    assert outcome["deleted_count"] == 1 and outcome["failed"] == []
    assert not any(path.exists() for path in (directory, source, part))
    assert media_store.account_video_result_for_download(token, task_id)[0].read_bytes() == preserved_result
    assert media_store.enforce_raw_media_retention()["deleted_count"] == 0
