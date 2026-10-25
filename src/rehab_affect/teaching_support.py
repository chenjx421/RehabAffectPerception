"""Teacher-selected support needs, not diagnoses or automatic treatment advice."""
import os

REFERENCES=[
    dict(id='cast2024',year=2024,title='CAST UDL Guidelines 3.0: multiple media for communication',
         url='https://udlguidelines.cast.org/action-expression/expression-communication/multiple-media/',
         support='允许学生通过多种媒介表达学习结果。',limitation='教学设计指南，不证明评分权重或个体疗效。'),
    dict(id='aac2024',year=2024,title='Mishra: face-to-face versus remote low-tech AAC randomized trial',
         url='https://doi.org/10.1044/2024_JSLHR-23-00390',
         support='研究了无口语自闭症儿童的低技术AAC教学及不同交付方式。',limitation='已核对摘要；不能推广为所有病症的治疗方案或本系统有效性证明。'),
]
NEEDS={
    'communication':dict(label='口语受限 / 辅助沟通',related='失语、言语或语言障碍需专业确认；少语不等于失语症。',
        actions=['允许图卡、手势、AAC或动作回应，按IEP约定方式观察。','将“是否理解任务”和“是否说出词语”分开记录。'],
        observe='在相同任务和支持条件下，记录有效回应、主动表达及所需提示。',references=['cast2024','aac2024']),
    'sensory':dict(label='感官负荷 / 环境适配',related='适用于存在感官支持需求的学生，不限于某个诊断。',
        actions=['与教师核对学生已知的声音、光线和触觉偏好。','提供可选择的休息与较低刺激的任务环境，不强迫眼神接触。'],
        observe='记录环境调整前后的参与机会与学生表达的需要，不从叫声直接推断情绪。',references=['cast2024']),
    'steps':dict(label='理解与任务步骤支持',related='可与智力或发展相关支持需求对应，实际方案以IEP为准。',
        actions=['将任务拆成可观察的小步骤，结合实物或图片。','记录独立完成和提示后完成，不把辅助器具本身视为失败。'],
        observe='在同一目标中比较提示类型、完成步骤和跨材料表现。',references=['cast2024']),
}


def deepseek_status():
    # Never expose a credential or accept an arbitrary endpoint from a browser.
    key=bool(os.environ.get('REHAB_DEEPSEEK_API_KEY','').strip())
    model=bool(os.environ.get('REHAB_DEEPSEEK_MODEL','').strip())
    return dict(provider='DeepSeek',key_configured=key,model_configured=model,
                network_enabled=False,status='入口已预留，联网调用尚未启用',
                boundary='拟仅发送经审批的去标识结构化信息；本页不会发送视频、姓名、诊断或自由文本。')


def safe_preview(work):
    return {'schema_version':1,'purpose':'teaching_support_explanation',
            'summary':{k:int(work['summary'][k]) for k in ('students','records','reviewed','scored','pending','reconfirm')},
            'references':[r['id'] for r in REFERENCES],
            'constraints':['do_not_change_scores','do_not_diagnose','missing_audio_is_not_no_response'],
            'network_sent':False}
