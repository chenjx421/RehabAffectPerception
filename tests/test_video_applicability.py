import pytest
from rehab_affect.video_applicability import ApplicabilityStore
from rehab_affect.demo2_identity_store import IdentityError
from rehab_affect.demo2_measurement_store import Demo2MeasurementStore, MeasurementError
from test_demo2_identity_store import env, make_task, login, OTHER, ADMIN, student, binding_payload, persist_result
from test_demo2_measurement_store import _payload


def confirm(store, task, category='special', **changes):
    state=store.workspace(task.token,task.task_id)
    return store.save(task.token,dict(task_id=task.task_id,version=state['version'],revision=state['revision'],
        category=category,goal='合成课堂的分类目标',reason='人工回看0至3秒及对应教案，仅测试使用',confirmed=True)|changes)


def test_default_never_claims_automatic_classroom_recognition(env):
    task=make_task(env); store=ApplicabilityStore(env.record)
    result=store.workspace(task.token,task.task_id)
    assert not result['allowed'] and result['category']=='pending'
    assert result['automatic_scene_recognition'] is False
    assert result['technical_ready']
    assert any('音轨' in w for w in result['warnings'])


@pytest.mark.parametrize('category',['general','irrelevant','uncertain','insufficient'])
def test_non_special_is_not_scored(env,category):
    task=make_task(env); store=ApplicabilityStore(env.record)
    assert not confirm(store,task,category)['allowed']


def test_visual_communication_can_be_confirmed_without_audio(env):
    task=make_task(env); store=ApplicabilityStore(env.record)
    assert confirm(store,task)['allowed']


def test_revision_and_missing_goal_fail_closed(env):
    task=make_task(env); store=ApplicabilityStore(env.record)
    with pytest.raises(IdentityError): confirm(store,task,goal='')
    with pytest.raises(IdentityError): confirm(store,task,revision='stale')
    with pytest.raises(IdentityError): confirm(store,task,confirmed=False)
    confirm(store,task)
    result=task.result|{'revision_test':1};persist_result(env,task.task_id,result)
    state=store.workspace(task.token,task.task_id)
    assert state['stale'] and not state['allowed']


@pytest.mark.parametrize('user',[OTHER,ADMIN])
def test_other_users_cannot_confirm(env,user):
    task=make_task(env);store=ApplicabilityStore(env.record)
    with pytest.raises(IdentityError):store.workspace(login(env,user)[1],task.task_id)


def test_score_report_and_longitudinal_exclusion(env):
    task=make_task(env); store=ApplicabilityStore(env.record); measurement=Demo2MeasurementStore(env.record)
    pupil=student(env,student_code='scope-qa')
    env.identity.save_binding(task.token,binding_payload(task,pupil['student_id']))
    payload=_payload(pupil['student_id'],source_type='video_review',task_id=task.task_id,start_sec=0,end_sec=2,
                     teacher_prompt='合成指令',student_response='合成指认',support_level='visual',observed_state='participating')
    with pytest.raises(MeasurementError,match='适用性'):measurement.save(task.token,payload)
    draft=measurement.save(task.token,payload|{'scores':{},'reviewed':False})
    assert not measurement.course_workspace(task.token,task.task_id)['report']['ready']
    confirm(store,task)
    measurement.save(task.token,payload|{'expected_version':draft['version']})
    assert measurement.course_workspace(task.token,task.task_id)['summary']['scored']==1
    confirm(store,task,'irrelevant')
    work=measurement.course_workspace(task.token,task.task_id)
    assert work['summary']['scored']==0 and not work['report']['ready']
    assert measurement.workspace(task.token)['trends'][0]['series']['lesson'][0]['score'] is None
    assert measurement.batch_workspace(task.token,task.task_id)['summary']['scored']==0


def test_expired_source_cannot_get_new_confirmation(env):
    task=make_task(env);store=ApplicabilityStore(env.record);task.source.unlink()
    with pytest.raises(IdentityError):confirm(store,task)
