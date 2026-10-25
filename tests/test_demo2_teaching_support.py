import json

import pytest

from test_demo2_identity_store import env, login, OTHER, ADMIN
from test_demo2_course_analysis import ready
from rehab_affect.demo2_measurement_store import MeasurementError
from rehab_affect.demo2_identity_store import IdentityError


def plan(tid, **changes):
    return dict(task_id=tid, expected_version=0, need='communication', lesson_date='2026-09-01',
                goal='分类', strength='提供图卡', next_action='保留等待时间', outcome='',
                next_check='核对三次回应', **changes)


def test_support_plan_version_and_private_preview(env):
    store,task,_,_,payload=ready(env)
    store.save(task.token,payload)
    assert store.save_support_plan(task.token,plan(task.task_id))['version']==1
    work=store.support_workspace(task.token,task.task_id)
    assert work['plan']['version']==1
    assert work['readiness'][3]['done']
    assert not work['deepseek']['network_enabled']
    assert not work['preview']['network_sent']
    assert '合成回应' not in json.dumps(work['preview'],ensure_ascii=False)
    with pytest.raises(MeasurementError):
        store.save_support_plan(task.token,plan(task.task_id))


@pytest.mark.parametrize('user',[OTHER,ADMIN])
def test_support_is_scoped(env,user):
    store,task,_,_,_=ready(env)
    with pytest.raises((IdentityError,MeasurementError)):
        store.support_workspace(login(env,user)[1],task.task_id)
    with pytest.raises((IdentityError,MeasurementError)):
        store.save_support_plan(login(env,user)[1],plan(task.task_id))


def test_missing_audio_does_not_lower_score_or_identify_speaker(env):
    store,task,_,binding,payload=ready(env)
    first=store.save(task.token,payload)
    second=store.save(task.token,{**payload,'expected_version':1,'audio_quality':'missing',
        'response_mode':'aac','vocalization':'other','speaker_confirmed':False})
    assert first['assessment']['overall_score']==second['assessment']['overall_score']
    assert second['vocalization_scope']=='scene_unknown_speaker'
    with env.record._connect() as db:
        db.execute("UPDATE demo2_identity_bindings SET status='revoked' WHERE binding_id=?",(binding['binding_id'],))
    assert not store.support_workspace(task.token,task.task_id)['readiness'][3]['done']


def test_invalid_audio_and_future_plan_rejected(env):
    store,task,_,_,payload=ready(env)
    with pytest.raises(MeasurementError):
        store.save(task.token,{**payload,'audio_quality':'diagnosed'})
    with pytest.raises(MeasurementError):
        store.save_support_plan(task.token,{**plan(task.task_id),'lesson_date':'2099-01-01'})
