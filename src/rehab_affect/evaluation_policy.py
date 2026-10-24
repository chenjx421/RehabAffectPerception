"""Explicit pilot weighting choices, not empirically calibrated coefficients."""
from copy import deepcopy

POLICY_VERSION = '2026-09-17.subject-goal-pilot-v1'
DOMAINS = [
    dict(id='perception', label='感知', items=['i3', 'i6'], reason='检查材料可感知性与辅助呈现。'),
    dict(id='cognition', label='认知', items=['i4', 'i8'], reason='检查概念难点与目标任务表现。'),
    dict(id='language', label='语言沟通', items=['i6', 'i9'], reason='检查沟通支持与指令可理解性，允许替代性表达。'),
    dict(id='motor', label='运动', items=['i5', 'i6'], reason='检查任务组织与操作辅助是否适配。'),
    dict(id='adaptation', label='社会适应', items=['i2', 'i7'], reason='检查生活经验联系与参与机会。'),
]
SUBJECT_ITEMS = {
    'general': [], 'language': ['i6', 'i7', 'i9'], 'math': ['i4', 'i6', 'i8'],
    'practice': ['i5', 'i6', 'i8'], 'sports': ['i5', 'i6', 'i7'], 'music': ['i6', 'i7', 'i9'],
}
SUBJECT_REASONS = {
    'general': '综合课程保留通用条目侧重。',
    'language': '表达课关注沟通渠道、回应机会与指令可理解性。',
    'math': '数学课关注概念突破、实物支持与约定条件下的目标达成。',
    'practice': '实践课关注操作顺序、适宜辅助与生活任务完成。',
    'sports': '体育课关注活动组织、安全适配与公平参与机会。',
    'music': '音乐课关注多感官支持、轮替参与与多种表达。',
}
ANCHORS = [
    dict(score=0, label='已有明确反向证据', detail='已有充分机会与观察，仍未提供所约定的必要支持。不能把缺失或未观察记为0。'),
    dict(score=2, label='支持明显不足', detail='已观察到的相关任务多次缺少必要安排，目标和支持条件明显不匹配。'),
    dict(score=4, label='部分满足约定', detail='有适宜安排，但机会覆盖或执行不稳定，需要实质改进。'),
    dict(score=6, label='达到本课最低约定', detail='在课前约定的辅助与表达方式下满足最低要求，证据可复核。'),
    dict(score=8, label='稳定满足约定', detail='在多个有效机会中保持适配，能根据困难调整教学。'),
    dict(score=10, label='充分且一致的证据', detail='相关分层目标、机会覆盖与调整均有一致证据支持，不要求所有学生同一表现。'),
]


def catalog_policy():
    return deepcopy(dict(version=POLICY_VERSION, domains=DOMAINS, anchors=ANCHORS,
        modes=[dict(id='school_context', label='学校基础 + 情境复核'), dict(id='common', label='通用试行权重'), dict(id='subject_trial', label='学科与本课目标试行权重')],
        subject_items=SUBJECT_ITEMS, subject_reasons=SUBJECT_REASONS,
        multiplier=.10, limitation='10%为保守的工程试行扰动幅度，并非文献推导或数据拟合结果；须校方校准。'))


def resolve_policy(template, payload):
    mode = payload.get('weight_policy', 'common')
    domains = payload.get('focus_domains', [])
    if mode not in {'common', 'subject_trial', 'school_context'}:
        raise ValueError('权重方案无效')
    if (not isinstance(domains, list) or len(domains) > 5 or any(not isinstance(x, str) for x in domains)
            or len(set(domains)) != len(domains) or not set(domains) <= {d['id'] for d in DOMAINS}):
        raise ValueError('请选择有效且不重复的本课目标领域')
    if (mode != 'subject_trial' or not template['enhanced_available']) and domains:
        raise ValueError('本课目标领域加权仅适用于基本表的学科试行方案')
    if mode != 'common' and not template['enhanced_available']:
        raise ValueError('此学校原表尚无学科增强映射')
    subject = payload.get('subject_id', 'general')
    selected = [d for d in DOMAINS if d['id'] in domains]
    result = deepcopy(template)
    rows = []
    for item in result['items']:
        base = item['school_weight'] if mode == 'school_context' else item['enhanced_weight']
        matched = [d for d in selected if item['id'] in d['items']]
        subject_match = mode == 'subject_trial' and item['id'] in SUBJECT_ITEMS[subject]
        goal_boost = .1 * len(matched) / len(selected) if selected else 0
        raw = base * (1 + .1 * subject_match + goal_boost) if base is not None else None
        rows.append(dict(id=item['id'], label=item['label'], base_weight=base, raw_weight=raw,
                         subject_match=bool(subject_match), domain_ids=[d['id'] for d in matched],
                         multiplier=1 + .1 * subject_match + goal_boost))
    if result['enhanced_available']:
        total = sum(r['raw_weight'] for r in rows)
        for item, row in zip(result['items'], rows):
            item['enhanced_weight'] = row['base_weight'] if mode != 'subject_trial' else row['raw_weight'] / total
            row['final_weight'] = item['enhanced_weight']
        if mode != 'common':
            for category in result['categories']:
                category['enhanced_weight'] = sum(i['enhanced_weight'] for i in result['items'] if i['category_id'] == category['id'])
                if mode == 'school_context':
                    category['rationale'] = '沿用学校分类权重，不因更换算法自动产生分差。'
    domain_rows = []
    for domain in DOMAINS:
        domain_rows.append(dict(**domain, selected=domain in selected,
                               status='本课重点支持' if domain in selected else '未选为本课重点，不计能力分'))
    return result, dict(version=POLICY_VERSION, mode=mode, focus_domains=domains, items=rows, domains=domain_rows,
                       rationale='保留学校逐项权重；无新证据沿用学校分，情境修正经教师复核后生效。' if mode == 'school_context' else SUBJECT_REASONS[subject] if mode == 'subject_trial' else '使用通用候选权重；学科不改变数值。',
                       formula='最终分 = 学校基础分 + 各项学校权重 × 已复核的单项分差。不设保底分，不自动加减分。' if mode == 'school_context' else '最终权重 = 基础权重 × (1 + 学科命中×10% + 命中领域数/所选领域数×10%)，再归一化至100%。未选领域时最后一项为0。',
                       limitation='情境修正是教师复核规则，尚未完成学校实测校准；不得仅依据障碍、非口语回应、课堂中断或采集缺失扣分。' if mode == 'school_context' else catalog_policy()['limitation'],
                       note='五领域是教学支持映射，未从IEP自动判定能力；不以障碍类型、动作幅度或是否口语表达扣分。')


def sensitivity(template, scores, reviewed):
    if not template['enhanced_available'] or any(s is None for s in scores):
        return dict(available=False, reason='增强条目不完整，暂不做权重敏感性检查')
    scenarios = []
    for category in template['categories']:
        for factor in (.9, 1.1):
            weights = [i['enhanced_weight'] * (factor if i['category_id'] == category['id'] else 1) for i in template['items']]
            score = sum(w * s for w, s in zip(weights, scores)) / sum(weights)
            scenarios.append(dict(category_id=category['id'], factor=factor, score=round(score, 4)))
    low, high = min(r['score'] for r in scenarios), max(r['score'] for r in scenarios)
    return dict(available=True, low=low, high=high, crosses_reference=low < 6 <= high,
                reviewed=reviewed, scenarios=scenarios,
                note='逐类将权重乘0.9或1.1后重新归一化。范围不是置信区间，也不是模型准确率。')
