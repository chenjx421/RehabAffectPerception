"""Task-scoped classroom evidence and deterministic, teacher-grounded reports."""
from __future__ import annotations

import json

from .assessment_rubric import DIMENSION_WEIGHTS, RUBRIC_VERSION

DIMENSIONS = {'accuracy':'任务正确性','independence':'独立完成','consistency':'表现稳定性','transfer':'情境迁移'}
STATES = {'unknown':'无法判断','participating':'参与任务','repeat_prompt':'需要重复提示',
          'help_requested':'主动求助','paused':'暂停或拒绝'}
SUPPORT = {'unknown':'未记录','independent':'独立完成','verbal':'口头提示','visual':'视觉提示',
           'demonstration':'动作示范','physical':'身体协助'}


def _excerpt(value, limit=100):
    text = str(value or '').strip()
    return text if len(text)<=limit else text[:limit]+'…'


def build_workspace(identity, task, records):
    students = {s['student_id']:s for s in identity['students']}
    bindings = [b for b in identity['bindings'] if b['status']=='confirmed'
                and b['current_revision'] and b['role']=='student']
    ids = {b['student_id'] for b in bindings} | {r['student_id'] for r in records}
    # No school-global roster or legacy demo results enter this workspace.
    people = []
    for sid in sorted(ids):
        if sid not in students:
            continue
        values = [r for r in records if r['student_id']==sid]
        people.append({**students[sid], 'records':values,
                       'bindings':[b for b in bindings if b['student_id']==sid],
                       'scored_count':sum(r['assessment']['overall_score'] is not None for r in values)})
    try:
        raw = json.loads(task.get('processing_result_json') or '{}')
    except (ValueError,TypeError):
        raw = {}
    media = raw.get('media', {}) if raw.get('source_sha256')==task.get('sha256') else {}
    reviewed = [r for r in records if r['reviewed'] and r['evidence_status']=='current']
    summary = {'students':len(people), 'records':len(records), 'reviewed':len(reviewed),
               'scored':sum(r['assessment']['overall_score'] is not None for r in records),
               'reconfirm':sum(r['evidence_status']!='current' for r in records),
               'pending':sum(not r['reviewed'] and r['evidence_status']=='current' for r in records)}
    result = {'task_id':identity['task_id'], 'course_name':identity['course_name'],
              'course_id':identity['course_id'], 'school_context':identity['school_context'],
              'frame_revision':identity['frame_revision'], 'media_available':identity['media_available'],
              'can_edit':identity['can_edit'], 'media':{k:media.get(k) for k in ('duration_sec','width','height','has_audio')},
              'frames':identity['frames'], 'people':people, 'records':records, 'summary':summary,
              'rubric_version':RUBRIC_VERSION, 'dimensions':DIMENSIONS, 'weights':DIMENSION_WEIGHTS,
              'states':STATES, 'support_levels':SUPPORT,
              'source_note':'评分与状态来自教师复核，不是自动情绪识别；单帧身份不代表连续人物追踪。',
              'report_scope':'仅本账号、本校及当前视频；未纳入未关联的其他课堂视频。'}
    result['report'] = build_report(result)
    return result


def build_report(work):
    s = work['summary']
    evidence = [r for r in work['records'] if r['reviewed'] and r['evidence_status']=='current']
    sections = []
    def add(title, text):
        sections.append({'title':title,'text':text})
    add('本次范围', f'本报告对应“{work["course_name"]}”的当前上传视频，已关联{s["students"]}名学生，'
        f'保存{s["records"]}条目标观察，其中教师已复核{s["reviewed"]}条、满足四维评分条件{s["scored"]}条。'
        '统计范围是已确认身份和已录入的教学目标，不代表全班覆盖率，也不等于整节课所有学习机会。'
        '未出现记录的学生和时段保留为空缺，不按零分处理。')
    if not evidence:
        add('证据待补充', '当前没有可用的教师复核证据，因此暂不生成学生掌握程度、个人状态或教学效果结论。'
            '请先确认视频中的学生，在对应时段记录教师提问、学生回应和实际支持方式，再复核观察记录。'
            '可以只保存观察，不强行补齐没有证据的维度。证据不足时不会用通用文字填满千字。')
    else:
        names = {p['student_id']:p['display_name'] for p in work['people']}
        examples = []
        for r in evidence[:3]:
            score = r['assessment']['overall_score']
            examples.append(f'{names.get(r["student_id"],"学生")}在{r["start_sec"]:g}至{r["end_sec"]:g}秒的'
                f'“{_excerpt(r["goal_id"],24)}”目标中，教师记录“{_excerpt(r["evidence"],70)}”；'
                f'支持方式为{SUPPORT.get(r.get("support_level"),"未记录")}，'
                + (f'本目标参考得分{score:.2f}/10。' if score is not None else '本目标证据尚不足以形成总分。'))
        add('目标与课堂证据', ''.join(examples)+'上述为部分证据摘要；完整原文、修订版本及片段位置保留在观察记录中。')
        first = evidence[0]
        known_states = sum(r.get('observed_state','unknown')!='unknown' for r in evidence)
        add('互动记录核对', f'在首条可用复核中，教师任务为“{_excerpt(first.get("teacher_prompt") or "未记录",55)}”，'
            f'学生回应为“{_excerpt(first.get("student_response") or "未记录",55)}”。'
            f'当前{len(evidence)}条可用复核中，有{known_states}条填写了可观察状态。'
            '这里统计的是目标记录数量，不是参与时长或专注比例；同一片段可能涉及多个教学目标。'
            '只有同时核对提问对象、学生实际回应及提示条件，才能进一步讨论目标是否达成；集体回答或他人代答不能自动归到该学生名下。')
        add('学生回应与支持', '分析围绕“教师提出了什么任务、学生如何回应、获得何种支持、是否达到事先约定目标”展开。'
            '口头提示、图卡辅助、动作示范和身体协助分别记录，避免将协助完成直接解释为独立掌握。'
            '参与、重复提示、求助、暂停等状态来自教师对可见行为的确认；离开视线、身体动作或安静本身都不能直接证明分心或学会。')
        add('量化口径', '学生目标测量采用十分制，正确性、独立性、稳定性和迁移的试行权重分别为35%、30%、20%和15%。'
            '仅在教师复核、至少两次有效观察且四维证据齐全时计算总分；未观察到的迁移保留空缺。'
            '6分是项目参考线，并非经过验证的官方及格标准。不同学生的目标和支持条件可能不同，因此不将个人分数简单平均为教师得分或班级排名。')
        add('教学调整建议', '下一次教学优先选择本课已有证据的一个具体目标，保持材料、指令和支持条件可比较。'
            '对反复需要提示的任务，可由教师决定拆分步骤、增加等待时间或使用视觉支持，再记录独立完成与提示后完成的差异。'
            '对已能完成的任务，可在适当情况下更换相似材料观察迁移；出现拒绝、疲劳或不适线索时，先确认学生需求，避免强迫参与。'
            '这些是待教师选择的教学建议，不是对诊断或治疗的判断。')
        add('连续追踪与边界', '本次记录与同一学生、同一目标、相同测量条件和量表版本的后续课程关联，才能讨论短期或长期变化。'
            '单段视频不能证明能力改善、退步或某种教学方法具有因果效果。后续逐课、每周、每月及60日趋势只汇总可比较的复核记录。'
            '身份确认被撤销、视频版本改变或证据失效时，相关评分暂停计入；原始视频到期后，报告需区分已归档观察与仍可回放的媒体证据。')
    if s['reconfirm']:
        add('需要重新确认', f'有{s["reconfirm"]}条记录的身份或视频版本证据失效，已从有效评分中排除。请重新确认学生后编辑复核。')
    if not work['media_available']:
        add('原始媒体状态', '本次原始视频目前不可回放。所列结果来自保留的教师观察记录，并非对已到期或缺失视频进行了重新分析。')
    return {'title':'课堂观察与学习支持报告','sections':sections,
            'character_count':sum(len(x['text']) for x in sections), 'generation':'本地规则与教师复核记录；未调用外部大模型',
            'ready':bool(evidence),'record_versions':[{'record_id':r['record_id'],'version':r['version']} for r in work['records']]}
