"""Subtask 6: classroom dual-track evaluation (school + enhanced + delta)."""
from datetime import date
import json
from types import SimpleNamespace

import pytest

from rehab_affect.classroom_rubric import RULE_VERSION, TEMPLATES
from rehab_affect.demo2_evaluation import render_evaluation
from rehab_affect.demo2_evaluation_store import LOCKED_FIELDS, Demo2EvaluationStore
from rehab_affect.demo2_measurement_store import MeasurementError
from rehab_affect.student_record_store import Demo2StudentRecordStore

_STUDENT_SCORE_HINTS = ('student_score', 'ability_score', 'student_ability')


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv('REHAB_DEMO2_ACCOUNT_PASSWORD_PREFIX', 'DualTrack-')
    monkeypatch.setenv('REHAB_DEMO2_EVALUATION_DEBUG_LOG_DIR', str(tmp_path / 'eval_logs'))
    records = Demo2StudentRecordStore(tmp_path / 'dual.sqlite3', tmp_path / 'documents')
    account = records.authenticate_account('school_uploader_01', 'DualTrack-school_uploader_01')
    token = records.create_account_session(account)['token']
    records.save_account_school_context(token, dict(city='测试市', district='测试区', school_name='合成学校'))
    return SimpleNamespace(records=records, store=Demo2EvaluationStore(records), token=token,
                           log_dir=tmp_path / 'eval_logs')


def payload(**changes):
    items = [dict(id=f'i{i}', school_score=8, enhanced_score=None, evidence='合成观察 00:20', reason='', suggestion='')
             for i in range(1, 11)]
    items[0].update(enhanced_score=9, reason='补充证据后复核', suggestion='下一课继续提供回应机会')
    p = dict(record_id='dual-1', expected_version=0, lesson_id='synthetic-context-20260929',
             lesson_date=date.today().isoformat(), course_name='合成验收 · 情境复核课堂', subject_id='language',
             template_id='basic_100', goal_context='合成案例：允许指认、手势和沟通板回应。',
             school_source='teacher_recorded', school_rater='合成复核员', reviewed=True, items=items,
             weight_policy='school_context')
    p.update(changes)
    return p


def _log_lines(env):
    lines = []
    for path in sorted(env.log_dir.glob('evaluation_debug_*.jsonl')):
        lines += [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
    return lines


def _walk_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


def test_ordinary_lesson_uses_school_score_as_baseline_and_deltas_match():
    from rehab_affect.classroom_rubric import evaluate
    result = evaluate(payload())
    template = TEMPLATES['basic_100']
    assert result['school']['score_10'] == 8
    assert result['enhanced']['score_10'] == pytest.approx(8.1)
    assert result['enhanced']['reference_line'] == 6
    assert result['enhanced']['coverage'] == dict(scored=10, total=10)
    comparison = result['comparison']
    assert comparison['total_delta'] == pytest.approx(result['enhanced']['score_10'] - result['school']['score_10'])
    assert comparison['evidence_delta'] == pytest.approx(0.1)
    assert comparison['weight_delta'] == 0
    assert len(comparison['items']) == len(template['items'])
    # Ordinary lesson: every category keeps the school weight as its enhanced weight.
    assert all(c['school_weight'] == pytest.approx(c['enhanced_weight']) for c in result['categories'])


def test_save_persists_evaluation_id_links_and_has_no_student_scores(env):
    saved = env.store.save(env.token, payload())
    assert saved['evaluation_id'] == 'evaluation-dual-1'
    assert saved['version'] == 1 and saved['result']['rule_version'] == RULE_VERSION
    assert saved['result']['status'] == 'reviewed'
    assert {'course_id', 'video_task_id', 'task_id', 'evaluation_id'} <= set(saved)
    assert saved['video_task_id'] == saved['task_id']
    assert saved['evaluation_scope'] == 'classroom'
    reopened = Demo2EvaluationStore(env.records).workspace(env.token)['records'][0]
    assert reopened['evaluation_id'] == saved['evaluation_id']
    with env.records._connect() as db:
        stored = json.loads(db.execute('SELECT payload_json FROM demo2_classroom_evaluations').fetchone()[0])
    assert stored['evaluation_id'] == 'evaluation-dual-1'
    for value in (saved, reopened, stored):
        keys = set(_walk_keys(value))
        assert not any(hint in key for key in keys for hint in _STUDENT_SCORE_HINTS)


def test_configuration_is_locked_after_save(env):
    env.store.save(env.token, payload())
    for change in (dict(subject_id='math'), dict(weight_policy='common')):
        with pytest.raises(MeasurementError) as exc:
            env.store.save(env.token, payload(expected_version=1, **change))
        assert exc.value.code == 'configuration_locked'
    # A different template has different items, so item validation rejects it first.
    with pytest.raises(MeasurementError):
        env.store.save(env.token, payload(expected_version=1, template_id='qingpu_15'))
    record = env.store.workspace(env.token)['records'][0]
    assert record['template_id'] == 'basic_100' and record['version'] == 1
    assert {'subject_id', 'template_id', 'weight_policy'} <= set(LOCKED_FIELDS)


def test_debug_log_covers_create_lock_review_compute_and_rejection(env):
    env.store.preview(env.token, payload())
    env.store.save(env.token, payload(reviewed=False))
    env.store.save(env.token, payload(expected_version=1))
    with pytest.raises(MeasurementError):
        env.store.save(env.token, payload(expected_version=2, subject_id='math'))
    env.store.withdraw(env.token, dict(record_id='dual-1', expected_version=2, reason='合成撤销'))
    lines = _log_lines(env)
    operations = [line['operation'] for line in lines]
    for name in ('dual_track_compute', 'evaluation_create', 'evaluation_save', 'evaluation_lock',
                 'evaluation_review', 'evaluation_rejected', 'evaluation_withdraw'):
        assert name in operations, name
    compute = [l for l in lines if l['operation'] == 'dual_track_compute' and l.get('phase') == 'save'][-1]
    assert compute['evaluation_id'] == 'evaluation-dual-1'
    assert compute['template_id'] == 'basic_100' and compute['rule_version'] == RULE_VERSION
    assert compute['school_score'] == 8 and compute['enhanced_score'] == pytest.approx(8.1)
    assert compute['total_delta'] == pytest.approx(0.1) and compute['status'] == 'reviewed'
    assert all('ts' in line and 'result' in line for line in lines)
    review = [l for l in lines if l['operation'] == 'evaluation_review'][-1]
    assert review['result'] == 'reviewed' and review['reviewed'] is True
    blocked = [l for l in lines if l['operation'] == 'evaluation_lock' and l['result'] == 'blocked'][-1]
    assert blocked['locked_fields'] == ['subject_id']
    text = '\n'.join(json.dumps(line, ensure_ascii=False) for line in lines)
    for private in ('合成复核员', '允许指认', '合成观察'):
        assert private not in text


def test_page_has_required_fields_tabs_and_enhanced_notice():
    page = render_evaluation({'username': 'school_uploader_01', 'login_alias': 't1'})
    for field in ('fLessonId', 'fLessonDate', 'fCourseName', 'fSubject', 'fTemplate', 'fGoalContext', 'fSchoolSource'):
        assert f'id="{field}"' in page
        assert f'["{field}",' in page
    assert 'validateRequired' in page and 'aria-invalid' in page and 'focusInvalid' in page
    for tab in ('学校标准', '系统增强', '双轨对照', '文献依据'):
        assert f'>{tab}</button>' in page
    for text in ('增强得分', '试行参考线（6分）', '已评/总项', '证据差值', '权重差值', '总分差值',
                 '尚未完成真实课堂校准', '不填写学生姓名', '课程口径（保存后锁定）', '不涉及学生个体能力评分'):
        assert text in page
    assert 'provisional:"草稿"' in page and 'reviewed:"已复核"' in page
