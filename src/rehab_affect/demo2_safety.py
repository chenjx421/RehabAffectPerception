"""Human safety review, separately authorized and never a grading signal."""
import json
import math
import mimetypes
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from .demo2_dossier_vault import DossierVault
from .demo2_evaluation_store import Demo2EvaluationStore
from .demo2_identity_store import Demo2IdentityStore
from .demo2_measurement_store import MeasurementError
from .student_record_store import _iso

STATES = {'pending': '待核查', 'supplement': '补充材料中', 'verified': '已核实',
          'ruled_out': '已排除', 'unclear': '无法判断'}


def fail(message, status=400):
    raise MeasurementError(status, 'safety_review_error', message)


class SafetyStore:
    def __init__(self, records):
        self.records = records
        self.vault = DossierVault(Path(records.upload_dir).parent / 'safety_review_v1')
        with records._connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS demo2_safety_events (
                id TEXT PRIMARY KEY, owner TEXT NOT NULL, reviewer TEXT NOT NULL,
                task_id TEXT NOT NULL, school_json TEXT NOT NULL, status TEXT NOT NULL,
                version INTEGER NOT NULL, expires_at TEXT NOT NULL, body BLOB NOT NULL)''')

    def _account(self, token):
        try:
            account = self.records.account_from_session(token)
        except ValueError:
            fail('请先登录', 401)
        if account['role'] != 'school_uploader':
            fail('仅事件提交者及明确授权的同校核查人可查看', 403)
        return account

    def _school(self, db, account):
        return Demo2IdentityStore._context(self.records._school_context_for_account(db, account['account_id']), required=False)

    def _cleanup(self, db):
        return db.execute(
            'DELETE FROM demo2_safety_events WHERE julianday(expires_at)<=julianday(?)',
            (_iso(),),
        ).rowcount

    def cleanup_expired(self):
        """Commit expiry deletion without a user request or vault key.

        Only encrypted safety-event rows are removed, never source media or
        other records. SQLite deletion does not erase WAL files or backups.
        """
        with self.records._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            deleted = self._cleanup(db)
            remaining = db.execute('SELECT COUNT(*) FROM demo2_safety_events').fetchone()[0]
        return {'deleted_count': deleted, 'remaining_count': remaining}

    def _access(self, db, account, event_id):
        row = db.execute('SELECT * FROM demo2_safety_events WHERE id=?', (event_id,)).fetchone()
        if not row or account['account_id'] not in (row['owner'], row['reviewer']):
            fail('事件不存在、已到期或无权查看', 404)
        if self._school(db, account) != json.loads(row['school_json']):
            fail('学校归属已变化，请重新核对授权', 403)
        return dict(row)

    def _decode(self, row):
        body = json.loads(self.vault.open(row['body']))
        return {k: row[k] for k in ('id', 'owner', 'reviewer', 'task_id', 'status', 'version', 'expires_at')} | body

    def _encode(self, body):
        return self.vault.seal(json.dumps(body, ensure_ascii=False).encode('utf8'))

    def workspace(self, token):
        a = self._account(token)
        with self.records._connect() as db:
            self._cleanup(db)
            school = self._school(db, a)
            if not school.get('school_name'):
                fail('请先填写学校归属')
            candidates = []
            for row in db.execute("SELECT * FROM platform_accounts WHERE role='school_uploader'").fetchall():
                other = dict(row)
                if other['account_id'] != a['account_id'] and self._school(db, other) == school:
                    candidates.append(dict(id=other['account_id'], label=other.get('login_alias') or other['username']))
            events = []
            for row in db.execute('SELECT * FROM demo2_safety_events WHERE owner=? OR reviewer=? ORDER BY rowid DESC LIMIT 200', (a['account_id'], a['account_id'])):
                if json.loads(row['school_json']) == school:
                    events.append(self._decode(dict(row)))
            self.records._audit(db, a['username'], 'safety_workspace_view', 'safety_event', '', {'count':len(events)})
            tasks = [dict(r) for r in db.execute("SELECT task_id,course_name FROM video_analysis_tasks WHERE account_id=? AND upload_status<>'cancelled' ORDER BY created_at DESC LIMIT 200", (a['account_id'],))]
        return dict(account_id=a['account_id'], events=events, reviewers=candidates, tasks=tasks, states=STATES)

    def create(self, token, p):
        a = self._account(token)
        if not isinstance(p, dict) or set(p) != {'task_id', 'start_sec', 'end_sec', 'observation', 'action'}:
            fail('请提交视频、时段、客观观察和现场处理记录')
        text = Demo2EvaluationStore._text
        observation, action = text(p['observation']), text(p['action'], required=False)
        start, end = p['start_sec'], p['end_sec']
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in (start, end)) or not 0 <= start < end:
            fail('时段必须是有效秒数，且结束晚于开始')
        with self.records._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self._cleanup(db)
            task = Demo2IdentityStore._task(db, a, p['task_id'])
            self.records._require_live_video(task)
            if not self.records._video_source_path(task).is_file():
                fail('原视频不可用')
            school = self._school(db, a)
            if Demo2IdentityStore._context(task['school_context_json']) != school:
                fail('视频学校与当前账号归属不一致')
            try:
                duration = json.loads(task['processing_result_json'])['media']['duration_sec']
            except (ValueError, KeyError, TypeError):
                fail('请等待视频处理完成，以校验实际时长')
            if type(duration) not in (int, float) or not math.isfinite(duration) or end > duration:
                fail('所选时段超出视频时长')
            body = dict(start_sec=start, end_sec=end, observation=observation, action=action,
                        source_sha256=task['sha256'], history=[dict(at=_iso(), actor=a['account_id'], status='pending', note='提交人工核查')])
            expiry = (datetime.now(timezone.utc)+timedelta(days=60)).isoformat()
            # No independent copy or retention extension of the source media.
            if task.get('expires_at'):
                expiry = min(expiry, task['expires_at'])
            event_id = uuid4().hex
            db.execute('INSERT INTO demo2_safety_events VALUES (?,?,?,?,?,?,?,?,?)',
                       (event_id, a['account_id'], '', task['task_id'], json.dumps(school, ensure_ascii=False), 'pending', 1, expiry, self._encode(body)))
            self.records._audit(db, a['username'], 'safety_created', 'safety_event', event_id, {})
        return dict(id=event_id)

    def update(self, token, p):
        a = self._account(token)
        if not isinstance(p, dict) or set(p) != {'id', 'version', 'command', 'reviewer', 'status', 'note', 'confirmed'}:
            fail('核查操作字段不完整')
        if any(not isinstance(p[k], str) or len(p[k]) > 120 for k in ('id','command','reviewer','status')):
            fail('核查编号或操作字段无效')
        note = Demo2EvaluationStore._text(p['note'], limit=2000)
        if type(p['version']) is not int or type(p['confirmed']) is not bool:
            fail('版本和确认字段无效')
        with self.records._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self._cleanup(db)
            row = self._access(db, a, p['id'])
            if row['version'] != p['version']:
                fail('记录已更新，请刷新后核对', 409)
            body = self._decode(row)
            if len(body['history']) >= 100:
                fail('记录已达到100条操作上限，请联系学校负责人处理')
            command = p['command']
            if command == 'assign':
                if a['account_id'] != row['owner'] or not p['confirmed']:
                    fail('仅提交者可在确认学校授权后指定核查人', 403)
                if p['reviewer']:
                    target = db.execute("SELECT * FROM platform_accounts WHERE account_id=? AND role='school_uploader'", (p['reviewer'],)).fetchone()
                    if not target or target['account_id'] == row['owner'] or self._school(db, dict(target)) != json.loads(row['school_json']):
                        fail('请选择另一名同校核查账号')
                row['reviewer'] = p['reviewer']
                row['status'] = 'pending'
            elif command == 'supplement':
                row['status'] = 'supplement'
            elif command == 'resolve':
                if a['account_id'] != row['reviewer'] or not p['confirmed']:
                    fail('仅指定核查人确认无利益冲突后可记录结论', 403)
                if p['status'] not in STATES:
                    fail('核查状态无效')
                if p['status'] == 'verified':
                    self._media_row(db, row)
                row['status'] = p['status']
            else:
                fail('未知操作')
            body['history'].append(dict(at=_iso(), actor=a['account_id'], command=command,
                reviewer=row['reviewer'], confirmed=p['confirmed'], status=row['status'], note=note))
            for key in ('id', 'owner', 'reviewer', 'task_id', 'status', 'version', 'expires_at'):
                body.pop(key, None)
            db.execute('UPDATE demo2_safety_events SET reviewer=?,status=?,version=version+1,body=? WHERE id=?',
                       (row['reviewer'], row['status'], self._encode(body), row['id']))
            self.records._audit(db, a['username'], 'safety_'+command, 'safety_event', row['id'], {'status': row['status']})
        return dict(id=row['id'])

    def _media_row(self, db, row):
        task = db.execute('SELECT * FROM video_analysis_tasks WHERE task_id=?', (row['task_id'],)).fetchone()
        if not task:
            fail('视频不可用', 404)
        task = dict(task)
        self.records._require_live_video(task)
        body = self._decode(row)
        if task['sha256'] != body['source_sha256']:
            fail('视频来源发生变化，需重新核对', 409)
        path = self.records._video_source_path(task)
        if not path.is_file():
            fail('视频已清理或不可用', 404)
        return path

    def media(self, token, event_id):
        a = self._account(token)
        with self.records._connect() as db:
            self._cleanup(db)
            row = self._access(db, a, event_id)
            path = self._media_row(db, row)
            self.records._audit(db, a['username'], 'safety_media_view', 'safety_event', event_id, {})
        return path, mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
