"""Limited pedagogic archive, not an IEP, clinical record or anonymous dataset.

Only this module's additive tables are written. Free-text identifier screening
is conservative, not a de-identification guarantee. Revocation purges logical
blobs; SQLite WAL/backups and previously downloaded exports need separate policy.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime, timedelta
from pathlib import Path
import re
from uuid import uuid4

from .assessment_rubric import RUBRIC_VERSION
from .demo2_dossier_vault import DossierVault, VaultError
from .demo2_identity_store import Demo2IdentityStore, IdentityError
from .demo2_measurement_store import Demo2MeasurementStore


DOMAINS = ('cognition', 'communication', 'motor', 'sensory', 'social_adaptation')
LEVELS = {'unknown', 'with_support', 'developing', 'independent'}
PAGE_SIZE = 20


def _now():
    return datetime.now().astimezone()


def _today():
    return _now().date()


def _policy():
    return dict(purpose='educational_followup', research=False, training=False,
                pseudonymous_not_anonymous=True, raw_retention_days=60,
                expiry_exclusive=True, maximum_authorization_days=365,
                free_text_requires_no_identifiers=True,
                stale_measurement_snapshots='retained_without_measurement',
                cleanup_scope='logical_database_blobs_only')


class StudentSummaryError(ValueError):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _fail(status, code, message):
    raise StudentSummaryError(status, code, message)


def _text(value, limit=120, required=True):
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        _fail(400, 'invalid_field', '摘要字段缺失或超出长度限制')
    if any(ord(c) < 32 and c not in '\n\t' for c in value):
        _fail(400, 'invalid_field', '字段不能包含控制字符')
    return value.strip()


def _payload(value, allowed, required):
    if not isinstance(value, dict) or set(value) - set(allowed) or not set(required) <= set(value):
        _fail(400, 'invalid_payload', '仅接受约定的教学摘要字段，不接受诊断、专业结论或完整个别化教育计划')


def _date(value):
    try:
        result = date.fromisoformat(value)
        if result.isoformat() != value:
            raise ValueError
        return result
    except (ValueError, TypeError):
        _fail(400, 'invalid_date', '请填写有效日期，格式为 YYYY-MM-DD')


class Demo2StudentSummaryStore:
    def __init__(self, records):
        self.records = records
        self.identities = Demo2IdentityStore(records)
        self.vault = DossierVault(Path(records.upload_dir).resolve().parent / 'student_summary_v1')
        with records._connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS demo2_summary_students (
                    student_id TEXT PRIMARY KEY, owner_account_id TEXT NOT NULL,
                    scope_key TEXT NOT NULL, public_id TEXT NOT NULL UNIQUE,
                    channel_id TEXT NOT NULL,
                    FOREIGN KEY(student_id,owner_account_id,scope_key)
                      REFERENCES demo2_identity_students(student_id,owner_account_id,scope_key)
                );
                CREATE TABLE IF NOT EXISTS demo2_summary_authorizations (
                    authorization_id TEXT PRIMARY KEY,
                    student_id TEXT NOT NULL REFERENCES demo2_summary_students(student_id),
                    valid_until TEXT NOT NULL, status TEXT NOT NULL,
                    reference_blob BLOB, created_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_summary_live_auth
                    ON demo2_summary_authorizations(student_id) WHERE status='active';
                CREATE TABLE IF NOT EXISTS demo2_summary_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    authorization_id TEXT NOT NULL REFERENCES demo2_summary_authorizations(authorization_id),
                    recorded_on TEXT NOT NULL, body_blob BLOB, created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_summary_snapshots_auth
                    ON demo2_summary_snapshots(authorization_id,recorded_on);
            ''')
        from .demo2_student_course_history import AutomaticCourseHistory, initialize
        with records._connect() as db:
            initialize(db)
        self.automatic_history = AutomaticCourseHistory(self)

    def _account(self, token, *, admin=False):
        try:
            account = self.identities._account(token, write=not admin)
        except IdentityError as exc:
            raise StudentSummaryError(exc.status, exc.code, exc.message) from None
        if admin and account['role'] != 'company_admin':
            _fail(403, 'summary_forbidden', '仅公司管理员可读取已授权摘要')
        return account

    def _student(self, db, account, student_id):
        student_id = _text(student_id)
        try:
            context = self.identities._context(self.records._school_context_for_account(db, account['account_id']))
        except IdentityError as exc:
            raise StudentSummaryError(exc.status, exc.code, exc.message) from None
        scope = self.identities._scope(account['account_id'], context)
        row = db.execute('''SELECT * FROM demo2_identity_students
            WHERE student_id=? AND owner_account_id=? AND scope_key=?''',
            (student_id, account['account_id'], scope)).fetchone()
        if row is None:
            _fail(404, 'student_unavailable', '学生不属于当前账号和学校，或已不可用')
        return row

    def _current_scope(self, db, student):
        owner = db.execute('''SELECT a.status,a.role,a.bound_channel_id,s.channel_id
            FROM platform_accounts a JOIN demo2_summary_students s ON s.owner_account_id=a.account_id
            WHERE s.student_id=? AND a.account_id=?''',
            (student['student_id'], student['owner_account_id'])).fetchone()
        if (owner is None or owner['status'] != 'active' or owner['role'] != 'school_uploader'
                or not owner['bound_channel_id'] or owner['bound_channel_id'] != owner['channel_id']):
            return False
        context = self.identities._context(
            self.records._school_context_for_account(db, student['owner_account_id']), required=False)
        return student['scope_key'] == self.identities._scope(student['owner_account_id'], context)

    def _seal(self, binding, body):
        try:
            raw = json.dumps({'binding': binding, 'body': body}, ensure_ascii=True, allow_nan=False).encode()
            return self.vault.seal(raw)
        except VaultError as exc:
            raise StudentSummaryError(503, exc.code, exc.message) from None

    def _open(self, binding, blob):
        try:
            value = json.loads(self.vault.open(blob))
            if value['binding'] != binding:
                raise ValueError
            return value['body']
        except (VaultError, ValueError, KeyError, TypeError):
            _fail(503, 'summary_integrity', '加密摘要不可用或完整性校验失败，请联系管理员')

    @staticmethod
    def _binding(student, auth_id, snapshot_id=''):
        return [student['student_id'], student['owner_account_id'], student['scope_key'], auth_id, snapshot_id]

    @staticmethod
    def _active(auth):
        return auth is not None and auth['status'] == 'active' and auth['valid_until'] > _today().isoformat()

    def _cleanup(self, db):
        db.execute("UPDATE demo2_summary_authorizations SET status='expired' WHERE status='active' AND valid_until<=?",
                   (_today().isoformat(),))
        snapshots = db.execute('''UPDATE demo2_summary_snapshots SET body_blob=NULL
            WHERE body_blob IS NOT NULL AND authorization_id IN
            (SELECT authorization_id FROM demo2_summary_authorizations WHERE status<>'active')''').rowcount
        references = db.execute("UPDATE demo2_summary_authorizations SET reference_blob=NULL WHERE status<>'active' AND reference_blob IS NOT NULL").rowcount
        from .demo2_student_course_history import cleanup
        cleanup(db)
        return {'purged_snapshots': snapshots, 'purged_references': references}

    def cleanup_expired(self):
        with self.records._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            return self._cleanup(db)

    def _safe_text(self, db, text, student):
        # Known identifiers and obvious contact details only; not a full PII detector.
        terms = []
        for row in db.execute('''SELECT student_id,display_name,student_code FROM demo2_identity_students
            WHERE owner_account_id=? AND scope_key=?''',
            (student['owner_account_id'], student['scope_key'])):
            terms.extend(row)
        columns = {r['name'] for r in db.execute('PRAGMA table_info(platform_accounts)')}
        for key in ('username', 'display_name', 'teacher_name', 'account_id'):
            if key in columns:
                terms.extend(r[0] for r in db.execute('SELECT ' + key + ' FROM platform_accounts WHERE account_id=?',
                                                     (student['owner_account_id'],)))
        if any(str(t).casefold() in text.casefold() for t in terms if t):
            _fail(400, 'identifiers_not_permitted', '学习目标或支持方法含已知姓名或编号，请移除后重新核对')
        if re.search(r'@|https?://|\d{7,}|诊断|专业结论|完整IEP|diagnos|full.?iep|professional.?conclusion', text, re.I):
            _fail(400, 'sensitive_text_not_permitted', '仅可录入不含身份线索、诊断或专业结论的教学目标与支持方法')

    def save_authorization(self, token, payload):
        account = self._account(token)
        fields = {'student_id', 'reference', 'valid_until', 'confirmed'}
        _payload(payload, fields, fields)
        if payload['confirmed'] is not True:
            _fail(400, 'confirmation_required', '请明确确认已核实本次授权')
        reference = _text(payload['reference'], 1000)
        until = _date(payload['valid_until'])
        if not _today() < until <= _today() + timedelta(days=365):
            _fail(400, 'invalid_validity', '授权截止日期须在明天至今天起365天内，截止日期零时起失效')
        with self.records._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self._cleanup(db)
            student = self._student(db, account, payload['student_id'])
            if db.execute("SELECT 1 FROM demo2_summary_authorizations WHERE student_id=? AND status='active'", (student['student_id'],)).fetchone():
                _fail(409, 'authorization_exists', '已有有效授权，请先撤回再重新登记')
            db.execute('INSERT OR IGNORE INTO demo2_summary_students VALUES(?,?,?,?,?)',
                       (student['student_id'], account['account_id'], student['scope_key'],
                        'ps_' + uuid4().hex, account.get('bound_channel_id') or ''))
            auth_id = 'sa_' + uuid4().hex
            blob = self._seal(self._binding(student, auth_id), {'reference': reference})
            db.execute('INSERT INTO demo2_summary_authorizations VALUES(?,?,?,?,?,?)',
                       (auth_id, student['student_id'], until.isoformat(), 'active', blob, _now().isoformat()))
            self.records._audit(db, account['account_id'], 'student_summary_authorized',
                                'student_summary_authorization', auth_id, {'valid_until': until.isoformat()})
        return self.student_workspace(token, payload['student_id'])['authorization']

    def _measurement(self, db, student, record_id, expected=None):
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='demo2_measurements'").fetchone():
            _fail(409, 'measurement_unavailable', '测量来源不存在或不属于本学生、账号和学校')
        row = db.execute('''SELECT * FROM demo2_measurements WHERE record_id=? AND student_id=?
            AND owner_account_id=? AND scope_key=?''',
            (record_id, student['student_id'], student['owner_account_id'], student['scope_key'])).fetchone()
        if row is None:
            _fail(409, 'measurement_unavailable', '测量来源不存在或不属于本学生、账号和学校')
        try:
            expiry = datetime.fromisoformat(row['expires_at'])
            data = json.loads(row['payload_json'])
            digest = hashlib.sha256(row['payload_json'].encode()).hexdigest()
            valid = (row['status'] == 'active' and expiry > _now() and data.get('reviewed') is True
                     and data.get('student_id') == student['student_id']
                     and data.get('record_id') == record_id and data.get('version') == row['version']
                     and data.get('source_type') in {'classroom_observation', 'video_review'})
            if expected and (expected['version'] != row['version'] or expected['sha256'] != digest):
                valid = False
            if not valid:
                raise ValueError
            if data['source_type'] == 'video_review':
                account = {'account_id': student['owner_account_id'], 'role': 'school_uploader'}
                task = self.identities._task(db, account, data['task_id'])
                context = self.identities._context(task.get('school_context_json'), required=False)
                if self.identities._scope(account['account_id'], context) != student['scope_key']:
                    raise ValueError
                self.identities._require_media(task)
                effective = Demo2MeasurementStore._effective_record(self, db, account, data)
                if effective['evidence_status'] != 'current':
                    raise ValueError
            if data.get('rubric_version') != RUBRIC_VERSION or _date(row['lesson_date']) > _today():
                raise ValueError
        except (ValueError, TypeError, KeyError, IdentityError):
            _fail(409, 'measurement_stale', '测量未复核、已过期、已撤回或来源版本失效，请重新核对')
        scores = {k: data.get('scores', {}).get(k) for k in ('accuracy', 'independence', 'consistency', 'transfer')}
        assessment = {k: data.get('assessment', {}).get(k) for k in
                      ('overall_score', 'provisional_score', 'confidence', 'passed', 'insufficient_evidence')}
        for value in [*scores.values(), *assessment.values()]:
            if value is not None and (type(value) not in (int, float, bool) or not math.isfinite(value)):
                _fail(409, 'measurement_invalid', '测量的结构化数值无效')
        measurement = dict(scores=scores, assessment=assessment,
                           opportunities=data.get('opportunities'), observed=data.get('observed'))
        for key in ('opportunities', 'observed'):
            if measurement[key] is not None and type(measurement[key]) is not int:
                _fail(409, 'measurement_invalid', '测量次数须为有效整数')
        provenance = dict(source_type=data['source_type'], source_version=row['version'],
                          rule_version=data['rubric_version'], source_date=row['lesson_date'],
                          source_status='current', source_note='关联测量来源当前有效，未自动生成或补齐分数')
        return measurement, provenance, dict(record_id=record_id, version=row['version'], sha256=digest)

    def save_snapshot(self, token, payload):
        account = self._account(token)
        fields = {'student_id', 'authorization_id', 'recorded_on', 'source_ref', 'learning_goals',
                  'support_methods', 'domains', 'measurement_id', 'reviewed'}
        _payload(payload, fields, fields - {'measurement_id'})
        if payload['reviewed'] is not True:
            _fail(400, 'review_required', '请明确确认教师已逐项核对本摘要')
        recorded = _date(payload['recorded_on'])
        if recorded > _today():
            _fail(400, 'invalid_date', '摘要记录日期不能晚于今天')
        domains = payload['domains']
        if (not isinstance(domains, dict) or set(domains) != set(DOMAINS)
                or any(not isinstance(v, str) or v not in LEVELS for v in domains.values())):
            _fail(400, 'invalid_domains', '请填写约定的五个领域，并使用有效的观察等级')
        source = _text(payload['source_ref'], 500)
        goals = _text(payload['learning_goals'], 2000)
        supports = _text(payload['support_methods'], 2000)
        auth_id = _text(payload['authorization_id'])
        measurement_id = _text(payload.get('measurement_id', ''), required=False)
        with self.records._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            student = self._student(db, account, payload['student_id'])
            auth = db.execute('SELECT * FROM demo2_summary_authorizations WHERE authorization_id=? AND student_id=?',
                              (auth_id, student['student_id'])).fetchone()
            if not self._active(auth):
                _fail(410, 'authorization_inactive', '授权不存在、已撤回或已到期，不能保存摘要')
            self._safe_text(db, goals + '\n' + supports, student)
            # Also authenticate the reference envelope before appending content.
            self._open(self._binding(student, auth_id), auth['reference_blob'])
            body = dict(recorded_on=recorded.isoformat(), source_ref=source, learning_goals=goals,
                        support_methods=supports, domains=domains, measurement=None,
                        provenance=dict(source_type='manual_pedagogic_summary', source_version=1,
                                        rule_version='pedagogic-summary-v1', source_date=recorded.isoformat(),
                                        source_status='manual_reviewed', source_note='教师已核对的独立教学摘要，未关联测量分数'),
                        reviewed=True, measurement_source=None)
            if measurement_id:
                body['measurement'], body['provenance'], body['measurement_source'] = self._measurement(db, student, measurement_id)
            snapshot_id = 'ss_' + uuid4().hex
            blob = self._seal(self._binding(student, auth_id, snapshot_id), body)
            db.execute('INSERT INTO demo2_summary_snapshots VALUES(?,?,?,?,?)',
                       (snapshot_id, auth_id, recorded.isoformat(), blob, _now().isoformat()))
            self.records._audit(db, account['account_id'], 'student_summary_saved',
                                'student_summary_snapshot', snapshot_id, {'reviewed': True})
        return self.student_workspace(token, payload['student_id'])

    def _snapshots(self, db, student, auth):
        if not self._active(auth) or not self._current_scope(db, student):
            return []
        self._open(self._binding(student, auth['authorization_id']), auth['reference_blob'])
        result = []
        for row in db.execute('SELECT * FROM demo2_summary_snapshots WHERE authorization_id=? AND body_blob IS NOT NULL ORDER BY recorded_on,snapshot_id',
                              (auth['authorization_id'],)):
            body = self._open(self._binding(student, auth['authorization_id'], row['snapshot_id']), row['body_blob'])
            try:
                self._safe_text(db, body['learning_goals'] + '\n' + body['support_methods'], student)
            except StudentSummaryError as exc:
                if exc.status == 400:
                    continue
                raise
            # The separately reviewed pedagogic fields outlive their optional
            # measurement source, but invalid source scores must never be served.
            if body['measurement_source']:
                origin = body['measurement_source']
                try:
                    self._measurement(db, student, origin['record_id'], origin)
                    status, note = 'current', '关联测量来源当前有效，未自动生成或补齐分数'
                except StudentSummaryError as exc:
                    if exc.status != 409:
                        raise
                    body['measurement'] = None
                    status = 'withheld'
                    note = '关联测量已不可用或来源已变化，不展示测量分数；独立核准的教学摘要在授权期内保留'
            else:
                status, note = 'manual_reviewed', '教师已核对的独立教学摘要，未关联测量分数'
            body['provenance'] = {**body['provenance'], 'source_status': status, 'source_note': note}
            result.append({**{k: body[k] for k in ('recorded_on', 'learning_goals', 'support_methods',
                                                  'domains', 'measurement', 'provenance', 'reviewed')},
                           'snapshot_id': row['snapshot_id']})
        return result

    def student_workspace(self, token, student_id):
        account = self._account(token)
        with self.records._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            student = self._student(db, account, student_id)
            auth = db.execute('''SELECT a.*,s.public_id FROM demo2_summary_authorizations a
                JOIN demo2_summary_students s USING(student_id) WHERE student_id=?
                ORDER BY a.created_at DESC,a.rowid DESC LIMIT 1''', (student_id,)).fetchone()
            public_auth = None
            if auth:
                active = self._active(auth)
                public_auth = dict(authorization_id=auth['authorization_id'], public_id=auth['public_id'],
                                   valid_until=auth['valid_until'], active=active,
                                   status=auth['status'] if active or auth['status'] != 'active' else 'expired')
                from .demo2_student_course_history import settings
                public_auth['automatic_archiving'] = settings(db, auth['authorization_id'])
            return dict(student={k: student[k] for k in ('student_id', 'display_name', 'student_code', 'class_name')},
                        authorization=public_auth, snapshots=self._snapshots(db, student, auth),
                        course_history=self.automatic_history.history(db, student, auth), policy=_policy())

    def set_automatic_archiving(self, token, payload):
        account = self._account(token)
        fields = {'student_id', 'authorization_id', 'enabled', 'confirmed', 'include_existing'}
        _payload(payload, fields, fields)
        if (payload['confirmed'] is not True or type(payload['enabled']) is not bool
                or type(payload['include_existing']) is not bool):
            _fail(400, 'confirmation_required', '请明确确认自动归档开关及是否回填既有课程')
        auth_id = _text(payload['authorization_id'])
        from .demo2_student_course_history import capture_boundary, settings
        with self.records._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            student = self._student(db, account, payload['student_id'])
            auth = db.execute('SELECT * FROM demo2_summary_authorizations WHERE authorization_id=? AND student_id=?',
                              (auth_id, student['student_id'])).fetchone()
            if not self._active(auth) or not self._current_scope(db, student):
                _fail(410, 'authorization_inactive', '授权或所属学校账号已失效，不能设置自动归档')
            self._open(self._binding(student, auth_id), auth['reference_blob'])
            previous = settings(db, auth_id)
            if payload['enabled'] and (not previous['enabled'] or
                    (previous['include_existing'] and not payload['include_existing'])):
                capture_boundary(db, student, auth_id)
            enabled_at = previous['enabled_at']
            if payload['enabled'] and not previous['enabled']:
                enabled_at = _now().isoformat()
            db.execute('''INSERT INTO demo2_summary_automatic_settings VALUES(?,?,?,?)
                ON CONFLICT(authorization_id) DO UPDATE SET enabled=excluded.enabled,
                include_existing=excluded.include_existing,enabled_at=excluded.enabled_at''',
                (auth_id, int(payload['enabled']), int(payload['include_existing']), enabled_at))
            self.records._audit(db, account['account_id'], 'student_summary_automatic_archiving_changed',
                                'student_summary_authorization', auth_id,
                                {'enabled': payload['enabled'], 'include_existing': payload['include_existing']})
            self.automatic_history.sync_student(db, student, auth)
        return self.student_workspace(token, payload['student_id'])

    def sync_automatic_history(self):
        """Internal maintenance hook; never expose as a sessionless HTTP route."""
        return self.automatic_history.sync_all()

    def revoke_authorization(self, token, payload):
        account = self._account(token)
        fields = {'student_id', 'authorization_id', 'confirmed'}
        _payload(payload, fields, fields)
        if payload['confirmed'] is not True:
            _fail(400, 'confirmation_required', '请明确确认撤回本次摘要授权')
        auth_id = _text(payload['authorization_id'])
        with self.records._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            student = self._student(db, account, payload['student_id'])
            row = db.execute('SELECT 1 FROM demo2_summary_authorizations WHERE authorization_id=? AND student_id=?',
                             (auth_id, student['student_id'])).fetchone()
            if not row:
                _fail(404, 'authorization_unavailable', '授权不存在或无权操作')
            db.execute("UPDATE demo2_summary_authorizations SET status='revoked' WHERE authorization_id=?", (auth_id,))
            self._cleanup(db)
            self.records._audit(db, account['account_id'], 'student_summary_revoked',
                                'student_summary_authorization', auth_id, {})
        return self.student_workspace(token, payload['student_id'])

    def admin_workspace(self, token, *, page=1, query=''):
        self._account(token, admin=True)
        if type(page) is not int or not 1 <= page <= 10000:
            _fail(400, 'invalid_page', '页码须为1至10000之间的整数')
        query = _text(query, 80, required=False)
        if query and not re.fullmatch(r'[A-Za-z0-9_-]+', query):
            _fail(400, 'invalid_query', '仅可使用公开编号或通道编号查询')
        # Escape SQL wildcard characters; no decrypted text participates in search.
        pattern = '%' + query.replace('_', '\\_') + '%'
        with self.records._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            where = ''' FROM demo2_summary_students s JOIN demo2_summary_authorizations a USING(student_id)
                WHERE a.status='active' AND a.valid_until>? AND
                (s.public_id LIKE ? ESCAPE '\\' OR s.channel_id LIKE ? ESCAPE '\\')'''
            args = (_today().isoformat(), pattern, pattern)
            # Scope changes invalidate access, even when old authorization is not expired.
            rows = [r for r in db.execute('SELECT s.*,a.authorization_id,a.valid_until,a.status,a.reference_blob' + where, args)
                    if self._current_scope(db, r)]
            rows.sort(key=lambda r: r['public_id'])
            total = len(rows)
            items = []
            for row in rows[(page-1)*PAGE_SIZE:page*PAGE_SIZE]:
                snapshots = self._snapshots(db, row, row)
                courses = self.automatic_history.history(db, row, row)
                items.append(dict(public_id=row['public_id'], channel_id=row['channel_id'],
                                  snapshot_count=len(snapshots),
                                  latest_recorded_on=max((s['recorded_on'] for s in snapshots), default=None),
                                  course_count=len(courses),
                                  latest_course_at=max((c['recorded_on'] for c in courses), default=None),
                                  valid_until=row['valid_until']))
        return dict(items=items, pagination=dict(page=page, page_size=PAGE_SIZE, total=total,
                                                total_pages=(total+PAGE_SIZE-1)//PAGE_SIZE), policy=_policy())

    def admin_export(self, token, public_id):
        account = self._account(token, admin=True)
        public_id = _text(public_id)
        with self.records._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('''SELECT s.*,a.authorization_id,a.valid_until,a.status,a.reference_blob
                FROM demo2_summary_students s JOIN demo2_summary_authorizations a USING(student_id)
                WHERE s.public_id=? AND a.status='active' AND a.valid_until>?''',
                (public_id, _today().isoformat())).fetchone()
            if row is None or not self._current_scope(db, row):
                _fail(404, 'summary_unavailable', '该公开编号无有效授权，或所属账号、学校、通道已变化')
            result = dict(public_id=public_id, valid_until=row['valid_until'], policy=_policy(),
                          snapshots=self._snapshots(db, row, row),
                          course_history=self.automatic_history.history(db, row, row))
            self.records._audit(db, account['account_id'], 'student_summary_exported',
                                'student_summary_public', public_id, {'snapshot_count': len(result['snapshots'])})
            return result
