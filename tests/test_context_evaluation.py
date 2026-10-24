from copy import deepcopy

import pytest

from rehab_affect.classroom_rubric import evaluate


def sample():
    return dict(template_id='basic_100', subject_id='general', reviewed=False,
                school_source='teacher_recorded', weight_policy='school_context',
                items=[dict(id=f'i{i+1}', school_score=6+i%5, enhanced_score=None,
                            evidence='教案与课堂片段 02:10', reason='', suggestion='')
                       for i in range(10)])


def test_ordinary_class_inherits_unequal_school_scores():
    result = evaluate(sample())
    assert result['school']['score_10'] == result['enhanced']['score_10'] == 8
    assert result['comparison']['weight_delta'] == 0
    assert result['comparison']['total_delta'] == 0


@pytest.mark.parametrize('proposed', [0, 10])
def test_adjustment_only_applied_after_review(proposed):
    payload = sample()
    payload['items'][0].update(enhanced_score=proposed, reason='教师应对与学生后续表现', suggestion='下节课确认支持')
    pending = evaluate(payload)
    assert pending['enhanced']['score_10'] == 8
    assert pending['context_review']['pending_count'] == 1
    payload['reviewed'] = True
    result = evaluate(payload)
    assert result['enhanced']['score_10'] == pytest.approx(8 + .1*(proposed-6))
    assert result['comparison']['weight_delta'] == 0
    assert result['context_review']['pending_count'] == 0


@pytest.mark.parametrize('field', ['evidence', 'reason', 'suggestion'])
def test_changed_score_requires_context(field):
    payload = sample()
    payload['items'][0].update(enhanced_score=8, evidence='片段', reason='应对和结果', suggestion='建议')
    payload['items'][0][field] = ''
    with pytest.raises(ValueError, match='情境修正须'):
        evaluate(payload)


def test_missing_school_evidence_never_zero():
    payload = sample()
    payload['items'][0]['school_score'] = None
    result = evaluate(payload)
    assert result['school']['score_10'] is None
    assert result['enhanced']['score_10'] is None


def test_missing_baseline_cannot_be_adjusted():
    payload = sample()
    payload['items'][0].update(school_score=None, enhanced_score=4)
    with pytest.raises(ValueError, match='先录入'):
        evaluate(payload)


def test_historical_default_unchanged_and_input_not_mutated():
    payload = sample()
    before = deepcopy(payload)
    evaluate(payload)
    assert payload == before
    del payload['weight_policy']
    assert evaluate(payload)['weight_policy']['mode'] == 'common'


def test_domains_cannot_silently_change_context_weights():
    payload = sample()
    payload['focus_domains'] = ['language']
    with pytest.raises(ValueError):
        evaluate(payload)
