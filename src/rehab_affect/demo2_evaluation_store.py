"""Account/school-scoped classroom evaluations with immutable rule snapshots."""
from __future__ import annotations

from datetime import date
import json
import re
import sqlite3
import unicodedata

from .classroom_rubric import RULE_VERSION, SUBJECTS, TEMPLATES, catalog, evaluate
from .demo2_evaluation_debug import evaluation_debug_event, result_fields
from .demo2_identity_store import Demo2IdentityStore, IdentityError
from .demo2_measurement_store import MeasurementError
from .evaluation_report_contract import school_id_from_context
from .student_record_store import _iso

# Fields frozen once a record has a saved version (课程口径保存后锁定).
LOCKED_FIELDS = ('subject_id','template_id','weight_policy','focus_domains','goal_context','lesson_id','lesson_date')
# Classroom evaluation never scores an individual student's ability.
_STUDENT_SCORE_KEYS = frozenset({'student_score','student_scores','ability_score','ability_scores',
                                 'student_ability','student_ability_score'})


class Demo2EvaluationStore:
    def __init__(self, records):
        self.records = records
        self.identities = Demo2IdentityStore(records)
        with records._connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS demo2_classroom_evaluations (
                    record_id TEXT PRIMARY KEY, owner_account_id TEXT NOT NULL,
                    scope_key TEXT NOT NULL, lesson_id TEXT NOT NULL, template_id TEXT NOT NULL,
                    version INTEGER NOT NULL, status TEXT NOT NULL, payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_classroom_active_lesson
                    ON demo2_classroom_evaluations(owner_account_id,scope_key,lesson_id,template_id)
                    WHERE status='active';
                CREATE TABLE IF NOT EXISTS demo2_classroom_evaluation_versions (
                    record_id TEXT NOT NULL,version INTEGER NOT NULL,payload_json TEXT NOT NULL,
                    saved_by TEXT NOT NULL,saved_at TEXT NOT NULL,PRIMARY KEY(record_id,version)
                );
            ''')

    def _account(self, token):
        try:
            account = self.records.account_from_session(token)
        except ValueError:
            raise MeasurementError(401,'authentication_required','请重新登录') from None
        if account['role'] != 'school_uploader':
            raise MeasurementError(403,'evaluation_forbidden','仅授权教师账号可访问课堂评价')
        return account

    def _scope(self, db, account, *, required=True):
        context = Demo2IdentityStore._context(self.records._school_context_for_account(db,account['account_id']),required=required)
        return context, Demo2IdentityStore._scope(account['account_id'],context)

    @staticmethod
    def _text(value, *, limit=200, required=True):
        if not isinstance(value,str) or len(value)>limit or any(unicodedata.category(c) in {'Cc','Cf','Cs'} and c not in '\n\r\t' for c in value):
            raise MeasurementError(400,'invalid_field','文字过长或包含无效字符')
        if required and not value.strip():
            raise MeasurementError(400,'required_field','请填写课程、目标与必填信息')
        return value.strip()

    @staticmethod
    def _id(value):
        if not isinstance(value,str) or re.fullmatch(r'[A-Za-z0-9_-]{1,120}',value) is None:
            raise MeasurementError(400,'invalid_id','记录编号无效')
        return value

    def _normalize(self,payload):
        keys={'record_id','expected_version','lesson_id','lesson_date','course_name','subject_id','template_id','goal_context','school_source','school_rater','reviewed','items'}
        optional={'weight_policy','focus_domains','task_id','frame_revision',
                  'course_id','iep_summary_id','report_id'}
        if not isinstance(payload,dict) or not keys<=set(payload) or set(payload)-keys-optional:
            raise MeasurementError(400,'invalid_payload','请提交完整的课堂评价字段；分数和权重由服务端计算')
        data={k:self._text(payload[k],limit=2000 if k=='goal_context' else 200,required=k!='school_rater')
              for k in ('lesson_id','lesson_date','course_name','subject_id','template_id','goal_context','school_source','school_rater')}
        data['record_id']=self._id(payload['record_id'])
        # The browser may choose a record id, but the evaluation id is a
        # server-owned stable alias used by reports and future integrations.
        data['evaluation_id']=f"evaluation-{data['record_id']}"
        # Keep the persisted payload self-describing.  These defaults are
        # written on new records so the returned record and audit snapshot
        # remain byte-for-byte compatible; legacy rows are annotated on read.
        data['course_id']=self._text(payload.get('course_id',''), limit=160, required=False)
        data['iep_summary_id']=self._text(payload.get('iep_summary_id',''), limit=160, required=False)
        data['report_id']=self._text(payload.get('report_id',''), limit=160, required=False)
        if type(payload['expected_version']) is not int or payload['expected_version']<0:
            raise MeasurementError(400,'invalid_version','记录版本无效')
        data['expected_version']=payload['expected_version']
        try:
            when=date.fromisoformat(data['lesson_date'])
            if when.isoformat()!=data['lesson_date'] or when>date.today(): raise ValueError
        except ValueError:
            raise MeasurementError(400,'invalid_date','请输入真实上课日期，不接受未来日期') from None
        if data['subject_id'] not in {s['id'] for s in SUBJECTS}:
            raise MeasurementError(400,'invalid_subject','课程类型无效')
        if data['school_source']=='teacher_recorded' and not data['school_rater']:
            raise MeasurementError(400,'rater_required','教师原始评分须注明评分人')
        if data['school_source']=='rubric_initial' and data['school_rater']:
            raise MeasurementError(400,'invalid_rater','初评不能标记为教师原始评分')
        data['reviewed']=payload['reviewed']
        data['items']=payload['items']
        data['weight_policy']=payload.get('weight_policy','common')
        data['focus_domains']=payload.get('focus_domains',[])
        if 'task_id' in payload or 'frame_revision' in payload:
            task_id=payload.get('task_id')
            revision=payload.get('frame_revision')
            if not isinstance(task_id,str) or not isinstance(revision,str) or (
                (task_id or revision) and (re.fullmatch(r'[A-Za-z0-9_-]{1,120}',task_id) is None
                                          or re.fullmatch(r'[a-f0-9]{64}',revision) is None)):
                raise MeasurementError(400,'invalid_source','请提交课堂任务编号与当前采样版本')
            data.update(task_id=task_id,frame_revision=revision)
        try:
            result=evaluate(data)
        except (ValueError,TypeError,OverflowError) as exc:
            raise MeasurementError(400,'invalid_evaluation',str(exc)) from None
        # Normalize whitespace/control characters only after the shape is validated.
        data['items']=[{**r,**{k:self._text(r[k],limit=2000,required=False) for k in ('evidence','reason','suggestion')}} for r in data['items']]
        result=evaluate(data)
        result['evaluation_id']=data['evaluation_id']
        return data,result

    def workspace(self,token):
        account=self._account(token)
        with self.records._connect() as db:
            context,scope=self._scope(db,account,required=False)
            rows=db.execute('SELECT payload_json FROM demo2_classroom_evaluations WHERE owner_account_id=? AND scope_key=? AND status=? ORDER BY updated_at DESC LIMIT 1001',(account['account_id'],scope,'active')).fetchall()
            if len(rows)>1000:
                raise MeasurementError(409,'too_many_records','记录超过工作区上限，请联系管理员归档')
            values=[self._public(json.loads(r['payload_json'])) for r in rows]
            for value in values:
                if value['task_id']:
                    try:
                        self._source(db,account,scope,dict(value),value)
                    except (MeasurementError,IdentityError,ValueError):
                        value['source_provenance']={**value['source_provenance'],'status':'needs_reconfirmation'}
        return {**catalog(),'records':values, 'needs_school_context':not bool(scope),'school_context':context}

    @staticmethod
    def _public(data):
        # Annotate legacy JSON on read, without rewriting its historical version.
        data=dict(data)
        data.setdefault('task_id','')
        # video_task_id is the integration-contract name of task_id.
        data['video_task_id']=data['task_id']
        data.setdefault('course_id','')
        data.setdefault('evaluation_id',f"evaluation-{data.get('record_id','')}")
        data.setdefault('iep_summary_id','')
        data.setdefault('report_id','')
        data.setdefault('frame_revision','')
        data.setdefault('source_sha256',None)
        data.setdefault('source_provenance',{'status':'unlinked','scope':'course','student_linkage':'not_asserted'})
        # Upstream stable IDs of the chain; derived on read so stored versions stay unchanged.
        data['school_id']=school_id_from_context(data['source_provenance'].get('school_context'))
        data['iep_document_id']=data['iep_summary_id']
        data['evaluation_scope']='classroom'
        for key in _STUDENT_SCORE_KEYS:
            data.pop(key,None)
        return data

    def _log_rejected(self,phase,exc,payload,account=None):
        payload=payload if isinstance(payload,dict) else {}
        record_id=payload.get('record_id') if isinstance(payload.get('record_id'),str) else None
        template_id=payload.get('template_id') if isinstance(payload.get('template_id'),str) else None
        task_id=payload.get('task_id') if isinstance(payload.get('task_id'),str) else None
        evaluation_debug_event(self.records,'evaluation_rejected',str(exc.status),phase=phase,code=exc.code,
            message=exc.message,record_id=record_id,evaluation_id=f'evaluation-{record_id}' if record_id else None,
            account_id=account['account_id'] if account else None,template_id=template_id,
            task_id=task_id,video_task_id=task_id,rule_version=RULE_VERSION)

    def _source(self,db,account,scope,data,old):
        old=self._public(old) if old else None
        task_id=data.get('task_id',old['task_id'] if old else '')
        revision=data.get('frame_revision',old['frame_revision'] if old else '')
        if old and (task_id!=old['task_id'] or revision!=old['frame_revision']):
            raise MeasurementError(409,'source_locked','评价来源已锁定，不能改为另一任务或版本；请新建记录')
        data.update(task_id=task_id,frame_revision=revision)
        if not task_id:
            if data.get('iep_summary_id'):
                raise MeasurementError(409,'iep_task_required','关联 IEP 摘要前请先选择课堂视频任务')
            data.update(source_sha256=None,source_provenance={'status':'unlinked','scope':'course','student_linkage':'not_asserted'})
            return
        try:
            task=Demo2IdentityStore._task(db,account,task_id)
            context=Demo2IdentityStore._context(task.get('school_context_json'))
            if Demo2IdentityStore._scope(account['account_id'],context)!=scope:
                raise MeasurementError(403,'source_school_mismatch','任务学校与当前学校不一致')
            self.identities._require_media(task)
            if task.get('analysis_status') not in {'evidence_ready','completed'}:
                raise MeasurementError(409,'source_not_ready','课堂视频尚未处理完成')
            manifest=json.loads(task.get('processing_result_json') or '{}')
            sha=task.get('sha256')
            if (not isinstance(sha,str) or re.fullmatch(r'[a-f0-9]{64}',sha) is None
                    or manifest.get('source_sha256')!=sha
                    or revision!=Demo2IdentityStore._revision(task)
                    or (old and old['source_sha256']!=sha)):
                raise MeasurementError(409,'source_version_changed','课堂视频来源或版本已变化，请核对后新建记录')
        except IdentityError as exc:
            raise MeasurementError(exc.status,exc.code,exc.message) from None
        except MeasurementError:
            raise
        except (ValueError,TypeError,AttributeError):
            raise MeasurementError(409,'invalid_source_manifest','课堂来源信息无效，请重新处理视频') from None
        if data.get('course_id') and data['course_id'] != task['course_id']:
            raise MeasurementError(409,'course_mismatch','课程编号与视频任务不一致')
        data['course_id'] = task['course_id']
        if data.get('iep_summary_id'):
            from .demo2_iep_context import iep_link_is_current
            from .demo2_dossier_store import debug_event, material_access_state
            document_id=data['iep_summary_id']
            if not iep_link_is_current(db,account,task,scope,document_id,self.identities):
                # Name the precise reason (withdrawn/expired/deleted) without exposing content.
                try:
                    state=material_access_state(db,document_id=document_id,purpose='scoring')
                except sqlite3.Error:
                    state={'available':False,'reason':'dossier_unavailable','student_id':'','document_type':''}
                if state['available'] or state['reason']=='document_missing':
                    reason,detail='iep_link_unavailable','IEP 摘要未关联本课，或课堂身份引用已失效'
                else:
                    reason,detail=state['reason'],state.get('message') or '资料服务暂不可用'
                debug_event(self.records,'scoring_iep_check','unavailable',task_id=task_id,document_id=document_id,
                            student_id=state.get('student_id') or None,document_type=state.get('document_type') or None,
                            reason=reason)
                raise MeasurementError(409,'iep_link_unavailable','IEP 摘要不可用于评分：'+detail)
            debug_event(self.records,'scoring_iep_check','available',task_id=task_id,document_id=document_id,document_type='iep')
        data.update(source_sha256=sha,source_provenance={'status':'linked','scope':'course',
                    'student_linkage':'not_asserted','task_id':task_id,'frame_revision':revision,
                    'source_sha256':sha,'school_context':context,'course_id':task['course_id']})

    def for_task(self, token, task_id):
        """Return only active evaluations linked to one owned video task."""
        account=self._account(token)
        if not isinstance(task_id,str) or re.fullmatch(r'[A-Za-z0-9_-]{1,120}',task_id) is None:
            raise MeasurementError(400,'invalid_task','课堂任务编号无效')
        with self.records._connect() as db:
            task=Demo2IdentityStore._task(db,account,task_id)
            context=Demo2IdentityStore._context(task.get('school_context_json'))
            scope=Demo2IdentityStore._scope(account['account_id'],context)
            rows=db.execute('''SELECT payload_json FROM demo2_classroom_evaluations
                WHERE owner_account_id=? AND scope_key=? AND status='active'
                AND json_extract(payload_json,'$.task_id')=?
                ORDER BY updated_at DESC''',
                (account['account_id'],scope,task_id)).fetchall()
            values=[]
            for row in rows:
                value=self._public(json.loads(row['payload_json']))
                try:
                    self._source(db,account,scope,dict(value),value)
                except (MeasurementError,IdentityError,ValueError):
                    # Historical evaluations stay in their workspace, but a
                    # changed source must not contribute to the current report.
                    continue
                values.append(value)
        return values

    @staticmethod
    def _reject_student_names(db,account,scope,goal):
        """The lesson goal is class-level text; a roster name there would leak identity."""
        if not scope:
            return
        folded=unicodedata.normalize('NFKC',goal).casefold()
        rows=db.execute('SELECT display_name FROM demo2_identity_students WHERE owner_account_id=? AND scope_key=?',
                        (account['account_id'],scope)).fetchall()
        for row in rows:
            name=unicodedata.normalize('NFKC',str(row['display_name'] or '')).strip().casefold()
            if len(name)>=2 and name in folded:
                raise MeasurementError(400,'goal_contains_student_name','本课目标不应填写学生姓名，请改用能力分层或支持方式描述')

    def _existing(self,db,account,scope,data):
        row=db.execute('SELECT * FROM demo2_classroom_evaluations WHERE record_id=?',(data['record_id'],)).fetchone()
        if row is None:
            if data['expected_version']!=0:
                raise MeasurementError(409,'version_conflict','记录版本已失效，请重新加载')
            return None
        if row['owner_account_id']!=account['account_id'] or row['scope_key']!=scope:
            raise MeasurementError(404,'record_unavailable','记录不存在或无权访问')
        if row['version']!=data['expected_version'] or row['status']!='active':
            raise MeasurementError(409,'version_conflict','记录已更新或撤销，请重新加载后核对')
        old=json.loads(row['payload_json'])
        changed=[k for k in ('template_id','subject_id','goal_context','lesson_id','lesson_date') if old[k]!=data[k]]
        if old.get('weight_policy','common')!=data['weight_policy']: changed.append('weight_policy')
        if old.get('focus_domains',[])!=data['focus_domains']: changed.append('focus_domains')
        if changed:
            evaluation_debug_event(self.records,'evaluation_lock','blocked',evaluation_id=data['evaluation_id'],
                record_id=data['record_id'],account_id=account['account_id'],version=row['version'],locked=True,
                locked_fields=changed,template_id=old['template_id'],rule_version=old['result']['rule_version'])
        if any(k in changed for k in ('template_id','subject_id','goal_context','lesson_id','lesson_date')):
            raise MeasurementError(409,'configuration_locked','本课目标、模板、学科和课节已锁定；改变口径请撤销后新建')
        if changed:
            raise MeasurementError(409,'configuration_locked','权重方案与本课领域已锁定；改变口径请撤销后新建')
        if old['result']['rule_version']!=RULE_VERSION:
            raise MeasurementError(409,'rule_version_locked','历史规则版本已锁定，请保留原记录并新建')
        return old

    def preview(self,token,payload):
        account=self._account(token)
        try:
            data,result=self._normalize(payload)
            with self.records._connect() as db:
                _,scope=self._scope(db,account)
                self._reject_student_names(db,account,scope,data['goal_context'])
                old=self._existing(db,account,scope,data)
                self._source(db,account,scope,data,old)
        except MeasurementError as exc:
            self._log_rejected('preview',exc,payload,account)
            raise
        evaluation_debug_event(self.records,'dual_track_compute','ok',phase='preview',
            evaluation_id=data['evaluation_id'],record_id=data['record_id'],account_id=account['account_id'],
            task_id=data.get('task_id'),video_task_id=data.get('task_id'),course_id=data.get('course_id'),
            subject_id=data['subject_id'],reviewed=data['reviewed'],**result_fields(result))
        return result

    def save(self,token,payload):
        account=self._account(token)
        try:
            return self._save(account,payload)
        except MeasurementError as exc:
            self._log_rejected('save',exc,payload,account)
            raise

    def _save(self,account,payload):
        data,result=self._normalize(payload)
        with self.records._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            _,scope=self._scope(db,account)
            self._reject_student_names(db,account,scope,data['goal_context'])
            old=self._existing(db,account,scope,data)
            self._source(db,account,scope,data,old)
            duplicate=db.execute('SELECT record_id FROM demo2_classroom_evaluations WHERE owner_account_id=? AND scope_key=? AND lesson_id=? AND template_id=? AND status=? AND record_id<>?',(account['account_id'],scope,data['lesson_id'],data['template_id'],'active',data['record_id'])).fetchone()
            if duplicate:
                raise MeasurementError(409,'duplicate_lesson','本课该模板已有评价，请编辑已有记录')
            # Persist the chain aliases _public() derives so the stored payload equals the returned record.
            data.update(video_task_id=data.get('task_id',''),evaluation_scope='classroom',
                        school_id=school_id_from_context(data['source_provenance'].get('school_context')),
                        iep_document_id=data.get('iep_summary_id',''))
            now=_iso();version=data.pop('expected_version')+1
            data.update(version=version,status='active',created_at=old['created_at'] if old else now,updated_at=now,saved_by=account['username'],result=result,
                rule_snapshot={**catalog(),'selected_template_id':data['template_id'],'selected_subject_id':data['subject_id']})
            content=json.dumps(data,ensure_ascii=False,allow_nan=False)
            db.execute('''INSERT INTO demo2_classroom_evaluations VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(record_id) DO UPDATE SET version=excluded.version,payload_json=excluded.payload_json,updated_at=excluded.updated_at''',
                (data['record_id'],account['account_id'],scope,data['lesson_id'],data['template_id'],version,'active',content,data['created_at'],now))
            db.execute('INSERT INTO demo2_classroom_evaluation_versions VALUES(?,?,?,?,?)',(data['record_id'],version,content,account['username'],now))
            self.records._audit(db,account['username'],'classroom_evaluation_saved','classroom_evaluation',data['record_id'],{'version':version,'rule_version':RULE_VERSION})
        common=dict(evaluation_id=data['evaluation_id'],record_id=data['record_id'],account_id=account['account_id'],
            task_id=data.get('task_id'),video_task_id=data.get('task_id'),course_id=data.get('course_id'),
            subject_id=data['subject_id'],version=version)
        scores=result_fields(result)
        evaluation_debug_event(self.records,'evaluation_create' if old is None else 'evaluation_save','ok',
            reviewed=data['reviewed'],**common,**scores)
        if old is None:
            evaluation_debug_event(self.records,'evaluation_lock','locked',locked=True,locked_fields=list(LOCKED_FIELDS),
                template_id=data['template_id'],rule_version=RULE_VERSION,**common)
        if data['reviewed'] or (old is not None and old.get('reviewed')):
            review_result=('reviewed' if result['status']=='reviewed' else
                           'review_cleared' if not data['reviewed'] else 'reviewed_incomplete')
            evaluation_debug_event(self.records,'evaluation_review',review_result,reviewed=data['reviewed'],
                template_id=data['template_id'],rule_version=RULE_VERSION,status=result['status'],**common)
        evaluation_debug_event(self.records,'dual_track_compute','ok',phase='save',reviewed=data['reviewed'],**common,**scores)
        return self._public(data)

    def withdraw(self,token,payload):
        account=self._account(token)
        try:
            data=self._withdraw(account,payload)
        except MeasurementError as exc:
            self._log_rejected('withdraw',exc,payload,account)
            raise
        evaluation_debug_event(self.records,'evaluation_withdraw','ok',
            evaluation_id=data.get('evaluation_id') or f"evaluation-{data['record_id']}",
            record_id=data['record_id'],account_id=account['account_id'],task_id=data.get('task_id'),
            video_task_id=data.get('task_id'),course_id=data.get('course_id'),version=data['version'],
            template_id=data.get('template_id'),rule_version=(data.get('result') or {}).get('rule_version'),
            status='withdrawn')
        return self._public(data)

    def _withdraw(self,account,payload):
        if not isinstance(payload,dict) or set(payload)!={'record_id','expected_version','reason'}:
            raise MeasurementError(400,'invalid_payload','请提供记录编号、版本和撤销原因')
        rid=self._id(payload['record_id']);reason=self._text(payload['reason'],limit=1000)
        if type(payload['expected_version']) is not int:
            raise MeasurementError(400,'invalid_version','版本必须为整数')
        with self.records._connect() as db:
            db.execute('BEGIN IMMEDIATE');_,scope=self._scope(db,account)
            row=db.execute('SELECT * FROM demo2_classroom_evaluations WHERE record_id=? AND owner_account_id=? AND scope_key=?',(rid,account['account_id'],scope)).fetchone()
            if row is None: raise MeasurementError(404,'record_unavailable','记录不存在或无权访问')
            if row['status']!='active' or row['version']!=payload['expected_version']:
                raise MeasurementError(409,'version_conflict','记录已更新或撤销，请刷新')
            data=json.loads(row['payload_json']);now=_iso()
            data.update(version=row['version']+1,status='withdrawn',withdrawal_reason=reason,updated_at=now,saved_by=account['username'])
            content=json.dumps(data,ensure_ascii=False,allow_nan=False)
            db.execute('UPDATE demo2_classroom_evaluations SET status=?,version=?,payload_json=?,updated_at=? WHERE record_id=?',('withdrawn',data['version'],content,now,rid))
            db.execute('INSERT INTO demo2_classroom_evaluation_versions VALUES(?,?,?,?,?)',(rid,data['version'],content,account['username'],now))
            self.records._audit(db,account['username'],'classroom_evaluation_withdrawn','classroom_evaluation',rid,{'version':data['version']})
        return data
