"""Subtask 35: evaluation page 4-step wizard UI and page-side debug events."""
from datetime import date
import json
import re
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from rehab_affect.classroom_rubric import RULE_VERSION, evaluate
from rehab_affect.demo2_evaluation import render_evaluation
from rehab_affect.demo2_evaluation_store import Demo2EvaluationStore
from rehab_affect.demo2_measurement_store import MeasurementError
from rehab_affect.student_record_store import Demo2StudentRecordStore


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv('REHAB_DEMO2_ACCOUNT_PASSWORD_PREFIX', 'Wizard-')
    monkeypatch.setenv('REHAB_DEMO2_EVALUATION_DEBUG_LOG_DIR', str(tmp_path / 'eval_logs'))
    records = Demo2StudentRecordStore(tmp_path / 'wizard.sqlite3', tmp_path / 'documents')
    account = records.authenticate_account('school_uploader_01', 'Wizard-school_uploader_01')
    token = records.create_account_session(account)['token']
    records.save_account_school_context(token, dict(city='测试市', district='测试区', school_name='合成学校'))
    other = records.authenticate_account('school_uploader_02', 'Wizard-school_uploader_02')
    other_token = records.create_account_session(other)['token']
    records.save_account_school_context(other_token, dict(city='测试市', district='测试区', school_name='另一合成学校'))
    return SimpleNamespace(store=Demo2EvaluationStore(records), token=token, other_token=other_token,
                           log_dir=tmp_path / 'eval_logs')


def _payload(**changes):
    items = [dict(id=f'i{i}', school_score=8, enhanced_score=None, evidence='合成观察 00:20', reason='', suggestion='')
             for i in range(1, 11)]
    items[2].update(school_score=None)
    items[0].update(enhanced_score=9, reason='补充证据后复核', suggestion='下一课继续提供回应机会')
    p = dict(record_id='wizard-1', expected_version=0, lesson_id='synthetic-wizard-1',
             lesson_date=date.today().isoformat(), course_name='合成验收 · 分步表单', subject_id='language',
             template_id='basic_100', goal_context='合成案例：允许指认、手势和沟通板回应。',
             school_source='teacher_recorded', school_rater='合成复核员', reviewed=False, items=items,
             weight_policy='school_context')
    p.update(changes)
    return p


def _lines(env):
    out = []
    for path in sorted(env.log_dir.glob('evaluation_debug_*.jsonl')):
        out += [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
    return out


def test_page_has_wizard_steps_item_cards_and_keeps_existing_ids():
    page = render_evaluation({'username': 'school_uploader_01', 'login_alias': 't1'})
    for index in range(1, 5):
        assert f'id="stepBtn{index}"' in page and f'id="stepPanel{index}"' in page
    for label in ('课程基本信息', '课程口径与本课目标', '逐项评分', '核对并保存'):
        assert label in page
    for element in ('stepPrev', 'stepNext', 'reviewSummary', 'sumScored', 'sumSchool10', 'resultInfo',
                    'kSchool', 'kEnhanced', 'kDelta', 'fReviewed', 'previewBtn', 'saveBtn', 'withdrawBtn',
                    'exportJsonBtn', 'printBtn', 'editRecordBtn', 'diffChart', 'refList', 'formMsg'):
        assert f'id="{element}"' in page, element
    assert '评分参考' in page and 'anchorPop_' in page and 'data-autogrow' in page
    assert 'validateStep' in page and 'evaluation_step_invalid' in page and '/evaluations/debug-event' in page
    assert 'goal_contains_student_name' in page and 'showStep(2,true)' in page
    assert '未评' in page and 'tag-support' in page and 'tag-limit' in page
    # Labels in the item-delta chart are rendered in full, never sliced.
    assert '.slice(0,9)' not in page


def test_page_scripts_parse():
    node = shutil.which('node')
    if not node:
        pytest.skip('Installed Node required')
    html = render_evaluation({'username': 'synthetic'})
    scripts = re.findall(r'<script>(.*?)</script>', html, re.S)
    result = subprocess.run([node, '-e', "JSON.parse(require('fs').readFileSync(0,'utf8')).forEach(s=>new Function(s))"],
                            input=json.dumps(scripts), text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr


def test_client_step_invalid_event_logs_step_code_fields_only(env):
    event = env.store.client_debug_event(env.token, dict(
        operation='evaluation_step_invalid', result='blocked', step=1, code='required_missing',
        fields=['fLessonId', 'fCourseName'], template_id='basic_100'))
    assert event['operation'] == 'evaluation_step_invalid' and event['step'] == 1
    line = _lines(env)[-1]
    assert line['source'] == 'client' and line['code'] == 'required_missing'
    assert line['fields'] == ['fLessonId', 'fCourseName'] and line['rule_version'] == RULE_VERSION
    assert 'ts' in line and line['result'] == 'blocked'


def test_client_edit_event_resolves_owned_record_and_drops_foreign_ids(env):
    env.store.save(env.token, _payload())
    env.store.client_debug_event(env.token, dict(operation='evaluation_edit', result='opened', step=3,
                                                 record_id='wizard-1', course_id='course-1'))
    line = _lines(env)[-1]
    assert line['evaluation_id'] == 'evaluation-wizard-1' and line['version'] == 1
    assert line['course_id'] == 'course-1' and line['step'] == 3
    env.store.client_debug_event(env.other_token, dict(operation='evaluation_edit', result='opened', record_id='wizard-1'))
    foreign = _lines(env)[-1]
    assert 'evaluation_id' not in foreign and 'record_id' not in foreign


@pytest.mark.parametrize('bad', [
    dict(operation='evaluation_save', result='ok'),
    dict(operation='evaluation_edit', result='Opened'),
    dict(operation='evaluation_edit', result='ok', step=5),
    dict(operation='evaluation_edit', result='ok', step=True),
    dict(operation='evaluation_edit', result='ok', goal_context='合成目标'),
    dict(operation='evaluation_step_invalid', result='blocked', fields=['含 空格']),
    dict(operation='evaluation_step_invalid', result='blocked', code='Bad Code'),
    dict(operation='evaluation_edit', result='ok', course_id='课程/1'),
    ['not', 'a', 'dict'],
])
def test_client_debug_event_rejects_free_text_and_unknown_fields(env, bad):
    with pytest.raises(MeasurementError) as caught:
        env.store.client_debug_event(env.token, bad)
    assert caught.value.status == 400 and caught.value.code == 'invalid_debug_event'


def test_debug_log_never_contains_goal_evidence_or_rater(env):
    env.store.preview(env.token, _payload())
    env.store.save(env.token, _payload())
    env.store.client_debug_event(env.token, dict(operation='evaluation_step_enter', result='ok', step=4))
    text = '\n'.join(json.dumps(line, ensure_ascii=False) for line in _lines(env))
    for private in ('合成复核员', '允许指认', '合成观察', '补充证据后复核'):
        assert private not in text


def test_unscored_item_is_not_counted_as_zero(env):
    record = env.store.save(env.token, _payload())
    result = record['result']
    assert result['school']['coverage'] == {'scored': 9, 'total': 10}
    assert result['school']['score_10'] is None and result['school']['raw_score'] is None
    third = next(item for item in result['comparison']['items'] if item['id'] == 'i3')
    assert third['school_score'] is None and third['total_delta'] is None
    assert {k: v for k, v in result.items() if k != 'evaluation_id'} == evaluate({**_payload(), 'reviewed': False})


def test_debug_event_requires_teacher_session(env):
    with pytest.raises(MeasurementError) as caught:
        env.store.client_debug_event('not-a-token', dict(operation='evaluation_edit', result='ok'))
    assert caught.value.status == 401
