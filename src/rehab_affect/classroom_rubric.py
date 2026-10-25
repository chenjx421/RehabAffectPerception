"""Versioned classroom-quality rules; not a student ability or model score."""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP
import math
from .evaluation_policy import catalog_policy, resolve_policy, sensitivity
from .teaching_support import REFERENCES as RECENT_SUPPORT_REFERENCES

RULE_VERSION = '2026-09-29.context-review-v3'
REFERENCES = [
    *RECENT_SUPPORT_REFERENCES,
    dict(id='policy', title='义务教育质量评价指南（2021）', url='https://www.gov.cn/zhengce/zhengceku/2021-03/18/content_5593750.htm', support='过程性、发展性评价与结果评价结合。', limitation='不是本项目具体百分比权重的依据。'),
    dict(id='feedback', title='The Power of Feedback · Hattie & Timperley (2007)', url='https://doi.org/10.3102/003465430298487', support='反馈方式、内容和情境值得评价，而非只数反馈次数。', limitation='一般教育研究，不证明特教候选权重有效。'),
    dict(id='gas', title='Goal attainment scaling · Turner-Stokes (2009)', url='https://doi.org/10.1177/0269215508101742', support='预设个别化目标和可观察的达成等级。', limitation='康复方法参考，不将自定义十分制冒充原版GAS。'),
    dict(id='udl', title='CAST UDL Guidelines 3.0', url='https://udlguidelines.cast.org/', support='多种表达、参与和辅助技术方式。', limitation='设计指导框架，不是计分权重验证研究。'),
]
SUBJECTS = [
    dict(id='language', label='生活语文 / 表达', focus=['功能性沟通', '理解与表达', '生活情境应用'], note='沟通板、手势和辅助表达均可作为有效回应。'),
    dict(id='math', label='生活数学 / 思考', focus=['数量概念', '实物操作', '生活问题解决'], note='区分理解、模仿与教师代答。'),
    dict(id='practice', label='动手实践 / 生活技能', focus=['操作步骤', '约定支持下完成', '生活应用'], note='依据本课目标判断支持程度，不因辅助器具自动扣分。'),
    dict(id='sports', label='体育 / 动作', focus=['动作目标', '安全适配', '参与机会与合作'], note='动作幅度和运动量不能直接代替学习效果。'),
    dict(id='music', label='音乐 / 互动', focus=['节奏与表达', '轮替', '共同活动'], note='安静参与不等于不投入，表情不能直接证明情绪。'),
    dict(id='general', label='综合课程', focus=['本课个别化目标', '适宜支持', '可复核学习表现'], note='本课未涉及领域不评价，不填零分。'),
]
_labels = [
    '教学目标落实课标要求，结合学生实际，体现差异性', '教学目标关注学生学习经历',
    '教学内容正确、科学，密度容量恰当', '教学重点突出，难点有突破', '教学组织有序，教学环节清晰、紧凑',
    '教学方法与手段恰当；资源运用合理，信息技术与辅助手段有效',
    '师生互动，学生主动参与，态度积极，活动面广', '教学目标落实，教学效果良好',
    '教态亲切，教学语言科学、语速适当，演示熟练，板书清楚规范', '有良好的课堂教学掌控能力和信息素养',
]
_cats = [
    ('goals', '目标适配与分层要求', .20, .25, '核对目标、学生起点与支持条件，特教适配需明确证据。'),
    ('content', '内容设计与教学组织', .30, .20, '保留内容正确与可及性，降低组织形式对总分的主导。'),
    ('process', '过程支持与目标达成', .30, .40, '重视机会覆盖、适当反馈和约定条件下的目标表现。'),
    ('teacher', '教师表达与响应调节', .20, .15, '保留专业素养，避免与实际过程支持重复计分。'),
]
_weights = [.15, .10, .08, .07, .05, .10, .10, .20, .08, .07]
_category_ids = ['goals'] * 2 + ['content'] * 3 + ['process'] * 3 + ['teacher'] * 2
_anchors = [
    '核对教案中的分层目标、实际学习起点和支持约定；不按障碍标签降低目标。',
    '核对与生活经验、既有学习经历的联系。',
    '内容正确性须教案或专业复核，视频安静有序不能代替科学性。',
    '以目标任务及学生回应核对重点、难点，不只看教师讲解次数。',
    '核对环节组织、等待时间和材料可及性。',
    '支持手段是否让学生能够完成约定任务；使用辅助器具不自动降分。',
    '按学生机会覆盖核对，不把少数学生重复发言当作全体参与。',
    '按本课分层目标核对；教师代答、机械跟读不自动等同于掌握。',
    '核对指令可理解性、示范与必要支持，而非统一口语或动作形式。',
    '记录识别困难后的实际调整及后续回应，不能由表情推断情绪。',
]
_basic = dict(id='basic_100', label='课堂教学基本评价指标 · 100分原表', source_file='课堂教学-基本评价指标.docx',
    version=RULE_VERSION, enhanced_available=True, school_min=1, school_max=10,
    note='10项各10分；原表教学得分另为总分×70%。增强权重为候选设计，尚未校准。',
    rules_note='学校单项A 9—10 / B 6—8 / C 3—5 / D 1—2；不推断学校总合格线。增强6分为试行参考线。',
    categories=[dict(id=i,label=l,school_weight=w,enhanced_weight=v,rationale=r) for i,l,w,v,r in _cats],
    items=[dict(id=f'i{n+1}',label=label,category_id=_category_ids[n],school_weight=.1,enhanced_weight=_weights[n],anchor=_anchors[n]) for n,label in enumerate(_labels)])
_legacy_categories = [('goals','目标',2),('content','内容',2),('process','过程与方法',4),('teacher','教师素养',4),('outcomes','学习效果',3)]
_legacy_labels = ['整体性：认知、行为、情感领域','针对性：符合学习能力，分层清晰','科学性：重点、容量与正确性','整合性：生活经验与内容整合','全体性：集体、小组、个别与分层落实','主体性：主动参与兴趣','实践性：知识与生活能力结合','合理性：设计层次与方法适配','教学策略：在愉快活动中体验学习','教学机智：观察学生、及时反馈调节','教学技能：语言规范与演示熟练','师生关系：耐心与和谐氛围','即时效果：达到预期目标','情意发展：参与及能力个性发展','习惯培养：生活行为与学习习惯']
_legacy_ids = [i for i,_,n in _legacy_categories for _ in range(n)]
_legacy = dict(id='qingpu_15', label='青浦区辅读学校课堂教学评价 · 15项试行表',source_file='课堂评价表.docx',
    version=RULE_VERSION,enhanced_available=False,school_min=2,school_max=5,
    note='A=5、B=4、C=3、D=2；原均分×2仅用于辅助显示。此表尚无增强映射。',
    rules_note='原均分等级边界与舍入规则待校方确认，不自动生成综合等第；无70分制折算。',
    categories=[dict(id=i,label=l,school_weight=n/15,enhanced_weight=None,rationale='原表按项目数等权平均。') for i,l,n in _legacy_categories],
    items=[dict(id=f'j{n+1}',label=l,category_id=_legacy_ids[n],school_weight=1/15,enhanced_weight=None,anchor='保留学校A/B/C/D原评分；不能从表情或缺失资料推断等级。') for n,l in enumerate(_legacy_labels)])
TEMPLATES = {'basic_100': _basic, 'qingpu_15': _legacy}


def catalog():
    return deepcopy(dict(templates=list(TEMPLATES.values()), subjects=SUBJECTS, references=REFERENCES, rule_version=RULE_VERSION, weight_policy=catalog_policy()))


def _subject_profile(subject_id):
    subject = next((item for item in SUBJECTS if item['id'] == subject_id), None)
    if subject is None:
        raise ValueError('请选择有效课程类型')
    return subject


def _round(value, places=4):
    return float(Decimal(str(value)).quantize(Decimal('1').scaleb(-places), rounding=ROUND_HALF_UP))


def _score(value, *, low, legacy=False):
    if value is None:
        return None
    if type(value) not in (int,float) or not math.isfinite(value) or not low <= value <= (5 if legacy else 10):
        raise ValueError('评分必须是范围内的有限数字，未评价请留空')
    if legacy and value not in (2,3,4,5):
        raise ValueError('15项原表仅接受A=5、B=4、C=3、D=2')
    return value


def evaluate(payload):
    """Compute from evidence inputs only. No client totals or weights accepted."""
    template = TEMPLATES.get(payload.get('template_id'))
    if template is None:
        raise ValueError('请选择有效学校模板')
    if type(payload.get('reviewed')) is not bool:
        raise ValueError('必须明确复核状态')
    if payload.get('school_source') not in ('teacher_recorded','rubric_initial'):
        raise ValueError('请选择学校评分来源')
    subject = _subject_profile(payload.get('subject_id', 'general'))
    template, policy = resolve_policy(template, payload)
    rows = payload.get('items')
    specs = template['items']
    if not isinstance(rows,list) or len(rows) != len(specs):
        raise ValueError('必须逐项提交完整模板，未评价项留空')
    expected_keys = {'id','school_score','enhanced_score','evidence','reason','suggestion'}
    if any(not isinstance(r,dict) or set(r) != expected_keys or not isinstance(r['id'],str) for r in rows):
        raise ValueError('评价条目字段无效')
    by_id = {r['id']:r for r in rows}
    if len(by_id) != len(rows) or set(by_id) != {s['id'] for s in specs}:
        raise ValueError('评价条目重复或不属于当前模板')
    basic = template['enhanced_available']
    context_mode = policy['mode'] == 'school_context'
    context_changes = []
    school, enhanced, deltas = [], [], []
    for spec in specs:
        row = by_id[spec['id']]
        for key in ('evidence','reason','suggestion'):
            if not isinstance(row[key],str) or len(row[key]) > 2000:
                raise ValueError('证据、原因和建议须为不超过2000字的文字')
        s = _score(row['school_score'],low=1 if basic else 2,legacy=not basic)
        z = _score(row['enhanced_score'],low=0)
        if context_mode:
            proposed = s if z is None else z
            if z is not None and s is None:
                raise ValueError('情境修正需要先录入该项学校基础分')
            if proposed != s:
                if not all(row[k].strip() for k in ('evidence', 'reason', 'suggestion')):
                    raise ValueError('情境修正须填写证据时间点、应对与后续表现的理由、下一课建议')
                context_changes.append(dict(id=spec['id'], label=spec['label'], school_score=s,
                    proposed_score=proposed, proposed_delta=_round(spec['school_weight']*(proposed-s)),
                    evidence=row['evidence'], reason=row['reason'], suggestion=row['suggestion'],
                    applied=payload['reviewed']))
            z = proposed if payload['reviewed'] else s
        if not basic and z is not None:
            raise ValueError('15项模板没有增强映射，不能输入增强分')
        if z is not None and z != s and not row['reason'].strip():
            raise ValueError('增强评分与原分不同，必须说明原因')
        if payload['reviewed'] and (s is not None or z is not None) and not row['evidence'].strip():
            raise ValueError('已复核的每个有评分条目必须有证据')
        school.append(s); enhanced.append(z)
        ed = spec['school_weight']*(z-s) if basic and s is not None and z is not None else None
        wd = (spec['enhanced_weight']-spec['school_weight'])*z if ed is not None else None
        deltas.append(dict(id=spec['id'],label=spec['label'],school_score=s,enhanced_score=z,
            evidence_delta=_round(ed) if ed is not None else None,weight_delta=_round(wd) if wd is not None else None,
            total_delta=_round(ed+wd) if ed is not None else None,reason=row['reason'],evidence=row['evidence'],suggestion=row['suggestion']))
    full_s = all(x is not None for x in school)
    full_e = basic and all(x is not None for x in enhanced)
    score_s = (sum(school)/len(specs)*(1 if basic else 2)) if full_s else None
    score_e = sum(s['enhanced_weight']*v for s,v in zip(specs,enhanced)) if full_e else None
    complete = full_s and (full_e if basic else True)
    status = 'reviewed' if complete and payload['reviewed'] else 'provisional' if complete else 'incomplete'
    comparable = full_s and full_e
    base_z = sum(z*spec['school_weight'] for z,spec in zip(enhanced,specs)) if full_e else None
    categories=[]
    for cat in template['categories']:
        indexes=[n for n,spec in enumerate(specs) if spec['category_id']==cat['id']]
        vals=[school[n] for n in indexes]; evals=[enhanced[n] for n in indexes]
        cscore = sum(vals)/len(vals)*(1 if basic else 2) if all(v is not None for v in vals) else None
        escore = sum(enhanced[n]*specs[n]['enhanced_weight'] for n in indexes)/cat['enhanced_weight'] if basic and all(v is not None for v in evals) else None
        categories.append({**cat,'school_score':_round(cscore) if cscore is not None else None,'enhanced_score':_round(escore) if escore is not None else None})
    school_reference_status = ('达到项目参考线' if score_s >= 6 else '低于项目参考线') if full_s and payload['reviewed'] else ('待教师复核' if full_s else '评分不完整')
    return dict(rule_version=RULE_VERSION,template_id=template['id'],status=status,weight_policy=policy,
        context_review=dict(enabled=context_mode, changes=context_changes,
            pending_count=sum(not c['applied'] for c in context_changes),
            note='缺失证据不扣分；疑似安全事件需单独人工核查，不由总分判定或掩盖。'),
        sensitivity=sensitivity(template,enhanced,payload['reviewed']),
        subject_context=dict(id=subject['id'], label=subject['label'], focus=list(subject['focus']),
            note=subject['note'], policy='学校基础权重不变，情境修正须人工复核' if context_mode else '已启用学科与本课目标试行加权' if policy['mode']=='subject_trial' else '通用方案尚未启用学科或五领域加权',
            calibration_status='候选映射与权重尚待校方确认及真实数据校准'),
        school=dict(score_10=_round(score_s) if score_s is not None else None,raw_score=_round(sum(school) if basic else sum(school)/15) if full_s else None,
            raw_max=100 if basic else 5,teaching_score_70=_round(sum(school)*.7,1) if basic and full_s else None,
            coverage=dict(scored=sum(x is not None for x in school),total=len(specs)),passed=None,reference_line=6,
            reference_status=school_reference_status,
            source_label='教师原始评分（人工录入）' if payload['school_source']=='teacher_recorded' else '按学校标准录入的待核对初评'),
        enhanced=dict(score_10=_round(score_e) if score_e is not None else None,coverage=dict(scored=sum(x is not None for x in enhanced),total=len(specs)),
            reference_line=6,passed=score_e>=6 if full_e and payload['reviewed'] else None,
            status_label=('学校基础 + 情境复核；未复核修正不计入总分' if context_mode else '候选权重，尚未验证；6分为试行参考线') if basic else '该表尚无增强映射'),
        comparison=dict(available=comparable,evidence_delta=_round(base_z-score_s) if comparable else None,
            weight_delta=_round(score_e-base_z) if comparable else None,total_delta=_round(score_e-score_s) if comparable else None,
            school_weight_reviewed_score=_round(base_z) if full_e else None,items=deltas),categories=categories,
        note='缺失不填零、不归一化；分差按先复核证据、后调整权重的固定顺序解释，不代表因果。未复核结果仅暂算。')
