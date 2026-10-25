"""Teacher-entered, account/school-scoped classroom measurements.

No legacy demo score or generated lesson date is imported. Every saved version
is retained for audit; only the latest, non-withdrawn version enters a trend.
"""
from __future__ import annotations

import json
import math
import re
from datetime import date, datetime, timedelta
from uuid import uuid4

from .assessment_rubric import RUBRIC_VERSION, build_assessment_summary, build_longitudinal_series
from .demo2_identity_store import Demo2IdentityStore, IdentityError, _field
from .student_record_store import _iso


class MeasurementError(ValueError):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


class Demo2MeasurementStore:
    def __init__(self, records):
        self.records = records
        self.identities = Demo2IdentityStore(records)
        with records._connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS demo2_measurements (
                    record_id TEXT PRIMARY KEY, owner_account_id TEXT NOT NULL,
                    scope_key TEXT NOT NULL, student_id TEXT NOT NULL,
                    lesson_date TEXT NOT NULL, lesson_id TEXT NOT NULL,
                    goal_id TEXT NOT NULL, measurement_context TEXT NOT NULL,
                    version INTEGER NOT NULL, status TEXT NOT NULL,
                    payload_json TEXT NOT NULL, created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL, expires_at TEXT NOT NULL,
                    FOREIGN KEY(student_id, owner_account_id, scope_key)
                      REFERENCES demo2_identity_students(student_id, owner_account_id, scope_key)
                );
                CREATE TABLE IF NOT EXISTS demo2_measurement_versions (
                    record_id TEXT NOT NULL, version INTEGER NOT NULL,
                    payload_json TEXT NOT NULL, saved_by TEXT NOT NULL,
                    saved_at TEXT NOT NULL, PRIMARY KEY(record_id,version)
                );
                CREATE INDEX IF NOT EXISTS idx_demo2_measurement_scope
                  ON demo2_measurements(owner_account_id,scope_key,student_id,lesson_date);
                CREATE INDEX IF NOT EXISTS idx_demo2_measurement_task
                  ON demo2_measurements(owner_account_id,scope_key,json_extract(payload_json,'$.task_id'))
                  WHERE status='active';
                CREATE UNIQUE INDEX IF NOT EXISTS idx_demo2_measurement_active_lesson
                  ON demo2_measurements(owner_account_id,scope_key,student_id,lesson_id,goal_id,measurement_context)
                  WHERE status='active';
                CREATE TABLE IF NOT EXISTS demo2_batch_decisions (
                    group_id TEXT PRIMARY KEY, owner_account_id TEXT NOT NULL, scope_key TEXT NOT NULL,
                    fingerprint TEXT NOT NULL, selected_record_id TEXT NOT NULL, reason TEXT NOT NULL,
                    version INTEGER NOT NULL, saved_by TEXT NOT NULL, saved_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS demo2_batch_decision_versions (
                    group_id TEXT NOT NULL, version INTEGER NOT NULL, payload_json TEXT NOT NULL,
                    PRIMARY KEY(group_id,version)
                );
                CREATE TABLE IF NOT EXISTS demo2_teaching_plans (
                    task_id TEXT NOT NULL, owner_account_id TEXT NOT NULL, scope_key TEXT NOT NULL,
                    version INTEGER NOT NULL, payload_json TEXT NOT NULL,
                    PRIMARY KEY(task_id,owner_account_id,scope_key)
                );
                CREATE TABLE IF NOT EXISTS demo2_teaching_plan_versions (
                    task_id TEXT NOT NULL, owner_account_id TEXT NOT NULL, version INTEGER NOT NULL,
                    payload_json TEXT NOT NULL, PRIMARY KEY(task_id,owner_account_id,version)
                );
            ''')

    def _account(self, token, *, admin=False):
        try:
            account = self.records.account_from_session(token)
        except ValueError:
            raise MeasurementError(401, 'authentication_required', '请重新登录') from None
        if account['role'] != ('company_admin' if admin else 'school_uploader'):
            raise MeasurementError(403, 'measurement_forbidden', '当前账号无此操作权限')
        return account

    def _scope(self, db, account):
        try:
            context = self.identities._context(self.records._school_context_for_account(db, account['account_id']))
            return self.identities._scope(account['account_id'], context)
        except IdentityError as exc:
            raise MeasurementError(exc.status, exc.code, exc.message) from None

    def _student(self, db, account, scope, student_id):
        row = db.execute('SELECT * FROM demo2_identity_students WHERE student_id=? AND owner_account_id=? AND scope_key=?',
                         (student_id, account['account_id'], scope)).fetchone()
        if row is None:
            raise MeasurementError(404, 'student_unavailable', '学生不存在或不属于当前学校名册')
        return row

    @staticmethod
    def _text(value, limit=200, required=True):
        try:
            return _field(value, limit, required=required)
        except IdentityError as exc:
            raise MeasurementError(400, 'invalid_field', exc.message) from None

    @staticmethod
    def _id(value):
        if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,120}', value):
            raise MeasurementError(400, 'invalid_id', '记录编号格式无效')
        return value

    def save(self, token, payload):
        account = self._account(token)
        allowed = {'record_id','expected_version','student_id','lesson_date','lesson_id','course_name',
                   'goal_id','measurement_context','criterion','scores','opportunities','observed',
                   'reviewed','evidence','source_type','task_id','start_sec','end_sec',
                   'teacher_prompt','student_response','support_level','observed_state',
                   'response_mode','audio_quality','vocalization','speaker_confirmed'}
        if not isinstance(payload, dict) or set(payload) - allowed:
            raise MeasurementError(400, 'invalid_payload', '测量记录包含未知字段')
        record_id = self._id(payload.get('record_id'))
        expected = payload.get('expected_version')
        if type(expected) is not int or expected < 0:
            raise MeasurementError(400, 'invalid_version', '请先读取当前记录版本')
        data = {k:self._text(payload.get(k,''), 2000 if k in {'criterion','evidence'} else 200)
                for k in ('student_id','lesson_id','course_name','goal_id','measurement_context','criterion','evidence')}
        raw_date = payload.get('lesson_date')
        try:
            when = date.fromisoformat(raw_date)
            if when.isoformat() != raw_date or when > date.today():
                raise ValueError
        except (ValueError, TypeError):
            raise MeasurementError(400, 'invalid_date', '请填写真实上课日期，不能使用未来日期') from None
        if type(payload.get('reviewed')) is not bool:
            raise MeasurementError(400, 'invalid_review', '请明确教师是否已复核')
        if not isinstance(payload.get('scores'), dict):
            raise MeasurementError(400, 'invalid_scores', '请填写四维测量结果')
        summary = build_assessment_summary(payload['scores'], opportunities=payload.get('opportunities'),
                                           observed=payload.get('observed'), reviewed=payload['reviewed'],
                                           source='教师逐课观察记录')
        source_type = payload.get('source_type')
        if source_type not in {'classroom_observation','video_review'}:
            raise MeasurementError(400,'invalid_source','请选择现场观察或视频复核')
        data.update(record_id=record_id, lesson_date=raw_date, scores=payload['scores'],
                    opportunities=payload['opportunities'], observed=payload['observed'],
                    reviewed=payload['reviewed'], source_type=source_type, task_id='',
                    start_sec=None,end_sec=None, rubric_version=RUBRIC_VERSION, assessment=summary)
        for field in ('teacher_prompt', 'student_response'):
            data[field] = self._text(payload.get(field, ''), 1000, required=False)
        options = {'support_level': {'unknown','independent','verbal','visual','demonstration','physical'},
                   'observed_state': {'unknown','participating','repeat_prompt','help_requested','paused'},
                   'response_mode': {'unknown','speech','gesture','picture','aac','gaze','action','vocalization','mixed'},
                   'audio_quality': {'unknown','clear','partial','missing'},
                   'vocalization': {'unknown','none','cry','laugh','other'}}
        for field, values in options.items():
            value = payload.get(field, 'unknown')
            if not isinstance(value, str) or value not in values:
                raise MeasurementError(400,'invalid_observation','课堂观察选项无效')
            data[field] = value
        if type(payload.get('speaker_confirmed',False)) is not bool:
            raise MeasurementError(400,'invalid_observation','请明确是否确认发声来源')
        data['speaker_confirmed']=payload.get('speaker_confirmed',False)
        data['vocalization_scope']='student' if data['speaker_confirmed'] else 'scene_unknown_speaker'
        if source_type == 'video_review':
            data['task_id'] = self._id(payload.get('task_id'))
            for key in ('start_sec','end_sec'):
                value=payload.get(key)
                if type(value) not in (int,float) or not math.isfinite(value) or not 0 <= value <= 10800:
                    raise MeasurementError(400,'invalid_time','视频时间必须为有效秒数')
                data[key]=value
            if data['end_sec'] <= data['start_sec']:
                raise MeasurementError(400,'invalid_time','结束时间必须晚于开始时间')
        with self.records._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            scope=self._scope(db,account)
            self._student(db,account,scope,data['student_id'])
            previous=db.execute('SELECT * FROM demo2_measurements WHERE record_id=?',(record_id,)).fetchone()
            if previous is not None:
                if previous['owner_account_id'] != account['account_id'] or previous['scope_key'] != scope:
                    raise MeasurementError(404,'record_unavailable','记录不存在或无权查看')
                if previous['version'] != expected or previous['status']=='withdrawn':
                    raise MeasurementError(409,'version_conflict','记录已更新或撤销，请刷新后核对')
                if previous['student_id'] != data['student_id']:
                    raise MeasurementError(409,'student_conflict','不可将记录改给另一名学生')
            elif expected != 0:
                raise MeasurementError(409,'version_conflict','记录版本已失效，请刷新后核对')
            duplicate=db.execute('''SELECT record_id FROM demo2_measurements WHERE owner_account_id=? AND scope_key=?
                AND student_id=? AND lesson_id=? AND goal_id=? AND measurement_context=? AND record_id<>? AND status='active' ''',
                (account['account_id'],scope,data['student_id'],data['lesson_id'],data['goal_id'],data['measurement_context'],record_id)).fetchone()
            if duplicate:
                raise MeasurementError(409,'duplicate_lesson','本课同一目标和条件已有记录，请编辑原记录')
            if source_type=='video_review':
                task=self.identities._task(db,account,data['task_id'])
                self.identities._require_media(task)
                from .video_applicability import assess
                suitability=assess(db,task,self.records)
                if not suitability['allowed'] and (any(v is not None for v in data['scores'].values()) or data['reviewed']):
                    raise MeasurementError(409,'applicability_required','请先确认视频适用性；当前仅可保存不评分、未复核的观察草稿')
                revision = self.identities._revision(task)
                manifest = json.loads(task['processing_result_json'])
                duration = manifest.get('media', {}).get('duration_sec')
                if type(duration) not in (int,float) or not math.isfinite(duration) or data['end_sec'] > duration:
                    raise MeasurementError(400,'invalid_time','复核时段不能超过视频实际时长')
                bound=db.execute('''SELECT * FROM demo2_identity_bindings WHERE task_id=? AND student_id=?
                    AND owner_account_id=? AND scope_key=? AND status='confirmed' AND role='student'
                    AND frame_revision=? AND source_sha256=? AND time_sec>=? AND time_sec<=?
                    ORDER BY time_sec LIMIT 1''',
                    (data['task_id'],data['student_id'],account['account_id'],scope,revision,task['sha256'],
                     data['start_sec'],data['end_sec'])).fetchone()
                if bound is None:
                    raise MeasurementError(409,'identity_required','请先在所选时间段确认该学生身份')
                self.identities._frame(task, bound['frame_key'], revision)
                data.update(binding_id=bound['binding_id'], frame_revision=revision, source_sha256=task['sha256'])
            now=_iso(); version=expected+1
            data.update(version=version, status='active', saved_by=account['username'], updated_at=now)
            content=json.dumps(data,ensure_ascii=False,allow_nan=False)
            expires=(datetime.now().astimezone()+timedelta(days=730)).isoformat(timespec='seconds')
            db.execute('''INSERT INTO demo2_measurements VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(record_id) DO UPDATE SET lesson_date=excluded.lesson_date,lesson_id=excluded.lesson_id,
                goal_id=excluded.goal_id,measurement_context=excluded.measurement_context,version=excluded.version,
                payload_json=excluded.payload_json,updated_at=excluded.updated_at''',
                (record_id,account['account_id'],scope,data['student_id'],raw_date,data['lesson_id'],data['goal_id'],
                 data['measurement_context'],version,'active',content,now,now,expires))
            db.execute('INSERT INTO demo2_measurement_versions VALUES(?,?,?,?,?)',(record_id,version,content,account['username'],now))
            self.records._audit(db,account['username'],'measurement_saved','measurement',record_id,
                                {'version':version,'reviewed':data['reviewed']})
        return data

    def withdraw(self,token,payload):
        account=self._account(token)
        if not isinstance(payload,dict) or set(payload)!={'record_id','expected_version','reason'}:
            raise MeasurementError(400,'invalid_payload','请提交记录编号、版本和撤销原因')
        record_id=self._id(payload['record_id']);reason=self._text(payload['reason'],1000)
        with self.records._connect() as db:
            db.execute('BEGIN IMMEDIATE');scope=self._scope(db,account)
            row=db.execute('SELECT * FROM demo2_measurements WHERE record_id=? AND owner_account_id=? AND scope_key=?',
                           (record_id,account['account_id'],scope)).fetchone()
            if row is None: raise MeasurementError(404,'record_unavailable','无权查看记录')
            if type(payload['expected_version']) is not int or row['version']!=payload['expected_version']:
                raise MeasurementError(409,'version_conflict','记录已变更，请刷新')
            if row['status']=='withdrawn':
                raise MeasurementError(409,'already_withdrawn','记录已撤销')
            data=json.loads(row['payload_json']);now=_iso();version=row['version']+1
            data.update(status='withdrawn',withdrawal_reason=reason,version=version,updated_at=now)
            content=json.dumps(data,ensure_ascii=False)
            db.execute('UPDATE demo2_measurements SET status=?,version=?,payload_json=?,updated_at=? WHERE record_id=?',
                       ('withdrawn',version,content,now,record_id))
            db.execute('INSERT INTO demo2_measurement_versions VALUES(?,?,?,?,?)',(record_id,version,content,account['username'],now))
            self.records._audit(db,account['username'],'measurement_withdrawn','measurement',record_id,{'version':version})
        return data

    def _effective_record(self, db, account, data):
        """Keep historical text, but exclude revoked or stale identity evidence."""
        data = dict(data)
        data['evidence_status'] = 'current'
        if data.get('source_type') != 'video_review':
            return data
        binding = db.execute('SELECT * FROM demo2_identity_bindings WHERE binding_id=? AND owner_account_id=?',
                             (data.get('binding_id',''), account['account_id'])).fetchone()
        try:
            task = self.identities._task(db, account, data['task_id'])
            from .video_applicability import assess
            suitability=assess(db,task,self.records)
            data['course_batch_id'] = task.get('course_id') or data['task_id']
            data['applicability_blocked']=not suitability['confirmed_for_source']
            valid = (suitability['confirmed_for_source'] and binding is not None and binding['status']=='confirmed'
                     and binding['student_id']==data['student_id'] and binding['task_id']==data['task_id']
                     and binding['frame_revision']==data.get('frame_revision')==self.identities._revision(task)
                     and binding['source_sha256']==data.get('source_sha256')==task.get('sha256'))
        except IdentityError:
            valid = False
        if not valid:
            data['evidence_status'] = 'needs_reconfirmation'
            data['assessment'] = {**data['assessment'], 'overall_score':None, 'provisional_score':None,
                                  'passed':None, 'insufficient_evidence':True,
                                  'band':{'key':'unobserved','label':'证据待重新确认','pass':None}}
        return data

    def course_workspace(self, token, task_id):
        from .demo2_course_analysis import build_workspace
        from .demo2_evaluation_store import Demo2EvaluationStore
        account = self._account(token)
        identity = self.identities.workspace(token, task_id)
        with self.records._connect() as db:
            task = self.identities._task(db, account, task_id)
            rows = db.execute('''SELECT payload_json FROM demo2_measurements
                WHERE owner_account_id=? AND scope_key=? AND status='active'
                AND json_extract(payload_json,'$.task_id')=?
                ORDER BY lesson_date,record_id''', (account['account_id'], identity['scope_key'],task_id)).fetchall()
            values = [json.loads(r['payload_json']) for r in rows]
            values = [self._effective_record(db,account,r) for r in values]
            from .video_applicability import assess
            suitability=assess(db,task,self.records)
        # Evaluation/report is a separate store, but it is joined here by the
        # immutable task id so the course page sees the same source video.
        evaluations=Demo2EvaluationStore(self.records).for_task(token,task_id)
        result=build_workspace(identity, task, values, evaluations=evaluations)
        from .demo2_iep_context import attach_iep_context
        attach_iep_context(self.records, token, result)
        result['applicability']=suitability
        if not suitability['confirmed_for_source']:
            explanation=suitability['label']+'。请先确认内容适用性；可保留通用观察，但不据此推断学生能力或教师教学质量。'
            result['report']={**result['report'],'title':'视频适用性检查记录（未形成课堂评价）','ready':False,'character_count':len(explanation),'sections':[{'title':'暂不生成特教评价','text':explanation}]}
        return result

    def course_report(self, token, task_id):
        """Build the downloadable report from the current task workspace."""
        from .demo2_course_analysis import build_task_report
        from .demo2_evaluation_store import Demo2EvaluationStore
        work=self.course_workspace(token, task_id)
        # Keep the legacy in-page report untouched when there is no saved
        # evaluation, while the explicit download endpoint always exposes the
        # stable task/report contract and its evidence-limit sections.
        with self.records._connect() as db:
            account=self._account(token)
            task=self.identities._task(db,account,task_id)
        evaluations=Demo2EvaluationStore(self.records).for_task(token,task_id)
        return build_task_report(
            task=task,
            school_context=work.get('school_context'),
            people=work.get('people',[]),
            records=work.get('records',[]),
            evaluations=evaluations,
            base_report=work['report'],
        )

    def course_tasks(self, token):
        account = self._account(token)
        with self.records._connect() as db:
            rows = db.execute('''SELECT task_id,course_name,course_id,original_filename AS filename,analysis_status,created_at
                FROM video_analysis_tasks WHERE account_id=? AND upload_status<>'cancelled'
                ORDER BY created_at DESC LIMIT 200''', (account['account_id'],)).fetchall()
        return {'tasks':[dict(r) for r in rows], 'limit':200}

    def support_workspace(self, token, task_id):
        from .teaching_support import NEEDS, REFERENCES, deepseek_status, safe_preview
        account=self._account(token)
        work=self.course_workspace(token,task_id)
        with self.records._connect() as db:
            task=self.identities._task(db,account,task_id)
            scope=self.identities._scope(account['account_id'],work['school_context'])
            rows=db.execute('''SELECT p.payload_json,t.course_name FROM demo2_teaching_plans p
                JOIN video_analysis_tasks t ON t.task_id=p.task_id
                WHERE p.owner_account_id=? AND p.scope_key=? ORDER BY json_extract(p.payload_json,'$.updated_at') DESC LIMIT 100''',
                (account['account_id'],scope)).fetchall()
            row=db.execute('SELECT payload_json FROM demo2_teaching_plans WHERE task_id=? AND owner_account_id=? AND scope_key=?',
                (task_id,account['account_id'],scope)).fetchone()
        history=[{**json.loads(r['payload_json']),'course_name':r['course_name']} for r in rows]
        current=json.loads(row['payload_json']) if row else None
        return {'course':work,'needs':NEEDS,'references':REFERENCES,'deepseek':deepseek_status(),
            'preview':safe_preview(work),'plan':current,'history':history,
            'readiness':[
                {'label':'学校归属','done':bool(work['school_context'].get('school_name')),'url':'/demo2/school'},
                {'label':'视频完整上传','done':task['upload_status']=='completed','url':'/demo2/upload'},
                {'label':'证据处理完成','done':task['analysis_status']=='evidence_ready','url':'/demo2/video?id='+task_id},
                {'label':'学生身份确认','done':any(p.get('bindings') for p in work['people']),'url':'/demo2/identity?task_id='+task_id},
                {'label':'教师复核记录','done':work['summary']['reviewed']>0,'url':'/demo2/analysis?task_id='+task_id}],
            'audio_note':'存在音轨，仍需试听远处声音、重叠声和非言语发声。' if work['media_available'] and work['media'].get('has_audio') else '未确认有可用音轨；不要据此判断学生没有回应。'}

    def save_support_plan(self, token, payload):
        from .teaching_support import NEEDS
        account=self._account(token)
        fields={'task_id','expected_version','need','lesson_date','goal','strength','next_action','outcome','next_check'}
        if not isinstance(payload,dict) or set(payload)!=fields:
            raise MeasurementError(400,'invalid_payload','请填写本课支持计划与改进记录')
        task_id=self._id(payload['task_id'])
        if type(payload['expected_version']) is not int or payload['expected_version']<0:
            raise MeasurementError(400,'invalid_version','记录版本无效')
        if not isinstance(payload['need'],str) or payload['need'] not in NEEDS:
            raise MeasurementError(400,'invalid_need','请选择支持需求，不填写诊断推断')
        try:
            day=date.fromisoformat(payload['lesson_date'])
            if day>date.today() or day.isoformat()!=payload['lesson_date']:raise ValueError
        except (TypeError,ValueError):
            raise MeasurementError(400,'invalid_date','请填写真实上课日期') from None
        data={k:self._text(payload[k],1000,required=k in {'goal','next_action','next_check'})
              for k in ('goal','strength','next_action','outcome','next_check')}
        with self.records._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            task=self.identities._task(db,account,task_id)
            scope=self.identities._scope(account['account_id'],self.identities._context(task.get('school_context_json')))
            previous=db.execute('SELECT version FROM demo2_teaching_plans WHERE task_id=? AND owner_account_id=? AND scope_key=?',
                (task_id,account['account_id'],scope)).fetchone()
            current=previous['version'] if previous else 0
            if current!=payload['expected_version']:
                raise MeasurementError(409,'version_conflict','记录已更新，请刷新后核对')
            data.update(task_id=task_id,need=payload['need'],lesson_date=payload['lesson_date'],version=current+1,updated_at=_iso())
            content=json.dumps(data,ensure_ascii=False)
            db.execute('''INSERT INTO demo2_teaching_plans VALUES(?,?,?,?,?) ON CONFLICT(task_id,owner_account_id,scope_key)
                DO UPDATE SET version=excluded.version,payload_json=excluded.payload_json''',(task_id,account['account_id'],scope,current+1,content))
            db.execute('INSERT INTO demo2_teaching_plan_versions VALUES(?,?,?,?)',(task_id,account['account_id'],current+1,content))
            self.records._audit(db,account['username'],'teaching_plan_saved','measurement',task_id,{'version':current+1})
        return data

    @staticmethod
    def _decisions(db, account, scope):
        return {r['group_id']:dict(r) for r in db.execute('''SELECT * FROM demo2_batch_decisions
            WHERE owner_account_id=? AND scope_key=?''',(account['account_id'],scope))}

    def _batch_workspace(self, db, account, task_id):
        from .demo2_batch_review import group_records
        task=self.identities._task(db,account,task_id)
        context=self.identities._context(task.get('school_context_json'),required=False)
        if not all(context.values()):
            # Keep an incomplete lesson readable without merging unscoped records.
            return {'task_id':task_id,'course_id':task['course_id'],'course_name':task['course_name'],
                'school_context':context,'scope_key':'','school_context_required':True,
                'tasks':[{k:task[k] for k in ('task_id','course_name','analysis_status','upload_status')}],
                'students':[],'groups':[],
                'summary':{'videos':1,'records':0,'goals':0,'pending':0,'scored':0},
                'policy':'本视频尚未确认学校归属，暂不合并其他视频或生成汇总评分。请先补充学校信息，并返回视频确认归属。'}
        scope=self.identities._scope(account['account_id'],context)
        tasks=[]
        for row in db.execute('''SELECT * FROM video_analysis_tasks WHERE account_id=?
            AND course_id=? ORDER BY created_at''',(account['account_id'],task['course_id'])):
            row=dict(row)
            if not task['course_id'] and row['task_id']!=task_id:
                continue
            candidate=self.identities._context(row.get('school_context_json'),required=False)
            if self.identities._scope(account['account_id'],candidate)!=scope:
                continue
            tasks.append({k:row[k] for k in ('task_id','course_name','analysis_status','upload_status')})
        ids={t['task_id'] for t in tasks}
        rows=db.execute('''SELECT payload_json FROM demo2_measurements
            WHERE owner_account_id=? AND scope_key=? AND status='active'
            AND json_extract(payload_json,'$.task_id') IN
                (SELECT task_id FROM video_analysis_tasks WHERE account_id=? AND course_id=?)''',
            (account['account_id'],scope,account['account_id'],task['course_id'])).fetchall()
        values=[json.loads(r['payload_json']) for r in rows]
        values=[self._effective_record(db,account,r) for r in values if r.get('task_id') in ids]
        groups=group_records(values,scope,self._decisions(db,account,scope))
        students=self.identities._students(db,account['account_id'],scope)
        students=[s for s in students if any(g['student_id']==s['student_id'] for g in groups)]
        return {'task_id':task_id,'course_id':task['course_id'],'course_name':task['course_name'],
            'school_context':context,'scope_key':scope,'tasks':tasks,'students':students,'groups':groups,
            'summary':{'videos':len(tasks),'records':len(values),'goals':len(groups),
                       'pending':sum(g['status'] in {'needs_review','stale','pending'} for g in groups),
                       'scored':sum(g['score'] is not None for g in groups)},
            'policy':'同批次按日期、学生、目标、条件、标准与量表版本分组；多条记录须核准代表记录，不叠加机会数、不平均分数。'}

    def batch_workspace(self, token, task_id):
        account=self._account(token)
        with self.records._connect() as db:
            return self._batch_workspace(db,account,task_id)

    def confirm_batch(self, token, payload):
        account=self._account(token)
        required={'task_id','group_id','fingerprint','expected_version','selected_record_id','reason','confirmed'}
        if not isinstance(payload,dict) or set(payload)!=required or payload['confirmed'] is not True:
            raise MeasurementError(400,'invalid_confirmation','请确认本课代表记录及核准理由')
        task_id=self._id(payload['task_id'])
        if type(payload['expected_version']) is not int or payload['expected_version']<0:
            raise MeasurementError(400,'invalid_version','核准版本无效')
        reason=self._text(payload['reason'],1000)
        with self.records._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            work=self._batch_workspace(db,account,task_id)
            group=next((g for g in work['groups'] if g['group_id']==payload['group_id']),None)
            if group is None:
                raise MeasurementError(404,'group_unavailable','未找到当前课程的目标组')
            if group['fingerprint']!=payload['fingerprint'] or group['version']!=payload['expected_version']:
                raise MeasurementError(409,'source_conflict','观察记录或核准版本已变化，请刷新后重新核对')
            selected=next((r for r in group['records'] if r['record_id']==payload['selected_record_id']),None)
            if not selected or not selected['reviewed'] or selected['evidence_status']!='current':
                raise MeasurementError(409,'record_not_reviewed','代表记录必须已复核且身份依据有效')
            version=group['version']+1
            decision={'group_id':group['group_id'],'owner_account_id':account['account_id'],
                'scope_key':work['scope_key'],'fingerprint':group['fingerprint'],
                'selected_record_id':selected['record_id'],'reason':reason,'version':version,
                'saved_by':account['username'],'saved_at':_iso()}
            db.execute('''INSERT INTO demo2_batch_decisions VALUES
                (:group_id,:owner_account_id,:scope_key,:fingerprint,:selected_record_id,:reason,:version,:saved_by,:saved_at)
                ON CONFLICT(group_id) DO UPDATE SET fingerprint=excluded.fingerprint,
                selected_record_id=excluded.selected_record_id,reason=excluded.reason,version=excluded.version,
                saved_by=excluded.saved_by,saved_at=excluded.saved_at''',decision)
            db.execute('INSERT INTO demo2_batch_decision_versions VALUES(?,?,?)',
                (group['group_id'],version,json.dumps(decision,ensure_ascii=False)))
            self.records._audit(db,account['username'],'batch_goal_confirmed','measurement',group['group_id'],{'version':version})
        return decision

    def workspace(self, token):
        account=self._account(token)
        roster=self.identities.roster(token)
        with self.records._connect() as db:
            rows=db.execute('''SELECT payload_json FROM demo2_measurements WHERE owner_account_id=? AND scope_key=?
                AND status='active' ORDER BY lesson_date,record_id LIMIT 5001''',(account['account_id'],roster['scope_key'])).fetchall()
        if len(rows)>5000:
            raise MeasurementError(409,'too_many_records','记录超过工作区上限，请联系管理员导出归档')
        with self.records._connect() as db:
            records=[self._effective_record(db,account,json.loads(r['payload_json'])) for r in rows]
            from .demo2_batch_review import trend_records
            trend_values=trend_records(records,roster['scope_key'],self._decisions(db,account,roster['scope_key']))
        groups={}
        for r in trend_values:
            # Criteria and rubric are also part of comparability, not just the subject.
            key=(r['student_id'],r['goal_id'],r['measurement_context'],r['criterion'],r['rubric_version'])
            groups.setdefault(key,[]).append(r)
        trends=[]
        for (student,goal,context,criterion,version),values in groups.items():
            points=[dict(v['assessment'],date=v['lesson_date'],record_id=v['record_id'],reviewed=v['reviewed']) for v in values]
            trends.append({'student_id':student,'goal_id':goal,'measurement_context':context,'criterion':criterion,
                           'rubric_version':version,'series':build_longitudinal_series(points)})
        return {**roster,'records':records,'trends':trends,'rubric_version':RUBRIC_VERSION,
                'standard_status':'试行量表；权重与6分参考线待校方确认，不是已验证官方量表',
                'retention':{'raw_media_days':60,'structured_days':730,'report':'按需生成，不额外保存含姓名副本'}}

    def admin_summary(self,token):
        account=self._account(token,admin=True)
        with self.records._connect() as db:
            rows=db.execute('''SELECT m.owner_account_id,a.bound_channel_id,m.status,m.payload_json,m.expires_at
                FROM demo2_measurements m JOIN platform_accounts a ON a.account_id=m.owner_account_id''').fetchall()
            result={};total=0;reviewed=0;due=0
            for row in rows:
                if row['status']!='active':continue
                value=json.loads(row['payload_json']);total+=1
                valid=value['assessment'].get('overall_score') is not None
                reviewed+=valid
                due+=row['expires_at'] <= _iso(datetime.now().astimezone()+timedelta(days=30))
                key=row['bound_channel_id'];group=result.setdefault(key,{'channel_id':key,'records':0,'reviewed':0,'pending':0})
                group['records']+=1;group['reviewed']+=valid;group['pending']+=not valid
            self.records._audit(db,account['username'],'measurement_summary_viewed','measurement','aggregate',{'records':total})
        return {'records':total,'reviewed':reviewed,'pending':total-reviewed,'due_30_days':due,'channels':list(result.values()),
                'scope':'仅运营统计，不返回学生姓名、分数或原文','structured_retention_days':730,
                'cleanup':'原始媒体按现有60天任务清理；结构化记录到期只提醒，人工归档后处理'}
