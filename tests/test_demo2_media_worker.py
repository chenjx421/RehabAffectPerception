from __future__ import annotations

import base64
import json
import subprocess
import threading
from pathlib import Path

import pytest

from src.rehab_affect import demo2_media_worker as worker_module
from src.rehab_affect.demo2_media_worker import VideoAnalysisWorker, WorkerLock


class WorkerStore:
    def __init__(self, root: Path):
        self.video_task_dir = root
        self.task = {"task_id": "test-task"}
        self.progress = []
        self.result = None
        self.error = None
        self.recovered = 0
        self.finished = threading.Event()

    def claim_next_video_analysis(self):
        task, self.task = self.task, None
        return task

    def recover_interrupted_video_analysis(self):
        self.recovered += 1

    def update_video_analysis_progress(self, *args):
        self.progress.append(args)

    def finish_video_analysis(self, task_id, result):
        self.result = result
        self.finished.set()

    def fail_video_analysis(self, *args):
        self.error = args
        self.finished.set()


def test_os_lock_excludes_second_worker_and_releases(tmp_path):
    first, second = WorkerLock(tmp_path / ".lock"), WorkerLock(tmp_path / ".lock")
    assert first.acquire()
    assert not first.acquire()
    assert not second.acquire()
    first.release()
    assert second.acquire()
    second.release()


def test_processing_is_off_request_thread_and_reports_progress(tmp_path):
    store = WorkerStore(tmp_path)
    main_thread = threading.get_ident()

    def process(task, directory, *, progress, stop_event):
        assert threading.get_ident() != main_thread
        assert directory == tmp_path / "analysis" / "test-task"
        assert not stop_event.is_set()
        progress(40, "sampling")
        return {"analysis_status": "evidence_ready"}

    worker = VideoAnalysisWorker(store, processor=process, poll_seconds=.01)
    try:
        assert worker.start()
        assert store.finished.wait(5)
        assert store.result == {"analysis_status": "evidence_ready"}
        assert store.progress == [("test-task", "sampling", 40)]
        assert store.recovered == 1
        assert not worker.start()
    finally:
        worker.stop()
    assert not worker.thread.is_alive()


def test_decoder_errors_do_not_expose_paths(tmp_path):
    store = WorkerStore(tmp_path)

    def fail(*args, **kwargs):
        raise RuntimeError("D:/sensitive/filename.mp4 ffmpeg command")

    worker = VideoAnalysisWorker(store, processor=fail)
    assert worker.run_once()
    assert store.error[1] == "processing_failed"
    assert "D:/" not in store.error[2]
    assert store.result is None
    assert not worker.run_once()


def test_shutdown_does_not_publish_incomplete_result(tmp_path):
    store = WorkerStore(tmp_path)

    def process(*args, stop_event, **kwargs):
        stop_event.set()
        return {"not": "complete"}

    worker = VideoAnalysisWorker(store, processor=process)
    assert worker.run_once()
    assert store.result is None
    assert store.error[1] == "interrupted"


@pytest.mark.parametrize("code, hint", [
    ("missing_dependency", "依赖"), ("invalid_media", "损坏"),
    ("timeout", "超时"), ("resource_limit", "上限"),
    ("hash_mismatch", "校验"), ("io_error", "磁盘"),
])
def test_engine_errors_without_public_message_are_specific_and_safe(tmp_path, code, hint):
    from src.rehab_affect.demo2_media_analysis import MediaAnalysisError

    store = WorkerStore(tmp_path)

    def fail(*args, **kwargs):
        raise MediaAnalysisError(code, "D:/private/student.mp4 /srv/private ffmpeg command")

    assert VideoAnalysisWorker(store, processor=fail).run_once()
    assert store.error[1] == code
    assert hint in store.error[2]
    assert not any(value in store.error[2] for value in ("D:/", "/srv", "student.mp4", "command"))
    assert store.result is None


@pytest.mark.parametrize("code", ["D:/private/error", None, {"secret": "path"}])
def test_unknown_error_codes_cannot_leak_or_break_failure_record(tmp_path, code):
    store = WorkerStore(tmp_path)

    def fail(*args, **kwargs):
        error = RuntimeError("private decoder command")
        error.code = code
        error.public_message = "D:/private/student.mp4"
        raise error

    assert VideoAnalysisWorker(store, processor=fail).run_once()
    assert store.error[1] == "processing_failed"
    assert "private" not in store.error[2]


def test_engine_cancellation_on_shutdown_is_recorded_as_interrupted(tmp_path):
    from src.rehab_affect.demo2_media_analysis import MediaAnalysisCancelled

    store = WorkerStore(tmp_path)

    def process(*args, stop_event, **kwargs):
        stop_event.set()
        raise MediaAnalysisCancelled()

    assert VideoAnalysisWorker(store, processor=process).run_once()
    assert store.error[1] == "interrupted"
    assert store.result is None


def test_second_worker_does_not_recover_active_tasks(tmp_path):
    first_store, second_store = WorkerStore(tmp_path), WorkerStore(tmp_path)
    first_store.task = second_store.task = None
    first, second = VideoAnalysisWorker(first_store), VideoAnalysisWorker(second_store)
    try:
        assert first.start()
        assert not second.start()
        assert first_store.recovered == 1
        assert second_store.recovered == 0
    finally:
        first.stop()
        second.stop()


def test_stop_timeout_keeps_lock_until_processor_really_exits(tmp_path):
    store = WorkerStore(tmp_path)
    entered, release = threading.Event(), threading.Event()

    def process(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return {"not": "publishable_after_stop"}

    worker = VideoAnalysisWorker(store, processor=process)
    other = WorkerLock(tmp_path / ".worker.lock")
    try:
        assert worker.start()
        assert entered.wait(5)
        worker.stop(timeout=0)
        assert worker.thread.is_alive()
        assert not other.acquire()
    finally:
        release.set()
        worker.stop()
    assert other.acquire()
    other.release()
    assert store.result is None
    assert store.error[1] == "interrupted"
    assert not worker.start()


@pytest.mark.parametrize("failure", ["recovery", "thread_start"])
def test_start_failure_releases_lock_and_clears_thread(tmp_path, monkeypatch, failure):
    store = WorkerStore(tmp_path)

    def fail(*args, **kwargs):
        raise RuntimeError("startup failed")

    if failure == "recovery":
        monkeypatch.setattr(store, "recover_interrupted_video_analysis", fail)
    else:
        class BrokenThread:
            def __init__(self, **kwargs):
                pass

            start = fail

        monkeypatch.setattr(worker_module, "Thread", BrokenThread)
    worker = VideoAnalysisWorker(store)
    with pytest.raises(RuntimeError, match="startup failed"):
        worker.start()
    assert worker.thread is None
    worker.stop()
    other = WorkerLock(tmp_path / ".worker.lock")
    assert other.acquire()
    other.release()


@pytest.mark.parametrize("task_id", ["..", "../outside", "C:/outside", "", "nested/task"])
def test_invalid_task_directory_never_reaches_processor(tmp_path, task_id):
    store = WorkerStore(tmp_path)
    store.task["task_id"] = task_id

    def forbidden(*args, **kwargs):
        pytest.fail("Invalid paths must not reach the processor")

    assert VideoAnalysisWorker(store, processor=forbidden).run_once()
    assert store.error[1] == "invalid_task_path"


def test_failed_state_write_is_retried_before_claiming_more_work(tmp_path, monkeypatch):
    store = WorkerStore(tmp_path)
    attempts, processed = [], []
    original = store.fail_video_analysis

    def flaky_failure(*args):
        attempts.append(args)
        if len(attempts) == 1:
            raise OSError("temporary database failure")
        original(*args)

    def process(task, *args, **kwargs):
        processed.append(task["task_id"])
        if len(processed) == 1:
            raise RuntimeError("decoder failed")
        return {"analysis_status": "evidence_ready"}

    monkeypatch.setattr(store, "fail_video_analysis", flaky_failure)
    worker = VideoAnalysisWorker(store, processor=process)
    with pytest.raises(OSError, match="temporary database failure"):
        worker.run_once()
    store.task = {"task_id": "next-task"}
    assert worker.run_once()
    assert attempts[0] == attempts[1]
    assert processed == ["test-task"]
    assert worker.run_once()
    assert processed == ["test-task", "next-task"]
    assert store.result == {"analysis_status": "evidence_ready"}


def test_real_repository_worker_progress_and_download_contract(tmp_path, monkeypatch):
    from src.rehab_affect.student_record_store import Demo2StudentRecordStore

    monkeypatch.setenv("REHAB_DEMO2_ACCOUNT_PASSWORD_PREFIX", "WorkerTest-")
    store = Demo2StudentRecordStore(tmp_path / "worker.sqlite3", tmp_path / "documents")
    account = store.authenticate_account("school_uploader_01", "WorkerTest-school_uploader_01")
    token = store.create_account_session(account)["token"]
    task = store.create_video_task({
        "account_id": account["account_id"], "account_session_token": token,
        "channel_id": "channel_1", "session_id": "lesson", "uploader_name": "Fixture Teacher",
        "course_id": "worker-course", "course_name": "Fixture Course", "filename": "lesson.mp4",
        "byte_size": 5, "total_chunks": 1,
    })
    store.append_video_chunk({
        "task_id": task["task_id"], "account_id": account["account_id"],
        "chunk_index": 0, "content_base64": base64.b64encode(b"video").decode("ascii"),
    })
    with pytest.raises(ValueError, match="尚无"):
        store.account_video_result_for_download(token, task["task_id"])

    def process(claimed, directory, *, progress, stop_event):
        assert directory.resolve() == Path(claimed["analysis_dir"]).resolve()
        progress(40, "sampling")
        current = store.account_video_task(token, task["task_id"])
        assert current["processing_progress"] == 40
        assert current["processing_stage"] == "sampling"
        progress(100, "evidence_ready")
        assert store.account_video_task(token, task["task_id"])["processing_progress"] == 99
        return {"task_id": task["task_id"], "analysis_version": "worker-fixture-v1", "media": {}, "segments": []}

    assert VideoAnalysisWorker(store, processor=process).run_once()
    current = store.account_video_task(token, task["task_id"])
    assert current["analysis_status"] == "evidence_ready"
    assert current["processing_progress"] == 100
    assert current["attempt_count"] == 1
    path, _ = store.account_video_result_for_download(token, task["task_id"])
    assert json.loads(path.read_text(encoding="utf-8"))["analysis_version"] == "worker-fixture-v1"


@pytest.mark.parametrize("failure", [None, "worker", "retention"])
def test_http_server_closes_resources_even_if_background_start_fails(tmp_path, monkeypatch, failure):
    from src.rehab_affect import scenario_lab_server as server_module

    events = []

    class FakeRetentionThread:
        ident = None

        def __init__(self, **kwargs):
            pass

        def start(self):
            if failure == "retention":
                raise RuntimeError("retention startup failed")
            self.ident = 1

        def join(self, **kwargs):
            events.append("retention_joined")

    class FakeWorker:
        def __init__(self, store):
            pass

        def start(self):
            if failure == "worker":
                raise RuntimeError("worker startup failed")

        def stop(self):
            events.append("worker_stopped")

    class FakeServer:
        def __init__(self, *args):
            pass

        def serve_forever(self):
            events.append("served")

        def server_close(self):
            events.append("server_closed")

    monkeypatch.setenv("REHAB_DEMO2_MEDIA_WORKER", "1")
    monkeypatch.setattr(server_module, "create_handler", lambda **kwargs: object())
    monkeypatch.setattr(server_module, "get_demo2_student_store", lambda: WorkerStore(tmp_path))
    monkeypatch.setattr(server_module, "ThreadingHTTPServer", FakeServer)
    monkeypatch.setattr(server_module, "Thread", FakeRetentionThread)
    monkeypatch.setattr(worker_module, "VideoAnalysisWorker", FakeWorker)
    if failure:
        with pytest.raises(RuntimeError, match="startup failed"):
            server_module.run_server(port=0)
        assert "served" not in events
    else:
        server_module.run_server(port=0)
        assert "served" in events
    assert "worker_stopped" in events
    assert ("retention_joined" in events) == (failure != "retention")
    assert events[-1] == "server_closed"


@pytest.fixture()
def analysis_action_handler(tmp_path, monkeypatch):
    from src.rehab_affect import scenario_lab_server as server_module

    class ActionStore:
        calls = []
        error = None

        def _action(self, action, token, task_id):
            self.calls.append((action, token, task_id))
            if self.error:
                raise ValueError(self.error)
            return {"task_id": task_id, "analysis_status": "queued"}

        def retry_account_video_analysis(self, token, task_id):
            return self._action("retry", token, task_id)

        def enqueue_legacy_video_analysis(self, token, task_id):
            return self._action("enqueue", token, task_id)

    store = ActionStore()
    monkeypatch.setattr(server_module, "get_demo2_student_store", lambda: store)
    handler_type = server_module.create_handler(scenario_dir=tmp_path, model_path=tmp_path, policy_name="rule")
    handler = object.__new__(handler_type)
    handler._session_cookie_token = lambda: "test-session"
    return handler, store


@pytest.mark.parametrize("action", ["retry", "enqueue"])
def test_processing_action_routes_use_authorized_repository_and_return_202(analysis_action_handler, action):
    from urllib.parse import urlparse

    handler, store = analysis_action_handler
    responses = []
    handler._require_account = lambda: {"role": "school_uploader"}
    handler._read_json = lambda **kwargs: {"task_id": " task-1 ", "account_id": "ignored-forged-id"}
    handler._send_demo2_json = lambda payload, **kwargs: responses.append((payload, kwargs))
    handler._handle_demo2_api_post(urlparse(f"/api/v1/demo2/upload/tasks/{action}"))
    assert store.calls == [(action, "test-session", "task-1")]
    assert responses == [({"ok": True, "task": {"task_id": "task-1", "analysis_status": "queued"}}, {"status": 202})]


@pytest.mark.parametrize("task_id", [None, "", "  ", 1, {}, []])
def test_processing_action_rejects_missing_or_non_string_task_id(analysis_action_handler, task_id):
    from src.rehab_affect.scenario_lab_server import Demo2APIError

    handler, store = analysis_action_handler
    with pytest.raises(Demo2APIError) as caught:
        handler._account_video_analysis_action({"task_id": task_id}, legacy=False)
    assert caught.value.status == 400
    assert store.calls == []


@pytest.mark.parametrize("legacy, error, status, code", [
    (False, "仅失败任务可重试", 409, "task_not_retryable"),
    (True, "仅旧预检任务可显式加入处理队列", 409, "task_not_enqueueable"),
    (False, "无权访问其他账号的视频任务", 403, "task_forbidden"),
    (True, "未找到视频任务", 404, "task_unavailable"),
    (False, "原视频已到期或已删除，不能读取或重新处理", 410, "media_expired"),
    (True, "登录会话已失效", 401, "authentication_required"),
    (False, "D:/private/student.mp4 invalid internal state", 400, "invalid_request"),
])
def test_processing_action_errors_are_stable_and_safe(analysis_action_handler, legacy, error, status, code):
    from src.rehab_affect.scenario_lab_server import Demo2APIError

    handler, store = analysis_action_handler
    store.error = error
    with pytest.raises(Demo2APIError) as caught:
        handler._account_video_analysis_action({"task_id": "task-1"}, legacy=legacy)
    assert (caught.value.status, caught.value.code) == (status, code)
    assert "D:/" not in caught.value.message


@pytest.mark.parametrize("media_kind", ["audio", "no_audio", "corrupt"])
def test_default_engine_integrates_with_worker_and_sqlite(tmp_path, monkeypatch, media_kind):
    from src.rehab_affect import demo2_media_analysis as media
    from src.rehab_affect.student_record_store import Demo2StudentRecordStore

    try:
        ffmpeg = media._resolve_tool("ffmpeg")
        media._resolve_tool("ffprobe")
    except media.MediaAnalysisError as exc:
        pytest.skip(str(exc))
    pytest.importorskip("cv2")
    if media_kind == "corrupt":
        content = b"not a media container"
    else:
        source = tmp_path / "synthetic.mp4"
        command = [ffmpeg, "-v", "error", "-nostdin", "-f", "lavfi", "-i",
                   "testsrc2=size=160x96:rate=10:duration=2.4"]
        if media_kind == "audio":
            command += ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000:duration=2.4"]
        command += ["-c:v", "mpeg4", "-q:v", "2", "-threads", "1"]
        if media_kind == "audio":
            command += ["-c:a", "aac", "-ac", "1", "-ar", "16000"]
        subprocess.run([*command, str(source)], check=True, capture_output=True, timeout=30)
        content = source.read_bytes()

    monkeypatch.setenv("REHAB_DEMO2_ACCOUNT_PASSWORD_PREFIX", "WorkerEngine-")
    store = Demo2StudentRecordStore(tmp_path / "worker.sqlite3", tmp_path / "documents")
    account = store.authenticate_account("school_uploader_01", "WorkerEngine-school_uploader_01")
    token = store.create_account_session(account)["token"]
    task = store.create_video_task({
        "account_id": account["account_id"], "account_session_token": token,
        "channel_id": "channel_1", "session_id": "lesson", "uploader_name": "Fixture Teacher",
        "course_id": "engine-course", "course_name": "Fixture Course", "filename": "synthetic.mp4",
        "byte_size": len(content), "total_chunks": 1,
    })
    task_id = task["task_id"]
    store.append_video_chunk({"task_id": task_id, "account_id": account["account_id"],
                              "chunk_index": 0, "content_base64": base64.b64encode(content).decode("ascii")})
    callbacks = []
    original_update = store.update_video_analysis_progress

    def update(task_id, stage, percent):
        callbacks.append((stage, percent))
        return original_update(task_id, stage, percent)

    monkeypatch.setattr(store, "update_video_analysis_progress", update)
    worker = VideoAnalysisWorker(store)
    assert worker.run_once()
    current = store.account_video_task(token, task_id)
    assert callbacks and all(isinstance(stage, str) and isinstance(percent, int) for stage, percent in callbacks)
    if media_kind == "corrupt":
        assert current["analysis_status"] == "failed"
        assert current["processing_error"]["code"] in {"tool_failed", "invalid_media"}
        assert str(tmp_path) not in current["processing_error"]["message"]
        with pytest.raises(ValueError, match="尚无"):
            store.account_video_result_for_download(token, task_id)
        return

    assert current["analysis_status"] == "evidence_ready", current["processing_error"]
    assert current["processing_progress"] == 100
    assert callbacks[-1] == ("evidence_ready", 100)
    path, _ = store.account_video_result_for_download(token, task_id)
    result = json.loads(path.read_text(encoding="utf-8"))
    assert result["analysis_version"] == media.ANALYSIS_VERSION
    assert result["media"]["duration_sec"] == pytest.approx(2.4, abs=0.1)
    assert result["media"]["has_audio"] == (media_kind == "audio")
    assert result["summary"]["decoded_frames"] == 24
    assert result["segments"] and result["segments"][0]["review_status"] == "unreviewed"
    assert not worker.run_once()
