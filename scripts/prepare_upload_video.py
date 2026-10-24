"""Explicit, offline upload preparation. Never uploads or discovers user videos.

Example: python scripts/prepare_upload_video.py recording.mov --resolution 1080p
Requires the project's media dependencies and approved FFmpeg/ffprobe binaries.
Advisory upload limits: 650 MiB / 60 minutes; never truncates or targets a size.
Lossy transcoding cannot guarantee unchanged face/action detail or a smaller file.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import importlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile


RECOMMENDED_BYTES = 650 * 1024**2
RECOMMENDED_SECONDS = 60 * 60
MAX_TIMEOUT = 2 * 60 * 60


class PreparationError(RuntimeError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def _load_media():
    root = str(Path(__file__).resolve().parents[1] / "src")
    if root not in sys.path:
        sys.path.insert(0, root)
    return importlib.import_module("rehab_affect.demo2_media_analysis")


@contextmanager
def _without_reports():
    previous = os.environ.pop("FFREPORT", None)
    try:
        yield
    finally:
        if previous is not None:
            os.environ["FFREPORT"] = previous


def _tool(media, name, supplied):
    if supplied is None:
        return media._resolve_tool(name)
    candidate = Path(supplied).expanduser()
    if not candidate.is_absolute():
        raise PreparationError("invalid_tool_path", "Tool overrides must be absolute executable paths.")
    if not candidate.is_file() or not os.access(candidate, os.X_OK):
        raise PreparationError("missing_dependency", "The specified media tool is unavailable.")
    return str(candidate.resolve(strict=True))


def _filter(resolution):
    long_side, short_side = (1280, 720) if resolution == "720p" else (1920, 1080)
    # Bound portrait and landscape independently, preserve aspect, never upscale.
    return (f"scale=w='if(gte(iw,ih),min({long_side},iw),min({short_side},iw))':"
            f"h='if(gte(iw,ih),min({short_side},ih),min({long_side},ih))':"
            "force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1,fps=25")


def _verify_encoding(media, tool, path, has_audio):
    command = [tool, "-v", "error", "-max_alloc", "67108864", *media._input_options(),
               "-show_entries", "stream=codec_type,codec_name,pix_fmt", "-of", "json", str(path)]
    raw = b"".join(media._pipe_chunks(command, stage="verify", stop_event=None,
                                    timeout=30, chunk_size=16384, max_bytes=256 * 1024))
    try:
        streams = json.loads(raw)["streams"]
        videos = [s for s in streams if s.get("codec_type") == "video"]
        audios = [s for s in streams if s.get("codec_type") == "audio"]
        valid = (len(videos) == 1 and videos[0].get("codec_name") == "h264"
                 and videos[0].get("pix_fmt") == "yuv420p"
                 and len(audios) == int(has_audio)
                 and all(s.get("codec_name") == "aac" for s in audios))
    except (ValueError, KeyError, TypeError, AttributeError):
        valid = False
    if not valid:
        raise PreparationError("verification_failed", "Output encoding did not match the requested format.")


def prepare(source, *, output=None, resolution="720p", crf=20, timeout=MAX_TIMEOUT,
            ffmpeg=None, ffprobe=None):
    """Process only the explicitly named local file; return a JSON-ready report.

    650 MiB / 60 minutes are advisory, not truncation or bitrate targets.
    Existing media safety limits (8 GiB / 3 hours / bounded dimensions) apply.
    """
    if resolution not in ("720p", "1080p") or not isinstance(crf, int) or not 16 <= crf <= 26:
        raise PreparationError("invalid_arguments", "Use 720p/1080p and CRF 16 through 26.")
    if not math.isfinite(timeout) or not 1 <= timeout <= MAX_TIMEOUT:
        raise PreparationError("invalid_arguments", "Timeout must be between 1 and 7200 seconds.")
    media = _load_media()
    source = media._local_path(source)
    if not source.is_file() or not 0 < source.stat().st_size <= media.MAX_INPUT_BYTES:
        raise PreparationError("invalid_input", "Input must be a nonempty local video of at most 8 GiB.")
    destination = media._local_path(output if output is not None else
                                   source.with_name(f"{source.stem}.upload-{resolution}.mp4"))
    if destination == source or destination.exists():
        raise PreparationError("output_exists", "Refusing to overwrite any existing file, including the original.")
    if destination.suffix.lower() != ".mp4" or not destination.parent.is_dir():
        raise PreparationError("invalid_output", "Output must be an MP4 path in an existing local directory.")
    original = source.stat()
    signature = (original.st_size, original.st_mtime_ns, original.st_ino)
    with _without_reports():
        encoder = _tool(media, "ffmpeg", ffmpeg)
        probe = _tool(media, "ffprobe", ffprobe)
        before = media._probe_media(probe, source, None)
        with tempfile.TemporaryDirectory(prefix=".prepare-upload-", dir=destination.parent) as directory:
            staged = Path(directory) / "prepared.mp4"
            command = [encoder, "-hide_banner", "-v", "error", "-nostdin", "-n", "-xerror",
                       "-max_alloc", "67108864", *media._input_options(), "-i", str(source),
                       "-map", f"0:{before['video_index']}"]
            if before["has_audio"]:
                command += ["-map", f"0:{before['audio_index']}"]
            command += ["-map_metadata", "-1", "-map_chapters", "-1", "-sn", "-dn",
                        "-vf", _filter(resolution), "-c:v", "libx264", "-preset", "medium",
                        "-crf", str(crf), "-pix_fmt", "yuv420p", "-threads", "2",
                        "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
                        "-movflags", "+faststart", "-f", "mp4", str(staged)]
            try:
                result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL, shell=False, timeout=timeout,
                                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            except subprocess.TimeoutExpired:
                raise PreparationError("timeout", "Transcoding timed out; no output was published.") from None
            if result.returncode:
                raise PreparationError("transcode_failed", "Video decoding/transcoding failed; no output was published.")
            after = media._probe_media(probe, staged, None)
            _verify_encoding(media, probe, staged, before["has_audio"])
            if (abs(after["duration_sec"] - before["duration_sec"]) > 0.5
                    or abs(after["fps"] - 25) > 0.01):
                raise PreparationError("verification_failed", "Output duration or frame rate is inconsistent.")
            current = source.stat()
            if (current.st_size, current.st_mtime_ns, current.st_ino) != signature:
                raise PreparationError("source_changed", "Input changed during processing; no output was published.")
            output_bytes = staged.stat().st_size
            warnings = ["Lossy conversion may reduce face/action detail; inspect the new video before manual upload."]
            if original.st_size > RECOMMENDED_BYTES:
                warnings.append("Input exceeds the recommended 650 MiB upload size.")
            if output_bytes > RECOMMENDED_BYTES:
                warnings.append("Output exceeds the recommended 650 MiB upload size; no automatic quality reduction was applied.")
            if before["duration_sec"] > RECOMMENDED_SECONDS:
                warnings.append("Video exceeds the recommended 60 minutes; the complete recording was retained.")
            if output_bytes >= original.st_size:
                warnings.append("Output is not smaller than the original.")
            report = {
                "ok": True, "source": str(source), "output": str(destination),
                "input_bytes": original.st_size, "output_bytes": output_bytes,
                "size_ratio": round(output_bytes / original.st_size, 6),
                "duration_sec": after["duration_sec"],
                "quality": {"resolution": resolution, "width": after["width"], "height": after["height"],
                            "fps": 25, "video_codec": "h264", "pixel_format": "yuv420p",
                            "crf": crf, "preset": "medium", "audio_codec": "aac" if before["has_audio"] else None,
                            "audio_bitrate_kbps": 128 if before["has_audio"] else None, "faststart": True},
                "recommendations": {"max_bytes": RECOMMENDED_BYTES, "max_duration_sec": RECOMMENDED_SECONDS},
                "within_recommendations": output_bytes <= RECOMMENDED_BYTES and before["duration_sec"] <= RECOMMENDED_SECONDS,
                "warnings": warnings, "uploaded": False,
            }
            media._no_links(destination)
            # Same-volume hard link is atomic and refuses even a concurrently created target.
            # Never use rename/replace, which can clobber a target on POSIX.
            try:
                os.link(staged, destination)
            except FileExistsError:
                raise PreparationError("output_exists", "Output appeared during processing; it was not overwritten.") from None
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", help="Explicit local video file; no batch scanning or upload")
    parser.add_argument("-o", "--output", help="New .mp4 path; existing files are always refused")
    parser.add_argument("--resolution", choices=("720p", "1080p"), default="720p")
    parser.add_argument("--crf", type=int, choices=range(16, 27), default=20,
                        help="H.264 CRF (default 20); lower is higher quality/larger, still lossy")
    parser.add_argument("--timeout", type=float, default=MAX_TIMEOUT, help="Encode timeout seconds, 1..7200")
    parser.add_argument("--ffmpeg", help="Absolute approved executable; otherwise existing project discovery")
    parser.add_argument("--ffprobe", help="Absolute approved executable; otherwise existing project discovery")
    args = parser.parse_args(argv)
    try:
        report = prepare(**vars(args))
    except KeyboardInterrupt:
        report = {"ok": False, "error_code": "cancelled", "uploaded": False}
    except (RuntimeError, OSError, ImportError) as error:
        report = {"ok": False, "error_code": getattr(error, "code", "preparation_failed"),
                  "message": "Preparation failed; the original was not overwritten. Check paths, tools and media limits.",
                  "uploaded": False}
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
