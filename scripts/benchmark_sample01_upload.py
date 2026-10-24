"""Operator-run, offline Sample01 first-60s comparison; never uploads anything.

Run on the cloud host with its already-controlled Sample01 path:
  .venv/bin/python scripts/benchmark_sample01_upload.py --source /private/Sample01.mp4 \
      --root /var/lib/rehabaffect-private/video-benchmarks --allow-controlled-sample01

Keeps a stream-copy excerpt, existing prepare_upload_video CLI output, bounded
ffprobe JSON, and a comparison report in a fresh private run directory. Size
ratios compare the SAME interval, not a 60-second output to the full recording.
No actual upload speed or unchanged visual quality is asserted.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import prepare_upload_video as prepare


def _save(path, value):
    with path.open('x', encoding='utf-8') as target:
        json.dump(value, target, ensure_ascii=True, indent=2)
        target.write('\n')
    path.chmod(0o600)


def _probe(media, tool, path):
    command = [tool, '-v', 'error', '-max_alloc', '67108864', *media._input_options(),
               '-show_entries', 'format=format_name,duration,size,bit_rate:'
               'stream=codec_type,codec_name,pix_fmt,width,height,avg_frame_rate,duration',
               '-of', 'json', str(path)]
    return json.loads(b''.join(media._pipe_chunks(command, stage='benchmark_probe', stop_event=None,
                                                timeout=30, chunk_size=16384, max_bytes=256 * 1024)))


def benchmark(source, root, *, allow_controlled_sample01=False):
    if not allow_controlled_sample01:
        raise prepare.PreparationError('authorization_required', 'Explicit controlled Sample01 selection is required.')
    media = prepare._load_media()
    source, root = media._local_path(source), media._local_path(root)
    if not source.is_file() or not 0 < source.stat().st_size <= media.MAX_INPUT_BYTES:
        raise prepare.PreparationError('invalid_input', 'A controlled local video is required.')
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = root.stat()
    if not root.is_dir() or (os.name == 'posix' and (info.st_uid != os.geteuid() or info.st_mode & 0o077)):
        raise prepare.PreparationError('unsafe_output', 'Use an owner-only private output root.')
    with prepare._without_reports():
        encoder, probe = (media._resolve_tool(name) for name in ('ffmpeg', 'ffprobe'))
        before = source.stat()
        signature = (before.st_size, before.st_mtime_ns, before.st_ino)
        metadata = media._probe_media(probe, source, None)
        if metadata['duration_sec'] < 60:
            raise prepare.PreparationError('short_sample', 'Sample01 must contain at least 60 seconds.')
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-')
        run = Path(tempfile.mkdtemp(prefix='sample01-bench-' + stamp, dir=root))
        run.chmod(0o700)
        original_probe = _probe(media, probe, source)
        _save(run / 'source.ffprobe.json', original_probe)
        # Stream copy retains source coding quality. Packet boundaries can differ
        # slightly from 60 seconds; both actual durations are recorded below.
        excerpt = run / 'sample01.first60.original.mkv'
        command = [encoder, '-v', 'error', '-nostdin', '-n', '-max_alloc', '67108864',
                   *media._input_options(), '-i', str(source), '-t', '60',
                   '-map', f"0:{metadata['video_index']}"]
        if metadata['has_audio']:
            command += ['-map', f"0:{metadata['audio_index']}"]
        command += ['-c', 'copy', '-map_metadata', '-1', '-map_chapters', '-1',
                    '-avoid_negative_ts', 'make_zero', '-f', 'matroska', str(excerpt)]
        started = time.perf_counter()
        subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, shell=False, check=True, timeout=120,
                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        excerpt_seconds = time.perf_counter() - started
        excerpt.chmod(0o600)
        excerpt_meta = media._probe_media(probe, excerpt, None)
        if abs(excerpt_meta['duration_sec'] - 60) > .5:
            raise prepare.PreparationError('excerpt_duration', 'Stream-copy excerpt differs too far from 60 seconds.')
        _save(run / 'excerpt.ffprobe.json', _probe(media, probe, excerpt))
        output = run / 'sample01.first60.720p25.mp4'
        # Invoke the existing CLI, rather than duplicating its encode settings.
        cli_report = run / 'prepare-cli.json'
        started = time.perf_counter()
        with cli_report.open('xb') as log:
            subprocess.run([sys.executable, str(Path(prepare.__file__).resolve()), str(excerpt),
                            '--output', str(output), '--resolution', '720p', '--crf', '20',
                            '--timeout', '7200', '--ffmpeg', encoder, '--ffprobe', probe],
                           stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.DEVNULL,
                           shell=False, check=True, timeout=7500,
                           creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        transcode_seconds = time.perf_counter() - started
        cli_report.chmod(0o600)
        output.chmod(0o600)
        with cli_report.open('rb') as log:
            settings = json.loads(log.read(1024 * 1024))
        output_meta = media._probe_media(probe, output, None)
        _save(run / 'output.ffprobe.json', _probe(media, probe, output))
        after = source.stat()
        if (after.st_size, after.st_mtime_ns, after.st_ino) != signature:
            raise prepare.PreparationError('source_changed', 'Controlled source changed during the comparison.')
        ratio = output.stat().st_size / excerpt.stat().st_size
        report = {
            'ok': True, 'sample_id': 'Sample01', 'source': str(source), 'run_directory': str(run),
            'source_stat_unchanged': True, 'source_bytes': before.st_size,
            'excerpt': {'path': str(excerpt), 'bytes': excerpt.stat().st_size, **excerpt_meta},
            'output': {'path': str(output), 'bytes': output.stat().st_size, **output_meta},
            'size_ratio_same_interval': ratio, 'bytes_saved_percent': (1 - ratio) * 100,
            'excerpt_wall_seconds': excerpt_seconds, 'prepare_cli_wall_seconds': transcode_seconds,
            'prepare_speed_x_realtime': excerpt_meta['duration_sec'] / transcode_seconds,
            'quality': settings['quality'], 'uploaded': False, 'measured_upload_speed': False,
            'notes': ['Excerpt is stream-copied; packet rounding up to 0.5 seconds is checked.',
                      'Matroska-to-MP4 container overhead is included in the size ratio.',
                      'CLI time includes process startup, probing, validation and encoding.',
                      'No network speed measurement or lossless visual-quality claim; inspect faces/actions manually.'],
        }
        _save(run / 'report.json', report)
        return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--source', type=Path, required=True, help='Explicit path to the already-controlled cloud Sample01')
    parser.add_argument('--root', type=Path, default=Path('/var/lib/rehabaffect-private/video-benchmarks'))
    parser.add_argument('--allow-controlled-sample01', action='store_true')
    args = parser.parse_args(argv)
    previous_umask = os.umask(0o077)
    try:
        report = benchmark(args.source, args.root, allow_controlled_sample01=args.allow_controlled_sample01)
    except (RuntimeError, OSError, ImportError, subprocess.SubprocessError) as error:
        print(json.dumps({'ok': False, 'error': getattr(error, 'code', 'benchmark_failed'), 'uploaded': False}))
        return 1
    finally:
        os.umask(previous_umask)
    print(json.dumps({'ok': True, 'report': str(Path(report['run_directory']) / 'report.json'), 'uploaded': False}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
