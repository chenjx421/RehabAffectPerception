"""Account/school-scoped classroom evaluations with immutable rule snapshots."""
from __future__ import annotations

from datetime import date
import json
import re
import sqlite3
import unicodedata

from .classroom_rubric import RULE_VERSION, SUBJECTS, TEMPLATES, catalog, evaluate
from .demo2_evaluation_debug import CLIENT_OPERATIONS, evaluation_debug_event, result_fields
from .demo2_identity_store import Demo2IdentityStore, IdentityError
from .demo2_measurement_store import MeasurementError
from .evaluation_report_contract import school_id_from_context
from .score_basis import evaluation_score_basis, redact_for_admin
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
                  'course_id','iep_summary_id','report_id','course_task_doc_id','system_suggestions'}
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
        data['course_task_doc_id']=self._text(payload.get('course_task_doc_id',''), limit=40, required=False)
        if 'system_suggestions' in payload:
            data['_system_suggestions']=self._system_suggestions(payload['system_suggestions'])
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

    @classmethod
    def _system_suggestions(cls,value):
        """Course evaluation: the suggestion fingerprint the teacher saw + reasons for modified items."""
        if (not isinstance(value,dict) or set(value)!={'fingerprint','reasons'} or not isinstance(value['fingerprint'],str)
                or re.fullmatch(r'[a-f0-9]{64}',value['fingerprint']) is None or not isinstance(value['reasons'],dict)
                or len(value['reasons'])>20):
            raise MeasurementError(400,'invalid_system_suggestions','系统建议分字段无效，请刷新页面后重试')
        reasons={}
        for key,text in value['reasons'].items():
            if not isinstance(key,str) or re.fullmatch(r'i(?:[1-9]|10)',key) is None:
                raise MeasurementError(400,'invalid_system_suggestions','系统建议分条目无效')
            reasons[key]=cls._text(text,limit=2000,required=False)
        return {'fingerprint':value['fingerprint'],'reasons':reasons}

    @staticmethod
    def _owned_task(db,account,task_id):
        """Task of this teacher; another school's task is 403, a missing one 404."""
        if not isinstance(task_id,str) or re.fullmatch(r'[A-Za-z0-9_-]{1,120}',task_id) is None:
            raise MeasurementError(400,'invalid_task','课堂任务编号无效')
        row=db.execute('SELECT * FROM video_analysis_tasks WHERE task_id=?',(task_id,)).fetchone()
        if row is None:
            raise MeasurementError(404,'task_unavailable','任务不存在或已删除')
        if row['account_id']!=account['account_id']:
            raise MeasurementError(403,'evaluation_forbidden','该课堂任务不属于当前学校账号，无权做课程评价')
        return dict(row)

    def course_suggestions(self,token,task_id):
        """System suggestion for each of the 10 items of one lesson, plus its active course evaluations."""
        from .demo2_course_evaluation import build_suggestions,load_lesson_data,short_id
        try:
            account=self._account(token)
        except MeasurementError as exc:
            evaluation_debug_event(self.records,'course_eval_suggest',exc.code,code=str(exc.status),
                                   task_short=short_id(task_id) if isinstance(task_id,str) else None)
            raise
        try:
            with self.records._connect() as db:
                task=self._owned_task(db,account,task_id)
                _,scope=self._scope(db,account,required=False)
                if task.get('analysis_status') not in {'evidence_ready','completed'}:
                    raise MeasurementError(409,'source_not_ready','课堂视频尚未处理完成，处理完成后再做课程评价')
                suggestions=build_suggestions(load_lesson_data(db,account['account_id'],task))
                rows=db.execute('''SELECT payload_json FROM demo2_classroom_evaluations
                    WHERE owner_account_id=? AND scope_key=? AND status='active' AND json_extract(payload_json,'$.task_id')=?
                    ORDER BY updated_at DESC''',(account['account_id'],scope,task_id)).fetchall()
                evaluations=[self._annotate_course(db,account,self._public(json.loads(r['payload_json']))) for r in rows]
        except MeasurementError as exc:
            evaluation_debug_event(self.records,'course_eval_suggest',exc.code,code=str(exc.status),
                                   account_id=account['account_id'],task_short=short_id(task_id),task_id=task_id)
            raise
        except (sqlite3.Error,ValueError,TypeError,KeyError) as exc:
            evaluation_debug_event(self.records,'course_eval_error','failed',phase='suggest',error=type(exc).__name__,
                                   account_id=account['account_id'],task_short=short_id(task_id),task_id=task_id)
            raise MeasurementError(500,'course_suggestion_failed','系统建议分暂时无法生成，请稍后重试') from None
        evaluation_debug_event(self.records,'course_eval_suggest','ok',account_id=account['account_id'],
            task_id=task_id,task_short=short_id(task_id),course_id=suggestions['course_id'] or None,
            item_count=len(suggestions['items']),suggested_count=suggestions['suggested_count'],
            insufficient_count=suggestions['insufficient_count'],
            suggested_items=[i['id'] for i in suggestions['items'] if i['status']=='suggested'],
            measurement_count=suggestions['measurement_summary']['record_count'],
            student_count=suggestions['measurement_summary']['student_count'],
            course_task_short=short_id(suggestions['course_task_doc_id']) or None,
            suggestion_version=suggestions['suggestion_version'])
        return {'task_id':task_id,'course_id':suggestions['course_id'],'course_name':task.get('course_name') or '',
                'suggestions':suggestions,'evaluations':evaluations}

    def _course_evaluation(self,db,account,data,old,result,phase):
        """Attach the system-suggestion snapshot of a course evaluation; the result is not recomputed."""
        from .demo2_course_evaluation import (TEMPLATE_ID,apply_teacher_decisions,build_suggestions,category_summary,
                                              load_lesson_data,school_grade_label,short_id)
        request=data.pop('_system_suggestions',None)
        if request is None:
            if old and old.get('course_evaluation'):
                raise MeasurementError(409,'configuration_locked','课程评价须随系统建议分一起保存，请从课程评价入口重新打开')
            return
        common=dict(account_id=account['account_id'],phase=phase,evaluation_id=data['evaluation_id'],
                    evaluation_short=short_id(data['evaluation_id']),task_id=data.get('task_id'),
                    task_short=short_id(data.get('task_id')))
        if data['template_id']!=TEMPLATE_ID or not data.get('task_id'):
            evaluation_debug_event(self.records,'course_eval_decision','rejected',code='course_template_required',**common)
            raise MeasurementError(400,'course_template_required','课程评价使用「课堂教学基本评价指标 · 100分原表」，并须关联本课视频任务')
        task=self._owned_task(db,account,data['task_id'])
        suggestions=build_suggestions(load_lesson_data(db,account['account_id'],task))
        if suggestions['fingerprint']['fingerprint']!=request['fingerprint']:
            evaluation_debug_event(self.records,'course_eval_basis_stale','suggestion_changed',stale=True,**common)
            raise MeasurementError(409,'suggestion_basis_changed','本课依据数据已变化（课程任务或学生测量有更新），请点「刷新系统建议分」后重新核对')
        snapshot,missing=apply_teacher_decisions(suggestions,data['items'],request['reasons'])
        counts=snapshot['counts']
        evaluation_debug_event(self.records,'course_eval_decision','missing_reason' if missing else 'ok',
            item_count=len(snapshot['items']),suggested_count=suggestions['suggested_count'],
            adopted_count=counts['adopted'],modified_count=counts['modified'],missing_reason_count=len(missing),
            modified_items=[i['id'] for i in snapshot['items'] if i['decision']=='modified'],
            missing_reason_items=missing,**common)
        if missing:
            exc=MeasurementError(400,'suggestion_reason_required',
                f'第 {"、".join(m[1:] for m in missing)} 项修改了系统建议分，请填写修改理由')
            exc.field='suggestion_reason_'+missing[0]
            raise exc
        school=(result.get('school') or {})
        system=(result.get('enhanced') or {})
        comparison=result.get('comparison') or {}
        snapshot['summary']={'categories':category_summary(result),
            'school_raw_100':school.get('raw_score'),'school_score_10':school.get('score_10'),
            'teaching_score_70':school.get('teaching_score_70'),'system_score_10':system.get('score_10'),
            'total_gap':comparison.get('total_delta') if comparison.get('available') else None,
            'school_grade':school_grade_label(school.get('score_10')),
            'system_grade':school_grade_label(system.get('score_10')),'status':result.get('status')}
        data['evaluation_kind']='course'
        data['course_evaluation']=snapshot

    def _annotate_course(self,db,account,value):
        """Read-time flag: cited course-task/measurement data changed since the course evaluation was saved."""
        from .demo2_course_evaluation import STALE_REASON_TEXT,data_fingerprint,load_lesson_data,short_id,stale_reasons
        snapshot=value.get('course_evaluation')
        if not isinstance(snapshot,dict) or not value.get('task_id'):
            return value
        try:
            row=db.execute('SELECT * FROM video_analysis_tasks WHERE task_id=? AND account_id=?',
                           (value['task_id'],account['account_id'])).fetchone()
            current=data_fingerprint(load_lesson_data(db,account['account_id'],dict(row))) if row else None
        except (sqlite3.Error,ValueError,TypeError,KeyError) as exc:
            evaluation_debug_event(self.records,'course_eval_error','failed',phase='stale_check',error=type(exc).__name__,
                account_id=account['account_id'],evaluation_id=value.get('evaluation_id'),
                evaluation_short=short_id(value.get('evaluation_id')),task_short=short_id(value['task_id']))
            return value
        reasons=['task_missing'] if current is None else stale_reasons(snapshot.get('fingerprint'),current)
        value['course_evaluation_stale']={'stale':bool(reasons),'reasons':reasons,
            'messages':[STALE_REASON_TEXT.get(r,'课堂任务已不存在') for r in reasons],
            'notice':'依据数据已变化，建议重新核对' if reasons else ''}
        if reasons:
            evaluation_debug_event(self.records,'course_eval_basis_stale','stale',stale=True,stale_reasons=reasons,
                account_id=account['account_id'],evaluation_id=value.get('evaluation_id'),
                evaluation_short=short_id(value.get('evaluation_id')),task_id=value['task_id'],
                task_short=short_id(value['task_id']),reviewed=value.get('reviewed') is True,version=value.get('version'))
        return value

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
                    self._annotate_course(db,account,value)
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
        data.setdefault('course_task_doc_id','')
        data.setdefault('course_task_version',0)
        data.setdefault('course_task_goals',[])
        data.setdefault('course_task_goal_basis',[])
        data.setdefault('measurement_refs',[])
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

    def _course_task(self,db,account,data,old):
        """Bind confirmed course-task goals; scores still come from the unchanged rubric."""
        from .demo2_course_task_store import document_by_id,evaluation_goal_basis,public_document,course_task_debug_event
        doc_id=data.get('course_task_doc_id','')
        previous=(old or {}).get('course_task_doc_id','')
        if old is not None and doc_id!=previous:
            raise MeasurementError(409,'configuration_locked','课程任务目标随本课目标一起锁定；更换课程任务版本请撤销后新建评价')
        if not doc_id:
            data.update(course_task_doc_id='',course_task_version=0,course_task_goals=[],course_task_goal_basis=[])
            return
        def reject(status,code,message):
            course_task_debug_event(self.records,'course_task_link_evaluation','rejected',account_id=account['account_id'],
                course_id=data.get('course_id') or None,course_task_doc_id=doc_id,code=code,http_status=status)
            return MeasurementError(status,code,message)
        row=document_by_id(db,doc_id)
        if row is None:
            raise reject(404,'course_task_not_found','课程任务文档不存在，请重新带入')
        if row['owner_account_id']!=account['account_id']:
            raise reject(403,'course_task_forbidden','当前账号无权使用该课程任务文档')
        if row['status']!='confirmed' and doc_id!=previous:
            raise reject(409,'course_task_superseded','该课程任务已有新版本，请刷新后重新带入本课目标')
        if data.get('course_id') and data['course_id']!=row['course_id']:
            raise reject(409,'course_task_course_mismatch','课程任务与本课课程批次号不一致')
        data['course_id']=row['course_id']
        doc=public_document(row)
        goals=[{k:g.get(k,'') for k in ('goal_code','description','pass_criteria','measurement_conditions','rubric_dimension')}
               for g in doc['goals']]
        template=TEMPLATES[data['template_id']]
        data.update(course_task_version=doc['version'],course_task_goals=goals,
                    course_task_goal_basis=evaluation_goal_basis(goals,data['template_id'],data['items'],
                                                                 bool(template.get('enhanced_available'))))

    @staticmethod
    def _measurement_links(db,account,data):
        """System track cites the lesson's measurement records (IDs/review state only), per goal too."""
        from .demo2_measurement_link import measurement_refs
        refs=measurement_refs(db,account['account_id'],data.get('task_id') or '')
        data['measurement_refs']=refs
        for basis in data.get('course_task_goal_basis') or []:
            linked=[r for r in refs if r['goal_id']==basis.get('goal_code')]
            basis['measurement_record_ids']=[r['record_id'] for r in linked]
            if linked:
                reviewed=sum(1 for r in linked if r['reviewed'])
                basis['basis_text']=(basis.get('basis_text') or '')+(f"关联本课测量记录 {len(linked)} 条"
                    f"（教师已复核 {reviewed} 条，视频来源 {sum(1 for r in linked if r['source_type']=='video')} 条）。")

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
                self._course_task(db,account,data,old)
                self._measurement_links(db,account,data)
                self._course_evaluation(db,account,data,old,result,'preview')
        except MeasurementError as exc:
            self._log_rejected('preview',exc,payload,account)
            raise
        basis=evaluation_score_basis({**data,'result':result})
        evaluation_debug_event(self.records,'dual_track_compute','ok',phase='preview',
            evaluation_id=data['evaluation_id'],record_id=data['record_id'],account_id=account['account_id'],
            task_id=data.get('task_id'),video_task_id=data.get('task_id'),course_id=data.get('course_id'),
            subject_id=data['subject_id'],reviewed=data['reviewed'],**result_fields(result))
        self._log_basis(basis,'preview',account,data)
        if data.get('course_evaluation'):
            result={**result,'course_evaluation':data['course_evaluation']}
        if data['course_task_doc_id']:
            # Basis is presentation only; the computed result itself is unchanged.
            return {**result,'course_task_doc_id':data['course_task_doc_id'],
                    'course_task_version':data['course_task_version'],
                    'course_task_goal_basis':data['course_task_goal_basis'],
                    **({'measurement_refs':data['measurement_refs']} if data['measurement_refs'] else {})}
        # Preview must equal the saved result; the basis card is read from the saved record.
        return {**result,'measurement_refs':data['measurement_refs']} if data['measurement_refs'] else result

    def _log_basis(self,basis,phase,account,data):
        common=dict(record_short=basis['record_short'],rule_version=basis['rubric_version'],
            rubric_version=basis['rubric_version'],detail_version=basis['detail_version'],
            record_id=data.get('record_id'),evaluation_id=data.get('evaluation_id'),account_id=account['account_id'],
            task_id=data.get('task_id'),template_id=data.get('template_id'))
        evaluation_debug_event(self.records,'score_basis_compute',basis['status'],phase=phase,
            basis_status=basis['status'],matches_page=basis['overall']['matches_page'],
            enhanced_score=basis['overall']['system_score'],**common)
        if basis['insufficient_items'] or basis['status'] in {'insufficient','not_available'}:
            evaluation_debug_event(self.records,'score_basis_insufficient','insufficient_evidence',phase=phase,
                basis_status=basis['status'],insufficient_items=basis['insufficient_items'],**common)

    def score_basis(self,token,record_id):
        """依据卡 for the system track; teachers see own records, company admin a redacted view."""
        record_id=self._id(record_id)
        try:
            account=self.records.account_from_session(token)
        except ValueError:
            raise MeasurementError(401,'authentication_required','请重新登录') from None
        role=account.get('role')
        common=dict(record_id=record_id,account_id=account['account_id'],viewer_role=role,rule_version=RULE_VERSION)
        if role not in {'school_uploader','company_admin'}:
            evaluation_debug_event(self.records,'score_basis_view','score_basis_forbidden',code='403',**common)
            raise MeasurementError(403,'score_basis_forbidden','当前账号无权查看评分依据')
        try:
            with self.records._connect() as db:
                row=db.execute('SELECT * FROM demo2_classroom_evaluations WHERE record_id=?',(record_id,)).fetchone()
                if row is None or row['status']!='active':
                    raise MeasurementError(404,'record_unavailable','记录不存在或已撤销')
                if role=='school_uploader':
                    if row['owner_account_id']!=account['account_id']:
                        raise MeasurementError(403,'score_basis_forbidden','该评价不属于当前学校账号，无权查看评分依据')
                    _,scope=self._scope(db,account,required=False)
                    if row['scope_key']!=scope:
                        raise MeasurementError(403,'score_basis_forbidden','该评价不属于当前学校账号，无权查看评分依据')
                else:
                    self.records._audit(db,account['username'],'evaluation_basis_viewed','classroom_evaluation',record_id,
                                        {'version':row['version']})
                data=self._public(json.loads(row['payload_json']))
        except MeasurementError as exc:
            evaluation_debug_event(self.records,'score_basis_view',exc.code,code=str(exc.status),**common)
            raise
        except (ValueError,TypeError,KeyError,sqlite3.Error) as exc:
            evaluation_debug_event(self.records,'score_basis_error','failed',error=type(exc).__name__,**common)
            raise MeasurementError(500,'score_basis_failed','评分依据暂时无法生成，请稍后重试') from None
        stored=data.get('score_basis') if isinstance(data.get('score_basis'),dict) else None
        basis=stored if stored else evaluation_score_basis(data)
        if stored is None:
            self._log_basis(basis,'read',account,data)
        basis={**basis,'basis_source':'saved' if stored else 'computed_on_read',
               'record':{'record_id':record_id,'evaluation_id':data.get('evaluation_id'),'version':data.get('version'),
                         'lesson_date':data.get('lesson_date'),'task_id':data.get('task_id') or '',
                         'course_name':data.get('course_name') or '','template_id':data.get('template_id'),
                         'reviewed':data.get('reviewed') is True}}
        if role=='company_admin':
            basis=redact_for_admin(basis)
            basis['record'].pop('course_name',None)
        evaluation_debug_event(self.records,'score_basis_view','ok' if basis['status'] in {'scored','provisional'} else 'insufficient',
            record_short=basis['record_short'],basis_status=basis['status'],basis_source=basis['basis_source'],
            detail_version=basis['detail_version'],rubric_version=basis['rubric_version'],
            enhanced_score=basis['overall']['system_score'],**{k:v for k,v in common.items() if k!='rule_version'},
            rule_version=basis['rubric_version'])
        return basis

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
            self._course_task(db,account,data,old)
            self._measurement_links(db,account,data)
            self._course_evaluation(db,account,data,old,result,'save')
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
            # Explains the system track item by item; the result above is not recomputed.
            data['score_basis']=evaluation_score_basis(data,computed_at=now)
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
        self._log_basis(data['score_basis'],'save',account,data)
        if data.get('course_evaluation'):
            from .demo2_course_evaluation import short_id
            snapshot=data['course_evaluation']
            course_common=dict(account_id=account['account_id'],evaluation_id=data['evaluation_id'],
                evaluation_short=short_id(data['evaluation_id']),task_id=data.get('task_id'),
                task_short=short_id(data.get('task_id')),version=version,item_count=len(snapshot['items']),
                adopted_count=snapshot['counts']['adopted'],modified_count=snapshot['counts']['modified'],
                suggested_count=snapshot['suggested_count'],status=result['status'])
            evaluation_debug_event(self.records,'course_eval_save','ok',reviewed=data['reviewed'],
                school_score=result['school'].get('score_10'),enhanced_score=result['enhanced'].get('score_10'),
                total_delta=result['comparison'].get('total_delta'),**course_common)
            if data['reviewed'] and result['status']=='reviewed':
                evaluation_debug_event(self.records,'course_eval_lock','locked',locked=True,**course_common)
        if data['course_task_doc_id']:
            from .demo2_course_task_store import course_task_debug_event
            course_task_debug_event(self.records,'course_task_link_evaluation','linked',account_id=account['account_id'],
                course_id=data.get('course_id'),course_task_doc_id=data['course_task_doc_id'],
                version=data['course_task_version'],goal_count=len(data['course_task_goals']),
                linked_goal_count=sum(1 for b in data['course_task_goal_basis'] if b.get('scored_item_count')),
                evaluation_id=data['evaluation_id'],task_id=data.get('task_id') or None)
        return self._public(data)

    _CLIENT_EVENT_KEYS=frozenset({'operation','result','step','code','fields','record_id','course_id','task_id','template_id','item_id'})

    def client_debug_event(self,token,payload):
        """Record one page-side action (step validation failure, edit, step change); no form text is accepted."""
        account=self._account(token)
        if not isinstance(payload,dict) or not {'operation','result'}<=set(payload) or set(payload)-self._CLIENT_EVENT_KEYS:
            raise MeasurementError(400,'invalid_debug_event','调试事件字段无效')
        if payload['operation'] not in CLIENT_OPERATIONS:
            raise MeasurementError(400,'invalid_debug_event','调试事件类型无效')
        if not isinstance(payload['result'],str) or re.fullmatch(r'[a-z_]{1,40}',payload['result']) is None:
            raise MeasurementError(400,'invalid_debug_event','调试事件结果无效')
        step=payload.get('step')
        if step is not None and (type(step) is not int or not 1<=step<=4):
            raise MeasurementError(400,'invalid_debug_event','调试事件步骤无效')
        code=payload.get('code')
        if code is not None and (not isinstance(code,str) or re.fullmatch(r'[a-z_]{1,60}',code) is None):
            raise MeasurementError(400,'invalid_debug_event','调试事件错误码无效')
        fields=payload.get('fields',[])
        if not isinstance(fields,list) or len(fields)>40 or any(not isinstance(f,str) or re.fullmatch(r'[A-Za-z0-9_-]{1,80}',f) is None for f in fields):
            raise MeasurementError(400,'invalid_debug_event','调试事件字段名无效')
        for key in ('record_id','course_id','task_id','template_id'):
            value=payload.get(key)
            if value not in (None,'') and (not isinstance(value,str) or re.fullmatch(r'[A-Za-z0-9_.:-]{1,120}',value) is None):
                raise MeasurementError(400,'invalid_debug_event','调试事件编号无效')
        item_id=payload.get('item_id')
        if item_id is not None and (not isinstance(item_id,str) or re.fullmatch(r'i(?:[1-9]|10)',item_id) is None):
            raise MeasurementError(400,'invalid_debug_event','调试事件条目无效')
        record_id=payload.get('record_id') or None
        version=None
        if record_id:
            with self.records._connect() as db:
                _,scope=self._scope(db,account,required=False)
                row=db.execute('SELECT version FROM demo2_classroom_evaluations WHERE record_id=? AND owner_account_id=? AND scope_key=?',
                               (record_id,account['account_id'],scope)).fetchone()
            # A record id the teacher does not own is still logged, but flagged instead of trusted.
            version=row['version'] if row is not None else None
            if row is None:
                record_id=None
        return evaluation_debug_event(self.records,payload['operation'],payload['result'],source='client',
            step=step,code=code,fields=fields or None,record_id=record_id,
            evaluation_id=f'evaluation-{record_id}' if record_id else None,account_id=account['account_id'],
            course_id=payload.get('course_id'),task_id=payload.get('task_id'),video_task_id=payload.get('task_id'),
            template_id=payload.get('template_id'),version=version,rule_version=RULE_VERSION,item_id=item_id,
            task_short=(payload.get('task_id') or '')[:8] or None,
            evaluation_short=record_id[:8] if record_id else None)

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
