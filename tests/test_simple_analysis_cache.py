"""Derived result refresh contracts, using only temporary tasks and fake inference."""
from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import sys
import threading
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.rehab_affect import demo2_media_analysis as media
from src.rehab_affect import student_record_store as store_module
from src.rehab_affect.demo2_media_worker import VideoAnalysisWorker, WorkerLock
from src.rehab_affect.student_record_store import Demo2StudentRecordStore


@pytest.fixture
def cache_case(tmp_path, monkeypatch):
    monkeypatch.setenv("REHAB_DEMO2_ACCOUNT_PASSWORD_PREFIX", "CacheFixture-")
    store = Demo2StudentRecordStore(tmp_path / "cache.sqlite3", tmp_path / "documents")
    account = store.authenticate_account("school_uploader_01", "CacheFixture-school_uploader_01")
    token = store.create_account_session(account)["token"]
    calls = []

    def build(segments, run, meta, *, stop_event):
        calls.append((segments, run, meta, stop_event))
        return {"available": True, "analysis_version": media.SIMPLE_ANALYSIS_VERSION,
                "persons": [{"person_id": "person_1", "windows": []}], "detected_samples": 76}

    monkeypatch.setattr(media, "_build_simple_student_analysis", build)

    def create():
        task = store.create_video_task({
            "account_id": account["account_id"], "account_session_token": token,
            "channel_id": "channel_1", "session_id": "cache-lesson", "uploader_name": "Fixture",
            "course_id": "cache-course", "course_name": "Synthetic Course", "filename": "synthetic.mp4",
            "byte_size": 5, "total_chunks": 1,
        })
        task_id = task["task_id"]
        store.append_video_chunk({"task_id": task_id, "account_id": account["account_id"], "chunk_index": 0,
                                  "content_base64": base64.b64encode(b"video").decode("ascii")})
        claim = store.claim_next_video_analysis()
        assert claim["task_id"] == task_id
        frames = Path(claim["analysis_dir"]) / "media_fixture" / "frames"
        frames.mkdir(parents=True)
        (frames / "frame_000000.jpg").write_bytes(b"synthetic-frame-not-decoded")
        result = {"task_id": task_id, "analysis_version": "technical_fixture_v1",
                  "media": {"duration_sec": 2280}, "artifacts": {"frames": "media_fixture/frames"},
                  "segments": [{"visual": {"samples": [{"time_sec": 0, "frame": "frame_000000.jpg"}]}}],
                  "simple_student_analysis": {"available": True, "analysis_version": "old_version",
                                              "persons": [{"person_id": "old_person"}]}}
        store.finish_video_analysis(task_id, result)
        return SimpleNamespace(task_id=task_id, frames=frames)

    item = create()
    return SimpleNamespace(store=store, token=token, account=account, task_id=item.task_id,
                           frames=item.frames, create=create, calls=calls, build=build)


def raw_task(case, task_id=None):
    with case.store._connect() as connection:
        return case.store._video_task_row(connection, task_id or case.task_id)


def change_task(case, **fields):
    with case.store._connect() as connection:
        connection.execute("UPDATE video_analysis_tasks SET " + ", ".join(f"{key} = ?" for key in fields)
                           + " WHERE task_id = ?", (*fields.values(), case.task_id))


def cache_path(case):
    return case.store._simple_analysis_cache_path(raw_task(case), media.SIMPLE_ANALYSIS_VERSION)[0]


def get_analysis(case):
    return case.store.account_simple_analysis(case.token, case.task_id)["analysis"]


def test_get_never_infers_or_writes_cache_and_hides_stale_people(cache_case):
    case = cache_case
    before = raw_task(case)
    files = sorted(p.relative_to(case.store.video_task_dir) for p in case.store.video_task_dir.rglob("*"))
    for _ in range(3):
        response = case.store.account_simple_analysis(case.token, case.task_id)
        assert response["task"]["analysis_status"] == "evidence_ready"
        analysis = response["analysis"]
        assert not analysis["available"] and analysis["persons"] == []
        assert analysis["status"] == "processing" and analysis["refresh_status"] == "pending"
    assert case.calls == []
    assert before == raw_task(case)
    assert files == sorted(p.relative_to(case.store.video_task_dir) for p in case.store.video_task_dir.rglob("*"))


def test_download_uses_derived_analysis_without_overwriting_original(cache_case):
    case = cache_case
    before = raw_task(case)
    original = Path(before['result_path']).read_bytes()
    assert case.store.refresh_next_simple_analysis()
    path, name = case.store.account_video_result_for_download(case.token, case.task_id)
    assert path != Path(before['result_path'])
    assert json.loads(path.read_text(encoding='utf-8'))['simple_student_analysis']['analysis_version'] == media.SIMPLE_ANALYSIS_VERSION
    assert Path(before['result_path']).read_bytes() == original
    assert raw_task(case) == before


def test_refresh_yields_to_new_upload_without_failure_backoff(cache_case, monkeypatch):
    case = cache_case
    def build(segments, run, meta, *, stop_event):
        # Simulate a new ready upload while the native process is running.
        with case.store._connect() as db:
            db.execute("UPDATE video_analysis_tasks SET analysis_status='queued' WHERE task_id=?", (case.task_id,))
        stop_event.next_check = 0
        assert stop_event.is_set()
        raise media.MediaAnalysisCancelled()
    monkeypatch.setattr(media, '_build_simple_student_analysis', build)
    assert not case.store.refresh_next_simple_analysis()
    assert not cache_path(case).exists()


def test_idle_refresh_publishes_hash_named_cache_without_touching_binding_revision(cache_case):
    case = cache_case
    before = raw_task(case)
    original_file = Path(before["result_path"]).read_bytes()
    worker = VideoAnalysisWorker(case.store)
    assert worker.run_once()
    assert len(case.calls) == 1
    segments, run, meta, stop = case.calls[0]
    assert stop.parent is worker.stop_event and run == case.frames.parent
    assert meta["duration_sec"] == 2280 and segments
    digest = hashlib.sha256(before["processing_result_json"].encode("utf-8")).hexdigest()
    path = cache_path(case)
    assert path.name == f"simple_{media.SIMPLE_ANALYSIS_VERSION}_{digest}.json"
    cached = json.loads(path.read_text(encoding="utf-8"))
    assert cached["status"] == "completed" and cached["source_sha256"] == digest
    assert get_analysis(case)["detected_samples"] == 76
    assert get_analysis(case)["refresh_status"] == "ready"
    assert raw_task(case) == before
    assert Path(before["result_path"]).read_bytes() == original_file
    assert not worker.run_once() and len(case.calls) == 1
    assert not list(path.parent.glob("*.tmp"))


def test_refresh_one_task_per_call(cache_case):
    case = cache_case
    second = case.create()
    assert case.store.refresh_next_simple_analysis()
    assert len(case.calls) == 1
    assert case.store.refresh_next_simple_analysis()
    assert len(case.calls) == 2
    assert case.store.account_simple_analysis(case.token, second.task_id)["analysis"]["available"]
    assert not case.store.refresh_next_simple_analysis()


def test_current_embedded_result_requires_no_refresh(cache_case):
    case = cache_case
    result = json.loads(raw_task(case)["processing_result_json"])
    result["simple_student_analysis"]["analysis_version"] = media.SIMPLE_ANALYSIS_VERSION
    change_task(case, processing_result_json=json.dumps(result))
    assert get_analysis(case)["available"]
    assert not case.store.refresh_next_simple_analysis()
    assert not cache_path(case).exists() and not case.calls


def test_existing_motion_result_get_and_download_repair_reports_without_rewriting_evidence(cache_case):
    case = cache_case
    result = json.loads(raw_task(case)['processing_result_json'])
    box = dict(x=.2, y=.2, width=.1, height=.2)
    window = dict(state='low_response', state_zh='old label', score=1.0, movement=.01,
                  start_sec=0, end_sec=30, frame_time_sec=0, frame='frame_000000.jpg', bbox=box,
                  observed_samples=30, expected_samples=30, evidence='old evidence')
    result['simple_student_analysis'] = {
        'available': True, 'analysis_version': media.SIMPLE_ANALYSIS_VERSION,
        'score_kind': 'individual_motion_index', 'observed_frames': 30,
        'persons': [dict(person_id='person_01', display_name='Person 1', anchor_bbox=box,
                         observation_roi=box, windows=[window], average_score=1.0, visibility=1.0)]}
    change_task(case, processing_result_json=json.dumps(result))
    before = raw_task(case)
    source = Path(before['result_path'])
    source.write_text(json.dumps(result), encoding='utf-8')
    original = source.read_bytes()
    presented = get_analysis(case)
    assert presented['persons'][0]['windows'][0]['state'] == 'movement_low'
    assert presented['persons'][0]['windows'][0]['bbox'] == box
    assert len(presented['persons'][0]['lesson_report']['text']) >= 300
    assert not case.calls and not cache_path(case).exists()
    exported, _ = case.store.account_video_result_for_download(case.token, case.task_id)
    assert exported != source
    downloaded = json.loads(exported.read_text(encoding='utf-8'))['simple_student_analysis']
    assert downloaded['persons'] == presented['persons']
    assert case.store.account_video_result_for_download(case.token, case.task_id)[0] == exported
    assert source.read_bytes() == original and raw_task(case) == before


@pytest.mark.parametrize("invalidation", ["version", "revision", "corrupt", "wrong_hash", "wrong_task", "bad_analysis", "oversize"])
def test_invalid_cache_is_never_returned_and_get_does_not_rebuild(cache_case, monkeypatch, invalidation):
    case = cache_case
    assert case.store.refresh_next_simple_analysis()
    path = cache_path(case)
    if invalidation == "version":
        monkeypatch.setattr(media, "SIMPLE_ANALYSIS_VERSION", "next_cache_version")
    elif invalidation == "revision":
        change_task(case, processing_result_json=raw_task(case)["processing_result_json"] + " ")
    elif invalidation == "corrupt":
        path.write_bytes(b'{"partial":')
    elif invalidation == "oversize":
        monkeypatch.setattr(store_module, "MAX_PROCESSING_RESULT_BYTES", 8)
    else:
        cached = json.loads(path.read_text(encoding="utf-8"))
        if invalidation == "wrong_hash":
            cached["source_sha256"] = "0" * 64
        elif invalidation == "wrong_task":
            cached["task_id"] = "another_task"
        else:
            cached["analysis"]["analysis_version"] = "wrong_version"
        path.write_text(json.dumps(cached), encoding="utf-8")
    assert get_analysis(case)["refresh_status"] == "pending"
    assert len(case.calls) == 1
    if invalidation != "oversize":
        assert case.store.refresh_next_simple_analysis()
        assert len(case.calls) == 2 and get_analysis(case)["available"]


def test_cache_publication_is_atomic(cache_case, monkeypatch):
    case = cache_case
    target = cache_path(case)
    task = raw_task(case)
    observed = []
    original = Path.replace

    def replace(source, destination):
        if destination == target:
            assert not target.exists()
            assert json.loads(source.read_text(encoding="utf-8"))["status"] == "completed"
            observed.append(case.store._read_simple_analysis_cache(task, media.SIMPLE_ANALYSIS_VERSION))
        return original(source, destination)

    monkeypatch.setattr(Path, "replace", replace)
    assert case.store.refresh_next_simple_analysis()
    assert observed == [None] and get_analysis(case)["available"]


def test_failure_backoff_survives_store_restart_and_allows_other_tasks(cache_case, monkeypatch):
    case = cache_case
    second = case.create()
    attempts = []

    def fail_first(segments, run, meta, *, stop_event):
        attempts.append(run)
        if run == case.frames.parent:
            raise RuntimeError("D:/private/source.mp4 decoder detail")
        return case.build(segments, run, meta, stop_event=stop_event)

    monkeypatch.setattr(media, "_build_simple_student_analysis", fail_first)
    before = raw_task(case)
    assert case.store.refresh_next_simple_analysis()
    assert raw_task(case) == before
    failure = json.loads(cache_path(case).read_text(encoding="utf-8"))
    assert failure["status"] == "failed" and failure["attempt"] == 1
    assert "private" not in json.dumps(failure)
    assert get_analysis(case)["refresh_status"] == "retry_wait"
    restarted = Demo2StudentRecordStore(case.store.db_path, case.store.upload_dir)
    assert restarted.refresh_next_simple_analysis()
    assert len(attempts) == 2
    assert restarted.account_simple_analysis(case.token, second.task_id)["analysis"]["available"]
    assert not restarted.refresh_next_simple_analysis()
    assert len(attempts) == 2
    now = store_module._now()
    monkeypatch.setattr(store_module, "_now", lambda: now + timedelta(seconds=31))
    assert restarted.refresh_next_simple_analysis()
    assert len(attempts) == 3
    failure = json.loads(cache_path(case).read_text(encoding="utf-8"))
    assert failure["attempt"] == 2
    assert not restarted.refresh_next_simple_analysis()


def test_recently_viewed_task_has_priority_across_store_instances(cache_case):
    case = cache_case
    second = case.create()
    before = raw_task(case, second.task_id)
    response = case.store.account_simple_analysis(case.token, second.task_id)
    assert response["analysis"]["refresh_status"] == "pending" and not case.calls
    assert raw_task(case, second.task_id) == before
    restarted = Demo2StudentRecordStore(case.store.db_path, case.store.upload_dir)
    assert restarted.refresh_next_simple_analysis()
    assert case.calls[0][1] == second.frames.parent
    with restarted._connect() as connection:
        assert not connection.execute("SELECT 1 FROM simple_analysis_refresh_requests WHERE task_id=?",
                                      (second.task_id,)).fetchone()
    assert restarted.refresh_next_simple_analysis()
    assert case.calls[1][1] == case.frames.parent


def test_polling_does_not_rewrite_request_timestamp_every_time(cache_case):
    case = cache_case
    get_analysis(case)
    with case.store._connect() as connection:
        first = tuple(connection.execute("SELECT * FROM simple_analysis_refresh_requests").fetchone())
    get_analysis(case)
    with case.store._connect() as connection:
        second = tuple(connection.execute("SELECT * FROM simple_analysis_refresh_requests").fetchone())
    assert first == second and not case.calls


@pytest.mark.parametrize("change", ["expired", "deleted", "cancelled", "revision", "queued", "source_missing"])
def test_revalidate_after_inference_before_publication(cache_case, monkeypatch, change):
    case = cache_case
    path = cache_path(case)
    before = raw_task(case)

    def mutate(segments, run, meta, *, stop_event):
        if change == "expired":
            change_task(case, expires_at=store_module._iso(store_module._now() - timedelta(seconds=1)))
        elif change == "deleted":
            change_task(case, raw_media_deleted_at=store_module._iso())
        elif change == "cancelled":
            change_task(case, upload_status="cancelled")
        elif change == "revision":
            change_task(case, processing_result_json=before["processing_result_json"] + " ")
        elif change == "queued":
            change_task(case, analysis_status="queued")
        else:
            Path(before["file_path"]).unlink()
        return case.build(segments, run, meta, stop_event=stop_event)

    monkeypatch.setattr(media, "_build_simple_student_analysis", mutate)
    assert case.store.refresh_next_simple_analysis()
    assert len(case.calls) == 1 and not path.exists()
    assert not list(path.parent.glob("*.tmp"))
    assert raw_task(case)["processing_result_json"] == before["processing_result_json"] + (" " if change == "revision" else "")


@pytest.mark.parametrize("expired", [False, True])
def test_get_checks_owner_and_expiry_even_with_valid_cache(cache_case, monkeypatch, expired):
    case = cache_case
    assert case.store.refresh_next_simple_analysis()
    if expired:
        change_task(case, expires_at=store_module._iso(store_module._now() - timedelta(seconds=1)))
    else:
        monkeypatch.setattr(case.store, "account_from_session", lambda token: {
            "role": "school_uploader", "account_id": "someone_else"})
    with pytest.raises(ValueError):
        get_analysis(case)
    assert len(case.calls) == 1


@pytest.mark.parametrize("mode", ["before", "during", "exception", "before_replace"])
def test_cancellation_never_publishes_success_or_failure(cache_case, monkeypatch, mode):
    case = cache_case
    stop = threading.Event()
    if mode == "before":
        stop.set()
    elif mode == "before_replace":
        original = store_module.os.fsync

        def fsync(fd):
            original(fd)
            stop.set()

        monkeypatch.setattr(store_module.os, "fsync", fsync)
    else:
        def cancel(segments, run, meta, *, stop_event):
            assert stop_event.parent is stop
            stop_event.set()
            if mode == "exception":
                raise media.MediaAnalysisCancelled()
            return case.build(segments, run, meta, stop_event=stop_event)

        monkeypatch.setattr(media, "_build_simple_student_analysis", cancel)
    assert not case.store.refresh_next_simple_analysis(stop_event=stop)
    assert not cache_path(case).exists()
    assert not list(cache_path(case).parent.glob("*.tmp"))
    assert raw_task(case)["analysis_status"] == "evidence_ready"


def test_global_refresh_lock_excludes_another_process(cache_case):
    case = cache_case
    path = case.store.video_task_dir / "analysis" / ".simple_refresh.lock"
    lock = WorkerLock(path)
    assert lock.acquire()
    try:
        command = [sys.executable, "-B", "-c",
                   "from pathlib import Path; import sys; "
                   "from src.rehab_affect.demo2_media_worker import WorkerLock; "
                   "lock=WorkerLock(Path(sys.argv[1])); print(lock.acquire()); lock.release()", str(path)]
        checked = subprocess.run(command, cwd=Path(__file__).resolve().parents[1],
                                 capture_output=True, text=True, timeout=15)
        assert checked.returncode == 0, checked.stderr
        assert checked.stdout.strip() == "False"
        assert not case.store.refresh_next_simple_analysis() and not case.calls
    finally:
        lock.release()
    assert case.store.refresh_next_simple_analysis()


@pytest.mark.parametrize("manifest", ["../frames", "/tmp/frames", "C:/frames", "media_fixture/../frames", "media_fixture/no_frames"])
def test_unsafe_or_missing_frame_manifest_never_reaches_inference(cache_case, manifest):
    case = cache_case
    result = json.loads(raw_task(case)["processing_result_json"])
    result["artifacts"]["frames"] = manifest
    change_task(case, processing_result_json=json.dumps(result))
    assert case.store.refresh_next_simple_analysis()
    assert not case.calls
    assert get_analysis(case)["refresh_status"] == "retry_wait"
    assert not case.store.refresh_next_simple_analysis()


@pytest.mark.parametrize("status", ["queued", "processing"])
def test_active_video_work_has_priority_over_cache_refresh(cache_case, status):
    case = cache_case
    second = case.create()
    with case.store._connect() as connection:
        connection.execute("UPDATE video_analysis_tasks SET analysis_status=? WHERE task_id=?", (status, second.task_id))
    assert not case.store.refresh_next_simple_analysis() and not case.calls


def test_worker_processes_upload_before_refresh(cache_case):
    case = cache_case
    second = case.create()
    with case.store._connect() as connection:
        connection.execute("UPDATE video_analysis_tasks SET analysis_status='queued' WHERE task_id=?", (second.task_id,))
    processed = []

    def process(task, directory, *, progress, stop_event):
        processed.append(task["task_id"])
        return {"analysis_version": "fixture", "content": {}}

    worker = VideoAnalysisWorker(case.store, processor=process)
    assert worker.run_once()
    assert processed == [second.task_id] and not case.calls
    assert worker.run_once() and len(case.calls) == 1


def test_negative_completed_result_is_cached_without_retry_loop(cache_case, monkeypatch):
    case = cache_case
    monkeypatch.setattr(media, "_build_simple_student_analysis", lambda *args, **kwargs: {
        "available": False, "reason": "no_video_samples", "persons": []})
    assert case.store.refresh_next_simple_analysis()
    assert not get_analysis(case)["available"]
    assert get_analysis(case)["refresh_status"] == "ready"
    assert not case.store.refresh_next_simple_analysis()
