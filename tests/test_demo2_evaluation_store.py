from copy import deepcopy
from datetime import date, timedelta
from types import SimpleNamespace
import pytest

from rehab_affect.demo2_evaluation_store import Demo2EvaluationStore
from rehab_affect.demo2_measurement_store import MeasurementError
from rehab_affect.student_record_store import Demo2StudentRecordStore


@pytest.fixture
def env(tmp_path,monkeypatch):
    monkeypatch.setenv('REHAB_DEMO2_ACCOUNT_PASSWORD_PREFIX','DualTest-')
    records=Demo2StudentRecordStore(tmp_path/'dual.sqlite3',tmp_path/'documents')
    tokens={}
    for key,user in [('t1','school_uploader_01'),('t2','school_uploader_02'),('admin','company_admin')]:
        account=records.authenticate_account(user,'DualTest-'+user)
        tokens[key]=records.create_account_session(account)['token']
        if key!='admin':records.save_account_school_context(tokens[key],dict(city='测试市',district='测试区',school_name='合成学校'))
    return SimpleNamespace(records=records,store=Demo2EvaluationStore(records),tokens=tokens)


def payload(**changes):
    p=dict(record_id='fixture-1',expected_version=0,lesson_id='class-1',lesson_date=date.today().isoformat(),course_name='合成数学课',
        subject_id='math',template_id='basic_100',goal_context='在约定支持下完成三次实物分类；仅合成记录',
        school_source='teacher_recorded',school_rater='合成评课人',reviewed=True,
        items=[dict(id=f'i{i}',school_score=8,enhanced_score=7,evidence='课堂观察\n00:20 提供回应机会',reason='补充证据后复核调整',suggestion='下一课安排独立回应机会') for i in range(1,11)])
    p.update(changes);return p


def test_preview_is_read_only_save_reopens_and_snapshots(env):
    preview=env.store.preview(env.tokens['t1'],payload())
    assert preview['school']['raw_score']==80
    assert preview['school']['teaching_score_70']==56
    assert preview['enhanced']['score_10']==7
    assert preview['comparison']['total_delta']==-1
    assert env.store.workspace(env.tokens['t1'])['records']==[]
    saved=env.store.save(env.tokens['t1'],payload())
    assert saved['version']==1 and saved['result']==preview
    assert saved['rule_snapshot']['templates'][0]['items'][0]['enhanced_weight']==.15
    reopened=Demo2EvaluationStore(env.records)
    assert reopened.workspace(env.tokens['t1'])['records']==[saved]


def test_context_proposals_survive_reload_then_teacher_review(env):
    p = payload(weight_policy='school_context', reviewed=False)
    saved = env.store.save(env.tokens['t1'], p)
    assert saved['result']['enhanced']['score_10'] == 8
    assert saved['result']['context_review']['pending_count'] == 10
    reopened = Demo2EvaluationStore(env.records).workspace(env.tokens['t1'])['records'][0]
    assert reopened['items'][0]['enhanced_score'] == 7
    p.update(expected_version=1, reviewed=True)
    confirmed = env.store.save(env.tokens['t1'], p)
    assert confirmed['result']['enhanced']['score_10'] == 7
    assert confirmed['result']['comparison']['weight_delta'] == 0


def test_optimistic_version_audit_and_configuration_lock(env):
    first=env.store.save(env.tokens['t1'],payload())
    second=env.store.save(env.tokens['t1'],payload(expected_version=1,course_name='修订名称'))
    assert second['version']==2
    assert second['created_at']==first['created_at']
    with pytest.raises(MeasurementError,match='已更新'):
        env.store.save(env.tokens['t1'],payload(expected_version=1))
    for changes in [dict(subject_id='language'),dict(goal_context='改变难度'),dict(lesson_id='other'),dict(lesson_date=(date.today()-timedelta(days=1)).isoformat())]:
        with pytest.raises(MeasurementError) as exc:
            env.store.save(env.tokens['t1'],payload(expected_version=2,**changes))
        assert exc.value.code=='configuration_locked'
    with env.records._connect() as db:
        assert db.execute('SELECT COUNT(*) FROM demo2_classroom_evaluation_versions').fetchone()[0]==2


def test_scopes_admin_denial_and_cross_account_collision(env):
    env.store.save(env.tokens['t1'],payload())
    assert env.store.workspace(env.tokens['t2'])['records']==[]
    for method,args in [('save',(payload(),)),('preview',(payload(),)),('withdraw',(dict(record_id='fixture-1',expected_version=1,reason='test'),))]:
        with pytest.raises(MeasurementError) as exc:getattr(env.store,method)(env.tokens['t2'],*args)
        assert exc.value.status==404
    for method,args in [('workspace',()),('save',(payload(),)),('preview',(payload(),))]:
        with pytest.raises(MeasurementError) as exc:getattr(env.store,method)(env.tokens['admin'],*args)
        assert exc.value.status==403
    with pytest.raises(MeasurementError) as exc:env.store.workspace('invalid')
    assert exc.value.status==401


def test_withdraw_preserves_history_and_allows_new_record(env):
    env.store.save(env.tokens['t1'],payload())
    with pytest.raises(MeasurementError) as exc:env.store.save(env.tokens['t1'],payload(record_id='fixture-2'))
    assert exc.value.code=='duplicate_lesson'
    result=env.store.withdraw(env.tokens['t1'],dict(record_id='fixture-1',expected_version=1,reason='录入有误'))
    assert result['version']==2 and result['status']=='withdrawn'
    assert env.store.workspace(env.tokens['t1'])['records']==[]
    env.store.save(env.tokens['t1'],payload(record_id='fixture-2'))
    with pytest.raises(MeasurementError):env.store.save(env.tokens['t1'],payload(expected_version=2))
    with env.records._connect() as db:
        assert db.execute('SELECT COUNT(*) FROM demo2_classroom_evaluation_versions').fetchone()[0]==3


@pytest.mark.parametrize('changes',[
    {'expected_version':True},{'expected_version':-1},{'reviewed':'true'},{'school_rater':''},
    {'school_source':'rubric_initial','school_rater':'伪造教师来源'},
    {'lesson_date':'2099-01-01'},{'lesson_date':'2026-1-1'}, {'subject_id':'unknown'},
    {'template_id':'missing'}, {'score_10':10},{'weights':[1]*10},{'goal_context':''},
])
def test_invalid_input_rejected_without_persistence(env,changes):
    with pytest.raises(MeasurementError):env.store.save(env.tokens['t1'],payload(**changes))
    assert not env.store.workspace(env.tokens['t1'])['records']


def test_draft_missing_scores_and_preliminary_provenance(env):
    p=payload(reviewed=False,school_source='rubric_initial',school_rater='')
    p['items'][0]['school_score']=None
    p['items'][0]['enhanced_score']=None
    p['items'][0]['evidence']=''
    saved=env.store.save(env.tokens['t1'],p)
    assert saved['result']['status']=='incomplete'
    assert saved['result']['school']['score_10'] is None
    assert saved['result']['school']['passed'] is None
    assert saved['result']['enhanced']['passed'] is None
    assert saved['result']['comparison']['total_delta'] is None


def test_school_change_hides_prior_scope_and_denies_edit(env):
    env.store.save(env.tokens['t1'],payload())
    env.records.save_account_school_context(env.tokens['t1'],dict(city='测试市',district='测试区',school_name='其他学校'))
    assert env.store.workspace(env.tokens['t1'])['records']==[]
    with pytest.raises(MeasurementError) as exc:env.store.save(env.tokens['t1'],payload(expected_version=1))
    assert exc.value.status==404
