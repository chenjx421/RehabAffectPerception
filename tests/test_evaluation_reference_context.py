"""Project reference lines must not become an invented school pass standard."""
import pytest

from rehab_affect.classroom_rubric import catalog, evaluate


def sample(score=8, reviewed=True):
    return {
        'template_id': 'basic_100', 'subject_id': 'math',
        'reviewed': reviewed, 'school_source': 'teacher_recorded',
        'items': [dict(id=item['id'], school_score=score, enhanced_score=score,
                       evidence='Synthetic observation', reason='', suggestion='')
                  for item in catalog()['templates'][0]['items']],
    }


@pytest.mark.parametrize('score,reviewed,expected', [
    (6, True, '达到项目参考线'), (5.9, True, '低于项目参考线'),
    (8, False, '待教师复核'), (None, True, '评分不完整'),
])
def test_project_reference_never_claims_school_pass(score, reviewed, expected):
    result = evaluate(sample(score, reviewed))
    assert result['school']['reference_status'] == expected
    assert result['school']['reference_line'] == 6
    assert result['school']['passed'] is None


def test_subject_changes_observation_focus_but_not_weights():
    payload = sample()
    math = evaluate(payload)
    payload['subject_id'] = 'sports'
    sports = evaluate(payload)
    assert math['subject_context']['focus'] != sports['subject_context']['focus']
    assert math['enhanced']['score_10'] == sports['enhanced']['score_10']
    assert math['categories'] == sports['categories']
    assert '尚未启用' in sports['subject_context']['policy']
