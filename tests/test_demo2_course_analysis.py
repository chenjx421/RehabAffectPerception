import json

import pytest

from rehab_affect.demo2_measurement_store import Demo2MeasurementStore, MeasurementError
from rehab_affect.demo2_evaluation_store import Demo2EvaluationStore
from rehab_affect.demo2_identity_store import IdentityError
from test_demo2_identity_store import (env, make_task, student, binding_payload, login,
                                       OTHER, ADMIN, persist_result)
from test_demo2_measurement_store import _payload
from test_demo2_evaluation_store import payload as evaluation_payload


def ready(env, **changes):
    task = make_task(env)
    from rehab_affect.video_applicability import ApplicabilityStore
    from test_video_applicability import confirm
    confirm(ApplicabilityStore(env.record), task)
    pupil = student(env, student_code='new-analysis')
    binding = env.identity.save_binding(task.token, binding_payload(task, pupil['student_id']))
    store = Demo2MeasurementStore(env.record)
    payload = _payload(pupil['student_id'], source_type='video_review', task_id=task.task_id,
                       start_sec=0, end_sec=3, teacher_prompt='合成分类任务', student_response='合成回应',
                       support_level='visual', observed_state='participating', **changes)
    return store, task, pupil, binding, payload


def test_report_is_task_scoped_and_tracks_teacher_evidence(env):
    store, task, pupil, binding, payload = ready(env)
    before = store.course_workspace(task.token, task.task_id)
    assert store.course_tasks(task.token)['tasks'][0]['task_id']==task.task_id
    assert before['summary']['records']==0
    assert not before['report']['ready']
    value = store.save(task.token, payload)
    assert value['binding_id']==binding['binding_id']
    result = store.course_workspace(task.token, task.task_id)
    assert result['summary']['scored']==1
    assert result['records'][0]['teacher_prompt']=='合成分类任务'
    assert result['report']['ready']
    assert 900 <= result['report']['character_count'] <= 1500
    assert result['people'][0]['student_id']==pupil['student_id']
    store.save(task.token,_payload(pupil['student_id'],record_id='elsewhere',lesson_id='other'))
    assert len(store.course_workspace(task.token,task.task_id)['records'])==1


def test_task_report_joins_dual_track_evaluation_by_task_id(env):
    store, task, pupil, binding, measurement = ready(env)
    store.save(task.token, measurement)
    evaluation = Demo2EvaluationStore(env.record)
    saved = evaluation.save(task.token, evaluation_payload(
        record_id='task-linked-evaluation', lesson_id=task.task_id,
        task_id=task.task_id, frame_revision=task.revision,
    ))

    work = store.course_workspace(task.token, task.task_id)
    assert work['report']['identifiers']['task_id'] == task.task_id
    assert work['report']['identifiers']['evaluation_id'] == saved['evaluation_id']
    assert work['report']['identifiers']['report_id'].startswith('report-')
    dual = next(section for section in work['report']['sections'] if section['title']=='双轨评价对照')
    assert '学校分 8.0' in dual['text']
    assert '系统增强分 7.0' in dual['text']
    assert work['identifiers']['report_id'] == work['report']['report_id']


def test_course_report_download_uses_current_task_report(env):
    store, task, _, _, measurement = ready(env)
    store.save(task.token, measurement)
    report = store.course_report(task.token, task.task_id)
    assert report['task_id'] == task.task_id
    assert report['report_download_url'].endswith('task_id='+task.task_id)
    assert report['full_text']
    assert '双轨评价对照' in report['full_text']


def test_evaluation_accepts_stable_linkage_ids_without_client_evaluation_id(env):
    _, task, _, _, _ = ready(env)
    evaluation = Demo2EvaluationStore(env.record)
    saved = evaluation.save(task.token, evaluation_payload(
        record_id='linked-evaluation', course_id='course-1',
        iep_summary_id='iep-1', report_id='report-placeholder',
        task_id=task.task_id, frame_revision=task.revision,
    ))
    assert saved['course_id'] == 'course-1'
    assert saved['iep_summary_id'] == 'iep-1'
    assert saved['report_id'] == 'report-placeholder'
    assert saved['evaluation_id'] == 'evaluation-linked-evaluation'


@pytest.mark.parametrize('username',[OTHER,ADMIN])
def test_course_analysis_never_allows_other_channel_or_admin_read(env,username):
    store, task, _, _, payload = ready(env)
    store.save(task.token,payload)
    with pytest.raises((IdentityError,MeasurementError)):
        store.course_workspace(login(env,username)[1],task.task_id)


@pytest.mark.parametrize('mutation',['revoke','revision'])
def test_invalid_identity_excludes_scores_and_trends(env,mutation):
    store, task, _, binding, payload = ready(env)
    store.save(task.token,payload)
    if mutation=='revoke':
        with env.record._connect() as db:
            db.execute("UPDATE demo2_identity_bindings SET status='revoked' WHERE binding_id=?",(binding['binding_id'],))
    else:
        changed=json.loads(task.raw);changed['audit_revision']='changed'
        persist_result(env,task.task_id,changed)
    result=store.course_workspace(task.token,task.task_id)
    assert result['summary']['scored']==0
    assert result['records'][0]['evidence_status']=='needs_reconfirmation'
    assert store.workspace(task.token)['trends'][0]['series']['lesson'][0]['score'] is None
    with pytest.raises(MeasurementError):
        store.save(task.token,{**payload,'expected_version':1})


def test_bounds_and_unknown_observation_options_are_rejected(env):
    store,task,_,_,payload=ready(env)
    for updates in ({'end_sec':9},{'observed_state':'autism'},{'support_level':False}):
        with pytest.raises(MeasurementError):
            store.save(task.token,{**payload,**updates})


def test_pending_unknown_dimensions_remain_unscored_and_withdraw_removes_report(env):
    store,task,_,_,payload=ready(env,reviewed=False,scores={})
    store.save(task.token,payload)
    result=store.course_workspace(task.token,task.task_id)
    assert result['summary']['pending']==1
    assert result['summary']['scored']==0
    assert not result['report']['ready']
    store.withdraw(task.token,{'record_id':payload['record_id'],'expected_version':1,'reason':'合成撤销'})
    assert store.course_workspace(task.token,task.task_id)['summary']['records']==0


def test_versions_and_missing_media_do_not_allow_silent_overwrite(env):
    store,task,_,_,payload=ready(env)
    store.save(task.token,payload)
    with pytest.raises(MeasurementError):
        store.save(task.token,payload)
    task.source.unlink()
    with pytest.raises(IdentityError):
        store.save(task.token,{**payload,'expected_version':1})
    result=store.course_workspace(task.token,task.task_id)
    assert result['media_available'] is False
    assert result['records'][0]['evidence']=='合成观察证据'
