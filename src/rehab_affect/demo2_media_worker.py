"""A single local media worker, separate from HTTP upload requests."""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from threading import Event, Thread
from typing import Any, Callable

from .demo2_upload_debug import task_fields, upload_debug_event


LOGGER = logging.getLogger(__name__)
_PROCESSING_ERROR_MESSAGES = {
    "missing_dependency": "视频处理依赖不可用，请联系管理员检查 FFmpeg、ffprobe 和 OpenCV",
    "invalid_media": "视频损坏或缺少可解码画面，请检查原文件后重新上传",
    "invalid_input": "原视频文件不可读取，请检查上传文件是否完整",
    "invalid_task": "视频任务参数无效，请联系管理员检查任务记录",
    "unsafe_path": "视频文件路径未通过安全检查，请联系管理员",
    "resource_limit": "视频时长、大小、分辨率或处理资源超过支持上限，请缩短或压缩后重试",
    "unsupported_rotation": "视频旋转角度不受支持，请转为标准方向后重新上传",
    "unsupported_timestamps": "视频或音轨时间戳不受支持，请重新编码为标准时间轴后上传",
    "source_changed": "处理期间原视频发生变化，请重新上传后重试",
    "hash_mismatch": "视频校验失败，请重新上传完整文件",
    "timeout": "视频处理超时，请稍后重试或缩短视频",
    "tool_start_failed": "视频处理工具无法启动，请联系管理员检查运行环境",
    "tool_io_failed": "视频处理工具读取失败，请重试或联系管理员",
    "tool_failed": "视频解码或音轨处理失败，请检查文件格式与完整性后重试",
    "io_error": "无法读写视频处理文件，请联系管理员检查磁盘空间与权限",
    "image_write_failed": "证据图片生成失败，请重试或联系管理员",
    "cancelled": "视频处理已取消，可重新处理该视频",
    "interrupted": "服务已停止，可重新处理该视频",
    "processing_failed": "视频处理未完成，请检查文件与运行环境后重试",
}


def _public_processing_error(exc: Exception) -> tuple[str, str]:
    # Engine versions may expose message, public_message, or only str(exc).
    # Map stable codes instead of exposing any decoder text or physical paths.
    code = getattr(exc, "code", "processing_failed")
    if not isinstance(code, str) or code not in _PROCESSING_ERROR_MESSAGES:
        code = "processing_failed"
    tool = getattr(exc, "tool", "")
    if code == "missing_dependency" and tool in {"ffmpeg", "ffprobe"}:
        # Name the missing tool so the teacher sees a concrete reason instead
        # of a task that silently never finishes.
        return code, (f"视频处理依赖不可用：服务器未找到 {tool}，请联系管理员检查 FFmpeg、ffprobe 和 OpenCV"
                      f"（可用 REHAB_{tool.upper()} 指定路径）")
    return code, _PROCESSING_ERROR_MESSAGES[code]


class WorkerLock:
    """OS-held lock releases after a crash without deleting another worker's file."""

    def __init__(self, path: Path):
        self.path = path
        self.handle = None

    def acquire(self) -> bool:
        if self.handle is not None:
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            import os

            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        self.handle = handle
        return True

    def release(self) -> None:
        if self.handle is not None:
            self.handle.close()
            self.handle = None


class VideoAnalysisWorker:
    def __init__(self, store: Any, *, processor: Callable | None = None, poll_seconds: float = 1.0):
        self.store = store
        self.processor = processor
        self.poll_seconds = poll_seconds
        self.stop_event = Event()
        self.thread: Thread | None = None
        self.lock = WorkerLock(store.video_task_dir / ".worker.lock")
        self._pending_failure: tuple[str, str, str] | None = None

    def _fail_task(self, task_id: str, code: str, message: str) -> None:
        # A transient database failure must not leave the claimed task blocking
        # the queue forever. Retry its state write before claiming more work.
        self._pending_failure = (task_id, code, message)
        try:
            self.store.fail_video_analysis(*self._pending_failure)
        except ValueError:
            # A rejected/stale claim is permanent, not a transient write failure.
            self._pending_failure = None
            raise
        self._pending_failure = None

    def run_once(self) -> bool:
        if self.stop_event.is_set():
            return False
        if self._pending_failure is not None:
            self._fail_task(*self._pending_failure)
            return True
        task = self.store.claim_next_video_analysis()
        if task is None:
            refresh = getattr(self.store, "refresh_next_simple_analysis", None)
            return bool(refresh(stop_event=self.stop_event)) if callable(refresh) else False
        task_id = task["task_id"]
        started = time.monotonic()
        fields = task_fields(task)
        upload_debug_event(self.store, "processing_start", "claimed", **fields)

        def elapsed_ms() -> float:
            return (time.monotonic() - started) * 1000

        if not isinstance(task_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", task_id):
            self._fail_task(task_id, "invalid_task_path", "处理目录无效")
            upload_debug_event(self.store, "processing_failed", "failed", code="invalid_task_path",
                               duration_ms=elapsed_ms(), **fields)
            return True
        output_dir = self.store.video_task_dir / "analysis" / task_id
        if output_dir.resolve().parent != (self.store.video_task_dir / "analysis").resolve():
            self._fail_task(task_id, "invalid_task_path", "处理目录无效")
            upload_debug_event(self.store, "processing_failed", "failed", code="invalid_task_path",
                               duration_ms=elapsed_ms(), **fields)
            return True
        try:
            if self.processor is None:
                from .demo2_media_analysis import process_video_task

                processor = process_video_task
            else:
                processor = self.processor
            result = processor(
                task,
                output_dir,
                progress=lambda percent, stage: self.store.update_video_analysis_progress(task_id, stage, percent),
                stop_event=self.stop_event,
            )
            if self.stop_event.is_set():
                self._fail_task(task_id, "interrupted", _PROCESSING_ERROR_MESSAGES["interrupted"])
                upload_debug_event(self.store, "processing_failed", "failed", code="interrupted",
                                   duration_ms=elapsed_ms(), **fields)
            else:
                self.store.finish_video_analysis(task_id, result)
                upload_debug_event(self.store, "processing_complete", "evidence_ready",
                                   analysis_status="evidence_ready", progress=100,
                                   duration_ms=elapsed_ms(), **{k: v for k, v in fields.items()
                                                                if k != "analysis_status"})
        except Exception as exc:
            if self._pending_failure is not None:
                raise
            code, message = _public_processing_error(exc)
            if self.stop_event.is_set():
                code, message = "interrupted", _PROCESSING_ERROR_MESSAGES["interrupted"]
            LOGGER.warning("Media task %s failed (%s)", task_id, code)
            self._fail_task(task_id, code, message)
            upload_debug_event(self.store, "processing_failed", "failed", code=code,
                               analysis_status="failed", duration_ms=elapsed_ms(),
                               **{k: v for k, v in fields.items() if k != "analysis_status"})
        return True

    def _loop(self) -> None:
        try:
            while not self.stop_event.is_set():
                try:
                    if self.run_once():
                        continue
                except Exception:
                    LOGGER.exception("Media worker could not update its task state")
                self.stop_event.wait(self.poll_seconds)
        finally:
            self.lock.release()

    def start(self) -> bool:
        if self.stop_event.is_set() or self.thread is not None or not self.lock.acquire():
            return False
        try:
            self._log_media_tools()
            self.store.recover_interrupted_video_analysis()
            self.thread = Thread(target=self._loop, name="demo2-media-analysis", daemon=True)
            self.thread.start()
        except Exception:
            self.thread = None
            self.lock.release()
            raise
        return True

    def _log_media_tools(self) -> None:
        # Record which FFmpeg/ffprobe the worker will use so a host without
        # them is visible at startup, before any teacher upload fails.
        if self.processor is not None:
            return
        try:
            from .demo2_media_analysis import media_tool_status

            status = media_tool_status()
        except Exception:
            LOGGER.exception("Media tool check failed")
            return
        if not status["tools_available"]:
            LOGGER.warning("Media tools missing: %s", ",".join(status["missing"]))
        upload_debug_event(self.store, "media_tools_check", "ok" if status["tools_available"] else "missing",
                           tools_available=status["tools_available"],
                           ffmpeg_source=status["ffmpeg_source"], ffprobe_source=status["ffprobe_source"])

    def stop(self, timeout: float = 30.0) -> None:
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=timeout)
