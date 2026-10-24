"""Benchmark safety and a synthetic 61-second end-to-end CLI comparison only."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'scripts'
SPEC = importlib.util.spec_from_file_location('benchmark_sample01_upload', SCRIPTS / 'benchmark_sample01_upload.py')
benchmark = importlib.util.module_from_spec(SPEC)
sys.path.insert(0, str(SCRIPTS))
try:
    SPEC.loader.exec_module(benchmark)
finally:
    sys.path.remove(str(SCRIPTS))


def test_authorization_gate_precedes_media_access(tmp_path, monkeypatch):
    def forbidden():
        pytest.fail('Must not access media without explicit controlled-source authorization')
    monkeypatch.setattr(benchmark.prepare, '_load_media', forbidden)
    with pytest.raises(RuntimeError) as error:
        benchmark.benchmark(tmp_path / 'not-opened.mp4', tmp_path / 'not-created')
    assert error.value.code == 'authorization_required'
    assert list(tmp_path.iterdir()) == []


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as source:
        while block := source.read(1024 * 1024):
            result.update(block)
    return result.hexdigest()


def test_synthetic_first60_comparison_uses_existing_cli(tmp_path):
    media = benchmark.prepare._load_media()
    try:
        ffmpeg = media._resolve_tool('ffmpeg')
        media._resolve_tool('ffprobe')
    except RuntimeError:
        pytest.skip('Approved local FFmpeg/ffprobe unavailable')
    source = tmp_path / 'synthetic-61s.mov'
    subprocess.run([ffmpeg, '-v', 'error', '-nostdin', '-n', '-f', 'lavfi', '-i',
        'testsrc2=size=160x96:rate=10:duration=61', '-f', 'lavfi', '-i',
        'sine=frequency=440:sample_rate=48000:duration=61', '-c:v', 'mpeg4', '-q:v', '2',
        '-c:a', 'aac', '-threads', '1', str(source)],
        timeout=60, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    original_hash = digest(source)
    root = tmp_path / 'private-runs'
    result = subprocess.run([sys.executable, str(SCRIPTS / 'benchmark_sample01_upload.py'),
        '--source', str(source), '--root', str(root), '--allow-controlled-sample01'],
        check=True, timeout=150, capture_output=True, text=True, encoding='utf-8')
    assert result.stderr == ''
    summary = json.loads(result.stdout)
    report_path = Path(summary['report'])
    report = json.loads(report_path.read_text(encoding='utf-8'))
    assert digest(source) == original_hash and report['source_stat_unchanged']
    assert not report['uploaded'] and not report['measured_upload_speed']
    assert report['excerpt']['duration_sec'] == pytest.approx(60, abs=.5)
    assert report['output']['duration_sec'] == pytest.approx(60, abs=.5)
    assert report['size_ratio_same_interval'] == pytest.approx(report['output']['bytes'] / report['excerpt']['bytes'])
    assert report['quality']['video_codec'] == 'h264' and report['quality']['audio_codec'] == 'aac'
    assert report['quality']['fps'] == 25 and report['quality']['resolution'] == '720p'
    assert report['prepare_cli_wall_seconds'] > 0 and report['prepare_speed_x_realtime'] > 0
    assert {path.name for path in report_path.parent.iterdir()} == {
        'sample01.first60.original.mkv', 'sample01.first60.720p25.mp4',
        'source.ffprobe.json', 'excerpt.ffprobe.json', 'output.ffprobe.json', 'prepare-cli.json', 'report.json'}
    probe = json.loads((report_path.parent / 'output.ffprobe.json').read_text(encoding='utf-8'))
    assert [s['codec_name'] for s in probe['streams']] == ['h264', 'aac']
    if os.name == 'posix':
        assert root.stat().st_mode & 0o777 == report_path.parent.stat().st_mode & 0o777 == 0o700
        assert all(path.stat().st_mode & 0o777 == 0o600 for path in report_path.parent.iterdir())


def test_report_writer_never_overwrites_existing_record(tmp_path):
    path = tmp_path / 'report.json'
    path.write_text('preserve', encoding='utf-8')
    with pytest.raises(FileExistsError):
        benchmark._save(path, {'unexpected': 'replacement'})
    assert path.read_text(encoding='utf-8') == 'preserve'
