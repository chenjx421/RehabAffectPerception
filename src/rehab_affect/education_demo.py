from __future__ import annotations

import json
from collections import Counter, defaultdict
from copy import deepcopy
from time import time
from typing import Any

import numpy as np

from .inputs import AudioChunk, CameraFrame, InputBatch, TaskBehavior
from .pipeline import RehabAffectPipeline
from .schema import RobotContext


DEMO_SOURCE_NOTE = (
    "当前 Demo 使用公开课堂视频风格的匿名模拟切片，不包含真实学生图像、姓名或声音。"
    "取得校方授权数据后，可把这里的切片输入替换为真实抽帧、ASR 和教师校准标签。"
)


STATE_LABELS_ZH = {
    "engaged": "参与",
    "neutral": "平稳",
    "confused": "困惑",
    "fatigued": "疲劳",
    "frustrated": "挫败",
    "refusing": "抗拒",
    "pain_risk": "不适风险",
    "low_attention": "注意力下降",
    "needs_help": "需要帮助",
}


ACTION_LABELS_ZH = {
    "continue_and_encourage": "继续任务并正向反馈",
    "continue_current_plan": "保持当前节奏",
    "regain_attention": "低刺激拉回注意力",
    "repeat_instruction_slowly": "放慢并重复指令",
    "reduce_task_load_and_offer_break": "降低任务负荷并询问是否休息",
    "pause_and_reduce_pressure": "暂停催促并降低压力",
    "pause_and_request_consent": "暂停并询问意愿",
    "offer_help": "主动询问是否需要帮助",
    "stop_and_check_pain_risk": "立即暂停并通知老师确认",
}


KNOWLEDGE_BASE = {
    "low_attention": {
        "reasons": [
            "当前任务等待时间变长，学生可能暂时脱离任务线索。",
            "视线偏离任务材料，说明注意对象已经从屏幕/教师转移。",
            "如果环境噪声或旁人动作增加，注意力下降更可能与外部刺激相关。",
        ],
        "guidance": [
            "屏幕高亮当前要看的物品，避免突然大声提醒。",
            "AI 助教用一句短指令拉回：先看这里，再点这一个。",
            "连续两次未回到任务时，把提醒推送给老师。",
        ],
    },
    "confused": {
        "reasons": [
            "学生重复等待或选择错误，可能没有理解当前指令。",
            "教师话语和屏幕任务之间的信息量过大，学生难以完成映射。",
            "学生出现“我不会/不知道”等表达时，应优先视为需要简化说明。",
        ],
        "guidance": [
            "把指令拆成一个动作：先找语文书。",
            "减少屏幕选项数量，只保留当前步骤相关物品。",
            "保留老师介入入口，但先让系统给一次低压力提示。",
        ],
    },
    "frustrated": {
        "reasons": [
            "连续失败后仍要求继续，会增加抗拒或情绪波动概率。",
            "语音音量升高、动作急促和错误次数上升同时出现，说明任务压力过高。",
            "如果学生表达“不想做”，系统不能继续追问或强迫。",
        ],
        "guidance": [
            "暂停计时和评分，避免把失败感继续放大。",
            "提供二选一：换简单任务，或休息半分钟。",
            "提醒老师关注，但不把学生公开标记为异常。",
        ],
    },
    "engaged": {
        "reasons": [
            "视线、操作和任务成功之间保持一致。",
            "学生能在短时间内回应指令，当前难度基本合适。",
        ],
        "guidance": [
            "保持当前任务节奏，给一句具体正反馈。",
            "下一步只小幅增加难度，不突然切换复杂规则。",
        ],
    },
    "needs_help": {
        "reasons": [
            "学生已经通过语言或行为表达需要帮助。",
            "多次重复说明后仍无法完成，继续让学生独立尝试的价值下降。",
        ],
        "guidance": [
            "AI 助教先确认：你需要老师帮忙吗？",
            "教师端弹出低优先级提示，标明学生卡住的步骤。",
            "如果同时出现不适线索，提升为立即确认。",
        ],
    },
    "fatigued": {
        "reasons": [
            "动作速度下降、回应变慢，可能是任务负荷过高。",
            "疲劳线索不等同于不配合，应优先降低负荷而不是批评。",
        ],
        "guidance": [
            "减少下一轮任务数量，允许短暂停顿。",
            "屏幕只保留一个清晰目标，等待学生重新回应。",
        ],
    },
}


DEMO_CLIPS: list[dict[str, Any]] = [
    {
        "clip_id": "bag_instruction_attention",
        "title": "听指令整理书包：注意力下降后拉回",
        "duration_s": 32,
        "class_context": "生活适应课，教师让学生把指定物品放入书包。",
        "target_problem": "学生能开始任务，但中途容易被旁边同学或环境吸引。",
        "persons": [
            {
                "person_id": "student_A",
                "display_name": "学生 A",
                "baseline": "能听懂一到两步指令，注意力维持时间较短。",
            }
        ],
        "frames": [
            {
                "t": 0,
                "person_id": "student_A",
                "scene": "小班教室，学生面前有书包、语文书、铅笔盒，教师在前方给出任务。",
                "activity": "教师发布任务：把语文书放进书包。",
                "teacher_action": "口头说明并指向桌面材料",
                "state_hint": "engaged",
                "attention_score": 0.82,
                "movement_speed": 0.42,
                "response_delay_sec": 0.9,
                "task_success": True,
                "instruction_repeated": 0,
                "recent_failure_count": 0,
                "speech": [
                    {
                        "speaker_id": "teacher_01",
                        "speaker_role": "teacher",
                        "text": "请把语文书放进书包。",
                        "confidence": 0.86,
                    }
                ],
                "visual_evidence": ["正视桌面材料", "手部开始接近书本", "坐姿稳定"],
            },
            {
                "t": 8,
                "person_id": "student_A",
                "scene": "同一教室，旁边学生移动，桌面材料仍在可见范围内。",
                "activity": "学生短暂停止操作，视线偏向侧方。",
                "teacher_action": "教师继续讲解下一名学生的任务",
                "state_hint": "low_attention",
                "attention_score": 0.34,
                "movement_speed": 0.18,
                "response_delay_sec": 4.3,
                "task_success": False,
                "instruction_repeated": 1,
                "recent_failure_count": 0,
                "speech": [],
                "visual_evidence": ["头部转向侧方", "手部停止操作", "任务物品未移动"],
            },
            {
                "t": 17,
                "person_id": "student_A",
                "scene": "屏幕显示书包和语文书，教师提醒学生看当前物品。",
                "activity": "AI 助教准备把屏幕目标高亮，并把指令拆成一步。",
                "teacher_action": "教师观察到学生停顿，但未立刻打断全班",
                "state_hint": "confused",
                "attention_score": 0.48,
                "movement_speed": 0.21,
                "response_delay_sec": 5.1,
                "task_success": False,
                "instruction_repeated": 2,
                "recent_failure_count": 1,
                "request_text": "不知道",
                "speech": [
                    {
                        "speaker_id": "student_A_voice",
                        "speaker_role": "student",
                        "person_id": "student_A",
                        "text": "不知道。",
                        "confidence": 0.72,
                    }
                ],
                "visual_evidence": ["看向屏幕但未选择", "手部悬停", "眉部收紧"],
            },
            {
                "t": 27,
                "person_id": "student_A",
                "scene": "屏幕只高亮语文书，其他物品变灰。",
                "activity": "学生按一步指令完成放入书包。",
                "teacher_action": "教师继续主课，系统记录学生完成恢复",
                "state_hint": "engaged",
                "attention_score": 0.76,
                "movement_speed": 0.36,
                "response_delay_sec": 1.3,
                "task_success": True,
                "instruction_repeated": 0,
                "recent_failure_count": 0,
                "speech": [
                    {
                        "speaker_id": "teacher_01",
                        "speaker_role": "teacher",
                        "text": "对，就是这一本。",
                        "confidence": 0.81,
                    }
                ],
                "visual_evidence": ["视线回到书本", "完成操作", "身体前倾参与"],
            },
        ],
    },
    {
        "clip_id": "rule_choice_confusion",
        "title": "课堂规则选择：学生听不懂题意",
        "duration_s": 28,
        "class_context": "班会/生活规则课，学生需要判断课堂行为是否合适。",
        "target_problem": "学生不是不愿意做，而是无法把语言规则映射到图片选项。",
        "persons": [
            {
                "person_id": "student_B",
                "display_name": "学生 B",
                "baseline": "愿意互动，但抽象规则理解较弱。",
            }
        ],
        "frames": [
            {
                "t": 0,
                "person_id": "student_B",
                "scene": "大屏显示两张图片：举手发言、离座乱跑。",
                "activity": "教师问：上课想说话时应该怎么做？",
                "teacher_action": "提问并等待学生选择",
                "state_hint": "engaged",
                "attention_score": 0.79,
                "movement_speed": 0.31,
                "response_delay_sec": 1.2,
                "task_success": None,
                "instruction_repeated": 0,
                "recent_failure_count": 0,
                "speech": [
                    {
                        "speaker_id": "teacher_01",
                        "speaker_role": "teacher",
                        "text": "上课想说话，要先做什么？",
                        "confidence": 0.83,
                    }
                ],
                "visual_evidence": ["看向大屏", "保持坐姿", "准备点击"],
            },
            {
                "t": 9,
                "person_id": "student_B",
                "scene": "学生点到错误图片，教师没有立刻否定。",
                "activity": "系统检测到错误选择和停顿。",
                "teacher_action": "教师等待系统给出简化提示",
                "state_hint": "confused",
                "attention_score": 0.53,
                "movement_speed": 0.19,
                "response_delay_sec": 5.4,
                "task_success": False,
                "instruction_repeated": 1,
                "recent_failure_count": 1,
                "speech": [
                    {
                        "speaker_id": "student_B_voice",
                        "speaker_role": "student",
                        "person_id": "student_B",
                        "text": "这个吗？",
                        "confidence": 0.75,
                    }
                ],
                "visual_evidence": ["反复看两个选项", "点击后看向教师", "动作变慢"],
            },
            {
                "t": 18,
                "person_id": "student_B",
                "scene": "屏幕改为单一动作提示：先举手。",
                "activity": "AI 助教用一步图片提示降低理解难度。",
                "teacher_action": "教师观察学生是否能独立修正",
                "state_hint": "needs_help",
                "attention_score": 0.58,
                "movement_speed": 0.20,
                "response_delay_sec": 5.8,
                "task_success": False,
                "instruction_repeated": 2,
                "recent_failure_count": 2,
                "request_text": "帮我",
                "speech": [
                    {
                        "speaker_id": "student_B_voice",
                        "speaker_role": "student",
                        "person_id": "student_B",
                        "text": "老师帮我。",
                        "confidence": 0.77,
                    }
                ],
                "visual_evidence": ["看向教师", "等待提示", "未继续乱点"],
            },
        ],
    },
    {
        "clip_id": "noisy_classroom_speech_uncertain",
        "title": "噪声课堂：语音不可靠时以视觉和任务行为为主",
        "duration_s": 35,
        "class_context": "多人小组互动，背景有同学说话和桌椅声音。",
        "target_problem": "校园环境中 ASR 容易不稳定，系统需要明确语音置信度并避免误判。",
        "persons": [
            {
                "person_id": "student_C",
                "display_name": "学生 C",
                "baseline": "容易因连续失败出现烦躁，需要降低任务压力。",
            }
        ],
        "frames": [
            {
                "t": 0,
                "person_id": "student_C",
                "scene": "四人桌面任务，教师在侧方巡视。",
                "activity": "学生尝试按颜色整理积木。",
                "teacher_action": "教师给出统一口令",
                "state_hint": "engaged",
                "attention_score": 0.74,
                "movement_speed": 0.38,
                "response_delay_sec": 1.4,
                "task_success": True,
                "instruction_repeated": 0,
                "recent_failure_count": 0,
                "speech": [
                    {
                        "speaker_id": "teacher_01",
                        "speaker_role": "teacher",
                        "text": "先找红色。",
                        "confidence": 0.68,
                    },
                    {
                        "speaker_id": "unknown_02",
                        "speaker_role": "background",
                        "text": "我也要这个。",
                        "confidence": 0.41,
                    },
                ],
                "visual_evidence": ["看向积木", "开始分类", "动作速度正常"],
                "audio_reliability": "medium",
            },
            {
                "t": 12,
                "person_id": "student_C",
                "scene": "背景说话声增加，学生连续两次拿错颜色。",
                "activity": "任务失败次数上升，学生动作变急。",
                "teacher_action": "教师正在帮助另一名学生",
                "state_hint": "frustrated",
                "attention_score": 0.46,
                "movement_speed": 0.57,
                "response_delay_sec": 3.8,
                "task_success": False,
                "instruction_repeated": 1,
                "recent_failure_count": 3,
                "request_text": "不要了",
                "speech": [
                    {
                        "speaker_id": "student_C_voice",
                        "speaker_role": "student",
                        "person_id": "student_C",
                        "text": "不要了。",
                        "confidence": 0.56,
                    },
                    {
                        "speaker_id": "unknown_03",
                        "speaker_role": "background",
                        "text": "不是这个。",
                        "confidence": 0.38,
                    },
                ],
                "visual_evidence": ["动作急促", "推开一个积木", "连续错误"],
                "audio_reliability": "low",
            },
            {
                "t": 25,
                "person_id": "student_C",
                "scene": "屏幕只保留红色积木示例，其他颜色暂时隐藏。",
                "activity": "系统降低任务压力，教师端收到状态提示。",
                "teacher_action": "教师准备靠近确认是否需要暂停",
                "state_hint": "fatigued",
                "attention_score": 0.51,
                "movement_speed": 0.13,
                "response_delay_sec": 4.4,
                "task_success": False,
                "instruction_repeated": 1,
                "recent_failure_count": 1,
                "speech": [],
                "visual_evidence": ["动作速度明显下降", "低头停顿", "不再主动选择"],
                "audio_reliability": "low",
            },
        ],
    },
]


def list_education_clips() -> list[dict[str, Any]]:
    return [
        {
            "clip_id": clip["clip_id"],
            "title": clip["title"],
            "duration_s": clip["duration_s"],
            "class_context": clip["class_context"],
            "target_problem": clip["target_problem"],
        }
        for clip in DEMO_CLIPS
    ]


def load_education_clip(clip_id: str) -> dict[str, Any]:
    for clip in DEMO_CLIPS:
        if clip["clip_id"] == clip_id:
            return deepcopy(clip)
    raise KeyError(f"Education demo clip not found: {clip_id}")


def run_education_demo(clip_id: str = "bag_instruction_attention") -> dict[str, Any]:
    clip = load_education_clip(clip_id)
    pipelines: dict[str, RehabAffectPipeline] = {}
    timeline: list[dict[str, Any]] = []
    person_events: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for frame in clip["frames"]:
        person_id = str(frame["person_id"])
        if person_id not in pipelines:
            pipelines[person_id] = RehabAffectPipeline(person_id=person_id, smooth_window=1)

        batch = _input_batch_from_frame(frame)
        context = _robot_context_from_frame(frame, clip)
        result = pipelines[person_id].process_batch(batch, robot_context=context)
        state = result.human_state.state
        robot_action = result.robot_action.to_dict()
        knowledge = _knowledge_for_state(state)
        reasons = _rank_reasons(state, frame)
        robot_action_payload = {
            **robot_action,
            "action_label_zh": ACTION_LABELS_ZH.get(
                robot_action["action_id"],
                robot_action["action_id"],
            ),
            "demo_carrier_now": _current_carrier_action(robot_action["action_id"]),
            "future_robot_embodiment": _future_robot_action(robot_action),
        }
        event = {
            "timestamp_s": frame["t"],
            "timestamp_label": _format_timestamp(frame["t"]),
            "person_id": person_id,
            "display_name": _display_name(clip, person_id),
            "clip_activity": frame["activity"],
            "recognition_heads": {
                "video_head_1_person_state": _video_head_1(frame, result.human_state.to_dict()),
                "video_head_2_scene_activity": _video_head_2(frame),
                "speech_head": _speech_head(frame),
            },
            "correlation_analysis": _correlation_analysis(frame, result.human_state.to_dict()),
            "likely_reasons": reasons,
            "knowledge_guidance": knowledge["guidance"],
            "human_state": result.human_state.to_dict(),
            "robot_action": robot_action_payload,
            "robot_execution": _robot_execution_plan(
                robot_action_payload,
                frame,
                result.human_state.to_dict(),
            ),
            "raw_signals": [signal.__dict__ for signal in result.raw_signals],
            "smoothed_signals": [signal.__dict__ for signal in result.smoothed_signals],
        }
        timeline.append(event)
        person_events[person_id].append(event)

    per_person = {
        person_id: _person_summary(clip, person_id, events)
        for person_id, events in person_events.items()
    }
    final_event = _default_focus_event(timeline)
    return {
        "demo_name": "辅读学校 AI 助教课堂状态 Demo",
        "source_note": DEMO_SOURCE_NOTE,
        "clip": {
            "clip_id": clip["clip_id"],
            "title": clip["title"],
            "duration_s": clip["duration_s"],
            "class_context": clip["class_context"],
            "target_problem": clip["target_problem"],
            "persons": clip["persons"],
        },
        "pipeline_overview": [
            "视频识别头1：抽帧后识别人脸/头部朝向/姿态/任务动作，输出人物状态。",
            "视频识别头2：总结课堂场景和正在进行的活动。",
            "语音识别头：按时间线整理说话人和文本，同时标注校园噪声下的不确定性。",
            "时间线融合：把状态、场景、语音、任务表现对齐到同一时间轴。",
            "人物知识库：按学生保存状态变化、可能原因和有效引导方案。",
            "动作输出：生成 teacher_dashboard、student_screen 和 robot_action JSON。",
        ],
        "timeline": timeline,
        "per_person_store": per_person,
        "final_output": {
            "human_state": final_event.get("human_state"),
            "robot_action": final_event.get("robot_action"),
            "robot_execution": final_event.get("robot_execution"),
            "teacher_dashboard": _teacher_dashboard(final_event),
            "student_screen": _student_screen(final_event),
        },
        "review_boundary": {
            "not_medical_diagnosis": True,
            "teacher_final_decision": True,
            "privacy": "演示数据不含真实学生隐私；真实数据需学校和家长授权后仅做脱敏研发。",
            "speech_caveat": "语音头在噪声环境下只作为辅助证据，不能单独触发高风险结论。",
        },
    }


def render_education_demo_html() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>辅读学校 AI 助教 Demo</title>
  <style>
    :root {
      --bg: #eef2f6;
      --panel: #ffffff;
      --ink: #18201c;
      --muted: #66706a;
      --line: #dce3dc;
      --blue: #2563eb;
      --green: #168348;
      --amber: #a15f10;
      --red: #c24135;
      --purple: #6b4eff;
      --soft: #eef4ee;
      --blue-soft: #edf4ff;
      --green-soft: #edf7f1;
      --amber-soft: #fff7ed;
      --shadow: 0 12px 34px rgba(30, 41, 59, 0.08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: "Segoe UI", Arial, sans-serif;
      line-height: 1.42;
    }
    header {
      min-height: 84px;
      padding: 16px 22px;
      background: rgba(255, 255, 255, 0.96);
      border-bottom: 1px solid var(--line);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
      flex-wrap: wrap;
      position: sticky;
      top: 0;
      z-index: 10;
    }
    h1 {
      margin: 0;
      font-size: 26px;
      letter-spacing: 0;
    }
    .sub {
      color: var(--muted);
      font-size: 13px;
      margin-top: 4px;
    }
    .toolbar {
      display: flex;
      gap: 8px;
      align-items: center;
      flex-wrap: wrap;
    }
    select, button {
      min-height: 40px;
      border: 1px solid var(--line);
      border-radius: 7px;
      background: #fff;
      color: var(--ink);
      padding: 8px 11px;
      font: inherit;
      font-size: 13px;
    }
    button {
      cursor: pointer;
      font-weight: 700;
      transition: transform 0.12s ease, border-color 0.12s ease, background 0.12s ease;
    }
    button:hover {
      transform: translateY(-1px);
      border-color: #b8c4d2;
    }
    select {
      min-width: 315px;
      max-width: 100%;
    }
    .primary {
      background: var(--blue);
      color: #fff;
      border-color: var(--blue);
    }
    .status-strip {
      padding: 12px 22px 0;
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
    }
    .status-item {
      background: rgba(255, 255, 255, 0.82);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px 12px;
      min-height: 58px;
      display: grid;
      align-content: center;
      gap: 2px;
    }
    .status-k {
      color: var(--muted);
      font-size: 11px;
      font-weight: 800;
    }
    .status-v {
      font-size: 16px;
      font-weight: 850;
      overflow-wrap: anywhere;
    }
    main {
      padding: 14px 22px 22px;
      display: grid;
      grid-template-columns: minmax(310px, 0.95fr) minmax(420px, 1.25fr) minmax(360px, 1.05fr);
      gap: 14px;
    }
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
      min-width: 0;
      box-shadow: var(--shadow);
    }
    .head {
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
      font-weight: 800;
      background: #fbfcfb;
    }
    .body {
      padding: 14px;
      display: grid;
      gap: 12px;
    }
    .video {
      background: #f9fbff;
      border: 1px solid var(--line);
      border-radius: 8px;
      min-height: 260px;
      overflow: hidden;
    }
    .video svg {
      width: 100%;
      min-height: 260px;
      display: block;
    }
    .grid2 {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
    }
    .metric, .head-card, .event, .person, .output-card {
      border: 1px solid var(--line);
      border-radius: 7px;
      background: #fff;
      padding: 10px;
      min-width: 0;
    }
    .metric {
      min-height: 72px;
      background: #fbfcfb;
    }
    .label {
      color: var(--muted);
      font-size: 11px;
      margin-bottom: 3px;
      font-weight: 750;
    }
    .value {
      font-weight: 800;
      overflow-wrap: anywhere;
      font-size: 17px;
    }
    .heads {
      display: grid;
      gap: 8px;
    }
    .head-card {
      display: grid;
      gap: 5px;
      border-left: 4px solid var(--line);
    }
    .head-card.vision { border-left-color: var(--blue); }
    .head-card.scene-head { border-left-color: var(--green); }
    .head-card.speech-head { border-left-color: var(--amber); }
    .timeline {
      display: grid;
      gap: 8px;
      max-height: 500px;
      overflow: auto;
      padding-right: 2px;
    }
    .event {
      cursor: pointer;
      border-left: 4px solid var(--line);
      transition: background 0.12s ease, transform 0.12s ease, border-color 0.12s ease;
    }
    .event:hover {
      transform: translateY(-1px);
      background: #fbfdff;
    }
    .event.active {
      border-left-color: var(--blue);
      background: var(--blue-soft);
    }
    .event-title {
      font-weight: 800;
      display: flex;
      justify-content: space-between;
      gap: 8px;
      align-items: center;
      margin-bottom: 5px;
    }
    .pill {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border-radius: 999px;
      padding: 3px 8px;
      font-size: 11px;
      color: #fff;
      background: var(--green);
      white-space: nowrap;
    }
    .pill.warn { background: var(--amber); }
    .pill.risk { background: var(--red); }
    .pill.info { background: var(--blue); }
    .small {
      font-size: 12px;
      color: var(--muted);
    }
    .person {
      background: var(--green-soft);
      border-color: #c9dfd0;
    }
    .action-card {
      background: var(--blue-soft);
      border-color: #bfd7ff;
    }
    .robot-card {
      background: #f6f2ff;
      border-color: #d8ccff;
      position: relative;
    }
    .robot-card::before {
      content: "";
      position: absolute;
      left: 0;
      top: 10px;
      bottom: 10px;
      width: 4px;
      background: var(--purple);
      border-radius: 0 4px 4px 0;
    }
    .robot-card .value {
      color: #3f2bb5;
      font-size: 18px;
    }
    .reason-list {
      margin: 0;
      padding-left: 18px;
      display: grid;
      gap: 5px;
      color: var(--ink);
      font-size: 13px;
    }
    .tabs {
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
    }
    .tab {
      background: #fbfcfb;
    }
    .tab.active {
      border-color: var(--blue);
      color: var(--blue);
      background: #f6f9ff;
    }
    pre {
      margin: 0;
      max-height: 420px;
      overflow: auto;
      background: #101812;
      color: #e8f5eb;
      border-radius: 7px;
      padding: 11px;
      font-size: 12px;
      line-height: 1.45;
      border: 1px solid #1f3024;
    }
    .source {
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 10px 11px;
      background: var(--soft);
      color: #425047;
      font-size: 12px;
    }
    @media (max-width: 1160px) {
      .status-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      main { grid-template-columns: 1fr; }
      .timeline { max-height: 360px; }
    }
    @media (max-width: 680px) {
      header { padding: 14px; }
      .status-strip { padding: 10px 14px 0; grid-template-columns: 1fr; }
      main { padding: 12px 14px 18px; }
      select { min-width: 0; width: 100%; }
      .toolbar { width: 100%; }
      .toolbar button { flex: 1; }
    }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>辅读学校 AI 助教 Demo</h1>
      <div class="sub">多模态切片分析 -> 时间线融合 -> 人物状态库 -> 教师端/学生端/机器人动作输出</div>
    </div>
    <div class="toolbar">
      <select id="clip"></select>
      <button class="primary" id="run">运行 Demo</button>
      <button id="download">导出 JSON</button>
    </div>
  </header>
  <div class="status-strip">
    <div class="status-item">
      <div class="status-k">输入形态</div>
      <div class="status-v">匿名课堂切片</div>
    </div>
    <div class="status-item">
      <div class="status-k">识别头</div>
      <div class="status-v">人物状态 / 场景 / 语音</div>
    </div>
    <div class="status-item">
      <div class="status-k">当前闭环</div>
      <div class="status-v">状态 -> 原因 -> 动作</div>
    </div>
    <div class="status-item">
      <div class="status-k">机器人接口</div>
      <div class="status-v">WebSocket / ROS2-ready</div>
    </div>
  </div>
  <main>
    <section class="panel">
      <div class="head">
        <span>切片输入与识别头</span>
        <span class="pill info" id="status">ready</span>
      </div>
      <div class="body">
        <div class="source" id="sourceNote"></div>
        <div class="video" id="video"></div>
        <div class="grid2">
          <div class="metric">
            <div class="label">当前学生</div>
            <div class="value" id="person">n/a</div>
          </div>
          <div class="metric">
            <div class="label">当前时间</div>
            <div class="value" id="timestamp">n/a</div>
          </div>
          <div class="metric">
            <div class="label">注意力分数</div>
            <div class="value" id="attention">n/a</div>
          </div>
          <div class="metric">
            <div class="label">语音可靠性</div>
            <div class="value" id="speechReliability">n/a</div>
          </div>
        </div>
        <div class="heads">
          <div class="head-card vision">
            <div class="label">视频识别头 1：人物状态</div>
            <div class="value" id="head1">n/a</div>
            <div class="small" id="head1Evidence"></div>
          </div>
          <div class="head-card scene-head">
            <div class="label">视频识别头 2：场景活动</div>
            <div class="value" id="head2">n/a</div>
            <div class="small" id="head2Scene"></div>
          </div>
          <div class="head-card speech-head">
            <div class="label">语音识别头：说话人时间线</div>
            <div class="value" id="speechHead">n/a</div>
            <div class="small" id="speechText"></div>
          </div>
        </div>
      </div>
    </section>

    <section class="panel">
      <div class="head">
        <span>时间线总结与状态关联</span>
        <span class="small" id="clipTitle">n/a</span>
      </div>
      <div class="body">
        <div class="source" id="targetProblem"></div>
        <div class="timeline" id="timeline"></div>
      </div>
    </section>

    <section class="panel">
      <div class="head">
        <span>人物状态库与动作输出</span>
        <span class="pill" id="statePill">n/a</span>
      </div>
      <div class="body">
        <div class="person" id="personStore"></div>
        <div class="output-card action-card">
          <div class="label">可能原因</div>
          <ul class="reason-list" id="reasons"></ul>
        </div>
        <div class="output-card robot-card">
          <div class="label">引导方案</div>
          <ul class="reason-list" id="guidance"></ul>
        </div>
        <div class="output-card">
          <div class="label">最终动作落点</div>
          <div class="value" id="actionLabel">n/a</div>
          <div class="small" id="carrierAction"></div>
        </div>
        <div class="output-card">
          <div class="label">机器人执行层预览</div>
          <div class="value" id="robotSpeech">n/a</div>
          <div class="small" id="robotExec"></div>
        </div>
        <div class="tabs">
          <button class="tab active" data-tab="final">final_output</button>
          <button class="tab" data-tab="event">current_event</button>
          <button class="tab" data-tab="robot">robot_executor</button>
          <button class="tab" data-tab="report">full_report</button>
        </div>
        <pre id="json">运行 Demo 后显示 JSON。</pre>
      </div>
    </section>
  </main>
  <script>
    const el = (id) => document.getElementById(id);
    const stateLabels = {
      engaged: '参与',
      neutral: '平稳',
      confused: '困惑',
      fatigued: '疲劳',
      frustrated: '挫败',
      refusing: '抗拒',
      pain_risk: '不适风险',
      low_attention: '注意力下降',
      needs_help: '需要帮助'
    };
    let report = null;
    let currentIndex = 0;
    let activeTab = 'final';

    async function api(path) {
      const response = await fetch(path);
      const data = await response.json();
      if (!response.ok || data.error) throw new Error(data.error || response.statusText);
      return data;
    }

    async function init() {
      const payload = await api('/api/education_clips');
      el('clip').innerHTML = payload.clips.map((clip) => `<option value="${clip.clip_id}">${clip.title}</option>`).join('');
      await runDemo();
    }

    async function runDemo() {
      el('status').textContent = 'running';
      report = await api('/api/education_demo?clip_id=' + encodeURIComponent(el('clip').value));
      currentIndex = defaultFocusIndex(report.timeline);
      el('sourceNote').textContent = report.source_note;
      el('clipTitle').textContent = report.clip.title;
      el('targetProblem').textContent = report.clip.target_problem;
      renderTimeline();
      renderCurrent();
      el('status').textContent = 'ready';
    }

    function renderTimeline() {
      el('timeline').innerHTML = report.timeline.map((event, index) => {
        const state = event.human_state?.state;
        return `<div class="event ${index === currentIndex ? 'active' : ''}" data-index="${index}">
          <div class="event-title">
            <span>${event.timestamp_label} ${event.display_name}</span>
            <span class="pill ${classForState(state)}">${stateLabels[state] || state}</span>
          </div>
          <div class="small">${event.clip_activity}</div>
          <div class="small">${event.correlation_analysis}</div>
        </div>`;
      }).join('');
      document.querySelectorAll('.event').forEach((node) => {
        node.addEventListener('click', () => {
          currentIndex = Number(node.dataset.index);
          renderTimeline();
          renderCurrent();
        });
      });
    }

    function renderCurrent() {
      const event = report.timeline[currentIndex];
      const head1 = event.recognition_heads.video_head_1_person_state;
      const head2 = event.recognition_heads.video_head_2_scene_activity;
      const speech = event.recognition_heads.speech_head;
      const state = event.human_state?.state;
      const person = report.per_person_store[event.person_id];

      el('person').textContent = event.display_name;
      el('timestamp').textContent = event.timestamp_label;
      el('attention').textContent = head1.attention_score.toFixed(2);
      el('speechReliability').textContent = speech.audio_reliability;
      el('head1').textContent = `${stateLabels[head1.state] || head1.state} / ${(head1.confidence * 100).toFixed(0)}%`;
      el('head1Evidence').textContent = head1.evidence.join('、') || '无';
      el('head2').textContent = head2.activity;
      el('head2Scene').textContent = head2.scene;
      el('speechHead').textContent = `${speech.utterance_count} 条语音 / ${speech.speaker_count} 个说话人`;
      el('speechText').textContent = speech.timeline.map((item) => `${item.speaker_role}:${item.text}`).join(' / ') || '无学生语音';
      el('statePill').textContent = stateLabels[state] || state;
      el('statePill').className = `pill ${classForState(state)}`;
      el('personStore').innerHTML = `
        <div class="label">人物状态库</div>
        <div class="value">${person.display_name}: ${stateLabels[person.last_state] || person.last_state}</div>
        <div class="small">状态路径：${person.state_path.map((s) => stateLabels[s] || s).join(' -> ')}</div>
        <div class="small">有效引导：${person.suggested_next_step}</div>
      `;
      renderList('reasons', event.likely_reasons);
      renderList('guidance', event.knowledge_guidance);
      el('actionLabel').textContent = event.robot_action.action_label_zh;
      el('carrierAction').textContent = `${event.robot_action.demo_carrier_now}；${event.robot_action.future_robot_embodiment}`;
      const exec = event.robot_execution || {};
      el('robotSpeech').textContent = exec.speech?.text || 'n/a';
      el('robotExec').textContent = `屏幕：${exec.student_screen?.prompt || 'n/a'}；表情/灯光：${exec.embodied_display?.expression || 'n/a'}；动作：${exec.motion?.summary || 'n/a'}；教师端：${exec.teacher_alert?.notify ? '提醒' : '记录'}`;
      renderVideo(event);
      renderJson();
    }

    function renderVideo(event) {
      const state = event.human_state?.state;
      const color = stateColor(state);
      const gaze = event.recognition_heads.video_head_1_person_state.attention_score > 0.65 ? '看向任务' : '视线偏离/停顿';
      const action = event.robot_action.action_label_zh;
      const cue = event.robot_execution?.speech?.text || action;
      el('video').innerHTML = `<svg viewBox="0 0 640 360" role="img" aria-label="classroom clip">
        <rect x="18" y="18" width="604" height="324" rx="8" fill="#fbfcff" stroke="#dce3dc"/>
        <rect x="38" y="34" width="232" height="82" rx="7" fill="#e8eef8" stroke="#c9d6ef"/>
        <text x="56" y="66" font-size="18" font-weight="700" fill="#24324a">教师 / 大屏</text>
        <text x="56" y="92" font-size="13" fill="#526179">${escapeText(event.clip_activity).slice(0, 18)}</text>
        <rect x="366" y="38" width="226" height="96" rx="7" fill="#eef4ee" stroke="#d0ded0"/>
        <text x="386" y="72" font-size="16" font-weight="700" fill="#243226">任务材料</text>
        <text x="386" y="100" font-size="13" fill="#526157">${escapeText(event.clip_activity).slice(0, 24)}</text>
        <rect x="92" y="212" width="450" height="72" rx="8" fill="#ece6d7" stroke="#d6c8a8"/>
        <rect x="370" y="160" width="218" height="62" rx="8" fill="#ffffff" stroke="#bfd7ff"/>
        <text x="388" y="184" font-size="13" font-weight="700" fill="#2563eb">AI 助教提示</text>
        <text x="388" y="206" font-size="13" fill="#243226">${escapeText(cue).slice(0, 19)}</text>
        <circle cx="322" cy="186" r="42" fill="${color}" opacity="0.95"/>
        <circle cx="305" cy="176" r="5" fill="#fff"/>
        <circle cx="338" cy="176" r="5" fill="#fff"/>
        <path d="M300 202 Q322 214 344 202" fill="none" stroke="#fff" stroke-width="5" stroke-linecap="round"/>
        <rect x="282" y="230" width="80" height="52" rx="14" fill="${color}" opacity="0.75"/>
        <line x1="250" y1="248" x2="192" y2="226" stroke="${color}" stroke-width="10" stroke-linecap="round"/>
        <line x1="392" y1="248" x2="460" y2="224" stroke="${color}" stroke-width="10" stroke-linecap="round"/>
        <text x="44" y="316" font-size="14" font-weight="700" fill="#18201c">${escapeText(event.timestamp_label)} ${escapeText(event.display_name)}：${escapeText(gaze)}</text>
        <text x="44" y="336" font-size="13" fill="#526157">${escapeText(action)}</text>
      </svg>`;
    }

    function renderList(id, items) {
      el(id).innerHTML = items.map((item) => `<li>${escapeText(item)}</li>`).join('');
    }

    function renderJson() {
      let data = selectedFinalOutput();
      if (activeTab === 'event') data = report.timeline[currentIndex];
      if (activeTab === 'robot') data = report.timeline[currentIndex].robot_execution;
      if (activeTab === 'report') data = report;
      el('json').textContent = JSON.stringify(data, null, 2);
    }

    function selectedFinalOutput() {
      const event = report.timeline[currentIndex];
      return {
        human_state: event.human_state,
        robot_action: event.robot_action,
        robot_execution: event.robot_execution,
        teacher_dashboard: {
          person_id: event.person_id,
          state: event.human_state.state,
          state_label_zh: stateLabels[event.human_state.state] || event.human_state.state,
          confidence: event.human_state.confidence,
          prompt: event.robot_action.action_label_zh,
          reason: event.likely_reasons[0] || '',
          handoff_required: event.robot_action.handoff_required
        },
        student_screen: {
          screen_action: event.robot_action.demo_carrier_now,
          low_stimulation: true,
          no_public_labeling: true
        }
      };
    }

    function defaultFocusIndex(events) {
      const index = events.findIndex((event) => !['engaged', 'neutral'].includes(event.human_state?.state));
      return index >= 0 ? index : Math.max(0, events.length - 1);
    }

    function classForState(state) {
      if (state === 'pain_risk' || state === 'needs_help' || state === 'refusing') return 'risk';
      if (state === 'confused' || state === 'fatigued' || state === 'frustrated' || state === 'low_attention') return 'warn';
      return '';
    }

    function stateColor(state) {
      return {
        engaged: '#168348',
        neutral: '#607069',
        confused: '#a15f10',
        fatigued: '#7c6d55',
        frustrated: '#c24135',
        refusing: '#c24135',
        pain_risk: '#c24135',
        low_attention: '#2563eb',
        needs_help: '#6b4eff'
      }[state] || '#607069';
    }

    function escapeText(value) {
      return String(value ?? '').replace(/[&<>"']/g, (char) => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
      }[char]));
    }

    function downloadJson() {
      if (!report) return;
      const blob = new Blob([JSON.stringify(report, null, 2)], {type: 'application/json'});
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${report.clip.clip_id}_education_demo_report.json`;
      a.click();
      URL.revokeObjectURL(url);
    }

    el('run').addEventListener('click', runDemo);
    el('clip').addEventListener('change', runDemo);
    el('download').addEventListener('click', downloadJson);
    document.querySelectorAll('.tab').forEach((button) => {
      button.addEventListener('click', () => {
        activeTab = button.dataset.tab;
        document.querySelectorAll('.tab').forEach((tab) => tab.classList.toggle('active', tab === button));
        renderJson();
      });
    });
    init().catch((error) => {
      el('status').textContent = 'error';
      el('json').textContent = error.stack || String(error);
    });
  </script>
</body>
</html>"""


def _input_batch_from_frame(frame: dict[str, Any]) -> InputBatch:
    timestamp = time() + float(frame["t"])
    state_hint = str(frame["state_hint"])
    attention = float(frame["attention_score"])
    movement_speed = float(frame["movement_speed"])
    transcript = _student_transcript(frame)
    audio_state = _audio_state_from_frame(frame)
    camera = CameraFrame(
        timestamp=timestamp,
        image=np.full((120, 160, 3), _brightness_for_state(state_hint), dtype=np.uint8),
        metadata={
            "state_hint": state_hint,
            "confidence": _state_confidence(frame),
            "face_detected": True,
            "attention_score": attention,
            "visual_evidence": frame.get("visual_evidence", []),
        },
    )
    audio = AudioChunk(
        timestamp=timestamp,
        samples=_mock_audio_samples(frame),
        sample_rate=16000,
        metadata={
            "state_hint": audio_state,
            "confidence": _speech_confidence(frame),
            "transcript": transcript,
            "speaker_timeline": frame.get("speech", []),
            "audio_reliability": frame.get("audio_reliability", "high" if frame.get("speech") else "none"),
        },
    )
    task = TaskBehavior(
        instruction_repeated=int(frame.get("instruction_repeated", 0)),
        response_delay_sec=float(frame.get("response_delay_sec", 0.0)),
        recent_failure_count=int(frame.get("recent_failure_count", 0)),
        request_text=frame.get("request_text") or transcript,
        task_success=frame.get("task_success"),
        task_stage=str(frame.get("activity", "")),
        metadata={
            "state_hint": state_hint,
            "confidence": _task_confidence(frame),
            "scene_activity": frame["activity"],
            "teacher_action": frame["teacher_action"],
        },
    )
    return InputBatch(
        timestamp=timestamp,
        camera=camera,
        audio=audio,
        pose_features={
            "state_hint": state_hint,
            "confidence": _pose_confidence(frame),
            "attention_score": attention,
            "movement_speed": movement_speed,
        },
        task_behavior=task,
    )


def _robot_context_from_frame(frame: dict[str, Any], clip: dict[str, Any]) -> RobotContext:
    return RobotContext(
        task_id=clip["clip_id"],
        task_stage=frame["activity"],
        robot_distance_m=1.2,
        obstacle_distance_m=1.4,
        is_robot_moving=False,
        task_difficulty="normal",
        visible_objects=["书包", "书本", "屏幕", "桌面材料"],
        metadata={
            "class_context": clip["class_context"],
            "scene": frame["scene"],
            "teacher_action": frame["teacher_action"],
        },
    )


def _video_head_1(frame: dict[str, Any], human_state: dict[str, Any]) -> dict[str, Any]:
    return {
        "state": human_state["state"],
        "state_label_zh": STATE_LABELS_ZH.get(human_state["state"], human_state["state"]),
        "confidence": float(human_state["confidence"]),
        "attention_score": float(frame["attention_score"]),
        "movement_speed": float(frame["movement_speed"]),
        "evidence": frame.get("visual_evidence", []),
        "output_target": "当前画面中人物的课堂状态",
    }


def _video_head_2(frame: dict[str, Any]) -> dict[str, Any]:
    return {
        "scene": frame["scene"],
        "activity": frame["activity"],
        "teacher_action": frame["teacher_action"],
        "output_target": "当前画面场景与课堂活动总结",
    }


def _speech_head(frame: dict[str, Any]) -> dict[str, Any]:
    speech = frame.get("speech", [])
    speakers = {item.get("speaker_id", "unknown") for item in speech}
    return {
        "audio_reliability": frame.get("audio_reliability", "high" if speech else "none"),
        "utterance_count": len(speech),
        "speaker_count": len(speakers),
        "timeline": [
            {
                "speaker_id": item.get("speaker_id"),
                "speaker_role": item.get("speaker_role"),
                "person_id": item.get("person_id"),
                "text": item.get("text"),
                "confidence": item.get("confidence"),
            }
            for item in speech
        ],
        "caveat": "校园真实环境噪声较大，语音头只作为辅助证据。",
    }


def _correlation_analysis(frame: dict[str, Any], human_state: dict[str, Any]) -> str:
    state = human_state["state"]
    if state == "low_attention":
        return "视线偏离和任务停顿同时出现，当前状态更可能与课堂环境刺激相关。"
    if state == "confused":
        return "重复指令、回应延迟和求助表达对齐，说明问题集中在指令理解。"
    if state == "frustrated":
        return "连续失败、动作急促和低置信语音共同出现，判断应以视觉和任务行为为主。"
    if state == "needs_help":
        return "学生出现求助语言，同时任务仍未完成，建议进入教师辅助链路。"
    if state == "fatigued":
        return "动作速度下降和回应变慢同步出现，建议降低任务负荷。"
    return "视觉、任务行为和课堂活动保持一致，当前可以继续任务。"


def _person_summary(
    clip: dict[str, Any],
    person_id: str,
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    states = [event["human_state"]["state"] for event in events]
    counts = Counter(states)
    last = events[-1]
    return {
        "person_id": person_id,
        "display_name": _display_name(clip, person_id),
        "baseline": _baseline(clip, person_id),
        "last_state": last["human_state"]["state"],
        "last_state_label_zh": STATE_LABELS_ZH.get(last["human_state"]["state"], last["human_state"]["state"]),
        "state_path": states,
        "state_counts": dict(counts),
        "risk_events": [
            {
                "timestamp_label": event["timestamp_label"],
                "state": event["human_state"]["state"],
                "action": event["robot_action"]["action_label_zh"],
            }
            for event in events
            if event["human_state"]["risk_level"] in {"medium", "high", "critical"}
        ],
        "suggested_next_step": _suggested_next_step(last),
    }


def _knowledge_for_state(state: str) -> dict[str, Any]:
    return KNOWLEDGE_BASE.get(state, KNOWLEDGE_BASE["engaged"])


def _rank_reasons(state: str, frame: dict[str, Any]) -> list[str]:
    reasons = list(_knowledge_for_state(state)["reasons"])
    if frame.get("recent_failure_count", 0) >= 2:
        reasons.insert(0, "近期失败次数升高，继续原难度可能扩大挫败感。")
    if frame.get("audio_reliability") == "low":
        reasons.insert(0, "语音置信度偏低，本次判断主要参考视觉和任务行为。")
    return reasons[:3]


def _teacher_dashboard(event: dict[str, Any]) -> dict[str, Any]:
    if not event:
        return {}
    action = event["robot_action"]
    return {
        "person_id": event["person_id"],
        "state": event["human_state"]["state"],
        "state_label_zh": STATE_LABELS_ZH.get(event["human_state"]["state"], event["human_state"]["state"]),
        "confidence": event["human_state"]["confidence"],
        "prompt": action["action_label_zh"],
        "reason": event["likely_reasons"][0] if event["likely_reasons"] else "",
        "handoff_required": action["handoff_required"],
    }


def _default_focus_event(timeline: list[dict[str, Any]]) -> dict[str, Any]:
    for event in timeline:
        if event["human_state"]["state"] not in {"engaged", "neutral"}:
            return event
    return timeline[-1] if timeline else {}


def _student_screen(event: dict[str, Any]) -> dict[str, Any]:
    if not event:
        return {}
    action_id = event["robot_action"]["action_id"]
    mapping = {
        "regain_attention": "高亮当前物品，只显示一步指令。",
        "repeat_instruction_slowly": "把任务拆成一步，并播放慢速提示。",
        "offer_help": "显示“需要老师帮忙吗？”两个大按钮。",
        "pause_and_reduce_pressure": "停止计时，显示休息或简单任务选择。",
        "reduce_task_load_and_offer_break": "减少屏幕选项，允许短暂停顿。",
        "continue_and_encourage": "显示具体正反馈并进入下一步。",
    }
    return {
        "screen_action": mapping.get(action_id, "保持当前任务界面。"),
        "low_stimulation": True,
        "no_public_labeling": True,
    }


def _current_carrier_action(action_id: str) -> str:
    mapping = {
        "regain_attention": "学生端屏幕高亮目标，教师端记录一次注意力拉回",
        "repeat_instruction_slowly": "学生端放慢指令并减少选项",
        "offer_help": "学生端显示求助确认，教师端收到提示",
        "pause_and_reduce_pressure": "学生端暂停计时，教师端提示任务压力偏高",
        "reduce_task_load_and_offer_break": "学生端降低题量，教师端记录疲劳风险",
        "continue_and_encourage": "学生端给具体正反馈，继续下一步",
    }
    return mapping.get(action_id, "教师端保持观察，学生端维持当前任务")


def _future_robot_action(action: dict[str, Any]) -> str:
    return (
        f"机器人层：speech={action['speech_action']}，motion={action['motion_policy']}，"
        f"task={action['task_adjustment']}，safety={action['safety_action']}"
    )


def _robot_execution_plan(
    action: dict[str, Any],
    frame: dict[str, Any],
    human_state: dict[str, Any],
) -> dict[str, Any]:
    action_id = str(action["action_id"])
    state = str(human_state["state"])
    speech_text = {
        "regain_attention": "我们先看这里，只做这一步。",
        "repeat_instruction_slowly": "没关系，我们慢一点。先找这一个。",
        "offer_help": "你需要老师帮忙吗？可以点一下。",
        "pause_and_reduce_pressure": "先停一下，你可以休息或换简单一点。",
        "reduce_task_load_and_offer_break": "我们少做一点，先休息十秒也可以。",
        "continue_and_encourage": "做得对，我们继续下一步。",
        "pause_and_request_consent": "如果你不想继续，可以选择暂停。",
        "stop_and_check_pain_risk": "先停下，我请老师来看一下。",
    }.get(action_id, "我们继续保持现在的节奏。")
    screen_prompt = {
        "regain_attention": "高亮当前目标：先看这一项",
        "repeat_instruction_slowly": "一步指令：先找当前物品",
        "offer_help": "两个按钮：需要帮助 / 再试一次",
        "pause_and_reduce_pressure": "暂停计时：休息一下 / 换简单任务",
        "reduce_task_load_and_offer_break": "减少选项：只保留当前步骤",
        "continue_and_encourage": "正反馈：完成当前步骤",
        "pause_and_request_consent": "选择界面：继续 / 暂停",
        "stop_and_check_pain_risk": "暂停界面：等待老师确认",
    }.get(action_id, "保持当前任务界面")
    expression = {
        "low_attention": "soft_focus",
        "confused": "thinking",
        "needs_help": "supportive",
        "frustrated": "calm",
        "fatigued": "gentle",
        "engaged": "encouraging",
        "refusing": "respectful",
        "pain_risk": "concerned",
    }.get(state, "neutral")
    light = {
        "soft_focus": "#2563EB",
        "thinking": "#A15F10",
        "supportive": "#6B4EFF",
        "calm": "#168348",
        "gentle": "#607069",
        "encouraging": "#168348",
        "respectful": "#607069",
        "concerned": "#C24135",
        "neutral": "#607069",
    }[expression]
    motion_policy = str(action["motion_policy"])
    motion = {
        "policy": motion_policy,
        "base": "stop" if motion_policy == "stop_motion" else "hold_position",
        "head_yaw_deg": 0,
        "head_pitch_deg": -6 if action_id in {"regain_attention", "repeat_instruction_slowly"} else 0,
        "speed_scale": 0.0 if motion_policy in {"stop_motion", "hold_position"} else 0.35,
        "summary": _motion_summary(motion_policy, action_id),
    }
    teacher_alert = _teacher_alert_for_action(action, frame, human_state)
    return {
        "executor": "school_robot_executor_mock_v1",
        "target_device": "student_screen_plus_optional_desktop_robot",
        "input_contract": "robot_action JSON",
        "speech": {
            "text": speech_text,
            "volume": "low",
            "speed": "slow" if action_id in {"repeat_instruction_slowly", "regain_attention"} else "normal",
            "interruptible": True,
        },
        "student_screen": {
            "prompt": screen_prompt,
            "highlight_target": action_id in {"regain_attention", "repeat_instruction_slowly"},
            "reduce_choices": action_id
            in {"repeat_instruction_slowly", "reduce_task_load_and_offer_break"},
            "no_public_labeling": True,
        },
        "embodied_display": {
            "expression": expression,
            "led_color": light,
            "animation": "slow_blink" if state != "engaged" else "small_nod",
        },
        "motion": motion,
        "teacher_alert": teacher_alert,
        "safety": {
            "low_stimulation": True,
            "no_touch": True,
            "teacher_can_override": True,
            "handoff_required": bool(action.get("handoff_required")),
        },
        "integration": {
            "websocket_event": "robot_action",
            "ros2_topic": "/ai_tutor/robot_action",
            "sdk_adapter": "replace mock executor with robot SDK or ROS2 node",
        },
    }


def _motion_summary(motion_policy: str, action_id: str) -> str:
    if motion_policy == "stop_motion":
        return "停止底盘/机械臂动作，等待老师确认。"
    if action_id == "regain_attention":
        return "保持距离，头部轻微朝向屏幕目标，不靠近学生。"
    if action_id == "repeat_instruction_slowly":
        return "保持当前位置，配合屏幕一步提示。"
    if action_id == "continue_and_encourage":
        return "可做轻微点头动画，不新增复杂动作。"
    return "保持当前位置，优先使用屏幕和语音引导。"


def _teacher_alert_for_action(
    action: dict[str, Any],
    frame: dict[str, Any],
    human_state: dict[str, Any],
) -> dict[str, Any]:
    action_id = str(action["action_id"])
    priority = str(action.get("priority", "low"))
    should_notify = priority in {"medium", "high", "critical"} or bool(action.get("handoff_required"))
    return {
        "notify": should_notify,
        "priority": priority,
        "message": (
            f"{STATE_LABELS_ZH.get(human_state['state'], human_state['state'])}: "
            f"{ACTION_LABELS_ZH.get(action_id, action_id)}"
        ),
        "evidence": frame.get("visual_evidence", [])[:2],
    }


def _suggested_next_step(event: dict[str, Any]) -> str:
    action_id = event["robot_action"]["action_id"]
    mapping = {
        "regain_attention": "先使用低刺激视觉提示，观察 10 秒内是否回到任务。",
        "repeat_instruction_slowly": "把下一步拆成单动作，并保留教师辅助入口。",
        "offer_help": "请教师确认学生卡住的位置，再决定是否手把手示范。",
        "pause_and_reduce_pressure": "暂停原任务，给学生一个可选择的低难度任务。",
        "reduce_task_load_and_offer_break": "降低下一轮题量，避免连续消耗。",
        "continue_and_encourage": "保持当前难度，只做小幅推进。",
    }
    return mapping.get(action_id, "继续观察并记录状态变化。")


def _display_name(clip: dict[str, Any], person_id: str) -> str:
    for person in clip.get("persons", []):
        if person["person_id"] == person_id:
            return person.get("display_name", person_id)
    return person_id


def _baseline(clip: dict[str, Any], person_id: str) -> str:
    for person in clip.get("persons", []):
        if person["person_id"] == person_id:
            return person.get("baseline", "")
    return ""


def _student_transcript(frame: dict[str, Any]) -> str:
    return " ".join(
        str(item.get("text", ""))
        for item in frame.get("speech", [])
        if item.get("speaker_role") == "student"
    )


def _audio_state_from_frame(frame: dict[str, Any]) -> str:
    transcript = _student_transcript(frame)
    if frame.get("audio_reliability") == "low" and not transcript:
        return "neutral"
    if frame.get("request_text"):
        if "帮" in str(frame["request_text"]):
            return "needs_help"
        if "不要" in str(frame["request_text"]):
            return "frustrated"
    return str(frame["state_hint"]) if transcript else "neutral"


def _brightness_for_state(state: str) -> int:
    return {
        "engaged": 205,
        "low_attention": 150,
        "confused": 165,
        "needs_help": 155,
        "frustrated": 142,
        "fatigued": 132,
    }.get(state, 170)


def _mock_audio_samples(frame: dict[str, Any]) -> np.ndarray:
    sample_rate = 16000
    duration = 0.45
    t = np.linspace(0.0, duration, int(sample_rate * duration), endpoint=False)
    speech_count = len(frame.get("speech", []))
    reliability = frame.get("audio_reliability", "high" if speech_count else "none")
    amplitude = {"none": 0.004, "low": 0.10, "medium": 0.055, "high": 0.04}.get(reliability, 0.04)
    tone = amplitude * np.sin(2.0 * np.pi * 230.0 * t)
    return np.asarray(tone, dtype=np.float32)


def _state_confidence(frame: dict[str, Any]) -> float:
    state = str(frame["state_hint"])
    base = {
        "engaged": 0.74,
        "low_attention": 0.71,
        "confused": 0.73,
        "needs_help": 0.78,
        "frustrated": 0.76,
        "fatigued": 0.68,
    }.get(state, 0.62)
    if frame.get("audio_reliability") == "low":
        base -= 0.04
    return max(0.35, min(0.92, base))


def _pose_confidence(frame: dict[str, Any]) -> float:
    return max(0.45, min(0.86, _state_confidence(frame) - 0.05))


def _task_confidence(frame: dict[str, Any]) -> float:
    if frame.get("task_success") is True:
        return 0.70
    if frame.get("response_delay_sec", 0) >= 5 or frame.get("recent_failure_count", 0) >= 2:
        return 0.78
    return 0.62


def _speech_confidence(frame: dict[str, Any]) -> float:
    speech = frame.get("speech", [])
    if not speech:
        return 0.30
    student_items = [item for item in speech if item.get("speaker_role") == "student"]
    if not student_items:
        return 0.35
    return float(max(item.get("confidence", 0.45) for item in student_items))


def _format_timestamp(seconds: int | float) -> str:
    seconds = int(seconds)
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def _ensure_jsonable(payload: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(payload, ensure_ascii=False))


def run_education_demo_json(clip_id: str = "bag_instruction_attention") -> dict[str, Any]:
    return _ensure_jsonable(run_education_demo(clip_id))
