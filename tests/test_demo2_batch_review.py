import pytest

from rehab_affect.demo2_measurement_store import MeasurementError
from rehab_affect.demo2_identity_store import IdentityError
from test_demo2_identity_store import env, make_task, binding_payload, login, school, CONTEXT, OTHER, ADMIN
from test_demo2_course_analysis import ready


def test_missing_school_is_readable_but_never_aggregates_or_scores(env):
    store, first, _, _, _ = two_records(env)
    with env.record._connect() as db:
        db.execute("UPDATE video_analysis_tasks SET school_context_json='{}' WHERE task_id=?", (first.task_id,))
    work = store.batch_workspace(first.token, first.task_id)
    assert work['school_context_required'] is True
    assert work['scope_key'] == ''
    assert work['groups'] == work['students'] == []
    assert [task['task_id'] for task in work['tasks']] == [first.task_id]
    assert work['summary']['scored'] == work['summary']['records'] == 0


def two_records(env):
    store,first,pupil,_,payload=ready(env)
    store.save(first.token,payload)
    second=make_task(env)
    from rehab_affect.video_applicability import ApplicabilityStore
    from test_video_applicability import confirm
    confirm(ApplicabilityStore(env.record),second)
    env.identity.save_binding(second.token,binding_payload(second,pupil['student_id']))
    other={**payload,'record_id':'other-video','task_id':second.task_id,'lesson_id':'second-video',
           'scores':dict(accuracy=4,independence=4,consistency=4,transfer=4)}
    store.save(second.token,other)
    return store,first,second,payload,other


def approval(store,task):
    group=store.batch_workspace(task.token,task.task_id)['groups'][0]
    return dict(task_id=task.task_id,group_id=group['group_id'],fingerprint=group['fingerprint'],
        expected_version=group['version'],selected_record_id=group['records'][0]['record_id'],
        reason='选择包含完整提问和独立回应的片段；另一段是同一次机会的重复录像。',confirmed=True)


def test_two_videos_are_not_two_lessons_and_not_averaged(env):
    store,first,_,_,_=two_records(env)
    batch=store.batch_workspace(first.token,first.task_id)
    assert batch['summary']==dict(videos=2,records=2,goals=1,pending=1,scored=0)
    points=store.workspace(first.token)['trends'][0]['series']['lesson']
    assert len(points)==1 and points[0]['score'] is None
    store.confirm_batch(first.token,approval(store,first))
    after=store.batch_workspace(first.token,first.task_id)
    assert after['groups'][0]['score']==6.85
    assert len(after['groups'][0]['records'])==2
    assert after['groups'][0]['selected_record']['opportunities']==3
    points=store.workspace(first.token)['trends'][0]['series']['lesson']
    assert len(points)==1 and points[0]['score']==6.85


@pytest.mark.parametrize('change',['edit','withdraw','identity'])
def test_source_mutations_invalidate_confirmation(env,change):
    store,first,second,payload,other=two_records(env)
    store.confirm_batch(first.token,approval(store,first))
    if change=='edit':
        store.save(first.token,{**payload,'expected_version':1,'evidence':'新补充的课堂证据'})
    elif change=='withdraw':
        store.withdraw(first.token,dict(record_id=other['record_id'],expected_version=1,reason='重复录像'))
    else:
        with env.record._connect() as db:
            db.execute("UPDATE demo2_identity_bindings SET status='revoked' WHERE task_id=?",(second.task_id,))
    group=store.batch_workspace(first.token,first.task_id)['groups'][0]
    assert group['status']=='stale' and group['score'] is None
    assert store.workspace(first.token)['trends'][0]['series']['lesson'][0]['score'] is None


def test_stale_client_and_invalid_selection_cannot_confirm(env):
    store,first,_,payload,_=two_records(env)
    command=approval(store,first)
    for mutation in ({'confirmed':False},{'selected_record_id':'not-in-group'}):
        with pytest.raises(MeasurementError):
            store.confirm_batch(first.token,{**command,**mutation})
    store.save(first.token,{**payload,'expected_version':1,'evidence':'新版证据'})
    with pytest.raises(MeasurementError) as exc:
        store.confirm_batch(first.token,command)
    assert exc.value.code=='source_conflict'


@pytest.mark.parametrize('username',[OTHER,ADMIN])
def test_batch_isolation(env,username):
    store,first,_,_,_=two_records(env)
    token=login(env,username)[1]
    with pytest.raises((MeasurementError,IdentityError)):
        store.batch_workspace(token,first.task_id)
    with pytest.raises((MeasurementError,IdentityError)):
        store.confirm_batch(token,approval(store,first))


def test_different_lesson_dates_do_not_merge(env):
    store,first,_,_,other=two_records(env)
    store.save(first.token,{**other,'expected_version':1,'lesson_date':'2026-09-09'})
    batch=store.batch_workspace(first.token,first.task_id)
    assert batch['summary']['goals']==2
    assert batch['summary']['scored']==2
    assert len(store.workspace(first.token)['trends'][0]['series']['lesson'])==2


def test_same_course_id_under_other_school_is_not_included(env):
    store,first,_,_,_=two_records(env)
    with pytest.raises(ValueError, match='管理员迁移'):
        school(env,context={**CONTEXT,'school_name':'另一所测试学校'})
    with env.record._connect() as db:
        db.execute("UPDATE school_contexts SET school_name=? WHERE account_id=?", ('另一所测试学校', env.record.account_from_session(first.token)['account_id']))
    foreign=make_task(env,set_school=False)
    batch=store.batch_workspace(first.token,first.task_id)
    assert batch['summary']['videos']==2
    assert foreign.task_id not in {t['task_id'] for t in batch['tasks']}


def test_confirmation_history_and_double_submit(env):
    store,first,_,_,_=two_records(env)
    command=approval(store,first)
    store.confirm_batch(first.token,command)
    with pytest.raises(MeasurementError) as exc:
        store.confirm_batch(first.token,command)
    assert exc.value.code=='source_conflict'
    revised=approval(store,first)
    revised['reason']='重新核对后的补充理由'
    store.confirm_batch(first.token,revised)
    with env.record._connect() as db:
        rows=db.execute('SELECT version FROM demo2_batch_decision_versions ORDER BY version').fetchall()
    assert [r['version'] for r in rows]==[1,2]
