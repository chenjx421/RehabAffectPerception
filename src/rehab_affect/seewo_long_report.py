from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = PROJECT_ROOT / "outputs" / "seewo_demo2" / "reports"
REVIEW_STORE = PROJECT_ROOT / "outputs" / "seewo_demo2" / "teacher_reviews.json"
REPORT_TARGET_CHARS = 1_000


def report_writer_status() -> dict[str, Any]:
    base_url = os.getenv("REHAB_REPORT_LLM_BASE_URL", "").strip()
    model = os.getenv("REHAB_REPORT_LLM_MODEL", "").strip()
    return {
        "default_engine": "evidence_template",
        "llm_configured": bool(base_url and model),
        "llm_model": model or "未配置",
        "supported_engines": ["evidence_template", "llm_assisted"],
        "privacy_note": "LLM只接收匿名化结构指标、课程标准和教师复核文本，不接收原始视频、音频或身份资料。",
    }


def load_teacher_reviews(course_id: str | None = None) -> dict[str, Any]:
    if not REVIEW_STORE.exists():
        return {}
    try:
        payload = json.loads(REVIEW_STORE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    reviews = payload.get("reviews", {}) if isinstance(payload, dict) else {}
    if course_id:
        prefix = f"{course_id}:"
        return {key: value for key, value in reviews.items() if key.startswith(prefix)}
    return reviews


def save_teacher_reviews(course_id: str, reviews: dict[str, Any]) -> dict[str, Any]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    existing = load_teacher_reviews()
    prefix = f"{course_id}:"
    existing = {key: value for key, value in existing.items() if not key.startswith(prefix)}
    for key, value in reviews.items():
        if key.startswith(prefix):
            existing[key] = _normalize_review(value)
    payload = {
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "reviews": existing,
    }
    REVIEW_STORE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return load_teacher_reviews(course_id)


def build_long_course_report(
    demo_payload: dict[str, Any],
    course_id: str,
    *,
    course_context: dict[str, Any] | None = None,
    reviews: dict[str, Any] | None = None,
    target_chars: int = REPORT_TARGET_CHARS,
    use_llm: bool = False,
) -> dict[str, Any]:
    course = next((item for item in demo_payload.get("courses", []) if item.get("course_id") == course_id), None)
    if course is None:
        raise KeyError(f"Unknown Demo2 course: {course_id}")
    context = _course_context(course, course_context or {})
    normalized_reviews = {
        key: _normalize_review(value)
        for key, value in (reviews or load_teacher_reviews(course_id)).items()
        if key.startswith(f"{course_id}:")
    }
    sections = _build_compact_sections(course, context, normalized_reviews)
    full_text = _join_sections(sections)
    engine = "evidence_template"
    engine_note = "未调用LLM；报告由本地证据模板生成。"
    if use_llm:
        aliases = {
            student["display_name"]: f"学生{chr(65 + index)}"
            for index, student in enumerate(course["student_results"])
        }
        full_text, engine, engine_note = _maybe_rewrite_with_llm(
            full_text, context, normalized_reviews, aliases
        )
        if engine == "llm_assisted":
            sections = [{"section_id": "llm_report", "title": "LLM辅助整理后的完整报告", "content": full_text}]

    result = {
        "report_id": f"{course_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "title": f"《{context['course_name']}》三学生课堂学习成效与支持行动报告",
        "course_id": course_id,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "target_char_count": target_chars,
        "char_count": len(full_text),
        "engine": engine,
        "engine_note": engine_note,
        "course_context": context,
        "review_summary": _review_summary(course, normalized_reviews),
        "sections": sections,
        "full_text": full_text,
        "boundary": "本报告用于课堂教育支持复盘，不构成医学诊断、学生能力定级或教师绩效结论。",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    safe_id = re.sub(r"[^A-Za-z0-9_.-]", "_", result["report_id"])
    (REPORT_DIR / f"{safe_id}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (REPORT_DIR / f"{safe_id}.txt").write_text(full_text, encoding="utf-8")
    return result


def _course_context(course: dict[str, Any], supplied: dict[str, Any]) -> dict[str, str]:
    values = {
        "course_type": supplied.get("course_type") or course.get("subject", "未填写"),
        "course_name": supplied.get("course_name") or course.get("course_name", "未命名课程"),
        "lesson_standard": supplied.get("lesson_standard") or course.get("lesson_standard", "未填写"),
        "school_assessment_standard": supplied.get("school_assessment_standard")
        or course.get("school_assessment_standard", "未填写"),
        "lesson_plan_requirement": supplied.get("lesson_plan_requirement")
        or "依据学校教案组织教学阶段、任务机会、提示等级和课后复核。",
        "confirmed_by": supplied.get("confirmed_by") or "演示人员",
    }
    return {key: _plain_text(value, 4000) for key, value in values.items()}


def _normalize_review(value: Any) -> dict[str, str]:
    if isinstance(value, str):
        value = {"verdict": value}
    if not isinstance(value, dict):
        value = {}
    return {
        "verdict": _plain_text(value.get("verdict", "待复核"), 30),
        "correctness": _plain_text(value.get("correctness", "未标注"), 30),
        "prompt_level": _plain_text(value.get("prompt_level", "未标注"), 30),
        "note": _plain_text(value.get("note", ""), 300),
        "updated_at": _plain_text(value.get("updated_at", ""), 50),
    }


def _section(section_id: str, title: str, paragraphs: list[str]) -> dict[str, str]:
    return {"section_id": section_id, "title": title, "content": "\n\n".join(p.strip() for p in paragraphs if p.strip())}


def _join_sections(sections: list[dict[str, str]]) -> str:
    text = "\n\n".join(f"{section['title']}\n{section['content']}" for section in sections)
    text = re.sub(r"([。！？；])\1+", r"\1", text)
    return text.replace("。；", "；")


def _plain_text(value: Any, limit: int) -> str:
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(value or "")).strip()
    return text[:limit]


def _build_compact_sections(
    course: dict[str, Any], context: dict[str, str], reviews: dict[str, dict[str, str]]
) -> list[dict[str, str]]:
    results = course["student_results"]
    teacher = course["teacher_effectiveness"]
    review = _review_summary(course, reviews)
    student_lines = []
    action_lines = []
    for student in results:
        state = student["state_summary"]
        mastery = student["mastery"]
        fit = student["course_fit"]
        student_lines.append(
            f"{student['display_name']}本节参与指数{state['participation_score']}分，学习掌握初评"
            f"{mastery['overall_score']}分，当前为“{mastery['band']}”，课程适配{fit['fit_score']}分。"
            f"重点目标为“{fit['largest_gap_objective']}”；下一课建议{student['next_lesson_actions'][0]}"
        )
        robot = student["robot_action"]
        action_lines.append(
            f"{student['display_name']}：屏幕“{robot['screen']}”，语音“{robot['speech']}”，"
            f"动作原语{robot['motion']}。"
        )
    return [
        _section(
            "scope",
            "一、课程与报告边界",
            [
                f"本报告对应{context['course_type']}《{context['course_name']}》，面向学校和任课教师形成一节课的课堂支持复盘。"
                f"课程要求为：{context['lesson_standard']}；校方考核口径为：{context['school_assessment_standard']}。"
                "报告把课程目标、视频线索、师生互动、个体档案和教师复核放在同一证据链中，不作医学诊断、能力定级或教师绩效结论。"
            ],
        ),
        _section(
            "class_overview",
            "二、班级课堂证据概览",
            [
                f"本节三名重点学生的学习掌握初评均值为{course['class_summary']['preliminary_mastery_score']}分，"
                f"参与信号均值为{course['class_summary']['participation_score']}分。参与和掌握分开统计：动作明显不等于学会，"
                "低回应也不能直接解释为分心或不会。固定机位视频适合观察任务启动、持续参与和明显回应；遮挡、远距离声音和答案正确性仍需教师回看片段确认。"
            ],
        ),
        _section(
            "student_findings",
            "三、学生个体学习判断",
            student_lines,
        ),
        _section(
            "teacher_support",
            "四、教师支持效果与复核",
            [
                f"本节教学支持效果指数为{teacher['overall_score']}分，结论为“{teacher['band']['label']}”。"
                "该指标衡量课程是否为三名学生提供了清晰任务、充分等待、适当提示、支持后恢复和学习结果证据，不评价教师个人能力。"
                f"系统推荐复核{review['total']}个关键片段，当前完成{review['reviewed']}个；未完成部分继续保留为系统初评。"
            ],
        ),
        _section(
            "embodied_action",
            "五、支持动作与下一课安排",
            [
                "机器人动作只作为未来载体接口：遵循低刺激、无主动接触、最小必要干预和教师在环原则。"
                "证据不足时保持位置，不连续呼叫，不使用闪烁强光或突然大声。",
                "本节建议：" + "".join(action_lines),
                "下一课应优先给每名学生一次清晰、可等待的独立成功机会，再逐步撤除提示；跨课比较只观察同类任务中的独立完成、提示减少、稳定性和迁移。",
            ],
        ),
        _section(
            "conclusion",
            "六、结论与使用方式",
            [
                "本报告用于教师复盘、下一课设计和个体档案留痕。关键学习结论必须由熟悉学生的教师确认；没有清晰任务机会或证据不足时标记为未观察，不写成学生不会。"
            ],
        ),
    ]


def _build_sections(
    course: dict[str, Any], context: dict[str, str], reviews: dict[str, dict[str, str]]
) -> list[dict[str, str]]:
    results = course["student_results"]
    teacher = course["teacher_effectiveness"]
    report = course["report_summary"]
    sections = [
        _section(
            "scope",
            "一、报告任务、结论层级与使用边界",
            [
                f"本报告针对{context['course_type']}课程《{context['course_name']}》形成，分析对象为三名由校方确认身份和固定座位的学生。报告不逐条罗列学生所有动作，而是把课程目标、课堂活动、学生可见回应、教师支持、学习机会和后续支持动作连接成可复核的证据链。系统先按固定时间窗口整理视频线索，再结合学校教案、个体化教育资料、上次课程表现和教师标注形成课堂支持初评。",
                "报告中的参与、低回应、出现操作和证据不足都是课堂观察术语。参与状态不能替代学习结果，低回应不能自动解释为分心、拒绝或能力不足；动作明显也不能证明回答正确。学习掌握度只在学生获得明确任务机会时评价，并区分独立完成、简单提示、示范或部分协助、尚未表现和未观察。",
                f"当前三人掌握初评均值为{course['class_summary']['preliminary_mastery_score']}分，参与信号均值为{course['class_summary']['participation_score']}分。两项指标分开呈现。涉及答案正确性、提示等级、知识迁移和原因解释的结论，需要教师回看时间段后确认。报告只服务于教学复盘、下一课设计和低刺激支持动作选择。",
            ],
        ),
        _section(
            "course_confirmation",
            "二、进入分析前的课程确认记录",
            [
                f"课程类型确认为：{context['course_type']}；课程名称确认为：《{context['course_name']}》。学校官方教案或课程要求为：{context['lesson_standard']}。页面进入前补充确认的教案执行要求为：{context['lesson_plan_requirement']}。校方考核标准为：{context['school_assessment_standard']}。确认人为：{context['confirmed_by']}。",
                "把课程确认放在分析之前，是为了防止系统先看到动作再倒推课堂目标。相同动作在不同课程阶段具有不同含义：教师讲解时短暂低动作可能是倾听，操作练习时持续低动作则可能提示任务尚未启动。学生抬手可能是回答、模仿、寻求帮助或无关动作，必须结合当时教案阶段和教师指令解释。",
                "课程标准决定系统寻找哪些学习机会，校方考核标准决定教师复核时记录什么，个体目标决定同一任务对不同学生如何分层。系统不会因为障碍类别自动降低课程目标，而是依据上次表现、当前证据和支持需要建议把目标拆成更短、更可观察的步骤。最终课程目标由教师和学校确认。",
            ],
        ),
    ]
    phase_text = "；".join(f"{key}{value}" for key, value in report.get("behavior_distribution", {}).items())
    sections.extend(
        [
            _section(
                "data_quality",
                "三、数据来源、视频质量与证据可靠性",
                [
                    f"本次使用的数据包括学生机课堂视频、教师机视频或课堂全景、远场音频、课程教案、个体化教育支持资料和上次课程表现。学生机视频为{course['data_source']['student_video']}，时长约{course['video_meta']['duration_min']}分钟，按{course['video_meta']['window_sec']}秒形成状态窗口。课堂阶段分布为：{phase_text}。",
                    "当前视频为固定机位和较远距离画面，适合观察座位区域动作变化、任务启动、持续参与和明显回应，不适合进行精细眼神、微表情或医学状态判断。系统通过固定座位ROI减少多人画面中的身份漂移；ROI由校方确认，不根据外貌或障碍类型推断身份。遮挡、成人经过、画面模糊和光照变化会降低证据质量，相关窗口进入教师复核队列。",
                    f"音频处理遵循保守原则：{course['data_source']['audio_status']}。在远场环境中，如果不能可靠完成说话人归属，系统只把声音作为课堂阶段、提问或活动变化的背景证据。后续若增加领夹麦、阵列麦克风或可确认的座位声源信息，可以进一步统计教师提问、候答时间、学生回答和提示类型。",
                    "证据可靠性由画面质量、状态窗口置信度、任务机会是否明确、教师复核是否完成共同决定。正式试点时应保存每条结论对应的时间段、课程阶段、任务、学生反应、提示等级和复核人，以便追溯和后续训练。",
                ],
            ),
            _section(
                "class_overview",
                "四、三名学生课堂过程总览",
                [
                    f"三名学生的课堂参与指数分别为：{_student_metric_line(results, 'participation')}。学习掌握初评分别为：{_student_metric_line(results, 'mastery')}。这些结果只与各自上次表现和本课目标比较，不用于学生之间排名。系统关注每名学生是否获得合适的任务机会、是否需要提示、提示后能否恢复、能否在类似任务中逐步减少支持。",
                    f"本节课教学支持效果指数为{teacher['overall_score']}分，结论为“{teacher['band']['label']}”。五项标准包括三人参与维持度、波动后恢复度、个体化目标适配度、学习结果证据度和低干扰支持环境。该指数评价的是本节课对三名学生是否提供了可受益的学习条件，不评价教师个人能力。",
                    "班级复盘应优先回答三个问题：三名学生是否都获得过清晰且可等待的独立作答或操作机会；低回应后，教师的指令、视觉提示或示范是否帮助其重新回到任务；任务完成后是否逐步撤除提示，并通过更换材料或情境验证迁移。",
                ],
            ),
        ]
    )
    for index, student in enumerate(results, start=1):
        sections.append(_student_section(course, student, reviews, index))
    sections.extend(
        [
            _teacher_section(course),
            _review_section(course, reviews),
            _embodied_action_section(course),
            _next_lesson_section(course),
        ]
    )
    return sections


def _student_metric_line(results: list[dict[str, Any]], metric: str) -> str:
    if metric == "participation":
        return "；".join(f"{item['display_name']}{item['state_summary']['participation_score']}分" for item in results)
    return "；".join(f"{item['display_name']}{item['mastery']['overall_score']}分" for item in results)


def _student_section(
    course: dict[str, Any], student: dict[str, Any], reviews: dict[str, dict[str, str]], index: int
) -> dict[str, str]:
    mastery = student["mastery"]
    state = student["state_summary"]
    fit = student["course_fit"]
    profile = student["education_profile"]
    objectives = []
    for row in mastery["objectives"]:
        objectives.append(
            f"目标“{row['label']}”权重{row['weight']:.0%}，上次等级{row['previous_level']}，本次初评等级"
            f"{row['provisional_level']}、折算{row['score']}分；系统记录{row['opportunities']}次机会，其中"
            f"{row['observed']}次可观察、{row['independent']}次初判独立、{row['prompted']}次存在提示，"
            f"{row['unobserved']}次未观察。答案正确性和提示等级仍需教师抽检。"
        )
    interactions = []
    for interaction_index, row in enumerate(student["key_interactions"]):
        key = f"{course['course_id']}:{student['student_id']}:{interaction_index}"
        review = reviews.get(key, _normalize_review({}))
        interactions.append(
            f"{row['time_label']}处于{row['lesson_phase']}，教师活动为“{row['teacher_activity']}”，系统观察为"
            f"“{row['observed_state']}”，证据为“{row['evidence']}”。教师复核：{review['verdict']}；"
            f"正确性：{review['correctness']}；提示等级：{review['prompt_level']}；备注："
            f"{review['note'] or '尚未填写'}。"
        )
    robot = student["robot_action"]
    title_number = ["五", "六", "七"][index - 1]
    return _section(
        f"student_{student['student_id']}",
        f"{title_number}、{student['display_name']}个体学习表现、支持需要与行动建议",
        [
            f"该生本课个体目标为：{student['individual_target']}。课程适配分为{fit['fit_score']}分，结论为"
            f"“{fit['fit_level']}”，最大差距目标为“{fit['largest_gap_objective']}”。{fit['conclusion']}"
            "课程适配表示本课要求与该生上次表现及支持资料的匹配程度，不代表对学生能力的固定判断。",
            f"本节课共形成{state['window_count']}个状态窗口，参与指数为{state['participation_score']}分。"
            f"稳定参与或出现回应信号约{state['engaged_ratio']:.0%}，回应信号较低约"
            f"{state['low_response_ratio']:.0%}，证据不足约{state['uncertain_ratio']:.0%}，平均置信度"
            f"{state['avg_confidence']:.2f}，建议重点复核{state['review_required_count']}个窗口。低回应窗口"
            "需要结合任务区分倾听、等待、思考、未理解、疲劳或遮挡，不能仅凭动作解释原因。",
            f"学习掌握综合初评为{mastery['overall_score']}分，分层为“{mastery['band']}”，置信度"
            f"{mastery['confidence']:.2f}。四维分别为正确性{mastery['dimensions']['accuracy']}分、独立程度"
            f"{mastery['dimensions']['independence']}分、重复一致性{mastery['dimensions']['consistency']}分和迁移"
            f"{mastery['dimensions']['transfer']}分。四维结果用于组织证据，最终值需由教师确认实际答案、提示类型"
            "和不同材料中的表现。",
            "分目标记录如下：\n" + "\n".join(objectives),
            "关键课堂片段与教师标注如下：\n" + "\n".join(interactions),
            f"可利用优势包括：{'；'.join(profile.get('strengths', [])) or '尚待补充'}。当前支持需要包括："
            f"{'；'.join(profile.get('support_needs', [])) or '尚待补充'}。已知有效支持方式包括："
            f"{'；'.join(profile.get('effective_support', [])) or '短指令、视觉提示和充分等待'}。安全约束包括："
            f"{'；'.join(profile.get('safety_constraints', [])) or '避免突然高强度刺激'}。这些资料只约束教学支持"
            "和机器人动作，不用于输出诊断结论。",
            f"下一课建议为：{'；'.join(action.rstrip('。； ') for action in student['next_lesson_actions'])}。屏幕端建议“{robot['screen']}”，语音端"
            f"建议“{robot['speech']}”，机器人动作建议为{robot['motion']}。"
            f"{'该动作需教师确认后执行。' if robot['teacher_confirmation_required'] else '该动作属于低风险建议，教师仍可关闭。'}"
            "判断进步时应优先比较同类目标中的独立完成比例、提示减少、表现稳定和迁移，不只比较单节课总分。",
        ],
    )


def _teacher_section(course: dict[str, Any]) -> dict[str, str]:
    teacher = course["teacher_effectiveness"]
    metric_text = "\n".join(
        f"{metric['name']}：{metric['score']}分，权重{metric['weight']}%。口径为{metric['benchmark']}"
        f"证据说明：{metric['evidence']}后续解释：{metric['interpretation']}"
        for metric in teacher["metrics"]
    )
    return _section(
        "teacher_support",
        "八、教学支持效果与教师复盘建议",
        [
            teacher["summary"],
            metric_text,
            "支持效果较好的部分应继续保留并抽样验证；分数较低的部分应回到视频，判断问题来自课程目标跨度、"
            "指令长度、等待时间、提示方式、材料难度、学生状态还是画面证据不足。系统不把所有低回应都归因于"
            "教师，也不把短时参与提高解释为长期进步。",
            "建议教师为关键片段补充四类标签：任务是否清晰、回答是否正确、采用了哪一级提示、提示后是否恢复"
            "或完成。标签完成后，下一课可调整最弱目标，同时保持已经验证有效的支持方式。高影响或可能造成刺激"
            "的动作只向教师提出建议，不直接面向学生执行。",
        ],
    )


def _review_section(course: dict[str, Any], reviews: dict[str, dict[str, str]]) -> dict[str, str]:
    summary = _review_summary(course, reviews)
    verdicts = summary["verdict_counts"]
    lines = [
        f"标注{key}：结论{value['verdict']}，正确性{value['correctness']}，提示等级"
        f"{value['prompt_level']}，备注{value['note'] or '无'}。"
        for key, value in sorted(reviews.items())
    ]
    return _section(
        "teacher_review",
        "九、教师复核标注完成度与结论修正原则",
        [
            f"本课计划复核{summary['total']}个关键互动片段，已完成{summary['reviewed']}个，完成率"
            f"{summary['completion_rate']:.0%}。其中符合{verdicts.get('符合', 0)}个、需修正"
            f"{verdicts.get('需修正', 0)}个、不确定{verdicts.get('不确定', 0)}个。未完成内容保留为系统初评。",
            "教师标注用于补充视频难以获得的课堂语义：当时要求学生做什么、答案是否正确、接受何种提示、提示后"
            "是否恢复，以及画面外是否存在材料或人员影响。标记需修正时，正式报告优先采用教师说明；标记不确定时，"
            "该片段不计入不会或退步。",
            ("已保存的复核记录如下：\n" + "\n".join(lines)) if lines else "当前尚未保存教师复核记录，报告中的学习结果均保持初评状态。",
        ],
    )


def _review_summary(course: dict[str, Any], reviews: dict[str, dict[str, str]]) -> dict[str, Any]:
    total = sum(len(student["key_interactions"]) for student in course["student_results"])
    completed = [item for item in reviews.values() if item.get("verdict") in {"符合", "需修正", "不确定"}]
    counts = Counter(item["verdict"] for item in completed)
    return {
        "total": total,
        "reviewed": len(completed),
        "completion_rate": len(completed) / total if total else 0.0,
        "verdict_counts": dict(counts),
        "report_status": "教师复核后报告" if len(completed) == total and total else "系统初评报告，仍需教师复核",
    }


def _embodied_action_section(course: dict[str, Any]) -> dict[str, str]:
    rows = []
    for student in course["student_results"]:
        action = student["robot_action"]
        rows.append(
            f"{student['display_name']}：屏幕“{action['screen']}”；语音“{action['speech']}”；动作原语"
            f"{action['motion']}；教师确认要求为"
            f"{'需要' if action['teacher_confirmation_required'] else '低风险动作可执行但可随时关闭'}。"
        )
    return _section(
        "embodied_action",
        "十、从课堂感知到屏幕、语音与机器人动作",
        [
            "具身闭环为：摄像头、麦克风和课程任务提供可观察证据，多模态融合形成human_state，时间平滑减少"
            "单帧误判，策略层结合风险、个体档案、当前任务和教师复核输出屏幕、短句语音、机器人动作及是否需要"
            "教师接管。动作执行后的学生反应再次进入状态估计，形成感知、决策、动作和反馈循环。",
            "本课三名学生的建议如下：\n" + "\n".join(rows),
            "所有动作遵循低刺激、无主动接触、最小必要干预和教师在环原则。证据不足时不自动靠近、不连续呼叫、"
            "不使用闪烁强光或突然大声；低风险动作以保持位置、慢速转向屏幕、轻微点头和单步视觉提示为主。需要"
            "降低难度、暂停任务、改变距离或通知照护者时必须由教师确认。后续可通过WebSocket或ROS2 Mock发布"
            "结构化动作，并在MuJoCo或Isaac Sim中验证距离、速度和安全约束。",
        ],
    )


def _next_lesson_section(course: dict[str, Any]) -> dict[str, str]:
    plans = [
        f"{student['display_name']}：" + "；".join(student["next_lesson_actions"])
        for student in course["student_results"]
    ]
    return _section(
        "next_lesson",
        "十一、下一课实施计划、观察指标与学校协作事项",
        [
            "下一课不建议同时修改全部目标。教师可为每名学生选择一个最需要巩固的目标、一个已经具备优势的成功"
            "任务和一种准备逐步撤除的提示。课前明确材料、任务口令、等待时间和允许的提示等级；课中只记录有明确"
            "机会的表现；课后复核少量关键片段，并把正确性、独立程度、重复一致性和迁移写入个体档案。",
            "个体计划如下：\n" + "\n".join(plans),
            "学校需要确认课程名称与类型、官方教案要求、考核标准、三名学生固定座位与匿名编号，并安排熟悉学生"
            "的教师完成关键片段复核。研发侧负责视频切片、状态窗口、报告生成、标注界面、数据库和动作接口。跨课"
            "比较至少需要多节同类任务；只有任务要求和复核口径相对一致时，才能讨论独立完成增加、提示减少、表现"
            "稳定或迁移改善。",
        ],
    )


def _build_appendix(
    course: dict[str, Any], target_chars: int, sections: list[dict[str, str]]
) -> list[dict[str, str]]:
    if len(_join_sections(sections)) >= target_chars:
        return []
    entries = []
    cycle = 0
    while len(_join_sections(sections) + "\n".join(entries)) < target_chars:
        for student in course["student_results"]:
            for objective in student["mastery"]["objectives"]:
                focus = [
                    "任务机会记录",
                    "教师提示撤除",
                    "不同材料迁移",
                    "回答正确性抽检",
                    "低回应后的恢复",
                ][cycle % 5]
                entries.append(
                    f"{student['display_name']}—{objective['label']}—{focus}：下一课至少安排"
                    f"{objective['opportunities']}次可辨认机会，记录任务材料、首次等待时间、答案或操作结果、提示等级、"
                    "提示后的反应和是否在新材料中重复出现。"
                    f"本次初评{objective['score']}分，未观察{objective['unobserved']}次，正式比较前须完成教师抽检。"
                    "如果课堂没有提供该目标的清晰机会，则标记未观察，不把缺少证据改写为学生不会。"
                )
        cycle += 1
        if cycle >= 4:
            break
    content = (
        "以下工作单用于把长报告转化为可执行记录，不增加新的能力判断。每条记录都应链接到具体时间段或课堂任务。\n"
        + "\n".join(entries)
    )
    return [_section("evidence_appendix", "附录：下一课目标级证据采集工作单", [content])]


def _maybe_rewrite_with_llm(
    draft: str,
    context: dict[str, str],
    reviews: dict[str, dict[str, str]],
    aliases: dict[str, str],
) -> tuple[str, str, str]:
    status = report_writer_status()
    if not status["llm_configured"]:
        return draft, "evidence_template", "未配置LLM服务，已回退到本地证据模板。"
    base_url = os.environ["REHAB_REPORT_LLM_BASE_URL"].rstrip("/")
    endpoint = base_url if base_url.endswith("/chat/completions") else f"{base_url}/chat/completions"
    api_key = os.getenv("REHAB_REPORT_LLM_API_KEY", "").strip()
    anonymous_draft = draft
    for display_name, alias in aliases.items():
        anonymous_draft = anonymous_draft.replace(display_name, alias)
    anonymous_context = {**context, "confirmed_by": "已由校方确认"}
    request_body = {
        "model": os.environ["REHAB_REPORT_LLM_MODEL"],
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是辅读学校课堂教育支持报告编辑器。只能重组给定事实，不得补造观察、诊断、病因或学生能力"
                    "结论。保留数字、复核状态、证据不足和教师在环边界，输出中文约一千字并保留章节标题。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "course_context": anonymous_context,
                        "teacher_review_count": len(reviews),
                        "evidence_draft": anonymous_draft,
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        "temperature": 0.2,
        "max_tokens": 2400,
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(request_body, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            result = json.loads(response.read().decode("utf-8"))
        content = result["choices"][0]["message"]["content"].strip()
        if len(content) < 7000:
            return draft, "evidence_template", "LLM返回内容过短，已回退到本地证据模板。"
        for display_name, alias in aliases.items():
            content = content.replace(alias, display_name)
        return content, "llm_assisted", f"由{status['llm_model']}在匿名化结构证据范围内辅助整理。"
    except (KeyError, OSError, ValueError, urllib.error.URLError) as exc:
        return draft, "evidence_template", f"LLM调用失败，已回退到本地证据模板：{type(exc).__name__}。"
