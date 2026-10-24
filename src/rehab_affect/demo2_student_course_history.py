"""Opt-in, pseudonymous course history; sampled identity is not lesson tracking."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import math
from uuid import uuid4

from . import demo2_student_summary_store as api
from .demo2_identity_store import IdentityError


def initialize(db):
    had_boundary_table = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='demo2_summary_auto_excluded_tasks'").fetchone()
    db.executescript('''
        CREATE TABLE IF NOT EXISTS demo2_summary_automatic_settings (
            authorization_id TEXT PRIMARY KEY REFERENCES demo2_summary_authorizations(authorization_id),
            enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
            include_existing INTEGER NOT NULL CHECK(include_existing IN (0,1)), enabled_at TEXT
        );
        CREATE TABLE IF NOT EXISTS demo2_summary_course_history (
            entry_id TEXT PRIMARY KEY,
            authorization_id TEXT NOT NULL REFERENCES demo2_summary_authorizations(authorization_id),
            student_id TEXT NOT NULL REFERENCES demo2_summary_students(student_id),
            task_id TEXT NOT NULL, revision INTEGER NOT NULL, fingerprint TEXT NOT NULL,
            body_blob BLOB, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE(authorization_id,student_id,task_id)
        );
        CREATE TABLE IF NOT EXISTS demo2_summary_auto_excluded_tasks (
            authorization_id TEXT NOT NULL REFERENCES demo2_summary_authorizations(authorization_id),
            task_id TEXT NOT NULL, PRIMARY KEY(authorization_id,task_id)
        );
    ''')
    if not had_boundary_table:
        # A legacy timestamp cutoff cannot distinguish tasks created in the same
        # second. Conservatively exclude existing tasks; archived rows survive.
        db.execute('''INSERT OR IGNORE INTO demo2_summary_auto_excluded_tasks
            SELECT p.authorization_id,t.task_id FROM demo2_summary_automatic_settings p
            JOIN demo2_summary_authorizations a USING(authorization_id)
            JOIN demo2_summary_students s USING(student_id)
            JOIN video_analysis_tasks t ON t.account_id=s.owner_account_id
            WHERE p.enabled=1 AND p.include_existing=0''')


def capture_boundary(db, student, auth_id):
    db.execute('DELETE FROM demo2_summary_auto_excluded_tasks WHERE authorization_id=?', (auth_id,))
    db.execute('''INSERT INTO demo2_summary_auto_excluded_tasks
        SELECT ?,task_id FROM video_analysis_tasks WHERE account_id=?''', (auth_id, student['owner_account_id']))


def settings(db, auth_id):
    row = db.execute('SELECT * FROM demo2_summary_automatic_settings WHERE authorization_id=?', (auth_id,)).fetchone()
    return dict(enabled=bool(row['enabled']), include_existing=bool(row['include_existing']),
                enabled_at=row['enabled_at']) if row else dict(enabled=False, include_existing=False, enabled_at=None)


def cleanup(db):
    db.execute('''UPDATE demo2_summary_course_history SET body_blob=NULL,fingerprint=''
        WHERE body_blob IS NOT NULL AND authorization_id IN
        (SELECT authorization_id FROM demo2_summary_authorizations WHERE status<>'active')''')
    db.execute('''UPDATE demo2_summary_automatic_settings SET enabled=0 WHERE authorization_id IN
        (SELECT authorization_id FROM demo2_summary_authorizations WHERE status<>'active')''')
    db.execute('''DELETE FROM demo2_summary_auto_excluded_tasks WHERE authorization_id IN
        (SELECT authorization_id FROM demo2_summary_authorizations WHERE status<>'active')''')


def _stamp(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError('Timestamp must include timezone')
    return parsed


def _join_keys(student_id, goal_id, measurement_context):
    def digest(value):
        encoded = json.dumps([student_id, value], ensure_ascii=True, separators=(',', ':')).encode()
        return hashlib.sha256(encoded).hexdigest()
    return dict(goal_key='goal_' + digest(goal_id), context_key='ctx_' + digest(measurement_context))


def _provenance(status):
    historical = status == 'historical_reviewed'
    return dict(source_type='automatic_course_archive', rule_version='course-archive-v1',
                source_status=status, identity_scope='confirmed_sample_frame',
                whole_lesson_tracking=False, scene_metrics_attributed_to_student=False,
                source_note='身份仅在已确认的采样帧关联，不代表整课跟踪、持续在课或全课观察；场景指标不归因于学生。'
                + ('原视频已按保留期删除，无法回查；仅保留此前已归档的教师复核数字，不代表当前可验证证据。' if historical else
                   '来源已失效或变化，测量分数不展示。' if status == 'withheld' else
                   '仅有效且已复核的测量可展示；技术处理完成不代表教学成效。'),
                **({'live_evidence_available': False} if historical else {}))


def _ratio(numerator, denominator):
    if not isinstance(numerator, int) or not isinstance(denominator, int) or denominator <= 0:
        return None
    return round(numerator / denominator, 4)


class AutomaticCourseHistory:
    def __init__(self, store):
        self.store = store

    def _binding(self, student, auth, task_id, entry_id):
        return self.store._binding(student, auth['authorization_id'], entry_id) + ['course-archive-v1', task_id]

    def _technical(self, db, student, task):
        if task is None:
            return None
        identities = self.store.identities
        try:
            if (task['account_id'] != student['owner_account_id'] or task['upload_status'] != 'completed'
                    or task['analysis_status'] != 'evidence_ready' or _stamp(task['expires_at']) <= api._now()):
                return None
            context = identities._context(task.get('school_context_json'))
            if identities._scope(task['account_id'], context) != student['scope_key']:
                return None
            mapped = db.execute('SELECT channel_id FROM demo2_summary_students WHERE student_id=?', (student['student_id'],)).fetchone()
            if mapped is None or mapped['channel_id'] != task['channel_id']:
                return None
            identities._require_media(task)
            manifest = json.loads(task['processing_result_json'])
            media = manifest['media']
            duration = media.get('duration_sec')
            if type(duration) not in (int, float) or not math.isfinite(duration) or duration <= 0:
                return None
            if media.get('has_audio') is not None and type(media['has_audio']) is not bool:
                return None
            revision = identities._revision(task)
            bindings = db.execute('''SELECT * FROM demo2_identity_bindings WHERE task_id=?
                AND student_id=? AND owner_account_id=? AND scope_key=? AND status='confirmed'
                AND role='student' AND frame_revision=? AND source_sha256=? ORDER BY binding_id''',
                (task['task_id'], student['student_id'], student['owner_account_id'], student['scope_key'], revision, task['sha256'])).fetchall()
            valid = []
            for binding in bindings:
                try:
                    identities._frame(task, binding['frame_key'], revision)
                    valid.append(binding['binding_id'])
                except IdentityError:
                    continue
            if not valid:
                return None
            from .video_applicability import assess
            applicability = assess(db, task, self.store.records)
            return dict(media=dict(duration_sec=duration, has_audio=media.get('has_audio')),
                        recorded_on=_stamp(task['created_at']).astimezone(api._now().tzinfo).date().isoformat(),
                        source=dict(revision=revision, sha256=task['sha256'], bindings=valid,
                                    applicability_version=applicability['version'], category=applicability['category']),
                        score_allowed=applicability['allowed'])
        except (IdentityError, ValueError, KeyError, TypeError, OSError):
            return None

    def _lesson_observation(self, db, student, task, technical):
        """Return a compact per-lesson observation summary, never its timeline.

        The detailed state timeline remains in the course-analysis workspace. The
        profile receives only a source-bound lesson summary after a completed
        observation job and a current identity binding are both available.
        """
        if technical is None:
            return None
        try:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='demo2_observation_jobs'").fetchone():
                return None
            job_row = db.execute('''SELECT * FROM demo2_observation_jobs
                WHERE task_id=? AND owner_account_id=? AND scope_key=? AND source_sha256=?
                AND frame_revision=? AND status='ready' ORDER BY updated_at DESC,job_id DESC LIMIT 1''',
                (task['task_id'], student['owner_account_id'], student['scope_key'],
                 task['sha256'], technical['source']['revision'])).fetchone()
            if job_row is None:
                return None
            from .demo2_observation_store import Demo2ObservationStore
            from .demo2_course_analysis import build_student_insights

            observation_store = Demo2ObservationStore(self.store.records, identities=self.store.identities)
            public = observation_store._public(dict(job_row))
            frames = self.store.identities._frames(task)
            revision = technical['source']['revision']
            bindings = self.store.identities._bindings(db, task, revision, set(frames))
            students = self.store.identities._students(db, student['owner_account_id'], student['scope_key'])
            identity = dict(task_id=task['task_id'], frame_revision=revision,
                            scope_key=student['scope_key'], media_available=True,
                            frames=[dict(frame) for frame in frames.values()], bindings=bindings,
                            students=students)
            links = {(row['person_id'], row['frame_key']): row['binding_id'] for row in db.execute('''
                SELECT person_id,frame_key,binding_id FROM demo2_observation_person_links
                WHERE job_id=? AND owner_account_id=? AND scope_key=?
                AND source_sha256=? AND frame_revision=?''',
                (job_row['job_id'], student['owner_account_id'], student['scope_key'],
                 task['sha256'], revision))}
            insights = build_student_insights(public, identity, task, links)
            profile = next((item for item in insights.get('students', [])
                            if item.get('student_id') == student['student_id']), None)
            if not profile:
                return None
            archive = profile.get('archive_summary')
            timeline = profile.get('state_timeline')
            if not isinstance(archive, dict) or not isinstance(timeline, list) or not timeline:
                return None
            frame_rows = {}
            for row in timeline:
                if not isinstance(row, dict) or not isinstance(row.get('frame_key'), str):
                    continue
                frame_rows.setdefault(row['frame_key'], row)
            if not frame_rows:
                return None
            states = [row.get('state_estimate') or {} for row in frame_rows.values()]
            participation = sum(state.get('participation_key') == 'observed' for state in states)
            oriented = sum(state.get('attention_key') == 'oriented' for state in states)
            interaction = sum(state.get('interaction_key') == 'observed' for state in states)
            lesson_summary = dict(
                title='本课表现总结',
                summary=str(archive.get('summary') or profile.get('headline') or '')[:2000],
                key_findings=[str(value)[:500] for value in archive.get('key_findings', [])
                              if isinstance(value, str)][:4],
                support_suggestions=[str(value)[:500] for value in archive.get('support_suggestions', [])
                                     if isinstance(value, str)][:3],
                sample_count=len(frame_rows),
                key_times_sec=[row.get('time_sec') for row in list(frame_rows.values())[:5]
                               if type(row.get('time_sec')) in (int, float) and math.isfinite(row['time_sec'])],
                source_type='automatic_course_archive',
                source_status='machine_observation_draft',
                teacher_review_status='not_reviewed',
                archive_scope='仅保存本节课总结、关键时间点和支持建议；逐时刻状态估计留在本课分析页。',
            )
            trend_point = dict(
                sample_count=len(frame_rows),
                participation_rate=_ratio(participation, len(states)),
                attention_oriented_rate=_ratio(oriented, len(states)),
                interaction_rate=_ratio(interaction, len(states)),
                source_status='machine_observation_draft',
                note='仅为已确认采样点中的可见线索比例，不是学习成绩、专注度或教育评分。',
            )
            return dict(lesson_summary=lesson_summary, trend_point=trend_point)
        except (ImportError, IdentityError, ValueError, KeyError, TypeError, OSError, AttributeError):
            return None

    def _course_measurement(self, db, student, task, technical, record_id, expected=None):
        row = db.execute('''SELECT payload_json,goal_id,measurement_context FROM demo2_measurements WHERE record_id=?
            AND owner_account_id=? AND scope_key=? AND student_id=?''',
            (record_id, student['owner_account_id'], student['scope_key'], student['student_id'])).fetchone()
        try:
            if row is None or technical is None or not technical['score_allowed']:
                raise ValueError
            data = json.loads(row['payload_json'])
            if data.get('task_id') != task['task_id'] or data.get('source_type') != 'video_review':
                raise ValueError
            start, end = data.get('start_sec'), data.get('end_sec')
            if (any(type(v) not in (int, float) or not math.isfinite(v) for v in (start, end))
                    or not 0 <= start < end <= technical['media']['duration_sec']):
                raise ValueError
            binding = db.execute('''SELECT * FROM demo2_identity_bindings WHERE binding_id=?
                AND task_id=? AND student_id=? AND owner_account_id=? AND scope_key=?
                AND role='student' AND status='confirmed' AND frame_revision=? AND source_sha256=?''',
                (data.get('binding_id'), task['task_id'], student['student_id'], student['owner_account_id'],
                 student['scope_key'], data.get('frame_revision'), data.get('source_sha256'))).fetchone()
            if binding is None or not start <= binding['time_sec'] <= end:
                raise ValueError
            frame, _ = self.store.identities._frame(task, binding['frame_key'], binding['frame_revision'])
            if frame['time_sec'] != binding['time_sec']:
                raise ValueError
        except (ValueError, KeyError, TypeError, IdentityError):
            api._fail(409, 'measurement_stale', '测量的采样帧身份、学校、时间区间或视频适用性已失效')
        measurement, provenance, source = self.store._measurement(db, student, record_id, expected)
        return measurement, provenance, {**source, **_join_keys(student['student_id'], row['goal_id'], row['measurement_context'])}

    def _measurements(self, db, student, task, technical):
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='demo2_measurements'").fetchone():
            return [], [], 'pending_review'
        rows = db.execute('''SELECT * FROM demo2_measurements WHERE owner_account_id=? AND scope_key=?
            AND student_id=? AND json_extract(payload_json,'$.task_id')=? ORDER BY record_id''',
            (student['owner_account_id'], student['scope_key'], student['student_id'], task['task_id'])).fetchall()
        if not rows:
            return [], [], 'pending_review'
        active = [row for row in rows if row['status'] == 'active']
        if not active:
            sources = [dict(record_id=row['record_id'], version=row['version'],
                            sha256=hashlib.sha256(row['payload_json'].encode()).hexdigest()) for row in rows]
            return [], sources, 'source_withheld'
        # Withdrawn versions are history, not competing current observations.
        rows = active
        measurements, sources = [], []
        pending, invalid = False, False
        dates = set()
        for row in rows:
            data = json.loads(row['payload_json'])
            sources.append(dict(record_id=row['record_id'], version=row['version'],
                                sha256=hashlib.sha256(row['payload_json'].encode()).hexdigest()))
            if data.get('source_type') != 'video_review' or row['status'] != 'active':
                invalid = True
                continue
            if data.get('reviewed') is not True:
                pending = True
                continue
            try:
                measurement, provenance, source = self._course_measurement(db, student, task, technical, row['record_id'])
                measurements.append(dict(measurement=measurement, provenance=provenance,
                                         goal_key=source['goal_key'], context_key=source['context_key']))
                dates.add(provenance['source_date'])
            except api.StudentSummaryError as exc:
                if exc.status != 409:
                    raise
                invalid = True
        if invalid:
            return [], sources, 'source_withheld'
        if pending or len(dates) != 1:
            return [], sources, 'pending_review'
        return measurements, sources, 'reviewed'

    def _historical(self, db, student, task, previous, *, require_retention=True):
        """Audit-gated export, or DB-only validation of a private checkpoint."""
        if (task is None or previous is None or previous['entry']['status'] not in
                {'reviewed', 'historical_reviewed'} or previous['entry']['reviewed'] is not True
                or not previous['entry']['measurements'] or not previous['technical_source']):
            return None
        try:
            now = api._now()
            expires = _stamp(task['expires_at'])
            if expires > now:
                return None
            if require_retention:
                deleted = _stamp(task['raw_media_deleted_at'])
                if not expires <= deleted <= now:
                    return None
                audit_matches = False
                for audit in db.execute('''SELECT detail_json FROM audit_logs WHERE actor='system_retention'
                    AND action='retention_delete' AND object_type='video_raw_media' AND object_id=?''', (task['task_id'],)):
                    try:
                        detail = json.loads(audit['detail_json'])
                        if (detail.get('expired_at') == task['expires_at'] and detail.get('derived_media_deleted') is True
                                and detail.get('raw_media_present_before_delete') is True
                                and detail.get('derived_media_present_before_delete') is True):
                            audit_matches = True
                            break
                    except (ValueError, TypeError, AttributeError):
                        continue
                if not audit_matches:
                    return None
            if task['upload_status'] != 'completed' or task['analysis_status'] != 'evidence_ready':
                return None
            mapped = db.execute('SELECT channel_id FROM demo2_summary_students WHERE student_id=?', (student['student_id'],)).fetchone()
            context = self.store.identities._context(task.get('school_context_json'))
            if (task['account_id'] != student['owner_account_id'] or mapped is None or mapped['channel_id'] != task['channel_id']
                    or self.store.identities._scope(task['account_id'], context) != student['scope_key']):
                return None
            original = previous['technical_source']
            revision = self.store.identities._revision(task)
            if task['sha256'] != original['sha256'] or revision != original['revision']:
                return None
            from .video_applicability import revision as applicability_revision
            applicability = db.execute('SELECT * FROM demo2_video_applicability WHERE task_id=?', (task['task_id'],)).fetchone()
            if (applicability is None or applicability['category'] != 'special' or original['category'] != 'special'
                    or applicability['revision'] != applicability_revision(task)
                    or applicability['version'] != original['applicability_version']):
                return None
            # _frames parses retained JSON metadata only; _frame/_require_media
            # would open live evidence and are deliberately not used here.
            frames = self.store.identities._frames(task)
            bindings = {}
            for binding_id in original['bindings']:
                binding = db.execute('''SELECT * FROM demo2_identity_bindings WHERE binding_id=?
                    AND task_id=? AND student_id=? AND owner_account_id=? AND scope_key=?
                    AND role='student' AND status='confirmed' AND frame_revision=? AND source_sha256=?''',
                    (binding_id, task['task_id'], student['student_id'], student['owner_account_id'],
                     student['scope_key'], revision, task['sha256'])).fetchone()
                if binding is None or binding['frame_key'] not in frames or frames[binding['frame_key']]['time_sec'] != binding['time_sec']:
                    return None
                bindings[binding_id] = binding
            sources, archived = previous['measurement_sources'], previous['entry']['measurements']
            if not bindings or len(sources) != len(archived):
                return None
            retained = []
            for source, item in zip(sources, archived):
                row = db.execute('''SELECT * FROM demo2_measurements WHERE record_id=? AND student_id=?
                    AND owner_account_id=? AND scope_key=?''', (source['record_id'], student['student_id'],
                    student['owner_account_id'], student['scope_key'])).fetchone()
                if (row is None or row['status'] != 'active' or row['version'] != source['version']
                        or _stamp(row['expires_at']) <= now
                        or hashlib.sha256(row['payload_json'].encode()).hexdigest() != source['sha256']):
                    return None
                data = json.loads(row['payload_json'])
                binding = bindings.get(data.get('binding_id'))
                start, end = data.get('start_sec'), data.get('end_sec')
                if (data.get('reviewed') is not True or data.get('rubric_version') != api.RUBRIC_VERSION
                        or data.get('source_type') != 'video_review' or data.get('task_id') != task['task_id']
                        or data.get('record_id') != source['record_id'] or data.get('student_id') != student['student_id']
                        or data.get('version') != source['version'] or data.get('status') != 'active'
                        or data.get('frame_revision') != revision or data.get('source_sha256') != task['sha256']
                        or binding is None or any(type(v) not in (int, float) or not math.isfinite(v) for v in (start, end))
                        or not 0 <= start < end <= previous['entry']['media']['duration_sec']
                        or not start <= binding['time_sec'] <= end):
                    return None
                retained.append(dict(item, **_join_keys(student['student_id'], row['goal_id'], row['measurement_context']),
                    provenance={**item['provenance'], 'source_status': 'historical_reviewed',
                                'live_evidence_available': False, 'source_note': '原视频已按保留期删除，仅保留此前归档的教师复核数字，无法回查原视频。'}))
            entry = dict(previous['entry'], status='historical_reviewed', reviewed=True, live_evidence_available=False,
                         measurements=retained, provenance=_provenance('historical_reviewed'))
            return dict(previous, entry=entry)
        except (ValueError, KeyError, TypeError, IdentityError):
            return None

    def _state(self, db, student, task_id, task, previous, enabled):
        technical = self._technical(db, student, task)
        if technical is None:
            if previous is None:
                return None
            checkpoint = previous.get('last_approved')
            if checkpoint is None and previous['entry']['status'] in {'reviewed', 'historical_reviewed'}:
                checkpoint = {key: previous[key] for key in ('entry', 'technical_source', 'measurement_sources')}
            # A maintenance interval may separate TTL expiry from deletion.
            # Retain approved numbers privately only while every DB source is
            # unchanged; no unaudited checkpoint is returned to the caller.
            checkpoint_valid = self._historical(db, student, task, checkpoint, require_retention=False)
            if checkpoint_valid is not None:
                historical = self._historical(db, student, task, checkpoint)
                if historical is not None:
                    return dict(historical, last_approved=checkpoint)
            entry = dict(previous['entry'], measurements=[], reviewed=False, status='source_withheld',
                         provenance=_provenance('withheld'))
            state = dict(entry=entry, technical_source=None, measurement_sources=previous['measurement_sources'])
            if checkpoint_valid is not None:
                state['last_approved'] = checkpoint
            return state
        if not enabled and previous is not None:
            valid = previous['technical_source'] == technical['source']
            keys = []
            for source in previous['measurement_sources']:
                try:
                    _, _, current = self._course_measurement(db, student, task, technical, source['record_id'], source)
                    keys.append(dict(goal_key=current['goal_key'], context_key=current['context_key']))
                except api.StudentSummaryError as exc:
                    if exc.status != 409:
                        raise
                    valid = False
            if valid:
                if previous['entry']['measurements']:
                    entry = dict(previous['entry'], measurements=[dict(item, **key) for item, key
                                 in zip(previous['entry']['measurements'], keys)])
                    return dict(previous, entry=entry)
                return previous
            entry = dict(previous['entry'], measurements=[], reviewed=False, status='source_withheld',
                         provenance=_provenance('withheld'))
            # Keep original source versions while paused: do not import new data.
            return dict(entry=entry, technical_source=previous['technical_source'],
                        measurement_sources=previous['measurement_sources'])
        measurements, sources, status = self._measurements(db, student, task, technical)
        if not sources and previous is not None and previous['measurement_sources']:
            sources, status = previous['measurement_sources'], 'source_withheld'
        if not technical['score_allowed']:
            measurements, status = [], 'pending_review'
        recorded_on, basis = technical['recorded_on'], 'upload_date'
        if status == 'reviewed':
            recorded_on = measurements[0]['provenance']['source_date']
            basis = 'lesson_date'
        entry = dict(recorded_on=recorded_on, date_basis=basis, status=status,
                     reviewed=status == 'reviewed', media=technical['media'], measurements=measurements,
                     provenance=_provenance('current' if status == 'reviewed' else
                                            'withheld' if status == 'source_withheld' else 'technical_only'))
        observation = self._lesson_observation(db, student, task, technical)
        if observation is not None:
            entry.update(observation)
        state = dict(entry=entry, technical_source=technical['source'], measurement_sources=sources)
        if status == 'reviewed':
            state['last_approved'] = dict(state)
        return state

    def sync_student(self, db, student, auth):
        stats = dict(created=0, updated=0, skipped=0, errors=0)
        if auth is not None:
            auth = db.execute('''SELECT * FROM demo2_summary_authorizations
                WHERE authorization_id=? AND student_id=?''',
                (auth['authorization_id'], student['student_id'])).fetchone()
        if not self.store._active(auth) or not self.store._current_scope(db, student):
            return stats
        self.store._open(self.store._binding(student, auth['authorization_id']), auth['reference_blob'])
        prefs = settings(db, auth['authorization_id'])
        existing = {r['task_id']: r for r in db.execute('''SELECT * FROM demo2_summary_course_history
            WHERE authorization_id=? AND student_id=? AND body_blob IS NOT NULL''',
            (auth['authorization_id'], student['student_id']))}
        tasks = {}
        if prefs['enabled']:
            for task in db.execute('''SELECT DISTINCT t.* FROM video_analysis_tasks t
                JOIN demo2_identity_bindings b ON b.task_id=t.task_id
                WHERE t.account_id=? AND b.owner_account_id=? AND b.scope_key=? AND b.student_id=?
                AND b.status='confirmed' AND b.role='student' AND t.upload_status='completed'
                AND t.analysis_status='evidence_ready' ''',
                (student['owner_account_id'], student['owner_account_id'], student['scope_key'], student['student_id'])):
                excluded = db.execute('''SELECT 1 FROM demo2_summary_auto_excluded_tasks
                    WHERE authorization_id=? AND task_id=?''', (auth['authorization_id'], task['task_id'])).fetchone()
                eligible = prefs['include_existing'] or excluded is None
                if eligible or task['task_id'] in existing:
                    tasks[task['task_id']] = dict(task)
        for task_id in existing:
            if task_id not in tasks:
                task = db.execute('SELECT * FROM video_analysis_tasks WHERE task_id=?', (task_id,)).fetchone()
                tasks[task_id] = dict(task) if task else None
        for task_id, task in tasks.items():
            row = existing.get(task_id)
            previous = self.store._open(self._binding(student, auth, task_id, row['entry_id']), row['body_blob']) if row else None
            state = self._state(db, student, task_id, task, previous, prefs['enabled'])
            if state is None:
                stats['skipped'] += 1
                continue
            fingerprint = hashlib.sha256(json.dumps(state, sort_keys=True, allow_nan=False).encode()).hexdigest()
            if row and fingerprint == row['fingerprint']:
                stats['skipped'] += 1
                continue
            entry_id = row['entry_id'] if row else 'ch_' + uuid4().hex
            now = api._now().isoformat()
            blob = self.store._seal(self._binding(student, auth, task_id, entry_id), state)
            revision = row['revision'] + 1 if row else 1
            db.execute('''INSERT INTO demo2_summary_course_history VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(authorization_id,student_id,task_id) DO UPDATE SET
                revision=excluded.revision,fingerprint=excluded.fingerprint,body_blob=excluded.body_blob,updated_at=excluded.updated_at''',
                (entry_id, auth['authorization_id'], student['student_id'], task_id, revision,
                 fingerprint, blob, row['created_at'] if row else now, now))
            self.store.records._audit(db, 'automatic_course_archive', 'student_course_history_synced',
                                      'student_course_history', entry_id, {'revision': revision})
            stats['updated' if row else 'created'] += 1
        return stats

    def history(self, db, student, auth):
        if not self.store._active(auth) or not self.store._current_scope(db, student):
            return []
        self.sync_student(db, student, auth)
        result = []
        for row in db.execute('''SELECT * FROM demo2_summary_course_history WHERE authorization_id=?
            AND student_id=? AND body_blob IS NOT NULL ORDER BY created_at,entry_id''',
            (auth['authorization_id'], student['student_id'])):
            state = self.store._open(self._binding(student, auth, row['task_id'], row['entry_id']), row['body_blob'])
            result.append(dict(state['entry'], entry_id=row['entry_id'], revision=row['revision'],
                               created_at=row['created_at'], updated_at=row['updated_at']))
        return result

    def sync_all(self):
        stats = dict(created=0, updated=0, skipped=0, errors=0)
        with self.store.records._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self.store._cleanup(db)
            rows = db.execute('''SELECT s.*,a.authorization_id,a.valid_until,a.status,a.reference_blob
                FROM demo2_summary_students s JOIN demo2_summary_authorizations a USING(student_id)
                WHERE a.status='active' ''').fetchall()
            for student in rows:
                db.execute('SAVEPOINT automatic_student')
                try:
                    counts = self.sync_student(db, student, student)
                    db.execute('RELEASE automatic_student')
                    for key in stats:
                        stats[key] += counts[key]
                except (api.StudentSummaryError, ValueError, TypeError, KeyError, OSError):
                    db.execute('ROLLBACK TO automatic_student')
                    db.execute('RELEASE automatic_student')
                    stats['errors'] += 1
        return stats
