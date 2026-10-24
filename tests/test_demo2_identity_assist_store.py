"""Teacher corrections and short tracking seeds use disposable, scoped fixtures."""

import copy
import json

import pytest

from rehab_affect.demo2_identity_store import Demo2IdentityStore, IdentityError
from test_demo2_identity_store import (
    ADMIN, BOX, OTHER, binding_payload, env, login, make_task, persist_result, student,
)


def test_partial_overlap_requires_explicit_boolean_and_survives_restart(env):
    task = make_task(env)
    first, second = student(env), student(env)
    a = env.identity.save_binding(task.token, binding_payload(task, first['student_id']))
    payload = binding_payload(task, second['student_id'], bbox={**BOX, 'x': 0.12})
    with pytest.raises(IdentityError, match='重叠'):
        env.identity.save_binding(task.token, payload)
    b = env.identity.save_binding(task.token, {**payload, 'overlap_confirmed': True})
    assert not a['overlap_confirmed'] and b['overlap_confirmed'] is True
    env.identity = Demo2IdentityStore(env.record)
    saved = env.identity.workspace(task.token, task.task_id)['bindings']
    assert {row['binding_id']: row['overlap_confirmed'] for row in saved}[b['binding_id']]


@pytest.mark.parametrize('value', [1, 0, 'true', None, [], {}])
def test_overlap_confirmation_cannot_be_truthy_coerced(env, value):
    task = make_task(env)
    pupil = student(env)
    with pytest.raises(IdentityError) as error:
        env.identity.save_binding(task.token, binding_payload(task, pupil['student_id'], overlap_confirmed=value))
    assert error.value.code == 'invalid_overlap_confirmation'
    assert env.identity.workspace(task.token, task.task_id)['bindings'] == []


def test_identical_region_and_same_student_never_overridden(env):
    task = make_task(env)
    first, second = student(env), student(env)
    env.identity.save_binding(task.token, binding_payload(task, first['student_id']))
    for pupil, code in [(first, 'duplicate_student_binding'), (second, 'indistinguishable_student_binding')]:
        with pytest.raises(IdentityError) as error:
            env.identity.save_binding(task.token, binding_payload(task, pupil['student_id'], overlap_confirmed=True))
        assert error.value.code == code


def tracked(env, *, count=10, role='student'):
    task = make_task(env, count=count)
    pupil = student(env) if role == 'student' else None
    saved = env.identity.save_binding(task.token, binding_payload(task, pupil['student_id'] if pupil else None))
    payload = {'task_id': task.task_id, 'binding_id': saved['binding_id'], 'frame_revision': task.revision}
    return task, saved, payload


def test_tracking_seed_is_bounded_to_existing_five_seconds_without_writes(env):
    task, saved, payload = tracked(env)
    before = env.identity.workspace(task.token, task.task_id)['bindings']
    seed = env.identity.tracking_seed(task.token, payload)
    assert seed['bbox'] == BOX
    assert len(seed['frames']) == 6
    assert [frame['time_sec'] for frame in seed['frames']] == list(range(6))
    assert all(frame['path'].is_file() for frame in seed['frames'])
    assert env.identity.workspace(task.token, task.task_id)['bindings'] == before


@pytest.mark.parametrize('who', [OTHER, ADMIN])
def test_tracking_seed_rejects_another_owner_and_readonly_admin(env, who):
    task, _, payload = tracked(env)
    with pytest.raises(IdentityError) as error:
        env.identity.tracking_seed(login(env, who)[1], payload)
    assert error.value.status in {403, 404}


def test_tracking_rejects_revoked_seed(env):
    task, saved, payload = tracked(env)
    env.identity.revoke_binding(task.token, {'task_id': task.task_id, 'binding_id': saved['binding_id'], 'reason': '重新核对'})
    with pytest.raises(IdentityError) as error:
        env.identity.tracking_seed(task.token, payload)
    assert error.value.code == 'tracking_seed_unavailable'


def test_tracking_rejects_unknown_identity(env):
    task, _, payload = tracked(env, role='unknown')
    with pytest.raises(IdentityError) as error:
        env.identity.tracking_seed(task.token, payload)
    assert error.value.code == 'tracking_seed_unavailable'


def test_tracking_requires_same_frame_revision(env):
    task, _, payload = tracked(env)
    result = json.loads(task.raw)
    result['changed'] = True
    persist_result(env, task.task_id, result)
    with pytest.raises(IdentityError) as error:
        env.identity.tracking_seed(task.token, payload)
    assert error.value.status == 409


def test_single_frame_source_returns_only_seed_for_insufficient_result(env):
    task, _, payload = tracked(env, count=1)
    assert len(env.identity.tracking_seed(task.token, payload)['frames']) == 1


@pytest.fixture()
def handler(tmp_path, monkeypatch):
    from rehab_affect import scenario_lab_server as backend
    monkeypatch.setattr(backend, 'get_demo2_student_store', lambda: object())
    return backend.create_handler(scenario_dir=tmp_path, model_path=tmp_path / 'unused', policy_name='rule')


def result_fixture():
    frames = [{'frame_key': 's0_f0', 'time_sec': 0}, {'frame_key': 's0_f1', 'time_sec': 1}]
    seed = {'bbox': dict(BOX), 'frames': frames}
    result = {'status': 'completed', 'points': [{**frame, 'bbox': dict(BOX), 'status': 'seed' if i == 0 else 'suggested', 'quality': .8, 'reason': 'seed' if i == 0 else 'tracked'} for i, frame in enumerate(frames)]}
    return seed, result


def test_tracking_result_strips_internal_fields_and_unsuitable_reasons(handler):
    seed, result = result_fixture()
    result['points'][1].update(reason='D:/private/student.jpg', raw_path='private', diagnostic='private')
    clean = handler._validated_track_points(result, seed)
    assert set(clean[1]) == {'frame_key', 'time_sec', 'bbox', 'status', 'quality', 'reason'}
    assert clean[1]['reason'] == 'manual_review_required'


@pytest.mark.parametrize('mutation', [
    lambda r: r.update(status='fake'),
    lambda r: r.update(points=[]),
    lambda r: r.update(points=r['points'][:1]),
    lambda r: r.update(status='lost'),
    lambda r: r.update(status='insufficient'),
    lambda r: r['points'][0].update(status='suggested'),
    lambda r: r['points'][1].update(status='seed'),
    lambda r: r['points'][1].update(frame_key='another'),
    lambda r: r['points'][1].update(time_sec=100),
    lambda r: r['points'][1].update(quality=float('nan')),
    lambda r: r['points'][1].update(quality=True),
    lambda r: r['points'][1].update(bbox=None),
    lambda r: r['points'][1]['bbox'].update(x=.9),
    lambda r: r['points'][1]['bbox'].update(width=0),
    lambda r: r['points'][1]['bbox'].update(x=True),
])
def test_tracking_result_rejects_inconsistent_or_unbounded_output(handler, mutation):
    from rehab_affect.scenario_lab_server import Demo2APIError
    seed, result = result_fixture()
    mutation(result)
    with pytest.raises(Demo2APIError) as error:
        handler._validated_track_points(result, seed)
    assert error.value.code == 'invalid_tracking_result'


def test_tracking_stops_on_loss_and_handles_insufficient(handler):
    seed, result = result_fixture()
    result['status'] = 'lost'
    result['points'][1].update(status='lost', bbox=None, quality=None)
    assert handler._validated_track_points(result, seed)[-1]['bbox'] is None
    result.update(status='insufficient', points=result['points'][:1])
    assert len(handler._validated_track_points(result, seed)) == 1
