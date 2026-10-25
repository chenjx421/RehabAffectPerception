"""Offline color reference previews, held only in memory.

The caller must authorize the source and keep its storage private. This is a
seek-based observation aid, NOT a pixel-identical original of a bound 1 fps
grayscale evidence frame. Never use this image for identity writes. Requested
time is a seek offset, not a claim about the returned frame's original PTS.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import stat
import struct
import subprocess
import threading
import time

from . import demo2_media_analysis as media_analysis


PREVIEW_TIMEOUT_SEC = 8.0
MAX_SOURCE_SIDE = 8192
MAX_PREVIEW_SIDE = 1920
MAX_JPEG_BYTES = 4 * 1024 * 1024
MAX_PROBE_BYTES = 64 * 1024
_CLEANUP_RESERVE_SEC = 0.5
_PIPE_CHUNK_BYTES = 64 * 1024
_PREVIEW_SLOT = threading.BoundedSemaphore(1)


class PreviewError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise PreviewError("timeout", "Frame preview exceeded its time limit.")
    return remaining


def _local_source(source_path: Path) -> Path:
    if not isinstance(source_path, Path):
        raise PreviewError("invalid_input", "A local source Path is required.")
    try:
        source_path = source_path.expanduser()
    except RuntimeError:
        raise PreviewError("invalid_input", "The local source path could not be expanded.") from None
    if str(source_path).startswith(("\\\\", "//")):
        raise PreviewError("unsafe_path", "Remote source paths are not allowed.")
    if os.name == "nt":
        import ctypes

        # The shared policy rejects UNC/URLs; mapped network drives need this
        # extra check BEFORE the shared helper performs filesystem operations.
        root = source_path.absolute().anchor
        if ctypes.windll.kernel32.GetDriveTypeW(root) == 4:
            raise PreviewError("unsafe_path", "Network drives are not allowed.")
    return media_analysis._local_path(source_path)


def _source_signature(source: Path) -> tuple[int, int, int, int, int]:
    media_analysis._no_links(source)
    info = source.stat()
    if not stat.S_ISREG(info.st_mode):
        raise PreviewError("invalid_input", "The source must be a regular local file.")
    if not 0 < info.st_size <= media_analysis.MAX_INPUT_BYTES:
        raise PreviewError("resource_limit", "The source exceeds the supported file-size limits.")
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _run_tool(command: list[str], deadline: float, max_bytes: int) -> bytes:
    """Bound stdout while reading; discard stderr, including private paths.

    communicate()/capture_output would buffer unlimited output before checking
    its size. One unbuffered reader retains at most max_bytes plus one chunk.
    The shared deadline reserves time for killing/reaping the child and reader.
    """
    work_deadline = deadline - _CLEANUP_RESERVE_SEC
    _remaining(work_deadline)
    env = os.environ.copy()
    env.pop("FFREPORT", None)
    try:
        process = subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, bufsize=0, shell=False, close_fds=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            env=env,
        )
    except OSError:
        raise PreviewError("tool_start_failed", "Could not start the local media tool.") from None

    contents = bytearray()
    done = threading.Event()
    closing = threading.Event()
    errors: list[str] = []

    def read_stdout() -> None:
        try:
            assert process.stdout is not None
            while not closing.is_set():
                block = process.stdout.read(_PIPE_CHUNK_BYTES)
                if not block:
                    break
                if len(contents) + len(block) > max_bytes:
                    errors.append("resource_limit")
                    break
                contents.extend(block)
        except (OSError, ValueError):
            errors.append("tool_io_failed")
        finally:
            done.set()

    reader = threading.Thread(target=read_stdout, name="frame-preview-stdout", daemon=True)
    started = False
    try:
        try:
            reader.start()
        except RuntimeError:
            raise PreviewError("tool_io_failed", "Could not start the bounded preview reader.") from None
        started = True
        if not done.wait(_remaining(work_deadline)):
            raise PreviewError("timeout", "Frame preview exceeded its time limit.")
        if errors:
            raise PreviewError(errors[0], "Frame preview output could not be read within its limits.")
        process.wait(timeout=_remaining(work_deadline))
        _remaining(work_deadline)
        if process.returncode:
            raise PreviewError("tool_failed", "The local media tool could not extract a preview.")
        return bytes(contents)
    except subprocess.TimeoutExpired:
        raise PreviewError("timeout", "Frame preview exceeded its time limit.") from None
    finally:
        closing.set()
        try:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=max(0.0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            raise PreviewError("timeout", "The media tool did not stop within its time limit.") from None
        finally:
            if started:
                reader.join(timeout=max(0.0, deadline - time.monotonic()))
            if process.stdout is not None:
                process.stdout.close()


def _probe_video(tool: str, source: Path, requested: float, deadline: float) -> int:
    command = [
        tool, "-v", "error", "-max_alloc", "67108864",
        *media_analysis._input_options(), "-select_streams", "V:0",
        "-show_entries", "stream=index,width,height,duration", "-of", "json", str(source),
    ]
    raw = _run_tool(command, deadline, MAX_PROBE_BYTES)
    try:
        payload = json.loads(raw)
        video = payload["streams"][0]
        width, height, index = int(video["width"]), int(video["height"]), int(video["index"])
        if not (0 < width <= MAX_SOURCE_SIDE and 0 < height <= MAX_SOURCE_SIDE
                and width * height <= media_analysis.MAX_PIXELS):
            raise PreviewError("resource_limit", "Video dimensions exceed the preview limits.")
        if not 0 <= index < media_analysis.MAX_STREAMS:
            raise PreviewError("invalid_media", "No usable video stream was found.")
        duration = media_analysis._number(video.get("duration"))
        if duration is not None and duration > 0 and requested >= duration:
            raise PreviewError("no_frame", "No video frame is available at the requested time.")
        return index
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, RecursionError, OverflowError):
        raise PreviewError("invalid_media", "No usable video metadata was found.") from None


def _scale_filter() -> str:
    # Shrink (never enlarge) non-square pixels to their display aspect, then
    # fit the actual decoded frame after FFmpeg's automatic display rotation.
    sar = "if(gt(sar,0),sar,1)"
    width, height = f"iw*min(1,{sar})", f"ih/max(1,{sar})"
    factor = f"min(1,{MAX_PREVIEW_SIDE}/max({width},{height}))"
    return (f"scale=w='max(1,trunc({width}*{factor}))':"
            f"h='max(1,trunc({height}*{factor}))':flags=lanczos,setsar=1")


def _jpeg_dimensions(data: bytes) -> tuple[int, int]:
    # Read the encoder's JPEG SOF without running another native image decoder
    # outside the subprocess deadline. Entropy data stays opaque and bounded.
    if not data:
        raise PreviewError("no_frame", "No video frame is available at the requested time.")
    if not data.startswith(b"\xff\xd8") or not data.endswith(b"\xff\xd9"):
        raise PreviewError("invalid_media", "The media tool did not return a complete JPEG.")
    position = 2
    while position + 4 <= len(data):
        if data[position] != 0xFF:
            break
        marker = data[position + 1]
        if marker == 0xFF:
            position += 1
            continue
        if marker in (0xDA, 0xD9):
            break
        length = struct.unpack_from(">H", data, position + 2)[0]
        if length < 2 or position + 2 + length > len(data):
            break
        if marker in (0xC0, 0xC1, 0xC2) and length >= 8:
            depth, height, width, components = struct.unpack_from(">BHHB", data, position + 4)
            if depth != 8 or components != 3:
                break
            if not (0 < width <= MAX_PREVIEW_SIDE and 0 < height <= MAX_PREVIEW_SIDE):
                raise PreviewError("resource_limit", "JPEG dimensions exceed the preview limits.")
            return width, height
        position += 2 + length
    raise PreviewError("invalid_media", "The media tool did not return a usable color JPEG.")


def extract_preview(source_path: Path, time_sec: float) -> dict:
    """Return image_bytes, content_type, width, height, requested_time_sec.

    One invocation at a time, with an 8-second shared deadline including probe
    and extraction. Source: regular local file <= the analysis byte/pixel caps,
    side <= 8192; requested seek: finite 0..MAX_DURATION_SEC (three hours).
    Output: color JPEG <= 4 MiB, longest side <= 1920, never upscaled or cached.
    PreviewError.code is one of invalid_input, invalid_time, unsafe_path,
    resource_limit, io_error, source_changed, missing_dependency, busy, timeout,
    tool_start_failed, tool_io_failed, tool_failed, invalid_media, no_frame.
    """
    deadline = time.monotonic() + PREVIEW_TIMEOUT_SEC
    if isinstance(time_sec, bool) or not isinstance(time_sec, (int, float)):
        raise PreviewError("invalid_time", "A finite numeric seek time is required.")
    try:
        requested = float(time_sec)
    except (ValueError, OverflowError):
        raise PreviewError("invalid_time", "A finite numeric seek time is required.") from None
    if not math.isfinite(requested) or not 0 <= requested <= media_analysis.MAX_DURATION_SEC:
        raise PreviewError("invalid_time", "Seek time must be between zero and three hours.")
    if not _PREVIEW_SLOT.acquire(blocking=False):
        raise PreviewError("busy", "Another frame preview is being extracted.")
    try:
        source = _local_source(source_path)
        signature = _source_signature(source)
        ffmpeg = media_analysis._resolve_tool("ffmpeg")
        ffprobe = media_analysis._resolve_tool("ffprobe")
        index = _probe_video(ffprobe, source, requested, deadline)
        if _source_signature(source) != signature:
            raise PreviewError("source_changed", "The source changed during preview extraction.")
        command = [
            ffmpeg, "-v", "error", "-nostdin", "-nostats", "-xerror",
            "-max_alloc", "67108864", "-filter_threads", "1",
            *media_analysis._input_options(), "-ss", f"{requested:.9f}",
            "-an", "-sn", "-dn", "-i", str(source), "-map", f"0:{index}",
            "-an", "-sn", "-dn", "-map_metadata", "-1", "-map_chapters", "-1",
            "-frames:v", "1", "-vf", _scale_filter(), "-threads", "1",
            "-c:v", "mjpeg", "-q:v", "3", "-pix_fmt", "yuvj420p",
            "-f", "image2pipe", "pipe:1",
        ]
        image_bytes = _run_tool(command, deadline, MAX_JPEG_BYTES)
        width, height = _jpeg_dimensions(image_bytes)
        if _source_signature(source) != signature:
            raise PreviewError("source_changed", "The source changed during preview extraction.")
        _remaining(deadline)
        return {"image_bytes": image_bytes, "content_type": "image/jpeg", "width": width,
                "height": height, "requested_time_sec": requested}
    except media_analysis.MediaAnalysisError as exc:
        raise PreviewError(exc.code, str(exc)) from None
    except (OSError, ValueError):
        raise PreviewError("io_error", "The local preview source is unavailable.") from None
    finally:
        _PREVIEW_SLOT.release()
