from copy import deepcopy
import pytest
from rehab_affect.classroom_rubric import evaluate
from test_demo2_evaluation_store import env, payload
from rehab_affect.demo2_measurement_store import MeasurementError


def sample(**changes):
    value = payload()
    value.update(weight_policy='subject_trial', focus_domains=['cognition'])
    value['items'][3]['enhanced_score'] = 4
    value.update(changes)
    return value


def test_subject_and_domain_change_only_enhanced_and_deltas_reconcile():
    math = evaluate(sample())
    sports = evaluate(sample(subject_id='sports', focus_domains=['motor']))
    assert math['school'] == sports['school']
    assert math['enhanced']['score_10'] != sports['enhanced']['score_10']
    assert sum(c['enhanced_weight'] for c in math['categories']) == pytest.approx(1)
    item = next(i for i in math['weight_policy']['items'] if i['id'] == 'i4')
    assert item['multiplier'] == pytest.approx(1.2)
    assert math['comparison']['total_delta'] == pytest.approx(math['comparison']['evidence_delta'] + math['comparison']['weight_delta'], abs=.00011)
    assert math['weight_policy']['limitation']


@pytest.mark.parametrize('updates', [
    dict(weight_policy='invalid'), dict(focus_domains=['invalid']),
    dict(focus_domains=['cognition','cognition']), dict(focus_domains='cognition'),
    dict(weight_policy='common', focus_domains=['cognition']),
    dict(template_id='qingpu_15'),
])
def test_invalid_configuration_is_rejected(updates):
    with pytest.raises(ValueError): evaluate(sample(**updates))


def test_missing_evidence_does_not_become_zero_or_robust_result():
    p = sample()
    p['items'][0]['enhanced_score'] = None
    result = evaluate(p)
    assert result['enhanced']['score_10'] is None
    assert result['sensitivity']['available'] is False


def test_sensitivity_reports_instability_at_threshold():
    p = sample(weight_policy='common', focus_domains=[])
    for i in p['items']: i['enhanced_score'] = 6
    p['items'][0]['enhanced_score'] = 8
    p['items'][7]['enhanced_score'] = 4.5
    result = evaluate(p)
    assert result['enhanced']['score_10'] == 6
    assert result['sensitivity']['low'] < 6 < result['sensitivity']['high']
    assert result['sensitivity']['crosses_reference']


def test_policy_saved_reopened_and_locked(env):
    p = sample()
    saved = env.store.save(env.tokens['t1'], p)
    assert saved['weight_policy'] == 'subject_trial'
    assert saved['rule_snapshot']['weight_policy']['version']
    assert env.store.workspace(env.tokens['t1'])['records'][0]['result'] == saved['result']
    p.update(expected_version=1, focus_domains=['motor'])
    with pytest.raises(MeasurementError, match='已锁定'):
        env.store.save(env.tokens['t1'], p)


def test_existing_record_old_rule_snapshot_not_silently_recomputed(env):
    record = env.store.save(env.tokens['t1'], sample())
    import json
    prior = deepcopy(record)
    prior['result']['rule_version'] = 'prior-version'
    with env.records._connect() as db:
        db.execute('UPDATE demo2_classroom_evaluations SET payload_json=? WHERE record_id=?',
                   (json.dumps(prior), prior['record_id']))
    assert env.store.workspace(env.tokens['t1'])['records'][0]['result']['rule_version'] == 'prior-version'
    with pytest.raises(MeasurementError, match='历史规则'):
        env.store.save(env.tokens['t1'], sample(expected_version=1))
