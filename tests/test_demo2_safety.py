import pytest
from cryptography.fernet import Fernet
from rehab_affect.demo2_safety import SafetyStore
from rehab_affect.demo2_measurement_store import MeasurementError
from test_demo2_identity_store import env, make_task, login, school, OTHER, ADMIN, CONTEXT


def prepare(env, monkeypatch):
    monkeypatch.setenv('REHAB_DEMO2_DOSSIER_KEY', Fernet.generate_key().decode())
    task = make_task(env)
    school(env, OTHER)
    store = SafetyStore(env.record)
    event = store.create(task.token, dict(task_id=task.task_id, start_sec=0, end_sec=2,
        observation='合成观察，不认定伤害', action='合成现场处理'))
    other, other_token = login(env, OTHER)
    return store, task, event['id'], other, other_token


def update(event_id, version=1, **kw):
    return dict(id=event_id, version=version, command='assign', reviewer='', status='pending',
                note='已取得学校单事件授权', confirmed=True) | kw


def test_end_to_end_authorization_and_revoke(env, monkeypatch):
    store, task, eid, other, ot = prepare(env, monkeypatch)
    assert store.workspace(ot)['events'] == []
    with pytest.raises(MeasurementError): store.media(ot, eid)
    store.update(task.token, update(eid, reviewer=other['account_id']))
    assert store.media(ot, eid)[0] == task.source
    store.update(ot, update(eid, 2, command='resolve', status='ruled_out', note='人工核对前后情境后排除'))
    assert store.workspace(task.token)['events'][0]['status'] == 'ruled_out'
    store.update(task.token, update(eid, 3, command='supplement', note='新材料，需要重核'))
    assert store.workspace(ot)['events'][0]['status'] == 'supplement'
    store.update(task.token, update(eid, 4))
    with pytest.raises(MeasurementError): store.media(ot, eid)
    assert len(store.workspace(task.token)['events'][0]['history']) == 5


def test_self_admin_and_cross_school_cannot_review(env, monkeypatch):
    store, task, eid, other, ot = prepare(env, monkeypatch)
    owner = env.record.account_from_session(task.token)
    with pytest.raises(MeasurementError): store.update(task.token, update(eid, reviewer=owner['account_id']))
    with pytest.raises(MeasurementError): store.update(task.token, update(eid, command='resolve', status='verified'))
    with pytest.raises(MeasurementError): store.workspace(login(env, ADMIN)[1])
    school(env, OTHER, CONTEXT | {'school_name':'其他学校'})
    with pytest.raises(MeasurementError): store.update(task.token, update(eid, reviewer=other['account_id']))


def test_encrypted_expiry_and_optimistic_version(env, monkeypatch):
    store, task, eid, other, ot = prepare(env, monkeypatch)
    with env.record._connect() as db:
        row = db.execute('SELECT * FROM demo2_safety_events').fetchone()
        assert '合成观察'.encode() not in row['body']
        expiry = db.execute('SELECT expires_at FROM video_analysis_tasks').fetchone()[0]
        assert row['expires_at'] <= expiry
    with pytest.raises(MeasurementError): store.update(task.token, update(eid, 99))
    with env.record._connect() as db: db.execute("UPDATE demo2_safety_events SET expires_at='2000-01-01T00:00:00+00:00'")
    assert store.workspace(task.token)['events'] == []


@pytest.mark.parametrize('start,end', [(1,1),(-1,1),(0,9),(False,2),(0,float('nan'))])
def test_bad_times_rejected(env, monkeypatch, start, end):
    store, task, *_ = prepare(env, monkeypatch)
    with pytest.raises(MeasurementError):
        store.create(task.token, dict(task_id=task.task_id,start_sec=start,end_sec=end,observation='观察',action=''))


def test_reviewer_school_change_revokes_read(env, monkeypatch):
    store, task, eid, other, ot = prepare(env, monkeypatch)
    store.update(task.token, update(eid, reviewer=other['account_id']))
    school(env, OTHER, CONTEXT | {'school_name':'新学校'})
    with pytest.raises(MeasurementError): store.media(ot, eid)
    assert store.workspace(ot)['events'] == []


def test_missing_media_prevents_verified_conclusion(env, monkeypatch):
    store, task, eid, other, ot = prepare(env, monkeypatch)
    store.update(task.token, update(eid, reviewer=other['account_id']))
    task.source.unlink()
    with pytest.raises(MeasurementError): store.update(ot, update(eid, 2, command='resolve',status='verified'))
