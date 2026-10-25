"""Synthetic-only browser fixtures. No real media, retained DB or service access."""

import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('e2e_browser_media', ROOT / 'scripts/cloud_e2e_acceptance.py')
e2e = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(e2e)


@pytest.fixture(scope='module')
def tools():
    media = e2e.smoke_module()._load_media()
    try:
        return {name: media._resolve_tool(name) for name in ('ffmpeg', 'ffprobe')}
    except RuntimeError:
        pytest.skip('Approved local FFmpeg/ffprobe unavailable')


@pytest.fixture
def generated(tmp_path, tools):
    blobs = e2e.generate(tmp_path, tools['ffmpeg'])
    paths = [tmp_path / name for name in ('audio.mp4', 'silent.mp4')]
    assert len(blobs) == 2 and all(blob == path.read_bytes() for blob, path in zip(blobs, paths))
    return paths


def atoms(path):
    names = []
    with path.open('rb') as source:
        while header := source.read(8):
            size, name = struct.unpack('>I4s', header)
            assert size >= 8
            names.append(name)
            source.seek(size - 8, 1)
    return names


def test_real_ffprobe_h264_aac_and_silent_faststart(generated, tools):
    for path, audio_count in zip(generated, (1, 0)):
        result = subprocess.run([tools['ffprobe'], '-v', 'error', '-show_entries',
            'format=duration:stream=codec_type,codec_name,codec_tag_string,profile,pix_fmt,width,height,avg_frame_rate,nb_frames',
            '-of', 'json', str(path)], check=True, capture_output=True, timeout=30)
        metadata = json.loads(result.stdout)
        video = [s for s in metadata['streams'] if s['codec_type'] == 'video']
        audio = [s for s in metadata['streams'] if s['codec_type'] == 'audio']
        assert len(video) == 1 and len(audio) == audio_count
        assert (video[0]['codec_name'], video[0]['pix_fmt'], video[0]['codec_tag_string']) == ('h264', 'yuv420p', 'avc1')
        assert 'Baseline' in video[0]['profile']
        assert (video[0]['width'], video[0]['height'], video[0]['avg_frame_rate'], video[0]['nb_frames']) == (160, 96, '10/1', '20')
        assert all(s['codec_name'] == 'aac' and s['profile'] == 'LC' for s in audio)
        assert float(metadata['format']['duration']) == pytest.approx(2, abs=.1)
        assert atoms(path).index(b'moov') < atoms(path).index(b'mdat')
        subprocess.run([tools['ffmpeg'], '-v', 'error', '-nostdin', '-xerror', '-i', str(path), '-f', 'null', '-'],
                       check=True, timeout=30, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def test_legacy_decoder_fixture_stays_mpeg4(tmp_path, tools):
    path = tmp_path / 'legacy.mp4'
    e2e.smoke_module()._generate(tools['ffmpeg'], path, audio=False)
    result = subprocess.run([tools['ffprobe'], '-v', 'error', '-select_streams', 'v:0',
                             '-show_entries', 'stream=codec_name', '-of', 'json', str(path)],
                            capture_output=True, check=True, timeout=30)
    assert json.loads(result.stdout)['streams'][0]['codec_name'] == 'mpeg4'


@pytest.mark.parametrize('name', ['audio.mp4', 'silent.mp4'])
def test_no_existing_fixture_is_overwritten(tmp_path, tools, name):
    path = tmp_path / name
    path.write_bytes(b'existing-owner')
    with pytest.raises(e2e.AcceptanceError, match='generation_failed'):
        e2e.generate(tmp_path, tools['ffmpeg'])
    assert list(tmp_path.iterdir()) == [path] and path.read_bytes() == b'existing-owner'


@pytest.mark.parametrize('mode', ['ok', 'timeout', 'failed', 'oserror'])
def test_subprocess_is_bounded_safe_and_report_free(tmp_path, monkeypatch, mode):
    tool = tmp_path / 'approved tool'
    tool.write_bytes(b'not-executed')
    monkeypatch.setenv('FFREPORT', 'PRIVATE_REPORT')
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        assert kwargs['timeout'] == 30 and kwargs['shell'] is False
        assert kwargs['stdin'] == kwargs['stdout'] == kwargs['stderr'] == subprocess.DEVNULL
        assert 'FFREPORT' not in kwargs['env'] and os.environ['FFREPORT'] == 'PRIVATE_REPORT'
        assert '-n' in command and '-y' not in command and '-nostdin' in command
        assert command[command.index('-c:v') + 1] == 'libx264'
        if mode == 'timeout':
            raise subprocess.TimeoutExpired('PRIVATE', 30)
        if mode == 'oserror':
            raise OSError('PRIVATE')
        Path(command[-1]).write_bytes(b'synthetic')
        return SimpleNamespace(returncode=1 if mode == 'failed' else 0)

    monkeypatch.setattr(e2e.subprocess, 'run', run)
    if mode == 'ok':
        assert e2e.generate(tmp_path, str(tool)) == [b'synthetic', b'synthetic']
        assert len(calls) == 2
    else:
        with pytest.raises(e2e.AcceptanceError, match='^generation_failed$'):
            e2e.generate(tmp_path, str(tool))
    assert os.environ['FFREPORT'] == 'PRIVATE_REPORT'


def playwright_module():
    override = os.environ.get('REHAB_TEST_PLAYWRIGHT_MODULE')
    candidates = [Path(override)] if override else [ROOT / 'node_modules' / 'playwright']
    cache = Path(os.environ.get('LOCALAPPDATA', Path.home() / '.cache')) / 'npm-cache' / '_npx'
    if not override and cache.is_dir():
        candidates.extend(cache.glob('*/node_modules/playwright'))
    return next((str(path) for path in candidates if (path / 'package.json').is_file()), None)


def test_real_browser_has_video_pixels_and_advancing_time(generated):
    node, module = shutil.which('node'), playwright_module()
    if not node or not module:
        pytest.skip('Installed Node/Playwright unavailable; no download attempted')
    script = r'''
const {chromium} = require(process.argv[1]);
const {readFileSync} = require('node:fs');
(async () => {
  const browser = await chromium.launch({headless: true,
    ...(process.env.REHAB_TEST_BROWSER_EXECUTABLE ? {executablePath: process.env.REHAB_TEST_BROWSER_EXECUTABLE} : {})});
  try {
    const context = await browser.newContext();
    await context.route('**/*', route => route.request().url().startsWith('blob:') ? route.continue() : route.abort());
    const page = await context.newPage();
    const results = [];
    for (const file of process.argv.slice(2)) {
      await page.goto('about:blank');
      await page.setContent('<video muted playsinline></video>');
      await page.evaluate(encoded => {
        const bytes = Uint8Array.from(atob(encoded), c => c.charCodeAt(0));
        document.querySelector('video').src = URL.createObjectURL(new Blob([bytes], {type:'video/mp4'}));
      }, readFileSync(file).toString('base64'));
      await page.waitForFunction(() => document.querySelector('video')?.readyState >= 2, null, {timeout: 15000});
      await page.evaluate(async () => {const v = document.querySelector('video'); v.muted = true; await v.play();});
      await page.waitForFunction(() => document.querySelector('video').currentTime > 0.2, null, {timeout: 10000});
      results.push(await page.evaluate(() => {
        const v = document.querySelector('video');
        const c = document.createElement('canvas'); c.width = v.videoWidth; c.height = v.videoHeight;
        const ctx = c.getContext('2d'); ctx.drawImage(v, 0, 0);
        const pixels = ctx.getImageData(0, 0, c.width, c.height).data;
        let nonblack = 0; for (let i = 0; i < pixels.length; i += 4) nonblack += pixels[i] + pixels[i+1] + pixels[i+2];
        return {width:v.videoWidth, height:v.videoHeight, time:v.currentTime,
          error:v.error?.code ?? null, nonblack, h264:v.canPlayType('video/mp4; codecs="avc1.42E01E"')};
      }));
    }
    console.log(JSON.stringify(results));
  } finally {await browser.close();}
})().catch(error => {console.error(error); process.exitCode = 1;});
'''
    result = subprocess.run([node, '-e', script, module, *(str(path) for path in generated)],
                            capture_output=True, text=True, encoding='utf-8', timeout=60, check=True)
    results = json.loads(result.stdout)
    assert len(results) == 2
    for value in results:
        assert (value['width'], value['height']) == (160, 96)
        assert value['error'] is None and value['time'] > .2 and value['nonblack'] > 0
        assert value['h264'] in ('probably', 'maybe')
