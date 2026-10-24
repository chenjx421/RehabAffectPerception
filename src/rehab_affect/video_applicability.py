"""Media readiness and explicit human scope confirmation, not scene recognition."""
import hashlib
import json
import math

from .demo2_identity_store import Demo2IdentityStore, IdentityError
from .student_record_store import _iso

LABELS = {'pending':'待确认内容适用性', 'special':'已人工确认特教课堂及评价目标',
          'general':'普通课堂，仅保留通用观察', 'irrelevant':'非课堂内容，不生成课堂评价',
          'uncertain':'内容类型无法判断', 'insufficient':'课堂证据不足'}


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS demo2_video_applicability (
        task_id TEXT PRIMARY KEY, revision TEXT NOT NULL, version INTEGER NOT NULL,
        category TEXT NOT NULL, goal TEXT NOT NULL, reason TEXT NOT NULL,
        saved_by TEXT NOT NULL, updated_at TEXT NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS demo2_video_applicability_history (
        task_id TEXT NOT NULL, version INTEGER NOT NULL, payload TEXT NOT NULL,
        PRIMARY KEY(task_id,version))''')


def revision(task):
    return hashlib.sha256((str(task.get('sha256',''))+'|'+str(task.get('processing_result_json',''))).encode()).hexdigest()


def assess(db, task, records):
    initialize(db)
    raw = {}
    try:
        raw = json.loads(task.get('processing_result_json') or '{}')
        media = raw.get('media', {})
        duration = media.get('duration_sec')
        ready = (task.get('analysis_status') in ('evidence_ready','completed')
                 and raw.get('source_sha256') == task.get('sha256')
                 and type(duration) in (int,float) and math.isfinite(duration) and duration > 0)
        records._require_live_video(task)
        ready = ready and records._video_source_path(task).is_file()
    except (ValueError, TypeError, AttributeError, OSError):
        ready, media = False, {}
    warnings = []
    if not ready:
        warnings.append('视频尚未处理完成、已到期或不可用，暂不进入课堂评分。')
    if media.get('has_audio') is False:
        warnings.append('没有音轨：不评价口头回答或说话人；可人工核对手势、指认等视觉回应，不据此扣分。')
    if type(media.get('height')) in (int,float) and media['height'] < 360:
        warnings.append('画面高度低于360像素，需人工核对目标是否清楚；这是工程提醒，不是教学质量判定。')
    if isinstance(raw, dict):
        samples=[s for seg in raw.get('segments',[]) if isinstance(seg,dict)
                 for s in seg.get('visual',{}).get('samples',[]) if isinstance(s,dict)]
        brightness=[s['brightness'] for s in samples if type(s.get('brightness')) in (int,float) and math.isfinite(s['brightness'])]
        if brightness and sum(v<=8 for v in brightness)/len(brightness)>=.95:
            warnings.append('至少95%的采样帧平均灰度不高于8/255，画面明显偏暗。请核对黑屏、遮挡或低照度；该工程阈值不能识别课堂内容。')
    row = db.execute('SELECT * FROM demo2_video_applicability WHERE task_id=?', (task['task_id'],)).fetchone()
    current = row is not None and row['revision'] == revision(task)
    category = row['category'] if current else 'pending'
    allowed = bool(ready and category == 'special')
    return dict(category=category, label=LABELS[category], allowed=allowed, technical_ready=bool(ready),
        confirmed_for_source=bool(current and category=='special'),
        warnings=warnings, version=row['version'] if row else 0, revision=revision(task),
        goal=row['goal'] if current else '', reason=row['reason'] if current else '',
        stale=bool(row and not current), confirmed_by=row['saved_by'] if current else None,
        automatic_scene_recognition=False,
        limitation='人物检测或处理完成不证明课堂适用性；内容类别由授权教师确认。无关视频即使能检测到人脸也不应生成特教评价。')


class ApplicabilityStore:
    def __init__(self, records):
        self.records = records

    def _account(self, token):
        try:
            a = self.records.account_from_session(token)
        except ValueError:
            raise IdentityError(401,'login_required','请重新登录') from None
        if a['role'] != 'school_uploader':
            raise IdentityError(403,'forbidden','仅视频所属上传账号可确认')
        return a

    def _task(self, db, a, task_id):
        task = Demo2IdentityStore._task(db, a, task_id)
        current = Demo2IdentityStore._context(self.records._school_context_for_account(db,a['account_id']))
        if current != Demo2IdentityStore._context(task.get('school_context_json')):
            raise IdentityError(403,'school_mismatch','请核对视频与账号的学校归属')
        return task

    def workspace(self, token, task_id):
        a = self._account(token)
        with self.records._connect() as db:
            return assess(db, self._task(db,a,task_id), self.records)

    def save(self, token, p):
        a = self._account(token)
        if not isinstance(p,dict) or set(p) != {'task_id','version','revision','category','goal','reason','confirmed'}:
            raise IdentityError(400,'invalid_input','请完整填写内容类型、目标和确认依据')
        if type(p['version']) is not int or p['confirmed'] is not True:
            raise IdentityError(400,'confirmation_required','请确认已回看视频并核对适用条件')
        for key in ('revision','category','goal','reason'):
            if not isinstance(p[key],str) or len(p[key])>1000:
                raise IdentityError(400,'invalid_input','字段格式无效或过长')
        if p['category'] not in LABELS or p['category']=='pending' or not p['reason'].strip():
            raise IdentityError(400,'invalid_category','请选择内容类型并填写依据')
        if p['category']=='special' and not p['goal'].strip():
            raise IdentityError(400,'goal_required','需填写本课目标或教案依据，不能仅凭上传标题确认')
        with self.records._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            task=self._task(db,a,p['task_id']); state=assess(db,task,self.records)
            if state['revision']!=p['revision'] or state['version']!=p['version']:
                raise IdentityError(409,'stale_confirmation','视频或确认记录已变化，请刷新')
            if p['category']=='special' and not state['technical_ready']:
                raise IdentityError(409,'media_not_ready','原视频尚不可用，不能确认进入评分')
            version=p['version']+1
            data=dict(task_id=task['task_id'],revision=state['revision'],version=version,
                      category=p['category'],goal=p['goal'].strip(),reason=p['reason'].strip(),
                      saved_by=a['account_id'],updated_at=_iso())
            db.execute('INSERT OR REPLACE INTO demo2_video_applicability VALUES (:task_id,:revision,:version,:category,:goal,:reason,:saved_by,:updated_at)',data)
            db.execute('INSERT INTO demo2_video_applicability_history VALUES (?,?,?)',(task['task_id'],version,json.dumps(data,ensure_ascii=False)))
            self.records._audit(db,a['username'],'applicability_confirmed','video_analysis_task',task['task_id'],{'category':p['category'],'version':version})
            return assess(db,task,self.records)
