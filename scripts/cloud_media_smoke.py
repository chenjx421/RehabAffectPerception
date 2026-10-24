"""Offline synthetic decoding check, not a student-scoring accuracy test."""

from __future__ import annotations

import argparse
from contextlib import contextmanager, redirect_stderr, redirect_stdout
import hashlib
import hmac
import importlib
import json
import logging
import math
import os
from pathlib import Path, PurePosixPath
import struct
import subprocess
import sys
import tempfile
from threading import Event, Timer
import wave


SCOPE = "synthetic_media_decode_only_not_scoring_accuracy"
ERROR_CODES = frozenset({
    "invalid_arguments", "invalid_tool_path", "missing_dependency", "tool_start_failed",
    "generation_failed", "timeout", "smoke_failed", "verification_failed", "io_error",
    "invalid_media", "invalid_input", "invalid_task", "unsafe_path", "resource_limit",
    "hash_mismatch", "source_changed", "unsupported_timestamps", "unsupported_rotation",
    "tool_failed", "tool_io_failed", "image_write_failed", "cancelled",
})


class SmokeError(Exception):
    def __init__(self, code: str):
        self.code = code


def _error_code(error: Exception) -> str:
    code = getattr(error, "code", None)
    if isinstance(code, str) and code in ERROR_CODES:
        return code
    if isinstance(error, ImportError):
        return "missing_dependency"
    if isinstance(error, OSError):
        return "io_error"
    return "smoke_failed"


@contextmanager
def _quiet():
    # Suppress Python logging and native-library diagnostics, including paths.
    saved_fds = []
    previous_logging = logging.root.manager.disable
    with open(os.devnull, "w") as sink:
        try:
            descriptors = {1, 2}
            for stream in (sys.stdout, sys.stderr):
                try:
                    stream.flush()
                    descriptors.add(stream.fileno())
                except (OSError, ValueError, AttributeError):
                    pass
            for fd in sorted(descriptors):
                try:
                    saved = os.dup(fd)
                except OSError:
                    continue
                saved_fds.append((fd, saved))
                os.dup2(sink.fileno(), fd)
            logging.disable(sys.maxsize)
            with redirect_stdout(sink), redirect_stderr(sink):
                yield
        finally:
            logging.disable(previous_logging)
            for fd, saved in reversed(saved_fds):
                try:
                    os.dup2(saved, fd)
                finally:
                    os.close(saved)


def _load_media():
    source_root = str(Path(__file__).resolve().parents[1] / "src")
    if source_root not in sys.path:
        sys.path.insert(0, source_root)
    return importlib.import_module("rehab_affect.demo2_media_analysis")


@contextmanager
def _tools(media, ffmpeg: str | None, ffprobe: str | None):
    previous = {key: os.environ.get(key) for key in ("REHAB_FFMPEG", "REHAB_FFPROBE", "FFREPORT")}
    try:
        os.environ.pop("FFREPORT", None)
        resolved = {}
        for name, supplied in (("ffmpeg", ffmpeg), ("ffprobe", ffprobe)):
            if supplied is not None:
                candidate = Path(supplied)
                if not candidate.is_absolute():
                    raise SmokeError("invalid_tool_path")
            else:
                candidate = Path(media._resolve_tool(name))
            if not candidate.is_file() or not os.access(candidate, os.X_OK):
                raise SmokeError("missing_dependency")
            resolved[name] = str(candidate.resolve(strict=True))
            os.environ[f"REHAB_{name.upper()}"] = resolved[name]
        yield resolved
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _generate(ffmpeg: str, source: Path, *, audio: bool) -> None:
    command = [ffmpeg, "-v", "error", "-nostdin", "-n", "-f", "lavfi", "-i",
               "testsrc2=size=160x96:rate=10:duration=2"]
    if audio:
        command += ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000:duration=2"]
    command += ["-map", "0:v:0", "-c:v", "mpeg4", "-q:v", "2", "-threads", "1"]
    command += (["-map", "1:a:0", "-c:a", "aac", "-ac", "1", "-ar", "16000"] if audio else ["-an"])
    command += [str(source)]
    try:
        result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=30, check=False, shell=False)
    except subprocess.TimeoutExpired:
        raise SmokeError("timeout") from None
    except OSError:
        raise SmokeError("tool_start_failed") from None
    if result.returncode != 0:
        raise SmokeError("generation_failed")


def _require(condition: bool) -> None:
    if not condition:
        raise SmokeError("verification_failed")


def _artifact(root: Path, relative: str) -> Path:
    _require(isinstance(relative, str) and bool(relative) and "\\" not in relative and ":" not in relative)
    parts = PurePosixPath(relative)
    _require(not parts.is_absolute() and ".." not in parts.parts)
    path = root.joinpath(*parts.parts).resolve(strict=True)
    _require(root.resolve() in path.parents and path.is_file())
    return path


def _verify(result: dict, output: Path, digest: str, *, audio: bool) -> dict:
    import cv2
    import numpy as np

    metadata, summary = result["media"], result["summary"]
    _require(result["analysis_status"] == "evidence_ready")
    _require(isinstance(result["source_sha256"], str) and hmac.compare_digest(result["source_sha256"], digest))
    duration = metadata["duration_sec"]
    _require(type(duration) in (int, float) and math.isfinite(duration) and abs(duration - 2) <= 0.1)
    _require(metadata["duration_basis"] == "decoded_video_frame_end")
    _require((metadata["width"], metadata["height"]) == (160, 96) and abs(metadata["fps"] - 10) < 0.01)
    _require(summary["decoded_frames"] == 20 and summary["sampled_frames"] == 2)
    _require(metadata["has_audio"] is audio and metadata["audio_status"] == ("extracted" if audio else "absent"))
    _require(result["provenance"]["network_used"] is False and result["provenance"]["models_downloaded"] is False)
    samples = [sample for segment in result["segments"] for sample in segment["visual"]["samples"]]
    _require(len(samples) == 2)
    for sample in samples:
        pixels = _artifact(output, sample["image_path"]).read_bytes()
        frame = cv2.imdecode(np.frombuffer(pixels, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
        _require(frame is not None and frame.shape == (96, 160))
    audio_seconds = None
    if audio:
        with wave.open(str(_artifact(output, result["artifacts"]["audio"])), "rb") as handle:
            _require((handle.getnchannels(), handle.getsampwidth(), handle.getframerate()) == (1, 2, 16000))
            count = handle.getnframes()
            _require(abs(count - 32000) <= 1)
            pcm = handle.readframes(count)
            _require(len(pcm) == count * 2)
            rms = math.sqrt(sum(value[0] ** 2 for value in struct.iter_unpack("<h", pcm)) / count) / 32768
            _require(rms > 0.01)
            audio_seconds = count / 16000
        _require(all(segment["audio"]["available"] is True for segment in result["segments"]))
    else:
        _require(result["artifacts"]["audio"] is None)
        _require(all(segment["audio"]["available"] is False for segment in result["segments"]))
    return {"duration_sec": float(duration), "width": 160, "height": 96, "fps": 10,
            "decoded_frames": 20, "sampled_frames": 2, "frame_artifacts_verified": True,
            "has_audio": audio, "audio_duration_sec": audio_seconds, "source_hash_verified": True}


def _case(media, ffmpeg: str, root: Path, *, audio: bool) -> dict:
    name = "with_audio" if audio else "without_audio"
    report = {"case": name, "ok": False}
    try:
        source, output = root / (name + ".mp4"), root / name
        _generate(ffmpeg, source, audio=audio)
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        task = {"task_id": "cloud_smoke_" + name, "file_path": str(source), "sha256": digest,
                "processing_config": {"upload_max_duration_sec": 3600}}
        stop = Event()
        timer = Timer(60, stop.set)
        timer.daemon = True
        timer.start()
        try:
            result = media.process_video_task(task, output, stop_event=stop)
        except Exception:
            if stop.is_set():
                raise SmokeError("timeout") from None
            raise
        finally:
            timer.cancel()
            timer.join()
        if stop.is_set():
            raise SmokeError("timeout")
        report.update(_verify(result, output, digest, audio=audio), ok=True)
    except Exception as error:
        report["error_code"] = _error_code(error)
    return report


def run_smoke(*, ffmpeg: str | None = None, ffprobe: str | None = None) -> dict:
    report = {"ok": False, "scope": SCOPE, "cases": []}
    try:
        with _quiet():
            media = _load_media()
            with _tools(media, ffmpeg, ffprobe) as tools:
                # Only TemporaryDirectory's newly allocated child is ever removed.
                parent = Path(tempfile.gettempdir()).resolve(strict=True)
                with tempfile.TemporaryDirectory(prefix="rehab-cloud-smoke-", dir=parent) as directory:
                    for audio in (True, False):
                        report["cases"].append(_case(media, tools["ffmpeg"], Path(directory), audio=audio))
        report["ok"] = all(case["ok"] for case in report["cases"]) and len(report["cases"]) == 2
    except KeyboardInterrupt:
        report["error_code"] = "cancelled"
    except Exception as error:
        report["error_code"] = _error_code(error)
    return report


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise SmokeError("invalid_arguments")


def main(argv=None) -> int:
    parser = _Parser(prog="cloud_media_smoke", add_help=False, allow_abbrev=False)
    parser.add_argument("--ffmpeg")
    parser.add_argument("--ffprobe")
    parser.add_argument("--help", action="store_true")
    try:
        args = parser.parse_args(argv)
        if args.help:
            report = {"ok": True, "scope": SCOPE,
                      "usage": "cloud_media_smoke [--ffmpeg ABSOLUTE_PATH] [--ffprobe ABSOLUTE_PATH]"}
        else:
            report = run_smoke(ffmpeg=args.ffmpeg, ffprobe=args.ffprobe)
    except KeyboardInterrupt:
        report = {"ok": False, "scope": SCOPE, "error_code": "cancelled", "cases": []}
    except Exception as error:
        report = {"ok": False, "scope": SCOPE, "error_code": _error_code(error), "cases": []}
    print(json.dumps(report, ensure_ascii=True, allow_nan=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    raise SystemExit(main())
