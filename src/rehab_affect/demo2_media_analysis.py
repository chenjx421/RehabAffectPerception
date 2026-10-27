"""Local media evidence only; no ASR, identity, affect, or learning inference.

``progress(percent: int, stage: str)`` runs on the caller's thread. Cancellation
raises MediaAnalysisCancelled; other expected failures raise MediaAnalysisError.
Artifacts live in a unique subdirectory of output_dir. All returned artifact
paths are relative to output_dir; the caller must authorize their delivery.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import queue
import re
import shutil
import stat
import subprocess
import tempfile
import threading
import time
import wave
from collections.abc import Callable, Iterator
from contextlib import closing
from fractions import Fraction
from pathlib import Path
from typing import Any

import numpy as np


ANALYSIS_VERSION = "demo2_media_evidence_v1.1"
MAX_DURATION_SEC = 3 * 60 * 60
MAX_INPUT_BYTES = 8 * 1024**3
MAX_OUTPUT_BYTES = 1536 * 1024**2
MAX_RESULT_BYTES = 10 * 1024**2
MAX_DIMENSION = 4096
MAX_PIXELS = 4096 * 2160
MAX_SOURCE_FPS = 120
MAX_STREAMS = 16
MAX_AUDIO_INTERVALS = 100000
MAX_DECODED_FRAMES = MAX_DURATION_SEC * MAX_SOURCE_FPS
# Keep the full-scene evidence bounded, but retain enough pixels for the
# small-face classroom detector.  The detector still runs at its fixed 640
# input size over enlarged local views.
MAX_SAMPLE_SIDE = 768
WINDOW_SEC = 20
SIMPLE_STATE_WINDOW_SEC = 30
MAX_SIMPLE_PERSONS = 3
MAX_FACE_DETECTION_SAMPLES = 120
SIMPLE_ANALYSIS_VERSION = "simple_student_seats_v3_8"
AUDIO_RATE = 16000
ENERGY_THRESHOLD_RMS = 0.01
PROBE_TIMEOUT_SEC = 30.0
PROCESS_TIMEOUT_SEC = 2 * 60 * 60.0
MAX_PROBE_BYTES = 256 * 1024
_FORMATS = "mov,matroska,webm,avi,mpegts,mpeg,ogg,flv"
_SCOPE = "Technical full-scene media evidence; not student or classroom evaluation."


class MediaAnalysisError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class MediaAnalysisCancelled(MediaAnalysisError):
    def __init__(self):
        super().__init__("cancelled", "Media analysis was cancelled.")


def _check_stop(stop_event: threading.Event | None) -> None:
    if stop_event is not None and stop_event.is_set():
        raise MediaAnalysisCancelled()


def _resolve_tool(name: str) -> str:
    configured = os.environ.get(f"REHAB_{name.upper()}", "").strip()
    found = shutil.which(configured or name)
    if not found and configured:
        candidate = Path(configured).expanduser()
        if candidate.is_file() and os.access(candidate, os.X_OK):
            found = str(candidate.resolve())
    if not found and name == "ffprobe" and not configured:
        ffmpeg = os.environ.get("REHAB_FFMPEG", "").strip() or shutil.which("ffmpeg")
        if ffmpeg:
            candidate = Path(ffmpeg).parent / ("ffprobe.exe" if os.name == "nt" else "ffprobe")
            if candidate.is_file() and os.access(candidate, os.X_OK):
                found = str(candidate.resolve())
    if not found and not configured:
        candidate = Path(__file__).resolve().parents[2] / ".tools" / (f"{name}.exe" if os.name == "nt" else name)
        if candidate.is_file() and os.access(candidate, os.X_OK):
            found = str(candidate.resolve())
    if not found and name == "ffmpeg" and not configured:
        try:
            import imageio_ffmpeg

            # Search installed binaries only: never trigger a download.
            binaries = Path(imageio_ffmpeg.__file__).parent / "binaries"
            candidates = sorted(binaries.glob("ffmpeg-*"))
            found = next((str(p.resolve()) for p in candidates if p.is_file() and os.access(p, os.X_OK)
                          and (p.suffix == ".exe" if os.name == "nt" else p.suffix != ".exe")), None)
        except ImportError:
            pass
    if not found:
        raise MediaAnalysisError(
            "missing_dependency", f"Install {name} or set REHAB_{name.upper()} to its executable."
        )
    return found


def _no_links(path: Path) -> None:
    for candidate in (path, *path.parents):
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise MediaAnalysisError("unsafe_path", "Symbolic links and reparse points are not allowed.")


def _local_path(value: Any) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not str(value).strip():
        raise MediaAnalysisError("invalid_input", "A local file path is required.")
    raw = os.fspath(value)
    if not isinstance(raw, str) or "\x00" in raw:
        raise MediaAnalysisError("unsafe_path", "Invalid local path.")
    if raw.startswith(("\\\\", "//")) or (":" in raw and not re.match(r"^[A-Za-z]:[\\/]", raw)):
        raise MediaAnalysisError("unsafe_path", "Remote paths and URL protocols are not allowed.")
    # Reject Windows alternate streams even after a legitimate drive prefix.
    if ":" in raw[2:]:
        raise MediaAnalysisError("unsafe_path", "Alternate data streams are not allowed.")
    path = Path(raw).expanduser().absolute()
    _no_links(path)
    return path


def _input_options() -> list[str]:
    return [
        "-protocol_whitelist", "file", "-format_whitelist", _FORMATS,
        "-probesize", "8000000", "-analyzeduration", "5000000", "-threads", "1",
        "-max_streams", str(MAX_STREAMS), "-max_pixels", str(MAX_PIXELS),
    ]


def _record_diagnostics(line: bytes, counters: dict[str, Any]) -> None:
    """Retain bounded numeric timing evidence, never paths or arbitrary tags."""
    if b"showinfo@evidence_video" in line and b"config in time_base:" in line:
        match = re.search(rb"time_base:\s*(\d+)/(\d+)", line)
        if match and int(match[2]):
            counters["video_time_base"] = int(match[1]) / int(match[2])
    # FFmpeg can interleave another output's header between a showinfo prefix
    # and its numeric record. Parse the complete numeric record, not its prefix.
    if "duration_samples" not in counters and re.search(rb"n:\s*\d+\s+pts:", line):
        match = re.search(rb"n:\s*(\d+)\s+pts:\s*(-?\d+).*?duration:\s*(\d+)", line)
        if match is None or "video_time_base" not in counters:
            counters["timing_error"] = True
            return
        index = int(match[1])
        pts, duration = (int(match[i]) * counters["video_time_base"] for i in (2, 3))
        if index != counters.get("decoded_frames", 0) or not math.isfinite(pts) or not math.isfinite(duration) or duration <= 0:
            counters["timing_error"] = True
            return
        if "first_pts" not in counters:
            counters["first_pts"] = pts
        if pts < counters.get("last_pts", pts) or pts - counters["first_pts"] + duration > MAX_DURATION_SEC:
            counters["timing_error"] = True
        counters.update(decoded_frames=index + 1, last_pts=pts, end_pts=pts + duration)
    elif "duration_samples" in counters and b"nb_samples:" in line:
        match = re.search(rb"\bpts:(-?\d+).*?rate:(\d+).*?nb_samples:(\d+)", line)
        if match is None:
            counters["timing_error"] = True
            return
        first, rate, samples = int(match[1]), int(match[2]), int(match[3])
        if rate != AUDIO_RATE or samples <= 0:
            counters["timing_error"] = True
            return
        # Audio diagnostics are emitted before async resampling / padding.
        end = first + samples
        if first < counters.get("last_audio_start", first):
            counters["timing_error"] = True
        counters["last_audio_start"] = first
        counters["decoded_audio_frames"] = counters.get("decoded_audio_frames", 0) + 1
        duration_samples = counters["duration_samples"]
        first, end = max(0, first), min(duration_samples, end)
        if end <= first:
            return
        intervals = counters.setdefault("audio_intervals", [])
        # asettb provides exact 1/16000 integer ticks, including long recordings.
        if intervals and first <= intervals[-1][1] + 1:
            intervals[-1][1] = max(intervals[-1][1], end)
        elif len(intervals) >= MAX_AUDIO_INTERVALS:
            counters["interval_limit"] = True
        else:
            intervals.append([first, end])


def _pipe_chunks(
    command: list[str], *, stage: str, stop_event: threading.Event | None,
    timeout: float, chunk_size: int, max_bytes: int, counters: dict[str, Any] | None = None,
) -> Iterator[bytes]:
    _check_stop(stop_event)
    try:
        process = subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except OSError:
        raise MediaAnalysisError("tool_start_failed", f"Could not start the media tool for {stage}.") from None
    messages: queue.Queue[bytes | BaseException | None] = queue.Queue(maxsize=2)
    closing = threading.Event()

    def send(item: bytes | BaseException | None) -> None:
        while not closing.is_set():
            try:
                messages.put(item, timeout=0.1)
                return
            except queue.Full:
                pass

    def read_stdout() -> None:
        try:
            assert process.stdout is not None
            while not closing.is_set():
                block = process.stdout.read(chunk_size)
                if not block:
                    break
                send(block)
        except (OSError, ValueError) as exc:
            send(exc)
        finally:
            send(None)

    def drain_stderr() -> None:
        # Never retain tool diagnostics containing paths or arbitrary media tags.
        try:
            assert process.stderr is not None
            while line := process.stderr.readline(4096):
                if counters is not None:
                    _record_diagnostics(line, counters)
        except (OSError, ValueError):
            pass

    readers = [threading.Thread(target=read_stdout, daemon=True), threading.Thread(target=drain_stderr, daemon=True)]
    deadline = time.monotonic() + timeout
    for reader in readers:
        reader.start()
    received = 0

    def check() -> None:
        _check_stop(stop_event)
        if time.monotonic() >= deadline:
            raise MediaAnalysisError("timeout", f"Media processing timed out during {stage}.")
        if counters is not None and counters.get("decoded_frames", 0) > MAX_DECODED_FRAMES:
            raise MediaAnalysisError("resource_limit", "Decoded frame count exceeds the supported limit.")
        if counters is not None and counters.get("interval_limit"):
            raise MediaAnalysisError("resource_limit", "Audio timing exceeds the interval limit.")
        if counters is not None and counters.get("timing_error"):
            raise MediaAnalysisError("unsupported_timestamps", "Media has missing, excessive or nonmonotonic decoded timestamps.")

    try:
        while True:
            check()
            try:
                block = messages.get(timeout=0.1)
            except queue.Empty:
                continue
            if block is None:
                break
            if isinstance(block, BaseException):
                raise MediaAnalysisError("tool_io_failed", f"Media pipe failed during {stage}.")
            received += len(block)
            if received > max_bytes:
                raise MediaAnalysisError("resource_limit", f"Media output exceeds the limit during {stage}.")
            yield block
        while process.poll() is None:
            check()
            time.sleep(0.05)
        check()
        readers[1].join(timeout=5)
        check()
        if process.returncode:
            raise MediaAnalysisError("tool_failed", f"Media processing failed during {stage} (exit {process.returncode}).")
    finally:
        closing.set()
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        for reader in readers:
            reader.join(timeout=5)
        if process.stdout:
            process.stdout.close()
        if process.stderr:
            process.stderr.close()


def _number(value: Any, default: float | None = None) -> float | None:
    try:
        result = float(Fraction(str(value)))
        return result if math.isfinite(result) else default
    except (ValueError, ZeroDivisionError, OverflowError):
        return default


def _packet_duration(tool: str, source: Path, start: float, fps: float, stop_event) -> float:
    """Bounded streaming timestamp scan for browser WebM without a duration header."""
    command = [tool, '-v', 'error', '-max_alloc', '67108864', *_input_options(),
               '-select_streams', 'v:0', '-show_entries', 'packet=pts_time,duration_time',
               '-of', 'csv=p=0', str(source)]
    pending = b''
    end = start
    count = 0
    def consume(line):
        nonlocal end, count
        if not line.strip():
            return
        fields=line.decode('ascii', errors='replace').strip().split(',')
        pts=_number(fields[0])
        duration=_number(fields[1]) if len(fields)>1 else None
        if pts is None:
            raise MediaAnalysisError('unsupported_timestamps', 'Recording packet has no valid timestamp.')
        end=max(end,pts+(duration if duration and duration>0 else 1/fps))
        count+=1
        if end-start>MAX_DURATION_SEC or count>MAX_DURATION_SEC*MAX_SOURCE_FPS+1:
            raise MediaAnalysisError('resource_limit', 'Recording exceeds the duration or packet limit.')
    chunks=_pipe_chunks(command,stage='probe',stop_event=stop_event,timeout=120,
                        chunk_size=16384,max_bytes=128*1024*1024)
    try:
        for block in chunks:
            pending+=block
            lines=pending.split(b'\n');pending=lines.pop()
            if len(pending)>4096:
                raise MediaAnalysisError('invalid_media','Recording packet metadata is malformed.')
            for line in lines:consume(line)
        if pending:consume(pending)
    finally:
        chunks.close()
    return end-start if count else 0.0


def _probe_media(tool: str, source: Path, stop_event: threading.Event | None) -> dict[str, Any]:
    entries = (
        "format=format_name,duration,start_time:"
        "stream=index,codec_type,width,height,avg_frame_rate,r_frame_rate,duration,start_time,channels,sample_rate:"
        "stream_disposition=attached_pic:stream_tags=rotate:stream_side_data=rotation"
    )
    command = [tool, "-v", "error", "-max_alloc", "67108864", *_input_options(),
               "-show_entries", entries, "-of", "json", str(source)]
    raw = b"".join(_pipe_chunks(command, stage="probe", stop_event=stop_event,
                              timeout=PROBE_TIMEOUT_SEC, chunk_size=16384, max_bytes=MAX_PROBE_BYTES))
    try:
        payload = json.loads(raw)
        streams = payload["streams"]
        video = next(s for s in streams if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic"))
        audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
        width, height = int(video["width"]), int(video["height"])
        start = _number(video.get("start_time"), _number(payload.get("format", {}).get("start_time"), 0.0))
        duration = _number(video.get("duration"))
        duration_basis = "video_stream" if duration is not None else "container_upper_bound"
        if duration is None:
            fmt = payload.get("format", {})
            duration = (_number(fmt.get("duration"), 0.0) or 0.0) + (_number(fmt.get("start_time"), start) or 0.0) - start
        fps = _number(video.get("avg_frame_rate")) or _number(video.get("r_frame_rate"))
        # MediaRecorder WebM omits a finalized Duration element. Derive it from
        # actual video packet timestamps; never trust a client-submitted length.
        if duration <= 0 and 'webm' in payload.get('format', {}).get('format_name','') and fps and 0 < fps <= MAX_SOURCE_FPS:
            duration = _packet_duration(tool, source, start, fps, stop_event)
            duration_basis = 'video_packets'
        rotation = _number(video.get("tags", {}).get("rotate"), 0.0)
        for side_data in video.get("side_data_list", []):
            if "rotation" in side_data:
                rotation = _number(side_data["rotation"], 0.0)
        normalized_rotation = round(rotation / 90) * 90
        if abs(rotation - normalized_rotation) > 0.1:
            raise MediaAnalysisError("unsupported_rotation", "Only right-angle display rotation is supported.")
        if not 0 < duration <= MAX_DURATION_SEC:
            raise MediaAnalysisError("resource_limit", "Video duration must be positive and at most three hours.")
        if not (0 < width <= MAX_DIMENSION and 0 < height <= MAX_DIMENSION and width * height <= MAX_PIXELS):
            raise MediaAnalysisError("resource_limit", "Video dimensions exceed the supported limit.")
        if fps is None or not 0 < fps <= MAX_SOURCE_FPS:
            raise MediaAnalysisError("resource_limit", "Video frame rate is missing or exceeds the supported limit.")
        if audio and (int(audio.get("channels", 0)) > 8 or int(audio.get("sample_rate", 0)) > 192000):
            raise MediaAnalysisError("resource_limit", "Audio stream exceeds the supported limit.")
        if normalized_rotation % 180:
            width, height = height, width
        return {
            "duration_sec": duration, "width": width, "height": height, "fps": fps,
            "has_audio": audio is not None, "source_start_sec": start,
            "rotation_degrees": normalized_rotation % 360, "video_index": int(video["index"]),
            "audio_index": int(audio["index"]) if audio else None,
            "audio_start_offset_sec": (_number(audio.get("start_time"), start) - start) if audio else None,
            "duration_basis": duration_basis,
        }
    except (KeyError, TypeError, ValueError, StopIteration, AttributeError):
        raise MediaAnalysisError("invalid_media", "No usable video metadata was found.") from None


def process_video_task(
    task: dict, output_dir: Path,
    progress: Callable[[int, str], None] | None = None,
    stop_event: threading.Event | None = None,
) -> dict:
    """Decode the complete video to a bounded 1 fps evidence stream.

    Duration <= 3h, file <= 8 GiB, dimensions <= 4096 and <= 4096x2160
    pixels, fps <= 120. The 1 fps timeline is normalized to video start PTS;
    samples are FFmpeg resampling grid times, not original frame timestamps.
    Technical metrics use the complete scene; segments are temporal records,
    not separately encoded video clips. Decoded frame-end timing is required
    (verified with bundled FFmpeg 7.1).
    Caller-owned output_dir must be private and not shared between tenants.
    """
    last_progress = -1

    def emit(percent: int, stage: str) -> None:
        nonlocal last_progress
        _check_stop(stop_event)
        percent = max(last_progress, min(100, percent))
        if progress is not None:
            progress(percent, stage)
        last_progress = percent
        _check_stop(stop_event)

    emit(0, "validating")
    if not isinstance(task, dict) or not isinstance(task.get("task_id"), str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", task["task_id"]):
        raise MediaAnalysisError("invalid_task", "task_id must be a bounded identifier.")
    source = _local_path(task.get("file_path"))
    root = _local_path(output_dir)

    def source_signature() -> tuple[int, int, int]:
        _no_links(source)
        info = source.stat()
        return info.st_size, info.st_mtime_ns, info.st_ino

    def check_source() -> None:
        if source_signature() != original_signature:
            raise MediaAnalysisError("source_changed", "The source changed during media processing.")

    try:
        if not source.is_file():
            raise MediaAnalysisError("invalid_input", "The source must be a regular local file.")
        original_signature = source_signature()
        size = original_signature[0]
        if not 0 < size <= MAX_INPUT_BYTES:
            raise MediaAnalysisError("resource_limit", "The source is empty or exceeds the file-size limit.")
        ffmpeg, ffprobe = _resolve_tool("ffmpeg"), _resolve_tool("ffprobe")
        try:
            import cv2
        except ImportError:
            raise MediaAnalysisError("missing_dependency", "OpenCV is required for image metrics.") from None
        digest = hashlib.sha256()
        read_bytes = 0
        with source.open("rb") as handle:
            while block := handle.read(1024 * 1024):
                read_bytes += len(block)
                if read_bytes > MAX_INPUT_BYTES:
                    raise MediaAnalysisError("resource_limit", "The source grew beyond its size limit.")
                digest.update(block)
                emit(min(8, int(read_bytes / size * 8)), "hashing")
        supplied_hash = task.get("sha256")
        if supplied_hash and (not isinstance(supplied_hash, str) or supplied_hash.lower() != digest.hexdigest()):
            raise MediaAnalysisError("hash_mismatch", "The source checksum does not match the registered file.")
        check_source()
        emit(9, "probing")
        meta = _probe_media(ffprobe, source, stop_event)
        config = task.get("processing_config", {})
        if not isinstance(config, dict):
            raise MediaAnalysisError("invalid_task", "Processing configuration must be an object.")
        upload_limit = config.get("upload_max_duration_sec", MAX_DURATION_SEC)
        if (isinstance(upload_limit, bool) or not isinstance(upload_limit, (int, float))
                or not math.isfinite(upload_limit) or upload_limit <= 0):
            raise MediaAnalysisError("invalid_task", "Upload duration limit must be a positive finite number.")
        upload_limit = min(upload_limit, MAX_DURATION_SEC)
        if meta["duration_sec"] > upload_limit:
            raise MediaAnalysisError("resource_limit", "Video exceeds this task's upload duration limit; shorten it and upload again.")
        _no_links(root)
        root.mkdir(parents=True, exist_ok=True)
        root = root.resolve(strict=True)
        run = Path(tempfile.mkdtemp(prefix="media_", dir=root))
    except OSError:
        raise MediaAnalysisError("io_error", "Could not access the local source or output directory.") from None

    written = 0

    def reserve(count: int) -> None:
        nonlocal written
        written += count
        if written > MAX_OUTPUT_BYTES:
            raise MediaAnalysisError("resource_limit", "Generated artifacts exceed the disk budget.")

    def relative(path: Path) -> str:
        return path.relative_to(root).as_posix()

    completed = False
    try:
        duration = meta["duration_sec"]
        segments: list[dict[str, Any]] = []
        for i in range(math.ceil(MAX_DURATION_SEC / WINDOW_SEC)):
            segments.append({
                "segment_id": f"segment_{i:04d}", "start_sec": i * WINDOW_SEC,
                "end_sec": min((i + 1) * WINDOW_SEC, duration),
                "visual": {"scope": "full_scene_technical_metrics", "samples": []},
                "audio": {"available": False, "rms": None, "energy_activity_ratio": None,
                          "reason": "no_audio_stream" if not meta["has_audio"] else "not_processed"},
                "review_status": "unreviewed",
            })
        scale = min(1.0, MAX_SAMPLE_SIDE / max(meta["width"], meta["height"]))
        sample_width, sample_height = max(1, round(meta["width"] * scale)), max(1, round(meta["height"] * scale))
        frame_bytes = sample_width * sample_height * 3
        frames_dir = run / "frames"
        frames_dir.mkdir()
        filters = f"setpts=PTS-STARTPTS,fps=1:start_time=0:round=near:eof_action=pass,scale={sample_width}:{sample_height},format=rgb24"
        command = [ffmpeg, "-v", "info", "-nostdin", "-nostats", "-xerror", "-max_alloc", "67108864",
                   "-copyts",
                   "-filter_threads", "1", *_input_options(), "-i", str(source),
                   "-map", f"0:{meta['video_index']}", "-an", "-sn", "-dn", "-threads", "1",
                   "-map_metadata", "-1", "-map_chapters", "-1",
                   "-vf", "showinfo@evidence_video=checksum=0",
                   "-c:v", "wrapped_avframe", "-fps_mode", "passthrough", "-f", "null", "pipe:2",
                   "-map", f"0:{meta['video_index']}", "-an", "-sn", "-dn", "-vf", filters,
                   "-map_metadata", "-1", "-map_chapters", "-1",
                   "-threads", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]
        # The null output records full-rate timing; only the sampled output
        # emits pixels. Numeric stderr diagnostics are discarded after parsing.
        counters: dict[str, Any] = {}
        previous = None
        count = 0
        emit(10, "sampling_video")
        with closing(_pipe_chunks(command, stage="video", stop_event=stop_event,
                                   timeout=PROCESS_TIMEOUT_SEC, chunk_size=frame_bytes,
                                   max_bytes=(MAX_DURATION_SEC + 1) * frame_bytes,
                                   counters=counters)) as chunks:
            for block in chunks:
                if len(block) != frame_bytes:
                    raise MediaAnalysisError("invalid_media", "The decoded video ended in an incomplete frame.")
                if count >= MAX_DURATION_SEC:
                    raise MediaAnalysisError("resource_limit", "Decoded video exceeds the duration limit.")
                rgb = np.frombuffer(block, dtype=np.uint8).reshape(sample_height, sample_width, 3)
                gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
                brightness = float(gray.mean())
                sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
                motion = float(cv2.absdiff(gray, previous).mean() / 255) if previous is not None else None
                previous = gray.copy()
                bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
                ok, encoded = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 80])
                if not ok:
                    raise MediaAnalysisError("image_write_failed", "Could not encode an evidence image.")
                reserve(encoded.nbytes)
                frame_path = frames_dir / f"frame_{count:06d}.jpg"
                with frame_path.open("xb") as handle:
                    handle.write(encoded.tobytes())
                segments[count // WINDOW_SEC]["visual"]["samples"].append({
                    "timestamp_sec": count, "brightness": round(brightness, 4),
                    "sharpness": round(sharpness, 4), "scene_motion": round(motion, 6) if motion is not None else None,
                    "image_path": relative(frame_path),
                })
                count += 1
                emit(10 + min(60, int(count / duration * 60)), "sampling_video")
        decoded_frames = counters.get("decoded_frames", 0)
        if decoded_frames <= 0 or not count:
            raise MediaAnalysisError("invalid_media", "The decoder did not report complete video timing.")
        decoded_duration = counters["end_pts"] - counters["first_pts"]
        # Stream duration can expose truncation. Container duration may instead
        # belong to a longer audio track, so it is only a preflight upper bound.
        if meta["duration_basis"] == "video_stream" and abs(decoded_duration - duration) > max(0.1, 2 / meta["fps"]):
            raise MediaAnalysisError("invalid_media", "Decoded video disagrees with the declared video stream duration.")
        duration = round(decoded_duration, 9)
        if not 0 < duration <= MAX_DURATION_SEC or not math.floor(duration) <= count <= math.ceil(duration):
            raise MediaAnalysisError("invalid_media", "Decoded video does not cover the sampling timeline.")
        if duration > upload_limit:
            raise MediaAnalysisError("resource_limit", "Decoded video exceeds this task's upload duration limit; shorten it and upload again.")
        if meta["has_audio"]:
            meta["audio_start_offset_sec"] += meta["source_start_sec"] - counters["first_pts"]
        meta.update(duration_sec=duration, source_start_sec=counters["first_pts"],
                    duration_basis="decoded_video_frame_end")
        segments = segments[:math.ceil(duration / WINDOW_SEC)]
        for segment in segments:
            segment["end_sec"] = min(segment["start_sec"] + WINDOW_SEC, duration)
        for segment in segments:
            visual = segment["visual"]
            samples = visual["samples"]
            visual["sampled_frames"] = len(samples)
            for key in ("brightness", "sharpness", "scene_motion"):
                values = [s[key] for s in samples if s[key] is not None]
                visual[f"mean_{'motion' if key == 'scene_motion' else key}"] = round(sum(values) / len(values), 6) if values else None
            visual["measurement_status"] = "measured" if samples else "unknown"
        audio_path = None
        if meta["has_audio"]:
            emit(71, "extracting_audio")
            audio_path = run / "audio.wav"
            _audio_evidence(ffmpeg, source, meta, segments, audio_path, reserve, emit, stop_event)
        else:
            emit(95, "audio_absent")
        emit(96, "detecting_people")
        simple_analysis = _build_simple_student_analysis(segments, run, meta, stop_event=stop_event)
        meta["audio_status"] = "extracted" if audio_path else "absent"
        result = {
            "task_id": task["task_id"], "analysis_version": ANALYSIS_VERSION,
            "analysis_status": "evidence_ready", "analysis_scope": _SCOPE,
            "source_sha256": digest.hexdigest(),
            "provenance": {"probe": "ffprobe_json", "video": "ffmpeg_full_decode_and_fps_filter",
                           "image_metrics": "opencv", "audio": "ffmpeg_pcm_and_numpy_energy",
                           "network_used": False, "models_downloaded": False},
            "media": {k: v for k, v in meta.items() if k not in {"video_index", "audio_index"}},
            "sampling": {"fps": 1, "window_sec": WINDOW_SEC, "width": sample_width, "height": sample_height,
                         "pixel_format": "rgb24 evidence frames; grayscale metrics only",
                         "timestamp_basis": "FFmpeg setpts=PTS-STARTPTS, then fixed 1 fps grid; not original frame PTS",
                         "brightness_unit": "gray_0_255", "sharpness_unit": "laplacian_variance_on_resized_gray",
                         "scene_motion_unit": "mean_absolute_gray_difference_divided_by_255"},
            "segments": segments,
            "summary": {"segment_count": len(segments), "decoded_frames": decoded_frames,
                        "sampled_frames": count, "reviewed_segments": 0,
                        "unknown_fields": ["student_identity", "speaker_identity", "emotion", "learning_mastery"],
                        "transcription_performed": False},
            "artifacts": {"audio": relative(audio_path) if audio_path else None,
                          "frames": relative(frames_dir), "result": relative(run / "analysis.json")},
            "simple_student_analysis": simple_analysis,
            "limitations": [
                _SCOPE,
                "Frames are sampled from the full scene at 1 fps; brief events can be missed or frames duplicated.",
                "Image metrics depend on scaling, lighting, camera motion and occlusion; no quality score grades a class.",
                "Anonymous person activity uses independent fixed-seat ROI pixels, not shared audio; it is not identity recognition, emotion recognition, diagnosis or a validated educational score.",
                "Rotation is applied by FFmpeg; grid time zero is the first decoded video PTS.",
                "Audio uses the decoded video start time; coverage excludes padding and RMS uses covered samples only.",
                "Energy activity is only a fixed RMS threshold, not speech VAD, ASR or speaker identification.",
                "Course and subject metadata are not identity evidence; every segment requires teacher review.",
            ],
        }
        emit(98, "writing_result")
        check_source()
        encoded_result = json.dumps(result, ensure_ascii=True, allow_nan=False, indent=2).encode("utf-8")
        if len(encoded_result) > MAX_RESULT_BYTES:
            raise MediaAnalysisError("resource_limit", "The evidence index exceeds the result-size limit.")
        reserve(len(encoded_result))
        with (run / "analysis.json").open("xb") as handle:
            handle.write(encoded_result)
        emit(100, "evidence_ready")
        completed = True
        return result
    except OSError:
        raise MediaAnalysisError("io_error", "Could not read or write the local media artifacts.") from None
    finally:
        # Only remove the unique directory created by this invocation, never caller data.
        if not completed and run.is_dir() and not run.is_symlink() and run.resolve().parent == root:
            shutil.rmtree(run)


def _build_simple_student_analysis(
    segments: list[dict[str, Any]], run: Path, meta: dict[str, Any],
    *, max_detection_samples: int | None = None,
    stop_event: threading.Event | None = None,
) -> dict[str, Any]:
    try:
        from .demo2_student_tracking import build_analysis
    except ImportError:
        # Keep the media evidence smoke path usable when only this module is
        # staged. The full application ships the tracker and uses it below.
        try:
            from rehab_affect.demo2_student_tracking import build_analysis
        except ImportError:
            return {
                "available": False,
                "analysis_version": SIMPLE_ANALYSIS_VERSION,
                "reason": "student_tracking_unavailable",
                "persons": [],
                "window_sec": SIMPLE_STATE_WINDOW_SEC,
                "message": "视频证据已生成，但学生状态分析模块未加载。",
            }
    return build_analysis(segments, run, meta, stop_event=stop_event)


def _audio_evidence(
    ffmpeg: str, source: Path, meta: dict[str, Any], segments: list[dict[str, Any]],
    path: Path, reserve: Callable[[int], None], emit: Callable[[int, str], None],
    stop_event: threading.Event | None,
) -> None:
    duration = meta["duration_sec"]
    filters = (f"asetpts=PTS-({meta['source_start_sec']})/TB,"
               f"aformat=sample_rates={AUDIO_RATE}:channel_layouts=mono,asettb=1/{AUDIO_RATE},"
               f"ashowinfo@evidence_audio,aresample={AUDIO_RATE}:async=1:first_pts=0:"
               f"min_comp=0:min_hard_comp={1 / AUDIO_RATE},"
               f"apad=whole_dur={duration}")
    command = [ffmpeg, "-v", "info", "-nostdin", "-nostats", "-xerror", "-max_alloc", "67108864",
               "-filter_threads", "1", "-copyts", *_input_options(), "-i", str(source),
               "-map", f"0:{meta['audio_index']}", "-vn", "-sn", "-dn", "-af", filters,
               "-map_metadata", "-1", "-map_chapters", "-1",
               "-t", str(duration), "-ac", "1", "-ar", str(AUDIO_RATE), "-threads", "1",
               "-f", "s16le", "-c:a", "pcm_s16le", "pipe:1"]
    position = 0
    expected_samples = round(duration * AUDIO_RATE)
    counters: dict[str, Any] = {"duration_samples": expected_samples}
    reserve(44)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(AUDIO_RATE)
        with closing(_pipe_chunks(command, stage="audio", stop_event=stop_event,
                                   timeout=PROCESS_TIMEOUT_SEC, chunk_size=640,
                                   max_bytes=(expected_samples + AUDIO_RATE) * 2,
                                   counters=counters)) as chunks:
            for block in chunks:
                if len(block) % 2:
                    raise MediaAnalysisError("invalid_media", "Decoded audio has an incomplete sample.")
                n = len(block) // 2
                if position + n > expected_samples + 1:
                    raise MediaAnalysisError("invalid_media", "Decoded audio exceeds the video timeline.")
                reserve(len(block))
                wav.writeframesraw(block)
                position += n
                if position % AUDIO_RATE < n:
                    emit(71 + min(21, int(position / AUDIO_RATE / duration * 21)), "extracting_audio")
    if not position or abs(position - expected_samples) > 1 or not counters.get("decoded_audio_frames"):
        raise MediaAnalysisError("invalid_media", "Decoded audio did not produce a complete aligned timeline.")

    # Diagnostics may arrive on a different pipe from PCM. Wait until decoding
    # completes, then stream the bounded WAV to exclude padded samples exactly.
    intervals = counters.get("audio_intervals", [])
    stats = [{"samples": 0, "covered": 0, "squares": 0.0, "active_samples": 0,
              "coverage_intervals": []} for _ in segments]
    for start, end in intervals:
        for index in range(start // (WINDOW_SEC * AUDIO_RATE), (end - 1) // (WINDOW_SEC * AUDIO_RATE) + 1):
            a = max(start, index * WINDOW_SEC * AUDIO_RATE)
            b = min(end, (index + 1) * WINDOW_SEC * AUDIO_RATE)
            stats[index]["coverage_intervals"].append({"start_sec": a / AUDIO_RATE, "end_sec": b / AUDIO_RATE})
    interval_index = 0
    position = 0
    emit(93, "measuring_audio")
    with wave.open(str(path), "rb") as wav:
        while block := wav.readframes(320):
            _check_stop(stop_event)
            values = np.frombuffer(block, dtype="<i2").astype(np.float64) / 32768.0
            row = stats[position // (WINDOW_SEC * AUDIO_RATE)]
            row["samples"] += len(values)
            covered = np.zeros(len(values), dtype=bool)
            end = position + len(values)
            while interval_index < len(intervals) and intervals[interval_index][1] <= position:
                interval_index += 1
            current = interval_index
            while current < len(intervals) and intervals[current][0] < end:
                a, b = intervals[current]
                covered[max(0, a - position):min(len(values), b - position)] = True
                current += 1
            values = values[covered]
            if len(values):
                squares = float(np.dot(values, values))
                row["covered"] += len(values)
                row["squares"] += squares
                if math.sqrt(squares / len(values)) >= ENERGY_THRESHOLD_RMS:
                    row["active_samples"] += len(values)
            position = end
    for segment, row in zip(segments, stats):
        n = row["samples"]
        covered = row["covered"]
        segment["audio"] = {
            "available": bool(covered), "rms": round(math.sqrt(row["squares"] / covered), 6) if covered else None,
            "energy_activity_ratio": round(row["active_samples"] / covered, 6) if covered else None,
            "sample_count": n, "sample_rate": AUDIO_RATE, "channels": 1,
            "observed_sample_count": covered, "padded_sample_count": n - covered,
            "coverage_ratio": round(covered / n, 6) if n else 0.0,
            "coverage_intervals": row["coverage_intervals"],
            "method": "20ms_rms_threshold_not_speech_vad", "energy_threshold_rms": ENERGY_THRESHOLD_RMS,
            "timeline": "video_relative_with_silence_padding",
            "reason": None if covered == n else "partial_audio_coverage" if covered else "no_audio_coverage",
        }
    emit(95, "audio_measured")
