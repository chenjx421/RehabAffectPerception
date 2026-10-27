import json
from pathlib import Path

import numpy as np
import pytest

from rehab_affect import demo2_student_tracking as tracking


def face(x):
    return dict(bbox=dict(x=x, y=.25, width=.07, height=.12), score=.95)


@pytest.fixture
def scene(tmp_path):
    cv = pytest.importorskip('cv2')
    root = tmp_path / 'frames'
    root.mkdir()
    image = np.full((180, 320, 3), 210, np.uint8)
    image[35:130, 40:100] = (40, 30, 100)
    image[35:130, 210:270] = (90, 170, 30)
    cv.line(image, (40, 36), (90, 110), (200, 50, 70), 3)
    cv.line(image, (211, 36), (251, 110), (50, 40, 200), 3)
    def make(count, *, moving=False, scene_cut=False):
        for i in range(count):
            frame = image.copy()
            if moving:
                cv.rectangle(frame, (50+i%10, 65), (60+i%10, 90), (100, 150, 160), -1)
            if scene_cut and i >= 30:
                frame[:] = 0
            _, encoded = cv.imencode('.jpg', frame)
            (root / f'frame_{i:06d}.jpg').write_bytes(encoded.tobytes())
        return dict(root=str(root), duration=count,
                    samples=[dict(frame=f'frame_{i:06d}.jpg', time=i) for i in range(count)])
    return make


def test_missed_left_face_does_not_steal_right_face(scene):
    calls = []
    def detect(image):
        calls.append(1)
        # The left student is often missed but still confirmed periodically;
        # a one-off detection that never returns is a rejected candidate.
        return [face(.68), face(.18)] if len(calls) % 3 else [face(.68)]
    result = tracking.analyze(scene(65, moving=True), detect)
    left, right = result['persons']
    assert left['anchor_bbox']['x'] < right['anchor_bbox']['x']
    assert all(w['bbox']['x'] < .3 for w in left['windows'] if w['bbox'])
    assert all(w['bbox']['x'] > .6 for w in right['windows'] if w['bbox'])
    assert all(w['frame'] for w in left['windows'])
    assert left['windows'][0]['movement'] > right['windows'][0]['movement']
    for person in (left, right):
        for window in person['windows']:
            assert window['state'] in tracking.STUDENT_STATE_LABELS
            assert not window['state'].startswith('movement_')
            assert 'robot_motion' not in window['recommended_action']


def test_full_timeline_keeps_every_window_and_same_time_image(scene):
    result = tracking.analyze(scene(121), lambda _: [face(.18), face(.68)])
    assert result['observed_frames'] == 121
    for person in result['persons']:
        assert len(person['windows']) == 5
        for w in person['windows']:
            assert w['frame']
            assert w['start_sec'] <= w['frame_time_sec'] < w['end_sec']
            assert int(Path(w['frame']).stem.split('_')[1]) == w['frame_time_sec']
    assert result['persons'][1]['windows'][0]['movement'] == 0


def test_person_reports_are_independent_and_motion_is_not_attention(scene):
    request = scene(65, moving=True)
    result = tracking.analyze(request, lambda _: [face(.18), face(.68)])
    assert result['analysis_version'] == tracking.VERSION
    assert result['network_used'] is False
    left, right = result['persons']
    assert left['average_score'] > right['average_score']
    assert left['observation_roi'] != right['observation_roi']
    for person in result['persons']:
        report = person['lesson_report']
        assert report['character_count'] >= 300
        assert report['character_count'] == len(report['text'])
        assert person['action_summary']
        assert all(window['state'] in tracking.STUDENT_STATE_LABELS for window in person['windows'])
        assert all('action_id' in window['recommended_action'] for window in person['windows'])
        assert all('robot_motion' not in window['recommended_action'] for window in person['windows'])
        assert person['key_moments'] and len(person['key_moments']) <= 6
        assert sum(person['state_summary']['counts'].values()) == len(person['windows'])
        assert all(window.get('teacher_confirmation_required') is not None
                   or 'teacher_confirmation_required' in window['recommended_action']
                   for window in person['windows'])
        assert '不能单凭运动强度判成走神' in report['text']
        assert '这份小结的边界' in report['text']
        assert '不代表他全程在场' in report['text'] and '身份也没有做人脸核验' in report['text']
        assert '操场多人动作练习' not in report['text']
    assert left['lesson_report']['text'] != right['lesson_report']['text']
    assert '不是成绩，也不是注意力分数' in result['score_note']
    assert '不能单凭运动强度判成走神' in result['score_note']
    assert result['classroom_rhythm']['window_count'] >= 1
    assert len(result['support_conclusions']['conclusions']) == 3
    assert result['support_conclusions']['next_lesson']
    assert result['support_conclusions']['profile']['attached'] is False


def test_legacy_motion_presentation_preserves_source_evidence_and_ignores_other_engines(scene):
    from copy import deepcopy
    result = tracking.analyze(scene(65, moving=True), lambda _: [face(.18), face(.68)])
    legacy = deepcopy(result)
    aliases = {'movement_high': 'active_response', 'movement_moderate': 'engaged', 'movement_low': 'low_response'}
    for person in legacy['persons']:
        person.pop('lesson_report')
        for window in person['windows']:
            window['state'] = aliases.get(window['state'], window['state'])
    legacy['analysis_version'] = 'simple_student_seats_v3_6'
    original = deepcopy(legacy)
    presented = tracking.present_motion_analysis(legacy)
    assert legacy == original
    assert presented['report_version'] == tracking.REPORT_VERSION
    for before, after in zip(legacy['persons'], presented['persons']):
        assert after['average_score'] == before['average_score']
        assert after['anchor_bbox'] == before['anchor_bbox']
        assert after['observation_roi'] == before['observation_roi']
        for a, b in zip(before['windows'], after['windows']):
            scratch = {'state', 'state_zh', 'evidence', 'recommended_action', 'interpretation'}
            assert {k: v for k, v in a.items() if k not in scratch} == {
                k: v for k, v in b.items() if k not in scratch}
    assert tracking.present_motion_analysis(presented) == presented
    other = dict(legacy, analysis_version='different_attention_engine')
    assert tracking.present_motion_analysis(other) == other
    legacy['persons'][0]['windows'][0]['state'] = 'low_attention'
    assert tracking.present_motion_analysis(legacy) == legacy


def test_camera_cut_never_relabels_another_person(scene):
    result = tracking.analyze(scene(65, scene_cut=True), lambda _: [face(.18), face(.68)])
    for p in result['persons']:
        assert p['windows'][0]['frame']
        assert p['windows'][1]['frame']
        assert p['windows'][1]['score'] is None
        assert p['windows'][1]['state'] == 'uncertain'


def test_sparse_input_not_claimed_as_absence(scene):
    request = scene(65)
    request['samples'] = request['samples'][:10] + request['samples'][60:]
    result = tracking.analyze(request, lambda _: [face(.18)])
    window = result['persons'][0]['windows'][1]
    assert window['state'] == 'uncertain'
    assert '未采样' in window['evidence']


def test_no_transitive_position_drift_and_no_seat_crossing():
    anchor = face(.4)['bbox']
    roi = tracking.seat_regions([anchor, face(.5)['bbox']])[0]
    assert tracking.face_in_seat(face(.41), anchor, roi)
    assert not tracking.face_in_seat(face(.5), anchor, roi)
    assert not tracking.face_in_seat(face(.7), anchor, roi)


def test_no_faces_has_current_version(scene):
    result = tracking.analyze(scene(10), lambda _: [])
    assert result['analysis_version'] == tracking.VERSION
    assert not result['available']


def test_invalid_times_and_paths_rejected(scene):
    request = scene(3)
    request['samples'][1]['time'] = float('nan')
    with pytest.raises(ValueError):
        tracking.analyze(request, lambda _: [])
    request = scene(3)
    request['samples'][0]['frame'] = '../private.jpg'
    with pytest.raises(ValueError):
        tracking.analyze(request, lambda _: [])


def test_one_off_face_on_static_background_is_not_reported_as_a_student(scene):
    calls = []

    def detect(image):
        calls.append(1)
        return [face(.4)] if len(calls) == 1 else []

    result = tracking.analyze(scene(65), detect)
    assert result['available'] is False
    assert result['reason'] == 'no_persistent_students'
    assert result['persons'] == []
    assert result['excluded_candidates']
    assert result['excluded_candidates'][0]['face_confirmation_ratio'] < 0.08
    assert '教师机' in result['message']
