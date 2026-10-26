"""Real SQLite/Fernet joins across dossiers, observation, scoring and reports."""
import json
from datetime import timedelta

import pytest

from rehab_affect import demo2_dossier_store as dossier_module
from rehab_affect.demo2_measurement_store import Demo2MeasurementStore, MeasurementError
from rehab_affect.demo2_evaluation_store import Demo2EvaluationStore
from rehab_affect.demo2_report_store import Demo2ReportStore, ReportError
from rehab_affect.video_applicability import ApplicabilityStore
from test_demo2_dossier_store import env, template, authorize, document, task, reference, SECRET, day
from test_demo2_evaluation_store import payload
from test_demo2_measurement_store import _payload


def prepared(env):
    video = task(env)
    token = env.tokens['a']
    suitability = ApplicabilityStore(env.records)
    state = suitability.workspace(token, video.task_id)
    suitability.save(token, dict(task_id=video.task_id, version=state['version'], revision=state['revision'],
        category='special', goal='合成课堂分类目标', reason='合成视频工程测试', confirmed=True))
    auth = authorize(env)
    doc = document(env, authorization=auth, filename='', content_base64='')
    ref = reference(env, video, [doc])
    measurements = Demo2MeasurementStore(env.records)
    observation = measurements.save(token, _payload(env.pupils['a1']['student_id'],
        source_type='video_review', task_id=video.task_id, start_sec=0, end_sec=1,
        support_level='visual', observed_state='participating', teacher_prompt='分类', student_response='指认'))
    evaluations = Demo2EvaluationStore(env.records)
    evaluation_payload = payload(task_id=video.task_id, frame_revision=video.revision, iep_summary_id=doc['document_id'])
    evaluation = evaluations.save(token, evaluation_payload)
    return video, auth, doc, ref, measurements, observation, evaluations, evaluation_payload, evaluation


def test_live_iep_join_uses_fixed_ids_without_plaintext_in_snapshot(env):
    video, auth, doc, ref, measurements, _, _, _, evaluation = prepared(env)
    work = measurements.course_workspace(env.tokens['a'], video.task_id)
    person = work['people'][0]
    assert person['student_id'] == env.pupils['a1']['student_id']
    assert person['identifiers']['iep_summary_id'] == doc['document_id']
    assert person['iep_context']['reference_id'] == ref['reference_id']
    assert SECRET in json.dumps(work['report'], ensure_ascii=False)
    assert 'professional_conclusion' not in json.dumps(person['iep_context'])
    assert evaluation['source_provenance']['student_linkage'] == 'not_asserted'
    reports = Demo2ReportStore(env.records)
    snapshot = reports.save_from_workspace(env.tokens['a'], work)
    assert snapshot['ready'] and snapshot['status'] == 'saved'
    assert snapshot['content_report_id'] == work['report']['report_id']
    for user in ('a', 'admin'):
        for fmt in ('json', 'md'):
            downloaded, _, _ = reports.download(env.tokens[user], snapshot['report_id'], fmt=fmt)
            assert SECRET not in downloaded
    teacher_stored = reports.get(env.tokens['a'], snapshot['report_id'])
    assert teacher_stored['payload']['report']['iep_links'][0]['reference_id'] == ref['reference_id']
    stored = reports.get(env.tokens['admin'], snapshot['report_id'])
    assert 'iep_links' not in stored['payload']['report']
    admin_download, _, _ = reports.download(env.tokens['admin'], snapshot['report_id'], fmt='json')
    assert 'iep_links' not in json.loads(admin_download)['report']
    assert stored['evaluation_count'] == 1
    with env.records._connect() as db:
        raw = db.execute('SELECT payload_json FROM demo2_reports').fetchone()[0]
        assert SECRET not in raw
    # Uploading v2 alone does not silently rebind an existing course reference.
    env.store.withdraw_authorization(env.tokens['a'], {'student_id': env.pupils['a1']['student_id'],
        'authorization_id': auth['authorization_id'], 'confirmed': True})
    new_auth = authorize(env)
    document(env, authorization=new_auth, filename='', content_base64='',
             summary={key: 'NEW-VERSION' for key in dossier_module.SUMMARY_FIELDS})
    again = measurements.course_workspace(env.tokens['a'], video.task_id)
    assert again['people'][0]['iep_summary_id'] == ''
    assert again['people'][0]['iep_context']['status'] != 'available'
    assert 'NEW-VERSION' not in json.dumps(again['report'])


@pytest.mark.parametrize('change', ['withdraw', 'expiry', 'identity'])
def test_unavailable_reference_is_not_reused_in_report_or_scoring(env, monkeypatch, change):
    video, auth, _, _, measurements, _, evaluations, evaluation_payload, _ = prepared(env)
    if change == 'withdraw':
        env.store.withdraw_authorization(env.tokens['a'], {'student_id': env.pupils['a1']['student_id'],
            'authorization_id': auth['authorization_id'], 'confirmed': True})
    elif change == 'expiry':
        tomorrow = dossier_module._today() + timedelta(days=20)
        monkeypatch.setattr(dossier_module, '_today', lambda: tomorrow)
    else:
        with env.records._connect() as db:
            db.execute("UPDATE demo2_identity_bindings SET status='revoked' WHERE binding_id=?", (video.binding['binding_id'],))
    work = measurements.course_workspace(env.tokens['a'], video.task_id)
    assert SECRET not in json.dumps(work['report'], ensure_ascii=False)
    assert not work['people'][0].get('iep_summary_id')
    assert work['people'][0]['iep_context']['documents'] == []
    assert evaluations.for_task(env.tokens['a'], video.task_id) == []
    with pytest.raises(MeasurementError):
        evaluations.preview(env.tokens['a'], {**evaluation_payload, 'expected_version': 1})


def test_wrong_student_or_task_document_cannot_be_asserted_as_iep(env):
    video, _, _, _, _, _, evaluations, _, _ = prepared(env)
    other = document(env, pupil='a2', filename='', content_base64='')
    with pytest.raises(MeasurementError) as exc:
        evaluations.preview(env.tokens['a'], payload(record_id='foreign-doc', lesson_id='another',
            task_id=video.task_id, frame_revision=video.revision, iep_summary_id=other['document_id']))
    assert exc.value.code == 'iep_link_unavailable'


def test_snapshot_download_rejects_changed_scoring_versions(env):
    video, _, _, _, measurements, _, evaluations, evaluation_payload, _ = prepared(env)
    reports = Demo2ReportStore(env.records)
    snapshot = reports.save_from_workspace(env.tokens['a'], measurements.course_workspace(env.tokens['a'], video.task_id))
    evaluations.save(env.tokens['a'], {**evaluation_payload, 'expected_version': 1})
    with pytest.raises(ReportError) as exc:
        reports.download(env.tokens['admin'], snapshot['report_id'])
    assert exc.value.code == 'report_stale'
    updated = reports.save_from_workspace(env.tokens['a'], measurements.course_workspace(env.tokens['a'], video.task_id))
    assert updated['report_id'] == snapshot['report_id']
    assert updated['content_report_id'] != snapshot['content_report_id']
    reports.download(env.tokens['admin'], updated['report_id'])


@pytest.mark.parametrize('change', ['authorization', 'reference'])
def test_snapshot_built_from_iep_expires_after_withdrawal(env, change):
    video, auth, doc, ref, measurements, _, _, _, _ = prepared(env)
    reports = Demo2ReportStore(env.records)
    snapshot = reports.save_from_workspace(env.tokens['a'], measurements.course_workspace(env.tokens['a'], video.task_id))
    reports.download(env.tokens['a'], snapshot['report_id'])
    if change == 'authorization':
        env.store.withdraw_authorization(env.tokens['a'], {'student_id': env.pupils['a1']['student_id'],
            'authorization_id': auth['authorization_id'], 'confirmed': True})
    else:
        env.store.withdraw_reference(env.tokens['a'], {'reference_id': ref['reference_id'], 'confirmed': True})
    for user in ('a', 'admin'):
        with pytest.raises(ReportError) as exc:
            reports.download(env.tokens[user], snapshot['report_id'])
        assert exc.value.code == 'report_stale'
    with env.records._connect() as db:
        assert db.execute('SELECT status FROM demo2_reports WHERE report_id=?', (snapshot['report_id'],)).fetchone()[0] == 'stale'
    # Regenerating without the withdrawn material restores a downloadable snapshot.
    regenerated = reports.save_from_workspace(env.tokens['a'], measurements.course_workspace(env.tokens['a'], video.task_id))
    assert regenerated['report_id'] == snapshot['report_id'] and regenerated['status'] == 'saved'
    downloaded, _, _ = reports.download(env.tokens['a'], regenerated['report_id'], fmt='json')
    assert SECRET not in downloaded
    assert all(not link['available'] for link in json.loads(downloaded)['report'].get('iep_links', []))
