import hashlib
import json
import re
import shutil
import subprocess
from contextlib import nullcontext
from pathlib import Path

import numpy as np
import pytest

from rehab_affect.demo2_simple_result import render_simple_result
from rehab_affect.student_record_store import Demo2StudentRecordStore


@pytest.fixture
def portrait_store(tmp_path, monkeypatch):
    cv = pytest.importorskip('cv2')
    frame = tmp_path / 'frames' / 'frame_000000.jpg'
    frame.parent.mkdir()
    image = np.full((240, 480, 3), 220, dtype=np.uint8)
    image[58:135, 198:252] = (20, 30, 230)
    ok, encoded = cv.imencode('.jpg', image)
    assert ok
    frame.write_bytes(encoded.tobytes())
    store = object.__new__(Demo2StudentRecordStore)
    monkeypatch.setattr(store, 'account_from_session', lambda _: {'username': 'synthetic'})
    monkeypatch.setattr(store, '_connect', lambda: nullcontext(None))
    monkeypatch.setattr(store, '_authorized_video_task', lambda *a: {'analysis_status': 'completed'})
    monkeypatch.setattr(store, '_require_live_video', lambda *a: None)
    monkeypatch.setattr(store, '_video_analysis_dir', lambda *a: tmp_path)
    monkeypatch.setattr(store, '_controlled_video_path', lambda path, *a: path)
    monkeypatch.setattr(store, '_audit', lambda *a: None)
    return store, cv, frame


def test_full_head_color_and_source_preserved_with_versioned_cache(portrait_store):
    store, cv, source = portrait_store
    box = dict(x=210/480, y=90/240, width=30/480, height=36/240)
    original = source.read_bytes()
    old_digest = hashlib.sha256(json.dumps(box, sort_keys=True, separators=(',', ':')).encode()).hexdigest()[:16]
    old = source.parent.parent / 'person_crops' / f'frame_000000_{old_digest}.jpg'
    old.parent.mkdir()
    old.write_bytes(b'old partial-head cache')
    crop, mime = store.account_simple_analysis_frame('test', 'task', source.name, box)
    assert crop != old and mime == 'image/jpeg'
    image = cv.imdecode(np.frombuffer(crop.read_bytes(), np.uint8), cv.IMREAD_COLOR)
    red = (image[:, :, 2] > 180) & (image[:, :, 0] < 90)
    rows, cols = np.where(red)
    assert rows.min() >= 3 and rows.max() < image.shape[0] - 3
    assert rows.max() - rows.min() >= 74
    assert cols.max() - cols.min() >= 50
    assert image.shape[1] < 150 and image.shape[0] < 150
    assert source.read_bytes() == original and old.read_bytes() == b'old partial-head cache'
    assert store.account_simple_analysis_frame('test', 'task', source.name, box)[0] == crop


def test_result_page_shows_demo1_states_actions_and_key_moments():
    html = render_simple_result()
    assert "p.lesson_report?.text" in html
    assert "p.action_summary" in html
    assert "stateLabel(w)" in html and "stateLabel(first)" in html
    for label in ("参与", "注意力下降", "困惑·停滞", "成人干扰下不确定", "无法判断"):
        assert label in html
    assert "建议" in html and "需教师确认" in html
    assert "关键片段" in html and "moment-list" in html
    assert "旧版动作线索（仅供回看，不作注意力判断）" in html
    assert "选中人物动作参考值" in html
    assert "const selected=persons[activeIndex]" in html
    assert "观察时间片" in html


@pytest.mark.parametrize('box', [
    dict(x=0, y=0, width=.12, height=.2),
    dict(x=.88, y=.8, width=.12, height=.2),
    dict(x=0, y=0, width=1., height=1.),
])
def test_portrait_at_frame_edges_contains_original_face(portrait_store, box):
    store, cv, source = portrait_store
    crop, _ = store.account_simple_analysis_frame('test', 'task', source.name, box)
    image = cv.imdecode(np.frombuffer(crop.read_bytes(), np.uint8), cv.IMREAD_COLOR)
    assert image.shape[0] >= round(box['height'] * 240)
    assert image.shape[1] >= round(box['width'] * 480)
    assert image.shape[0] <= 240 and image.shape[1] <= 480


@pytest.mark.parametrize('box', [
    {}, dict(x=-.1, y=0, width=.2, height=.2),
    dict(x=0, y=0, width=0, height=.2),
    dict(x=.9, y=0, width=.2, height=.2),
    dict(x=float('nan'), y=0, width=.2, height=.2),
])
def test_invalid_crop_rejected(portrait_store, box):
    store, _, source = portrait_store
    with pytest.raises(ValueError):
        store.account_simple_analysis_frame('test', 'task', source.name, box)


def test_source_preview_is_bounded_cached_and_does_not_replace_evidence(portrait_store, monkeypatch):
    from rehab_affect import demo2_frame_preview
    store, cv, frame = portrait_store
    source = frame.parent.parent / 'synthetic.mp4'
    source.write_bytes(b'synthetic source; decoder stubbed')
    monkeypatch.setattr(store, '_video_source_path', lambda task: source)
    original = frame.read_bytes()
    image = cv.imdecode(np.frombuffer(original, np.uint8), cv.IMREAD_COLOR)
    ok, larger = cv.imencode('.jpg', cv.resize(image, (1920, 960)))
    assert ok
    calls = []
    def preview(path, time):
        calls.append((path, time))
        return {'image_bytes': larger.tobytes()}
    monkeypatch.setattr(demo2_frame_preview, 'extract_preview', preview)
    result = {'segments': [{'visual': {'samples': [{'timestamp_sec': 0}]}}]}
    box = dict(x=210/480, y=90/240, width=30/480, height=36/240)
    derived = store._simple_person_preview({}, result, source.parent, frame, box)
    assert derived != frame and derived.is_file()
    assert store._simple_person_preview({}, result, source.parent, frame, box) == derived
    assert calls == [(source, 0)] and frame.read_bytes() == original
    assert source.read_bytes() == b'synthetic source; decoder stubbed'
    assert store._simple_person_preview({}, {'segments': []}, source.parent, frame, box) == frame


def test_preview_rejects_changed_person_patch(portrait_store, monkeypatch):
    from rehab_affect import demo2_frame_preview
    store, cv, frame = portrait_store
    source = frame.parent.parent / 'synthetic.mp4'
    source.write_bytes(b'synthetic source')
    monkeypatch.setattr(store, '_video_source_path', lambda task: source)
    original = cv.imdecode(np.frombuffer(frame.read_bytes(), np.uint8), cv.IMREAD_COLOR)
    different = cv.resize(original, (1920, 960))
    different[360:504, 840:960] = (240, 240, 240)
    _, encoded = cv.imencode('.jpg', different)
    monkeypatch.setattr(demo2_frame_preview, 'extract_preview', lambda *a: {'image_bytes': encoded.tobytes()})
    result = {'segments': [{'visual': {'samples': [{'timestamp_sec': 0}]}}]}
    box = dict(x=210/480, y=90/240, width=30/480, height=36/240)
    assert store._simple_person_preview({}, result, source.parent, frame, box) == frame


def test_preview_timeout_keeps_original_available_and_releases_lock(portrait_store, monkeypatch):
    from rehab_affect import demo2_frame_preview, student_record_store
    store, _, frame = portrait_store
    source = frame.parent.parent / 'synthetic.mp4'
    source.write_bytes(b'synthetic source')
    monkeypatch.setattr(store, '_video_source_path', lambda task: source)
    def fail(*args):
        raise demo2_frame_preview.PreviewError('timeout', 'test')
    monkeypatch.setattr(demo2_frame_preview, 'extract_preview', fail)
    result = {'segments': [{'visual': {'samples': [{'timestamp_sec': 0}]}}]}
    box = dict(x=.1, y=.1, width=.1, height=.2)
    assert store._simple_person_preview({}, result, source.parent, frame, box) == frame
    assert not student_record_store._PERSON_PREVIEW_LOCK.locked()


def test_browser_helpers_never_render_empty_or_full_scene_portrait():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node required')
    html = render_simple_result()
    script = re.search(r'<script>(.*?)</script>', html, re.S)[1]
    # Evaluate the real helpers without network requests or page startup.
    helpers = script[:script.index('async function savePerson')]
    checks = '''
const assert=require('node:assert/strict');
assert(!frameMarkup({}, 'missing').includes('<img'));
assert(!frameMarkup({frame:'frame_000000.jpg'}, 'unlocated').includes('<img'));
const w={frame:'frame_000000.jpg',bbox:{x:.1,y:.1,width:.1,height:.2}};
assert(simpleFrame(w.frame,w.bbox).includes('crop=person'));
assert.deepEqual(portraitWindow({windows:[{frame:'frame_000001.jpg'},w]}),w);
assert(frameMarkup(w,'person').includes('<img'));
'''
    prelude = "global.document={getElementById:()=>({})};global.location={search:'?task_id=test'};"
    result = subprocess.run([node, '-e', prelude + helpers + checks], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert '.person-tab img,.hero-frame,.event img{object-fit:contain}' in html
