from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("cloud_media_smoke", ROOT / "scripts" / "cloud_media_smoke.py")
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)


@pytest.fixture()
def isolated_tmp(tmp_path, monkeypatch):
    parent = tmp_path / "\u4e91\u7aef\u9a8c\u6536 \u4e34\u65f6\u76ee\u5f55"
    parent.mkdir()
    marker = parent / "unrelated.txt"
    marker.write_text("preserve", encoding="utf-8")
    monkeypatch.setattr(smoke.tempfile, "gettempdir", lambda: str(parent))
    yield parent
    assert marker.read_text(encoding="utf-8") == "preserve"
    assert list(parent.iterdir()) == [marker]


@pytest.fixture(scope="module")
def real_tools():
    try:
        media = smoke._load_media()
        return media, {name: str(Path(media._resolve_tool(name)).resolve()) for name in ("ffmpeg", "ffprobe")}
    except (ImportError, RuntimeError):
        pytest.skip("Local media tools unavailable; real decoding not verified")


def test_missing_dependency_is_sanitized_and_cli_fails(monkeypatch, capsys):
    def missing():
        print("PRIVATE_SOURCE_PATH", file=sys.stderr)
        raise ImportError("PRIVATE_SECRET")
    monkeypatch.setattr(smoke, "_load_media", missing)
    assert smoke.main([]) == 1
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out)["error_code"] == "missing_dependency"
    assert "PRIVATE" not in captured.out


@pytest.mark.parametrize("args,code", [(["--unknown", "PRIVATE_SECRET"], "invalid_arguments"),
    (["--ffmpeg"], "invalid_arguments"), (["--ffmpeg", "relative/tool"], "invalid_tool_path")])
def test_invalid_arguments_never_echo_values(monkeypatch, capsys, args, code):
    monkeypatch.setattr(smoke, "_load_media", lambda: SimpleNamespace())
    assert smoke.main(args) == 1
    captured = capsys.readouterr()
    assert captured.err == "" and "PRIVATE" not in captured.out and "relative/tool" not in captured.out
    assert json.loads(captured.out)["error_code"] == code


def test_missing_explicit_tool_has_no_fallback_or_env_change(tmp_path, monkeypatch):
    monkeypatch.setattr(smoke, "_load_media", lambda: SimpleNamespace())
    monkeypatch.setenv("REHAB_FFMPEG", "original_value")
    result = smoke.run_smoke(ffmpeg=str(tmp_path / "absent"))
    assert not result["ok"] and result["error_code"] == "missing_dependency"
    assert os.environ["REHAB_FFMPEG"] == "original_value"


def test_missing_discovered_tool_is_failure(monkeypatch):
    def missing(_name):
        raise smoke.SmokeError("missing_dependency")
    monkeypatch.setattr(smoke, "_load_media", lambda: SimpleNamespace(_resolve_tool=missing))
    assert smoke.run_smoke()["error_code"] == "missing_dependency"


@pytest.mark.parametrize("error,code", [(RuntimeError("PRIVATE_PATH"), "smoke_failed"),
    (smoke.SmokeError("PRIVATE_SECRET"), "smoke_failed"),
    (smoke.SmokeError("hash_mismatch"), "hash_mismatch")])
def test_processing_failure_is_sanitized_and_cleans_owned_temp(isolated_tmp, monkeypatch, capfd, error, code):
    def generate(_ffmpeg, source, **_kwargs):
        source.write_bytes(b"synthetic")
    def fail(*_args, **_kwargs):
        print("PRIVATE_STDOUT")
        print("PRIVATE_STDERR", file=sys.stderr)
        os.write(1, b"PRIVATE_NATIVE_STDOUT")
        os.write(2, b"PRIVATE_NATIVE_STDERR")
        raise error
    fake = SimpleNamespace(process_video_task=fail)
    monkeypatch.setattr(smoke, "_load_media", lambda: fake)
    monkeypatch.setattr(smoke, "_generate", generate)
    assert smoke.main(["--ffmpeg", sys.executable, "--ffprobe", sys.executable]) == 1
    captured = capfd.readouterr()
    result = json.loads(captured.out)
    assert not result["ok"] and len(result["cases"]) == 2
    assert all(case["error_code"] == code for case in result["cases"])
    assert captured.err == "" and "PRIVATE" not in captured.out


@pytest.mark.parametrize("failure,code", [
    (subprocess.TimeoutExpired("PRIVATE_COMMAND", 30, output=b"PRIVATE"), "timeout"),
    (OSError("PRIVATE_EXECUTABLE"), "tool_start_failed"),
    (None, "generation_failed"),
])
def test_generation_errors_are_bounded_and_not_logged(tmp_path, monkeypatch, failure, code):
    def run(command, **kwargs):
        assert kwargs["shell"] is False and kwargs["timeout"] == 30
        assert kwargs["stdout"] == kwargs["stderr"] == subprocess.DEVNULL
        assert isinstance(command, list)
        if failure:
            raise failure
        return SimpleNamespace(returncode=1)
    monkeypatch.setattr(smoke.subprocess, "run", run)
    with pytest.raises(smoke.SmokeError) as error:
        smoke._generate("tool", tmp_path / "source.mp4", audio=True)
    assert error.value.code == code


def test_actual_incompatible_executable_fails_without_version_guessing(isolated_tmp):
    # Python is executable but cannot generate FFmpeg media. No version allowlist.
    result = smoke.run_smoke(ffmpeg=sys.executable, ffprobe=sys.executable)
    assert not result["ok"]
    assert all(case["error_code"] == "generation_failed" for case in result["cases"])


def test_tool_overrides_and_ffreport_are_restored(monkeypatch):
    monkeypatch.setenv("REHAB_FFMPEG", "original_ffmpeg")
    monkeypatch.setenv("REHAB_FFPROBE", "original_ffprobe")
    monkeypatch.setenv("FFREPORT", "PRIVATE_REPORT_PATH")
    with smoke._tools(SimpleNamespace(), sys.executable, sys.executable):
        assert "FFREPORT" not in os.environ
        assert os.environ["REHAB_FFMPEG"] == str(Path(sys.executable).resolve())
    assert os.environ["FFREPORT"] == "PRIVATE_REPORT_PATH"
    assert os.environ["REHAB_FFMPEG"] == "original_ffmpeg"
    assert os.environ["REHAB_FFPROBE"] == "original_ffprobe"


def test_interrupt_is_json_failure(monkeypatch, capsys):
    def interrupted():
        raise KeyboardInterrupt
    monkeypatch.setattr(smoke, "_load_media", interrupted)
    assert smoke.main([]) == 1
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out)["error_code"] == "cancelled"


def test_real_smoke_and_no_store_import(real_tools, isolated_tmp, monkeypatch):
    _, tools = real_tools
    original = smoke.importlib.import_module
    def guarded(name, *args, **kwargs):
        assert "store" not in name
        return original(name, *args, **kwargs)
    monkeypatch.setattr(smoke.importlib, "import_module", guarded)
    before = set(sys.modules)
    result = smoke.run_smoke(**tools)
    assert result["ok"], result
    assert not any("store" in name and "rehab_affect" in name for name in set(sys.modules) - before)
    assert result["scope"] == smoke.SCOPE
    for case, audio in zip(result["cases"], (True, False)):
        assert case["decoded_frames"] == 20 and case["sampled_frames"] == 2
        assert case["duration_sec"] == pytest.approx(2, abs=0.1)
        assert case["source_hash_verified"] and case["frame_artifacts_verified"]
        assert case["has_audio"] is audio
        assert case["audio_duration_sec"] == (2.0 if audio else None)
    assert str(isolated_tmp) not in json.dumps(result)


@pytest.mark.parametrize("field,value", [("source_sha256", "0" * 64), ("decoded_frames", 19), ("duration_sec", 1.0)])
def test_actual_result_corruption_is_rejected(real_tools, isolated_tmp, monkeypatch, field, value):
    media, tools = real_tools
    original = media.process_video_task
    def corrupt(*args, **kwargs):
        result = original(*args, **kwargs)
        target = result if field == "source_sha256" else result["summary"] if field == "decoded_frames" else result["media"]
        target[field] = value
        return result
    monkeypatch.setattr(media, "process_video_task", corrupt)
    result = smoke.run_smoke(**tools)
    assert not result["ok"]
    assert all(case["error_code"] == "verification_failed" for case in result["cases"])


def test_cli_from_chinese_absolute_project_path(real_tools, tmp_path):
    media, tools = real_tools
    project = tmp_path / "\u4e2d\u6587\u5de5\u7a0b \u9a8c\u6536"
    scripts = project / "scripts"
    package = project / "src" / "rehab_affect"
    scripts.mkdir(parents=True)
    package.mkdir(parents=True)
    shutil.copyfile(smoke.__file__, scripts / "cloud_media_smoke.py")
    shutil.copyfile(media.__file__, package / "demo2_media_analysis.py")
    (package / "__init__.py").write_text("", encoding="utf-8")
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run([sys.executable, "-B", str(scripts / "cloud_media_smoke.py"),
                                "--ffmpeg", tools["ffmpeg"], "--ffprobe", tools["ffprobe"]],
                               cwd=tmp_path, env=environment, capture_output=True, timeout=90, check=False)
    assert completed.returncode == 0, completed.stdout
    assert completed.stderr == b""
    result = json.loads(completed.stdout)
    assert result["ok"] and len(result["cases"]) == 2
    assert str(project).encode() not in completed.stdout
