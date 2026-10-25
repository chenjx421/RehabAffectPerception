"""Join current authorized dossier references without duplicating their storage."""
from __future__ import annotations

import sqlite3
import json

from .demo2_dossier_store import Demo2DossierStore, DossierError


def iep_link_is_current(db, account, task, scope, document_id, identities):
    """Check a document-version link inside the caller's existing transaction."""
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='demo2_dossier_references'").fetchone():
        return False
    refs = db.execute('''SELECT r.* FROM demo2_dossier_references r
        JOIN demo2_dossier_reference_documents d ON d.reference_id=r.reference_id
        WHERE r.task_id=? AND r.owner_account_id=? AND r.scope_key=? AND d.document_id=?''',
        (task['task_id'], account['account_id'], scope, document_id)).fetchall()
    from .demo2_dossier_store import _today
    today = _today().isoformat()
    for ref in refs:
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


def attach_iep_context(records, token, workspace):
    people = workspace.get('people', [])
    for person in people:
        person['iep_context'] = {'status': 'not_linked', 'reference_id': '', 'documents': []}
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
            person['iep_context']['status'] = 'unavailable'
        workspace['iep_status'] = 'unavailable'
        return
    references = dossier['references']
    links, lines = [], []
    for person in people:
        candidates = [ref for ref in references if ref['student_id'] == person['student_id']]
        current = [ref for ref in candidates if ref['available']]
        chosen = (current or candidates or [None])[-1]
        if chosen is None:
            continue
        available = chosen['available']
        documents = [
            {**{key: doc[key] for key in ('document_id', 'version', 'document_type')},
             'summary': {key: doc['summary'].get(key, '') for key in ('learning_goals', 'support_methods', 'safety_notes')}}
            for doc in chosen['documents'] if available and doc['available']
        ]
        iep_docs = [doc for doc in documents if doc['document_type'] == 'iep']
        person['iep_summary_id'] = iep_docs[0]['document_id'] if iep_docs else ''
        person.setdefault('identifiers', {})['iep_summary_id'] = person['iep_summary_id']
        person['iep_context'] = {'status': 'available' if available else chosen['status'],
                                 'reference_id': chosen['reference_id'], 'documents': documents}
        links.append({'student_id': person['student_id'], 'reference_id': chosen['reference_id'],
                      'available': available, 'status': person['iep_context']['status'],
                      'document_versions': chosen['document_versions']})
        if available:
            excerpts = []
            for doc in documents:
                summary = doc['summary']
                excerpts.append('学习目标：' + str(summary.get('learning_goals') or '未填写')
                                + '；支持方式：' + str(summary.get('support_methods') or '未填写'))
            lines.append(f"{person['display_name']}：" + '。'.join(excerpts)
                         + '。仅作为本课目标与支持条件的背景，不自动证明目标已达成。')
        else:
            lines.append(f"{person['display_name']}：原资料引用已失效或不可用，本次不读取其摘要。")
    report = workspace['report']
    report['iep_links'] = links
    if lines:
        report['sections'].append({'title': '授权资料与本课目标', 'source': 'authorized_iep', 'text': '\n'.join(lines)})
        report['character_count'] = sum(len(section['text']) for section in report['sections'])
        if 'full_text' in report:
            report['full_text'] = '\n\n'.join(section['title'] + '\n' + section['text'] for section in report['sections'])
    workspace['iep_status'] = 'available' if any(link['available'] for link in links) else 'not_available'


def snapshot_report(report):
    """Snapshots keep reference IDs, never reusable plaintext IEP summaries."""
    result = dict(report)
    result['sections'] = [dict(section) for section in report.get('sections', [])
                          if section.get('source') != 'authorized_iep']
    result['full_text'] = '\n\n'.join(section['title'] + '\n' + section['text'] for section in result['sections'])
    result['character_count'] = len(result['full_text'])
    return result
