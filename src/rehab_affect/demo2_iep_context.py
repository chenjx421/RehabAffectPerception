"""Join current authorized dossier references without duplicating their storage."""
from __future__ import annotations

import sqlite3
import json

from .demo2_dossier_store import Demo2DossierStore, DossierError, debug_event, material_access_state


def iep_link_is_current(db, account, task, scope, document_id, identities):
    """Check a document-version link inside the caller's existing transaction."""
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='demo2_dossier_references'").fetchone():
        return False
    refs = db.execute('''SELECT r.* FROM demo2_dossier_references r
        JOIN demo2_dossier_reference_documents d ON d.reference_id=r.reference_id
        JOIN demo2_dossier_documents doc ON doc.document_id=d.document_id
        WHERE r.task_id=? AND r.owner_account_id=? AND r.scope_key=?
          AND d.document_id=? AND doc.document_type='iep' ''',
        (task['task_id'], account['account_id'], scope, document_id)).fetchall()
    from .demo2_dossier_store import _today
    today = _today().isoformat()
    for ref in refs:
        # A classroom-level withdrawal stops the reference feeding analysis or scoring.
        if 'withdrawn_at' in ref.keys() and ref['withdrawn_at']:
            continue
        if ref['frame_revision'] != identities._revision(task) or ref['source_sha256'] != task['sha256']:
            continue
        docs = db.execute('''SELECT d.*, l.version AS linked_version FROM demo2_dossier_documents d
            JOIN demo2_dossier_reference_documents l ON l.document_id=d.document_id WHERE l.reference_id=?''',
            (ref['reference_id'],)).fetchall()
        valid = bool(docs)
        for doc in docs:
            auth = db.execute('SELECT * FROM demo2_dossier_authorizations WHERE authorization_id=?',
                              (doc['authorization_id'],)).fetchone()
            valid = valid and (doc['status'] == 'available' and doc['metadata_ciphertext'] is not None
                               and doc['retain_until'] > today and doc['version'] == doc['linked_version']
                               and auth is not None and Demo2DossierStore._auth_active(auth)
                               and all(doc[key] == auth[key] == ref[key]
                                       for key in ('student_id', 'owner_account_id', 'scope_key')))
        bindings = json.loads(ref['binding_ids_json'])
        frames = identities._frames(task)
        for item in bindings:
            binding = db.execute('SELECT * FROM demo2_identity_bindings WHERE binding_id=?', (item['binding_id'],)).fetchone()
            valid = valid and (binding is not None and binding['status'] == 'confirmed' and binding['role'] == 'student'
                and binding['student_id'] == ref['student_id'] and binding['task_id'] == task['task_id']
                and binding['owner_account_id'] == account['account_id'] and binding['scope_key'] == scope
                and binding['frame_revision'] == ref['frame_revision'] and binding['source_sha256'] == ref['source_sha256']
                and binding['frame_key'] in frames and binding['time_sec'] == frames[binding['frame_key']]['time_sec'])
        if valid and bindings:
            return True
    return False


NOT_LINKED_MESSAGE = '本课未关联该学生的授权资料，分析不读取 IEP 或专业资料。'
AMBIGUOUS_MESSAGE = '存在多份当前有效的 IEP 或资料引用，系统不自动选择，请教师先明确对应的 IEP 版本。'


def _unavailable_reason(records, reference):
    """Name the first reason a stale reference may no longer feed analysis."""
    if reference.get('withdrawn') or reference.get('status') == 'withdrawn':
        return 'reference_withdrawn', '本课资料引用授权已撤回，本次分析与评分不读取 IEP 或专业资料。'
    try:
        with records._connect() as db:
            for version in reference.get('document_versions', []):
                state = material_access_state(db, student_id=reference['student_id'],
                                              document_id=version['document_id'], purpose='analysis')
                if not state['available']:
                    return state['reason'], state['message']
    except (sqlite3.Error, OSError, KeyError, TypeError):
        return 'dossier_unavailable', '资料服务暂不可用，本次分析不读取 IEP 或专业资料。'
    evidence = {'outdated_revision': ('identity_outdated', '课堂身份采样版本已变化，原资料引用不再用于分析。'),
                'identity_unavailable': ('identity_unavailable', '课堂身份确认已失效，原资料引用不再用于分析。'),
                'task_unavailable': ('task_unavailable', '课堂任务证据不可用，原资料引用不再用于分析。')}
    return evidence.get(reference.get('evidence_status'), ('reference_unavailable', '原资料引用已失效，本次分析不读取其摘要。'))


def _log_person(records, workspace, person):
    context = person['iep_context']
    debug_event(records, 'analysis_iep_context', context['status'], task_id=workspace.get('task_id'),
                student_id=person.get('student_id'), reference_id=context.get('reference_id') or None,
                document_id=person.get('iep_summary_id') or None, document_type='iep', reason=context.get('reason'),
                candidate_count=len(context.get('documents', [])))


def attach_iep_context(records, token, workspace):
    people = workspace.get('people', [])
    for person in people:
        person['iep_context'] = {'status': 'not_linked', 'reference_id': '', 'documents': [],
                                 'reason': 'not_linked', 'message': NOT_LINKED_MESSAGE}
    # Ordinary video analysis must work without a dossier key or imported IEP.
    with records._connect() as db:
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='demo2_dossier_references'").fetchone()
        if not exists or not db.execute('SELECT 1 FROM demo2_dossier_references WHERE task_id=? LIMIT 1',
                                       (workspace['task_id'],)).fetchone():
            return
    try:
        dossier = Demo2DossierStore(records).task_workspace(token, workspace['task_id'])
    except (DossierError, sqlite3.Error, OSError):
        for person in people:
            person['iep_context'].update(status='unavailable', reason='dossier_unavailable',
                                         message='资料服务暂不可用，本次分析不读取 IEP 或专业资料。')
            _log_person(records, workspace, person)
        workspace['iep_status'] = 'unavailable'
        return
    references = dossier['references']
    links, lines = [], []
    for person in people:
        candidates = [ref for ref in references if ref['student_id'] == person['student_id']]
        current = [ref for ref in candidates if ref['available']]
        iep_families = {doc['family_id'] for ref in current for doc in ref['documents']
                        if doc['available'] and doc['document_type'] == 'iep'}
        if len(current) > 1 or len(iep_families) > 1:
            person['iep_context'] = {'status': 'ambiguous', 'reference_id': '', 'documents': [],
                                     'reason': 'multiple_current_iep', 'message': AMBIGUOUS_MESSAGE}
            person['iep_summary_id'] = ''
            person.setdefault('identifiers', {})['iep_summary_id'] = ''
            _log_person(records, workspace, person)
            for ref in current:
                links.append({'student_id': person['student_id'], 'reference_id': ref['reference_id'],
                              'available': True, 'status': 'ambiguous',
                              'document_versions': ref['document_versions']})
            lines.append(f"{person['display_name']}：存在多条当前有效的授权资料引用，本次不自动选择，请先明确对应的 IEP 版本。")
            continue
        chosen = (current or candidates or [None])[0]
        if chosen is None:
            _log_person(records, workspace, person)
            continue
        available = chosen['available']
        documents = [
            {**{key: doc[key] for key in ('document_id', 'version', 'document_type')},
             'summary': {key: doc['summary'].get(key, '') for key in ('learning_goals', 'support_methods', 'safety_notes')}}
            for doc in chosen['documents']
            if available and doc['available'] and doc['document_type'] == 'iep'
        ]
        # One IEP family may be linked at v1 and v2; the newest linked version is current.
        documents.sort(key=lambda doc: doc['version'], reverse=True)
        person['iep_summary_id'] = documents[0]['document_id'] if documents else ''
        person.setdefault('identifiers', {})['iep_summary_id'] = person['iep_summary_id']
        status = ('available' if documents else 'no_iep_summary') if available else chosen['status']
        if available:
            reason, message = ('available', '已读取本课引用的唯一有效 IEP 摘要。') if documents else (
                'no_iep_summary', '当前引用没有可用的 IEP 摘要，本次不读取其他专业资料。')
        else:
            reason, message = _unavailable_reason(records, chosen)
        person['iep_context'] = {'status': status, 'reference_id': chosen['reference_id'], 'documents': documents,
                                 'reason': reason, 'message': message}
        _log_person(records, workspace, person)
        links.append({'student_id': person['student_id'], 'reference_id': chosen['reference_id'],
                      'available': bool(available and documents), 'status': status,
                      'document_versions': chosen['document_versions']})
        if documents:
            excerpts = []
            for doc in documents:
                summary = doc['summary']
                excerpts.append('学习目标：' + str(summary.get('learning_goals') or '未填写')
                                + '；支持方式：' + str(summary.get('support_methods') or '未填写'))
            lines.append(f"{person['display_name']}：" + '。'.join(excerpts)
                         + '。仅作为本课目标与支持条件的背景，不自动证明目标已达成。')
        elif available:
            lines.append(f"{person['display_name']}：当前引用没有可用的 IEP 摘要，本次不读取其他专业资料。")
        else:
            lines.append(f"{person['display_name']}：原资料引用已失效或不可用（{message}），本次不读取其摘要。")
    report = workspace['report']
    report['iep_links'] = links
    if lines:
        report['sections'].append({'title': '授权资料与本课目标', 'source': 'authorized_iep', 'text': '\n'.join(lines)})
        report['character_count'] = sum(len(section['text']) for section in report['sections'])
        if 'full_text' in report:
            report['full_text'] = '\n\n'.join(section['title'] + '\n' + section['text'] for section in report['sections'])
    if any(link['status'] == 'ambiguous' for link in links):
        workspace['iep_status'] = 'ambiguous'
    else:
        workspace['iep_status'] = 'available' if any(link['available'] for link in links) else 'not_available'


def snapshot_report(report):
    """Snapshots keep reference IDs, never reusable plaintext IEP summaries."""
    result = dict(report)
    result['sections'] = [dict(section) for section in report.get('sections', [])
                          if section.get('source') != 'authorized_iep']
    result['full_text'] = '\n\n'.join(section['title'] + '\n' + section['text'] for section in result['sections'])
    result['character_count'] = sum(len(section.get('text', '')) for section in result['sections'])
    return result
