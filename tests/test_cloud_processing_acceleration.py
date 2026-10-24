"""Cloud-only acceleration parity; generated clips and temporary outputs only."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import io
import os
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
REFERENCE_ROOT = Path(os.environ.get('REHAB_CLOUD_REFERENCE_SOURCE', str(ROOT)))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


baseline = load('_baseline_media_acceleration', REFERENCE_ROOT / 'src/rehab_affect/demo2_media_analysis.py')
cloud = load('_cloud_media_acceleration', ROOT / '.runtime/cloud_release_overrides/demo2_media_analysis.py')


@pytest.fixture(autouse=True)
def default_threads(monkeypatch):
    monkeypatch.delenv(cloud.DECODER_THREADS_ENV, raising=False)


@pytest.fixture(scope='module')
def tools():
    pytest.importorskip('cv2')
    try:
        return baseline._resolve_tool('ffmpeg'), baseline._resolve_tool('ffprobe')
    except baseline.MediaAnalysisError:
        pytest.skip('Local FFmpeg/ffprobe unavailable; real parity not verified')


def task(source):
    return {'task_id': 'synthetic-acceleration', 'file_path': str(source),
            'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}


def normalize(result):
    result = copy.deepcopy(result)
    for key, value in result['artifacts'].items():
        result['artifacts'][key] = Path(value).name if value else None
    for segment in result['segments']:
        for sample in segment['visual']['samples']:
            sample['image_path'] = Path(sample['image_path']).name
    return result


def artifact_hashes(result, output):
    paths = [sample['image_path'] for segment in result['segments']
             for sample in segment['visual']['samples']]
    if result['artifacts']['audio']:
        paths.append(result['artifacts']['audio'])
    return [hashlib.sha256((output / path).read_bytes()).hexdigest() for path in paths]


@pytest.fixture(scope='module')
def generated(tmp_path_factory, tools):
    root = tmp_path_factory.mktemp('synthetic_acceleration_clips')
    clips = {}
    for kind in ('audio', 'silent', 'absent', 'delayed', 'gap', 'fractional', 'vfr'):
        duration = 20.033333333 if kind == 'fractional' else 3.2
        path = root / (kind + '.mp4')
        command = [tools[0], '-v', 'error', '-nostdin', '-n', '-f', 'lavfi', '-i',
                   f'testsrc2=size=160x96:rate=30:duration={duration}']
        if kind != 'absent':
            delay = 1 if kind == 'delayed' else 0
            if delay:
                command += ['-itsoffset', str(delay)]
            signal = '0' if kind == 'silent' else 'if(lt(mod(t,0.04),0.02),0.2*sin(2*PI*440*t),0)'
            command += ['-f', 'lavfi', '-i', f"aevalsrc='{signal}':s=44100:d={duration-delay}"]
            if kind == 'gap':
                command += ['-af', "aselect='not(between(t,1,1.04))'"]
        if kind == 'vfr':
            command += ['-vf', "select='if(lt(t,1),1,not(mod(n,2)))'", '-fps_mode', 'vfr']
        command += ['-c:v', 'mpeg4', '-q:v', '2', '-threads', '1']
        command += ['-an'] if kind == 'absent' else ['-c:a', 'aac', '-ac', '1', '-ar', '44100']
        subprocess.run(command + [str(path)], stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True, timeout=30)
        clips[kind] = path
    return clips


@pytest.mark.parametrize('threads', ['1', '2'])
@pytest.mark.parametrize('kind', ['audio', 'silent', 'absent', 'delayed', 'gap', 'fractional', 'vfr'])
def test_full_evidence_pixels_pcm_and_20ms_metrics_match_baseline(
        tmp_path, generated, monkeypatch, kind, threads):
    source = generated[kind]
    before_dir, after_dir = tmp_path / 'before', tmp_path / 'after'
    before = baseline.process_video_task(task(source), before_dir)
    monkeypatch.setenv(cloud.DECODER_THREADS_ENV, threads)
    timings = {}
    after = cloud.process_video_task(task(source), after_dir, stage_timings=timings)
    assert after['analysis_version'] == before['analysis_version']
    assert normalize(after) == normalize(before)
    assert artifact_hashes(after, after_dir) == artifact_hashes(before, before_dir)
    assert 'stage_timings' not in after and 'timings' not in after
    assert {'validating', 'hashing', 'probing', 'sampling_video', 'writing_result', 'total'} <= timings.keys()
    assert all(value >= 0 for value in timings.values())
    assert sum(value for key, value in timings.items() if key != 'total') <= timings['total']
    if kind != 'absent':
        assert {'extracting_audio', 'measuring_audio'} <= timings.keys()
        assert all(segment['audio']['method'] == '20ms_rms_threshold_not_speech_vad'
                   for segment in after['segments'])


@pytest.mark.parametrize('value', [None, '1', '2'])
def test_only_explicit_bounded_decoder_threads_are_used(monkeypatch, value):
    if value is not None:
        monkeypatch.setenv(cloud.DECODER_THREADS_ENV, value)
    options = cloud._input_options()
    assert options[options.index('-threads') + 1] == (value or '1')
    if value is None:
        assert options == baseline._input_options()


@pytest.mark.parametrize('value', ['', '0', '3', '-1', 'auto', '1.0', ' 2', 'PRIVATE_ENV'])
def test_untrusted_decoder_thread_values_fail_without_echo(monkeypatch, value):
    monkeypatch.setenv(cloud.DECODER_THREADS_ENV, value)
    with pytest.raises(cloud.MediaAnalysisError) as error:
        cloud._input_options()
    assert error.value.code == 'invalid_task'
    assert 'PRIVATE_ENV' not in str(error.value)


def test_audio_pipe_batches_one_second_without_changing_measurement(monkeypatch, tmp_path):
    seen = []
    def chunks(*args, **kwargs):
        seen.append(kwargs['chunk_size'])
        kwargs['counters'].update(decoded_audio_frames=1, audio_intervals=[[0, 32000]])
        yield b'\0' * 64000
    monkeypatch.setattr(cloud, '_pipe_chunks', chunks)
    segments = [{'start_sec': 0, 'end_sec': 2}]
    cloud._audio_evidence('unused', tmp_path / 'unused.mp4',
                          {'duration_sec': 2, 'source_start_sec': 0, 'audio_index': 1},
                          segments, tmp_path / 'audio.wav', lambda _: None,
                          lambda *args: None, None)
    assert seen == [32000]
    assert segments[0]['audio']['sample_count'] == 32000
    assert segments[0]['audio']['rms'] == 0
    assert segments[0]['audio']['energy_activity_ratio'] == 0
    assert segments[0]['audio']['method'] == '20ms_rms_threshold_not_speech_vad'


def hash_only(monkeypatch, tmp_path, clock, progress, stop_event=None):
    pytest.importorskip('cv2')
    source = tmp_path / 'hash-only.mp4'
    source.write_bytes(b'x' * 1000)
    real_open = Path.open
    class Bytewise(io.BytesIO):
        def read(self, size=-1):
            return super().read(min(size, 1))
    def opened(path, *args, **kwargs):
        if path == source:
            return Bytewise(b'x' * 1000)
        return real_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', opened)
    monkeypatch.setattr(cloud, '_resolve_tool', lambda _: 'unused')
    monkeypatch.setattr(cloud, 'time', SimpleNamespace(monotonic=clock, perf_counter=time.perf_counter))
    with pytest.raises(cloud.MediaAnalysisError) as error:
        cloud.process_video_task({'task_id': 'synthetic', 'file_path': str(source), 'sha256': '0' * 64},
                                 tmp_path / 'unused-output', progress, stop_event)
    return error.value.code


def test_duplicate_progress_is_coalesced_but_stage_changes_are_published(monkeypatch, tmp_path):
    calls = []
    code = hash_only(monkeypatch, tmp_path, lambda: 0.0,
                     lambda percent, stage: calls.append((percent, stage)))
    assert code == 'hash_mismatch'
    assert calls == [(0, 'validating')] + [(percent, 'hashing') for percent in range(9)]


def test_unchanged_progress_has_two_second_heartbeat(monkeypatch, tmp_path):
    now, calls = [0.0], []
    def clock():
        now[0] += 0.25
        return now[0]
    code = hash_only(monkeypatch, tmp_path, clock,
                     lambda percent, stage: calls.append((percent, stage, now[0])))
    assert code == 'hash_mismatch'
    assert any(left[:2] == right[:2] for left, right in zip(calls, calls[1:]))
    assert all(right[2] - left[2] <= 2 for left, right in zip(calls, calls[1:]))
    assert all(right[:2] != left[:2] or right[2] - left[2] == 2
               for left, right in zip(calls, calls[1:]))


def test_suppressed_callback_still_checks_stop_event_after_clock(monkeypatch, tmp_path):
    event, calls, ticks = threading.Event(), [], [0]
    def clock():
        ticks[0] += 1
        if ticks[0] == 3:
            event.set()
        return 0.0
    code = hash_only(monkeypatch, tmp_path, clock,
                     lambda percent, stage: calls.append((percent, stage)), event)
    assert code == 'cancelled'
    assert calls == [(0, 'validating'), (0, 'hashing')]
    assert not (tmp_path / 'unused-output').exists()


@pytest.mark.parametrize('stage', ['sampling_video', 'extracting_audio'])
def test_cancelled_runs_match_baseline_cleanup(tmp_path, generated, stage):
    for name, module in [('before', baseline), ('after', cloud)]:
        output = tmp_path / name
        output.mkdir()
        marker = output / 'unrelated.txt'
        marker.write_text('preserve')
        event = threading.Event()
        def progress(percent, current):
            if current == stage:
                event.set()
        with pytest.raises(module.MediaAnalysisError) as error:
            module.process_video_task(task(generated['audio']), output, progress, event)
        assert error.value.code == 'cancelled'
        assert list(output.iterdir()) == [marker]


@pytest.mark.parametrize('content', [b'', b'not a video'])
def test_corrupt_media_has_same_error_and_no_evidence(tmp_path, tools, content):
    source = tmp_path / 'corrupt.mp4'
    source.write_bytes(content)
    errors = []
    for name, module in [('before', baseline), ('after', cloud)]:
        output = tmp_path / name
        with pytest.raises(module.MediaAnalysisError) as error:
            module.process_video_task(task(source), output)
        errors.append(error.value.code)
        assert not output.exists()
    assert errors[0] == errors[1]
