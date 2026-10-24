from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("prepare_upload_video", ROOT / "scripts/prepare_upload_video.py")
cli = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cli)


@pytest.fixture
def fake(tmp_path, monkeypatch):
    source = tmp_path / "\u5b66\u751f synthetic & sample.mov"
    source.write_bytes(b"synthetic-input")
    meta = {"video_index": 0, "audio_index": 1, "has_audio": True,
            "duration_sec": 2.0, "fps": 25, "width": 1280, "height": 720}
    media = cli._load_media()
    monkeypatch.setattr(cli, "_tool", lambda *args: "approved-tool")
    monkeypatch.setattr(media, "_probe_media", lambda *args: dict(meta))
    monkeypatch.setattr(cli, "_verify_encoding", lambda *args: None)
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        Path(command[-1]).write_bytes(b"new-video")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(cli.subprocess, "run", run)
    return source, meta, calls


def test_defaults_and_safe_arguments(fake, monkeypatch):
    source, _, calls = fake
    monkeypatch.setenv("FFREPORT", "private-report")
    report = cli.prepare(source)
    command, kwargs = calls[0]
    assert kwargs["shell"] is False and kwargs["timeout"] == 7200
    assert kwargs["stdin"] == kwargs["stdout"] == kwargs["stderr"] == subprocess.DEVNULL
    assert "-n" in command and "-y" not in command and "-nostdin" in command and "-xerror" in command
    assert command[command.index("-i") + 1] == str(source)
    assert command[command.index("-protocol_whitelist") + 1] == "file"
    assert command[command.index("-format_whitelist") + 1]
    assert command[command.index("-crf") + 1] == "20"
    assert command[command.index("-movflags") + 1] == "+faststart"
    assert "fps=25" in command[command.index("-vf") + 1]
    assert "-t" not in command and "-fs" not in command and "-shortest" not in command
    assert report["quality"]["resolution"] == "720p" and report["uploaded"] is False
    assert report["size_ratio"] == round(9 / len(b"synthetic-input"), 6)
    assert source.read_bytes() == b"synthetic-input"
    assert Path(report["output"]).read_bytes() == b"new-video"
    assert not list(source.parent.glob(".prepare-upload-*"))
    assert os.environ["FFREPORT"] == "private-report"


@pytest.mark.parametrize("same_source", [True, False])
def test_existing_output_never_touched(fake, same_source):
    source, _, calls = fake
    output = source if same_source else source.with_suffix(".mp4")
    if not same_source:
        output.write_bytes(b"existing")
    original = output.read_bytes()
    with pytest.raises(cli.PreparationError, match="overwrite"):
        cli.prepare(source, output=output)
    assert output.read_bytes() == original and not calls


@pytest.mark.parametrize("kwargs", [{"timeout": 0}, {"timeout": 7201}, {"timeout": float("nan")},
                                    {"crf": 51}, {"resolution": "4k"}])
def test_invalid_settings(fake, kwargs):
    with pytest.raises(cli.PreparationError):
        cli.prepare(fake[0], **kwargs)
    assert not fake[2]


@pytest.mark.parametrize("path", ["https://example.org/video.mp4", "file:///tmp/test.mp4", "//server/share/a.mp4"])
def test_remote_inputs_rejected(fake, path):
    with pytest.raises(RuntimeError):
        cli.prepare(path)
    assert not fake[2]


@pytest.mark.parametrize("mode", ["timeout", "failed", "interrupt", "verify", "changed"])
def test_failure_cleans_only_owned_files(fake, monkeypatch, mode):
    source, _, _ = fake
    original_run = cli.subprocess.run

    def run(command, **kwargs):
        result = original_run(command, **kwargs)
        assert "FFREPORT" not in os.environ
        if mode == "timeout":
            raise subprocess.TimeoutExpired(command, 1)
        if mode == "interrupt":
            raise KeyboardInterrupt
        if mode == "changed":
            source.write_bytes(b"externally-changed")
        return SimpleNamespace(returncode=1) if mode == "failed" else result

    monkeypatch.setenv("FFREPORT", "preserve-setting")
    monkeypatch.setattr(cli.subprocess, "run", run)
    if mode == "verify":
        def invalid(*args):
            raise cli.PreparationError("verification_failed", "invalid encoding")
        monkeypatch.setattr(cli, "_verify_encoding", invalid)
    with pytest.raises((cli.PreparationError, KeyboardInterrupt)):
        cli.prepare(source)
    assert list(source.parent.iterdir()) == [source]
    if mode != "changed":
        assert source.read_bytes() == b"synthetic-input"
    assert os.environ["FFREPORT"] == "preserve-setting"


def test_racing_output_is_preserved(fake, monkeypatch):
    source, _, _ = fake
    original_link = cli.os.link

    def racing_link(staged, target):
        Path(target).write_bytes(b"concurrent-owner")
        original_link(staged, target)

    monkeypatch.setattr(cli.os, "link", racing_link)
    with pytest.raises(cli.PreparationError) as error:
        cli.prepare(source)
    assert error.value.code == "output_exists"
    assert source.with_name(source.stem + ".upload-720p.mp4").read_bytes() == b"concurrent-owner"
    assert not list(source.parent.glob(".prepare-upload-*"))


def test_recommendations_are_advisory_and_1080p(fake):
    source, meta, calls = fake
    meta["duration_sec"] = 3601
    report = cli.prepare(source, resolution="1080p", crf=18)
    assert not report["within_recommendations"]
    assert report["quality"]["crf"] == 18
    assert report["recommendations"] == {"max_bytes": 650 * 1024**2, "max_duration_sec": 3600}
    assert any("60 minutes" in warning for warning in report["warnings"])
    assert "1920" in calls[0][0][calls[0][0].index("-vf") + 1]


def test_missing_tool_override_does_not_fallback(tmp_path):
    with pytest.raises(cli.PreparationError) as error:
        cli._tool(cli._load_media(), "ffmpeg", str(tmp_path / "missing.exe"))
    assert error.value.code == "missing_dependency"
    with pytest.raises(cli.PreparationError):
        cli._tool(cli._load_media(), "ffmpeg", "relative.exe")


@pytest.mark.parametrize("kind", ["missing", "empty", "directory"])
def test_invalid_local_input(fake, kind):
    source, _, calls = fake
    if kind == "missing":
        source.unlink()
    elif kind == "empty":
        source.write_bytes(b"")
    else:
        source.unlink()
        source.mkdir()
    with pytest.raises(cli.PreparationError) as error:
        cli.prepare(source)
    assert error.value.code == "invalid_input" and not calls


@pytest.mark.parametrize("output", ["wrong.avi", "absent/output.mp4"])
def test_invalid_output(fake, output):
    source, _, calls = fake
    with pytest.raises(cli.PreparationError) as error:
        cli.prepare(source, output=source.parent / output)
    assert error.value.code == "invalid_output" and not calls


def test_output_size_recommendation_never_forces_quality_reduction(fake, monkeypatch):
    monkeypatch.setattr(cli, "RECOMMENDED_BYTES", 1)
    report = cli.prepare(fake[0])
    assert not report["within_recommendations"]
    assert report["quality"]["crf"] == 20 and len(fake[2]) == 1
    assert any("no automatic quality reduction" in warning for warning in report["warnings"])


@pytest.mark.parametrize("payload", [b"not-json", b"{}", b'{"streams":[42]}',
                                    b'{"streams":[{"codec_type":"video","codec_name":"hevc"}]}'])
def test_output_codec_verification_rejects_invalid_metadata(monkeypatch, tmp_path, payload):
    media = SimpleNamespace(_input_options=lambda: [], _pipe_chunks=lambda *args, **kwargs: iter([payload]))
    with pytest.raises(cli.PreparationError) as error:
        # The real verifier is not replaced by the fake fixture here.
        cli._verify_encoding(media, "approved-probe", tmp_path / "output.mp4", False)
    assert error.value.code == "verification_failed"


def test_cli_report(fake, capsys):
    assert cli.main([str(fake[0]), "--resolution", "1080p"]) == 0
    assert json.loads(capsys.readouterr().out)["quality"]["resolution"] == "1080p"
    assert cli.main([str(fake[0]), "--timeout", "inf"]) == 1
    assert json.loads(capsys.readouterr().out)["error_code"] == "invalid_arguments"


@pytest.fixture(scope="module")
def real_tools():
    media = cli._load_media()
    try:
        return {name: media._resolve_tool(name) for name in ("ffmpeg", "ffprobe")}
    except RuntimeError:
        pytest.skip("Approved local FFmpeg/ffprobe unavailable")


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            result.update(block)
    return result.hexdigest()


def atom_types(path):
    atoms = []
    with path.open("rb") as stream:
        while header := stream.read(8):
            size, kind = struct.unpack(">I4s", header)
            if size == 1:
                size = struct.unpack(">Q", stream.read(8))[0]
                header = b"x" * 16
            assert size >= len(header)
            atoms.append(kind)
            stream.seek(size - len(header), 1)
    return atoms


@pytest.mark.parametrize("size,audio,resolution,expected", [
    ("1600x900", True, "720p", (1280, 720)),
    ("120x200", False, "1080p", (120, 200)),
    ("900x1600", True, "720p", (720, 1280)),
])
def test_real_synthetic_conversion_only(tmp_path, real_tools, size, audio, resolution, expected):
    source = tmp_path / "\u5408\u6210 video & source.mov"
    command = [real_tools["ffmpeg"], "-v", "error", "-nostdin", "-n", "-f", "lavfi", "-i",
               f"testsrc2=size={size}:rate=30:duration=1"]
    if audio:
        command += ["-f", "lavfi", "-i", "sine=frequency=440:duration=1"]
    command += ["-c:v", "mpeg4", "-q:v", "2", "-threads", "1", "-c:a", "pcm_s16le", str(source)]
    subprocess.run(command, check=True, timeout=30, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    before = digest(source)
    prepared = subprocess.run([sys.executable, str(ROOT / "scripts/prepare_upload_video.py"), str(source),
                               "--resolution", resolution, "--timeout", "60", "--ffmpeg", real_tools["ffmpeg"],
                               "--ffprobe", real_tools["ffprobe"]], capture_output=True, text=True,
                              encoding="utf-8", timeout=90, check=True)
    assert prepared.stderr == ""
    report = json.loads(prepared.stdout)
    target = Path(report["output"])
    assert digest(source) == before
    assert (report["quality"]["width"], report["quality"]["height"]) == expected
    assert report["quality"]["audio_codec"] == ("aac" if audio else None)
    assert report["duration_sec"] == pytest.approx(1, abs=0.1)
    assert atom_types(target).index(b"moov") < atom_types(target).index(b"mdat")
    subprocess.run([real_tools["ffmpeg"], "-v", "error", "-nostdin", "-xerror", "-i", str(target),
                    "-f", "null", "-"], check=True, timeout=30, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    assert set(tmp_path.iterdir()) == {source, target}


def test_real_nonvideo_rejected_before_publication(tmp_path, real_tools):
    source = tmp_path / "not-a-video.mp4"
    source.write_bytes(b"This is not media.")
    with pytest.raises(RuntimeError):
        cli.prepare(source, **real_tools)
    assert list(tmp_path.iterdir()) == [source]


def test_real_audio_only_is_not_a_video(tmp_path, real_tools):
    source = tmp_path / "audio-only.mov"
    subprocess.run([real_tools["ffmpeg"], "-v", "error", "-nostdin", "-n", "-f", "lavfi", "-i",
                    "sine=frequency=440:duration=0.2", "-c:a", "aac", str(source)],
                   check=True, timeout=30, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    before = digest(source)
    with pytest.raises(RuntimeError) as error:
        cli.prepare(source, **real_tools)
    assert error.value.code == "invalid_media"
    assert digest(source) == before and list(tmp_path.iterdir()) == [source]
