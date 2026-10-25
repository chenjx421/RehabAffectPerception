from __future__ import annotations

import json
import re
import subprocess
from collections import Counter
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any

import numpy as np

from .seewo_long_report import load_teacher_reviews, report_writer_status
from .assessment_rubric import RUBRIC_VERSION, build_assessment_summary, build_longitudinal_series


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "data" / "processed" / "seewo_demo2" / "session_config.json"
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "seewo_demo2"
ANALYSIS_PATH = OUTPUT_DIR / "analysis.json"
UI_VERSION = "seewo_demo2_v9_legacy_boundary"

STATE_ZH = {
    "engaged": "稳定参与",
    "active_response": "出现回应或操作",
    "low_response": "回应信号较低",
    "not_observed": "未观察到有效作答机会",
    "uncertain": "证据不足",
}


def load_seewo_demo2(force: bool = False) -> dict[str, Any]:
    if not force and ANALYSIS_PATH.exists():
        try:
            cached = json.loads(ANALYSIS_PATH.read_text(encoding="utf-8"))
            if cached.get("ui_version") == UI_VERSION and len(cached.get("courses", [])) == 2:
                cached["saved_reviews"] = load_teacher_reviews()
                cached["report_writer"] = report_writer_status()
                return cached
        except (OSError, json.JSONDecodeError):
            pass
    return build_seewo_demo2()


def build_seewo_demo2() -> dict[str, Any]:
    config = _load_config()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    students = config["students"]
    courses = [_analyze_course(course, students) for course in config["courses"]]
    payload = {
        "ui_version": UI_VERSION,
        "demo_name": "辅读学校三学生课堂学习成效分析 Demo2",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "privacy_level": config.get("privacy_level", "sensitive_private_local_only"),
        "class_context": config.get("class_context", {}),
        "students": [_public_student(student) for student in students],
        "courses": courses,
        "saved_reviews": load_teacher_reviews(),
        "report_writer": report_writer_status(),
        "review_boundary": {
            "mastery": "掌握度只对明确出现的学习机会进行评价；没有机会、遮挡或说话人不确定时标记U。",
            "identity": "身份由校方截图和固定座位确认，不使用障碍类型或外貌推断身份。",
            "audio": "远场课堂音频用于识别教学阶段和互动机会，无法可靠归属时不强行绑定到学生。",
            "medical": "IEP仅用于个体化支持和安全约束，不输出医学诊断结论。",
            "teacher_review": "当前正确性和提示等级为演示性初评，正式报告必须由教师复核关键片段。",
        },
    }
    ANALYSIS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def _load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Demo2 local session config is missing: {CONFIG_PATH}")
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _public_student(student: dict[str, Any]) -> dict[str, Any]:
    return {
        "student_id": student["student_id"],
        "display_name": student["display_name"],
        "seat_label": student["seat_label"],
        "identity_status": "校方已确认",
        "education_profile": student.get("education_profile", {}),
    }


def _analyze_course(course: dict[str, Any], students: list[dict[str, Any]]) -> dict[str, Any]:
    meta, windows, measured = _measure_video(course, students)
    assets = _write_course_assets(course, students, meta)
    fit = _build_course_fit(course, students)
    student_results = [
        _build_student_result(course, student, windows, fit["students_by_id"][student["student_id"]], assets)
        for student in students
    ]
    teacher_effectiveness = _build_teacher_effectiveness(course, student_results, windows)
    report_summary = _build_report_summary(course, meta, student_results, windows)
    course_analysis = _build_course_analysis(
        course,
        meta,
        student_results,
        teacher_effectiveness,
    )
    class_score = round(mean(item["mastery"]["overall_score"] for item in student_results))
    class_participation = round(mean(item["state_summary"]["participation_score"] for item in student_results))
    assessment_standard = {
        "rubric_version": RUBRIC_VERSION,
        "scale": {"min": 0, "max": 10, "pass_score": 6, "pass_label": "及格"},
        "dimensions": {
            key: {"weight": value["weight"], "weight_percent": value["weight_percent"]}
            for key, value in student_results[0]["mastery"]["assessment"]["dimensions"].items()
        },
        "note": "系统初评只服务于教学复盘；教师复核后才作为正式记录。",
    }
    return {
        "course_id": course["course_id"],
        "course_name": course["course_name"],
        "subject": course["subject"],
        "lesson_standard": course["lesson_standard"],
        "school_assessment_standard": course["school_assessment_standard"],
        "individual_targets": course.get("individual_targets", {}),
        "objectives": course["objectives"],
        "video_meta": meta,
        "measurement_status": measured,
        "assets": assets,
        "course_fit": {key: value for key, value in fit.items() if key != "students_by_id"},
        "timeline": windows,
        "student_results": student_results,
        "assessment_standard": assessment_standard,
        "teacher_effectiveness": teacher_effectiveness,
        "report_summary": report_summary,
        "course_analysis": course_analysis,
        "teacher_review_spec": _teacher_review_spec(),
        "data_source": {
            "student_video": Path(course["student_video"]).name,
            "teacher_video": Path(course.get("teacher_video", "")).name,
            "lesson_plan": Path(course.get("lesson_plan", "")).name,
            "audio_status": "课堂远场音频已随视频接入；说话人不确定时不绑定到具体学生。",
            "privacy_note": "原始视频和个体资料仅在本地授权目录处理，页面不输出身份证号、联系方式或住址。",
        },
        "class_summary": {
            "preliminary_mastery_score": class_score,
            "participation_score": class_participation,
            "review_required": True,
            "summary": (
                f"本节课对三名重点学生的初步掌握度均值为{class_score}分，课堂参与信号均值为"
                f"{class_participation}分。两项指标分别呈现，不把安静或动作多少直接等同于学会。"
            ),
        },
    }


def _measure_video(
    course: dict[str, Any],
    students: list[dict[str, Any]],
    *,
    step_sec: int = 5,
    window_sec: int = 30,
) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    video_path = Path(course["student_video"])
    try:
        cv2 = _import_cv2()
    except RuntimeError:
        return _fallback_meta(), _fallback_windows(students), "cached_or_synthetic_without_opencv"
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return _fallback_meta(), _fallback_windows(students), "video_missing_using_explainable_fallback"

    fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1920)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1080)
    duration_sec = frame_count / fps if frame_count else 0.0
    meta = {
        "file_name": video_path.name,
        "width": width,
        "height": height,
        "fps": round(fps, 3),
        "duration_sec": round(duration_sec, 2),
        "duration_min": round(duration_sec / 60, 2),
        "window_sec": window_sec,
    }
    cap.release()

    samples = _decode_keyframe_samples(video_path, students, width, height, cv2)
    if not samples:
        samples = _seek_samples(video_path, students, duration_sec, cv2, step_sec=max(15, step_sec))

    _normalize_motion(samples, students)
    windows = _aggregate_windows(samples, students, duration_sec, window_sec)
    return meta, windows, "measured_from_student_camera_keyframes"


def _decode_keyframe_samples(
    video_path: Path,
    students: list[dict[str, Any]],
    source_width: int,
    source_height: int,
    cv2: Any,
) -> list[dict[str, Any]]:
    """Decode I-frames once, then evaluate all student ROIs on each frame."""
    try:
        import imageio_ffmpeg

        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError):
        return []

    decode_width, decode_height = 640, 360
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "info",
        "-skip_frame",
        "nokey",
        "-i",
        str(video_path),
        "-an",
        "-vf",
        f"scale={decode_width}:{decode_height},format=gray,showinfo",
        "-fps_mode",
        "passthrough",
        "-f",
        "rawvideo",
        "pipe:1",
    ]
    try:
        result = subprocess.run(command, capture_output=True, check=True, timeout=45)
    except (OSError, subprocess.SubprocessError):
        return []

    frame_size = decode_width * decode_height
    frame_count = len(result.stdout) // frame_size
    timestamps = [float(value) for value in re.findall(rb"pts_time:([0-9.]+)", result.stderr)]
    usable = min(frame_count, len(timestamps))
    if usable == 0:
        return []
    frames = np.frombuffer(result.stdout[: usable * frame_size], dtype=np.uint8).reshape(
        usable, decode_height, decode_width
    )
    scale_x = decode_width / max(1, source_width)
    scale_y = decode_height / max(1, source_height)
    scaled_students = []
    for student in students:
        roi = student["roi"]
        scaled_students.append(
            {
                **student,
                "roi": {
                    "x": round(roi["x"] * scale_x),
                    "y": round(roi["y"] * scale_y),
                    "w": max(1, round(roi["w"] * scale_x)),
                    "h": max(1, round(roi["h"] * scale_y)),
                },
            }
        )
    return _frames_to_samples(frames, timestamps[:usable], scaled_students, cv2)


def _seek_samples(
    video_path: Path,
    students: list[dict[str, Any]],
    duration_sec: float,
    cv2: Any,
    *,
    step_sec: int,
) -> list[dict[str, Any]]:
    cap = cv2.VideoCapture(str(video_path))
    frames = []
    timestamps = []
    for sec in range(0, max(1, int(duration_sec)), step_sec):
        cap.set(cv2.CAP_PROP_POS_MSEC, sec * 1000.0)
        ok, frame = cap.read()
        if not ok:
            continue
        frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
        timestamps.append(float(sec))
    cap.release()
    return _frames_to_samples(frames, timestamps, students, cv2)


def _frames_to_samples(
    frames: Any,
    timestamps: list[float],
    students: list[dict[str, Any]],
    cv2: Any,
) -> list[dict[str, Any]]:
    previous: dict[str, np.ndarray] = {}
    samples: list[dict[str, Any]] = []
    for gray, sec in zip(frames, timestamps):
        record: dict[str, Any] = {"sec": round(sec, 3), "students": {}}
        for student in students:
            student_id = student["student_id"]
            crop = _crop(gray, student["roi"])
            if crop.size == 0:
                record["students"][student_id] = {"motion_raw": 0.0, "quality": 0.0}
                continue
            small = cv2.resize(crop, (96, 96), interpolation=cv2.INTER_AREA)
            prior = previous.get(student_id)
            motion = float(np.mean(cv2.absdiff(small, prior)) / 255.0) if prior is not None else 0.0
            previous[student_id] = small
            blur = float(cv2.Laplacian(small, cv2.CV_64F).var())
            brightness = float(np.mean(small))
            quality = _clip01((blur / 120.0) * 0.62 + (1.0 if 35 <= brightness <= 225 else 0.35) * 0.38)
            record["students"][student_id] = {
                "motion_raw": motion,
                "quality": quality,
                "blur": blur,
                "brightness": brightness,
            }
        samples.append(record)
    return samples


def _normalize_motion(samples: list[dict[str, Any]], students: list[dict[str, Any]]) -> None:
    for student in students:
        student_id = student["student_id"]
        values = [sample["students"][student_id]["motion_raw"] for sample in samples]
        if not values:
            continue
        low = float(np.percentile(values, 10))
        high = float(np.percentile(values, 90))
        scale = max(1e-6, high - low)
        for sample in samples:
            raw = sample["students"][student_id]["motion_raw"]
            sample["students"][student_id]["motion"] = _clip01((raw - low) / scale)


def _aggregate_windows(
    samples: list[dict[str, Any]],
    students: list[dict[str, Any]],
    duration_sec: float,
    window_sec: int,
) -> list[dict[str, Any]]:
    total_windows = max(1, int(np.ceil(duration_sec / window_sec)))
    output = []
    for index in range(total_windows):
        start = index * window_sec
        end = min(duration_sec, start + window_sec)
        group = [sample for sample in samples if start <= sample["sec"] < end]
        lesson_phase = _lesson_phase(start, duration_sec)
        teacher_activity = _teacher_activity(start, duration_sec)
        response_expected = lesson_phase in {"引导练习", "个别练习与迁移", "总结与回顾"}
        student_states = {}
        for student in students:
            student_id = student["student_id"]
            rows = [sample["students"][student_id] for sample in group]
            motion = mean(row.get("motion", 0.0) for row in rows) if rows else 0.0
            quality = mean(row.get("quality", 0.0) for row in rows) if rows else 0.0
            if quality < 0.38:
                state = "uncertain"
            elif motion >= 0.66:
                state = "active_response"
            elif motion < 0.24 and not response_expected:
                state = "not_observed"
            elif motion < 0.24:
                state = "low_response"
            else:
                state = "engaged"
            confidence = _clip01(0.42 + quality * 0.38 + abs(motion - 0.45) * 0.18)
            student_states[student_id] = {
                "state": state,
                "state_zh": STATE_ZH[state],
                "confidence": round(confidence, 3),
                "motion_signal": round(motion, 3),
                "evidence_quality": round(quality, 3),
                "evidence": _state_evidence(state),
            }
            student_states[student_id].update(
                _state_contract(
                    student_id=student_id,
                    state=state,
                    start_sec=start,
                    confidence=confidence,
                    motion=motion,
                    quality=quality,
                )
            )
        output.append(
            {
                "window_id": f"window_{index:03d}",
                "start_sec": start,
                "end_sec": round(end, 1),
                "time_label": f"{_format_time(start)}-{_format_time(end)}",
                "lesson_phase": lesson_phase,
                "teacher_activity": teacher_activity,
                "students": student_states,
            }
        )
    return output


def _fallback_meta() -> dict[str, Any]:
    return {
        "file_name": "cached_demo.mp4",
        "width": 1920,
        "height": 1080,
        "fps": 30.0,
        "duration_sec": 2160.0,
        "duration_min": 36.0,
        "window_sec": 30,
    }


def _fallback_windows(students: list[dict[str, Any]]) -> list[dict[str, Any]]:
    windows = []
    states = [
        "engaged",
        "active_response",
        "not_observed",
        "low_response",
        "engaged",
        "uncertain",
    ]
    for index in range(18):
        student_states = {}
        for offset, student in enumerate(students):
            state = states[(index + offset) % len(states)]
            student_states[student["student_id"]] = {
                "state": state,
                "state_zh": STATE_ZH[state],
                "confidence": 0.66,
                "motion_signal": 0.42,
                "evidence_quality": 0.65,
                "evidence": _state_evidence(state),
            }
            student_states[student["student_id"]].update(
                _state_contract(
                    student_id=student["student_id"],
                    state=state,
                    start_sec=index * 120,
                    confidence=0.66,
                    motion=0.42,
                    quality=0.65,
                )
            )
        windows.append(
            {
                "window_id": f"window_{index:03d}",
                "start_sec": index * 120,
                "end_sec": (index + 1) * 120,
                "time_label": f"{_format_time(index * 120)}-{_format_time((index + 1) * 120)}",
                "lesson_phase": _lesson_phase(index * 120, 2160),
                "teacher_activity": _teacher_activity(index * 120, 2160),
                "students": student_states,
            }
        )
    return windows


def _state_contract(
    *,
    student_id: str,
    state: str,
    start_sec: float,
    confidence: float,
    motion: float,
    quality: float,
) -> dict[str, Any]:
    if state in {"engaged", "active_response"}:
        action = {
            "action_id": "continue_current_task",
            "screen": "保持当前教学画面，不额外弹窗",
            "speech": "保持当前节奏，完成后给予具体反馈。",
            "robot_motion": "idle_or_soft_nod",
            "teacher_alert": False,
        }
        interpretation = "当前存在课堂参与或回应线索，继续观察任务完成情况。"
        risk_level = "low"
    elif state == "low_response":
        action = {
            "action_id": "regain_attention_low_stimulation",
            "screen": "轻微高亮当前一步或目标物",
            "speech": "我们先看这里，只完成这一步。",
            "robot_motion": "slow_turn_to_screen",
            "teacher_alert": False,
        }
        interpretation = "回应线索较低，可能是在等待、思考或暂时脱离任务，应结合课堂提问确认。"
        risk_level = "low"
    elif state == "not_observed":
        action = {
            "action_id": "hold_until_learning_opportunity",
            "screen": "保持当前内容，不追加提示",
            "speech": "当前没有明确作答机会，继续等待课堂任务。",
            "robot_motion": "no_motion",
            "teacher_alert": False,
        }
        interpretation = "该时段没有识别到明确作答机会或有效回应证据，不计入不会、拒绝或退步。"
        risk_level = "low"
    else:
        action = {
            "action_id": "defer_to_teacher_observation",
            "screen": "不触发学生端强提示",
            "speech": "该片段证据不足，建议人工确认。",
            "robot_motion": "no_motion",
            "teacher_alert": True,
        }
        interpretation = "画面质量、遮挡或可见行为不足，系统不自动判断学生状态。"
        risk_level = "review"
    evidence = _state_evidence(state)
    return {
        "features": {
            "target_motion": round(motion, 3),
            "context_motion": None,
            "adult_interference": None,
            "audio_activity": None,
        },
        "quality": {
            "video_quality": "medium" if quality >= 0.5 else "limited",
            "evidence_quality": round(quality, 3),
            "audio_available": True,
        },
        "interpretation": interpretation,
        "recommended_action": action,
        "human_state_json": {
            "timestamp_sec": round(start_sec, 1),
            "person_id": student_id,
            "state": state,
            "confidence": round(confidence, 3),
            "evidence": evidence,
            "risk_level": risk_level,
            "handoff_required": bool(action["teacher_alert"]),
            "recommended_robot_action": action["action_id"],
        },
    }


def _build_course_fit(course: dict[str, Any], students: list[dict[str, Any]]) -> dict[str, Any]:
    rows = []
    by_id = {}
    for student in students:
        student_id = student["student_id"]
        previous = course["previous_mastery"][student_id]
        weighted_gap = sum(
            max(0.0, objective["required_level"] - previous.get(objective["objective_id"], 1))
            * objective["weight"]
            for objective in course["objectives"]
        )
        fit_score = max(45, min(96, round(93 - weighted_gap * 28)))
        if fit_score >= 82:
            level = "适配"
            conclusion = "目标与上次表现基本匹配，可按计划实施并保留个体化提示。"
        elif fit_score >= 66:
            level = "需分层"
            conclusion = "总体目标可保留，但需要降低单次任务量并增加视觉或语言提示。"
        else:
            level = "需调整"
            conclusion = "目标跨度偏大，应拆分为更小步骤，并先保证可观察的成功机会。"
        weakest = min(
            course["objectives"],
            key=lambda objective: previous.get(objective["objective_id"], 1) - objective["required_level"],
        )
        strategies = student["education_profile"].get("effective_support", [])
        row = {
            "student_id": student_id,
            "display_name": student["display_name"],
            "fit_score": fit_score,
            "fit_level": level,
            "previous_average": round(mean(previous.values()), 2),
            "largest_gap_objective": weakest["label"],
            "conclusion": conclusion,
            "recommended_modifications": [
                f"将“{weakest['label']}”拆成可单独观察的一步任务。",
                strategies[0] if strategies else "使用短指令和视觉提示。",
                strategies[1] if len(strategies) > 1 else "每次提示后保留等待时间。",
            ],
        }
        rows.append(row)
        by_id[student_id] = row
    overall = round(mean(row["fit_score"] for row in rows))
    return {
        "overall_fit_score": overall,
        "overall_level": "适配" if overall >= 82 else "建议分层实施" if overall >= 66 else "建议修改课程目标",
        "students": rows,
        "students_by_id": by_id,
        "decision_note": "适配判断来自上次表现、IEP支持目标和本课要求之间的差距，不根据障碍名称直接降低目标。",
    }


def _build_student_result(
    course: dict[str, Any],
    student: dict[str, Any],
    windows: list[dict[str, Any]],
    fit: dict[str, Any],
    assets: dict[str, Any],
) -> dict[str, Any]:
    student_id = student["student_id"]
    states = [window["students"][student_id] for window in windows]
    counts = Counter(item["state"] for item in states)
    total = max(1, len(states))
    scorable_windows = max(1, total - counts["not_observed"])
    engaged_ratio = (counts["engaged"] + counts["active_response"]) / scorable_windows
    low_ratio = counts["low_response"] / scorable_windows
    uncertain_ratio = counts["uncertain"] / total
    not_observed_ratio = counts["not_observed"] / total
    quality = mean(item["evidence_quality"] for item in states)
    participation_score = round(_clip01(engaged_ratio * 0.82 + (1 - uncertain_ratio) * 0.18) * 100)
    prior = course["previous_mastery"][student_id]
    objective_rows = []
    behavior_adjustment = (participation_score - 65) / 100.0
    for index, objective in enumerate(course["objectives"]):
        prior_level = float(prior.get(objective["objective_id"], 1))
        provisional_level = max(1.0, min(4.0, prior_level + behavior_adjustment + (0.08 if index < 3 else 0.0)))
        opportunities = 4 if objective["weight"] >= 0.2 else 3
        observed = max(1, opportunities - (1 if uncertain_ratio > 0.18 else 0))
        independent = max(0, min(observed, round((provisional_level - 1) / 3 * observed)))
        prompted = max(0, observed - independent)
        score = round(provisional_level / 4 * 100)
        objective_rows.append(
            {
                "objective_id": objective["objective_id"],
                "label": objective["label"],
                "weight": objective["weight"],
                "previous_level": prior_level,
                "provisional_level": round(provisional_level, 1),
                "score": score,
                "score_10": round(score / 10, 1),
                "opportunities": opportunities,
                "observed": observed,
                "independent": independent,
                "prompted": prompted,
                "unobserved": opportunities - observed,
                "review_status": "待教师复核",
                "evidence_source": "课堂行为窗口、教案目标与既有教育评估；答案正确性需抽检片段确认。",
            }
        )
    overall = round(sum(row["score"] * row["weight"] for row in objective_rows))
    mastery_band = _mastery_band(overall)
    key_interactions = _select_key_interactions(windows, student_id)
    mastery = {
        "overall_score": overall,
        "band": mastery_band,
        "confidence": round(_clip01(quality * 0.62 + 0.18), 3),
        "review_status": "初评，待教师复核",
        "dimensions": {
            "accuracy": max(35, min(95, overall - 2)),
            "independence": max(30, min(95, round(mean(row["provisional_level"] for row in objective_rows) / 4 * 100))),
            "consistency": max(35, min(95, participation_score)),
            "transfer": objective_rows[-1]["score"],
        },
        "objectives": objective_rows,
    }
    # Compatibility: existing pages still consume 0--100 fields.  The shared
    # assessment contract is emitted alongside them on a 0--10 scale with a
    # fixed 6-point pass line.
    # Legacy heuristic scores and generated opportunity counts are demonstration
    # assets. They cannot be converted into validated classroom measurements.
    mastery["assessment"] = build_assessment_summary({}, source="旧版演示，非逐课教师测量")
    mastery["longitudinal"] = build_longitudinal_series([])
    state_summary = {
        "window_count": total,
        "participation_score": participation_score,
        "engaged_ratio": round(engaged_ratio, 3),
        "low_response_ratio": round(low_ratio, 3),
        "uncertain_ratio": round(uncertain_ratio, 3),
        "not_observed_ratio": round(not_observed_ratio, 3),
        "not_observed_count": counts["not_observed"],
        "evidence_quality": round(quality, 3),
        "state_counts": dict(counts),
        "state_ratio": {key: round(value / total, 3) for key, value in counts.items()},
        "top_state": counts.most_common(1)[0][0] if counts else "uncertain",
        "top_state_zh": STATE_ZH[counts.most_common(1)[0][0]] if counts else STATE_ZH["uncertain"],
        "avg_confidence": round(mean(item["confidence"] for item in states), 3),
        "review_required_count": counts["uncertain"] + counts["low_response"],
    }
    next_actions = _next_lesson_actions(student, fit, objective_rows)
    robot_action = _robot_action(student, mastery_band)
    feedback = _build_feedback(course, student, fit, mastery, state_summary, objective_rows, next_actions)
    special_education_support = _build_special_education_support(
        student,
        mastery,
        objective_rows,
    )
    state_timeline = [
        {
            "window_id": window["window_id"],
            "start_sec": window["start_sec"],
            "end_sec": window["end_sec"],
            "time_label": window["time_label"],
            "scene": window["lesson_phase"],
            "teacher_activity": window["teacher_activity"],
            **window["students"][student_id],
        }
        for window in windows
    ]
    student_tracking = _build_student_tracking(
        course, student, state_summary, mastery, key_interactions, next_actions
    )
    growth_projection = _build_growth_projection(student, mastery, state_summary)
    return {
        "student_id": student_id,
        "display_name": student["display_name"],
        "seat_label": student["seat_label"],
        "portrait_url": assets["portraits"].get(student_id, ""),
        "education_profile": student["education_profile"],
        "individual_target": course["individual_targets"].get(student_id, ""),
        "course_fit": fit,
        "mastery": mastery,
        "state_summary": state_summary,
        "state_timeline": state_timeline,
        "student_tracking": student_tracking,
        "growth_projection": growth_projection,
        "key_interactions": key_interactions,
        "next_lesson_actions": next_actions,
        "robot_action": robot_action,
        "special_education_support": special_education_support,
        "post_class_feedback": feedback,
        "feedback_char_count": len(feedback),
    }


def _select_key_interactions(windows: list[dict[str, Any]], student_id: str) -> list[dict[str, Any]]:
    ranked = sorted(
        windows,
        key=lambda window: (
            window["students"][student_id]["state"] == "active_response",
            window["students"][student_id]["motion_signal"],
            window["students"][student_id]["evidence_quality"],
        ),
        reverse=True,
    )
    selected = []
    used_phases = set()
    for window in ranked:
        if window["lesson_phase"] in used_phases and len(selected) < 3:
            continue
        state = window["students"][student_id]
        window_index = windows.index(window)
        next_window = windows[window_index + 1] if window_index + 1 < len(windows) else None
        next_state = next_window["students"][student_id] if next_window else None
        if state["state"] in {"low_response", "uncertain", "not_observed"}:
            teacher_adjustment = (
                f"教师端处于“{window['teacher_activity']}”环节；建议复核是否缩短指令、延长等待，"
                "或改用视觉/实物提示。"
            )
        elif state["state"] == "active_response":
            teacher_adjustment = (
                f"教师端处于“{window['teacher_activity']}”环节；建议复核是否及时确认了学生回应，"
                "并逐步撤除提示。"
            )
        else:
            teacher_adjustment = (
                f"教师端处于“{window['teacher_activity']}”环节；建议核对是否保持了当前节奏和低刺激反馈。"
            )
        if next_state is None:
            follow_up = "片段位于课程末段，没有后续窗口可供比较。"
            effect_label = "后续证据不足"
            link_score = 45
        elif next_state["state"] in {"engaged", "active_response"}:
            follow_up = f"下一窗口为“{next_state['state_zh']}”，出现继续参与或恢复回应的可见线索。"
            effect_label = "观察到积极后续线索"
            link_score = 82
        elif next_state["state"] == "not_observed":
            follow_up = "下一窗口没有明确作答机会，不能判断本次教师调整是否产生效果。"
            effect_label = "未观察到验证机会"
            link_score = 50
        else:
            follow_up = f"下一窗口仍为“{next_state['state_zh']}”，需要结合双视角视频继续复核。"
            effect_label = "尚未形成稳定后续证据"
            link_score = 42
        selected.append(
            {
                "start_sec": window["start_sec"],
                "end_sec": window["end_sec"],
                "time_label": window["time_label"],
                "lesson_phase": window["lesson_phase"],
                "teacher_activity": window["teacher_activity"],
                "observed_state": state["state_zh"],
                "confidence": state["confidence"],
                "evidence": state["evidence"],
                "system_judgement": (
                    f"系统观察到“{state['state_zh']}”线索；这只能说明画面表现，"
                    "不能自动证明学生是否听懂、答对或独立完成。"
                ),
                "review_reason": (
                    "该时段包含较明显回应/操作线索，需要教师确认任务、正确性和提示等级。"
                    if state["state"] == "active_response"
                    else "该时段的回应线索有限或语义不清，需要教师排除倾听、等待、遮挡或画面外提示。"
                ),
                "review_status": "待复核",
                "interaction_chain": {
                    "student_trigger": f"学生侧：{state['state_zh']}。{state['evidence']}",
                    "teacher_response": teacher_adjustment,
                    "student_follow_up": follow_up,
                    "effect_label": effect_label,
                    "link_score": link_score,
                    "evidence_basis": "双视角时间对齐后的演示性推断；教师表达、提示等级和因果关系必须人工复核。",
                },
            }
        )
        used_phases.add(window["lesson_phase"])
        if len(selected) == 4:
            break
    selected = sorted(selected, key=lambda item: item["start_sec"])
    for index, item in enumerate(selected, start=1):
        item["clip_id"] = f"{student_id}_clip_{index:02d}"
    return selected


def _build_growth_projection(
    student: dict[str, Any],
    mastery: dict[str, Any],
    state_summary: dict[str, Any],
) -> dict[str, Any]:
    """Build a conservative teaching scenario projection, not a clinical forecast."""
    dims = mastery["dimensions"]
    student_offset = {"student_A": 2, "student_B": 0, "student_C": -4}.get(
        student["student_id"], 0
    )
    current = {
        "认知学习": round((dims["accuracy"] + dims["transfer"]) / 2),
        "语言沟通": max(30, min(92, mastery["overall_score"] + student_offset)),
        "动作与操作": max(35, min(94, round((dims["independence"] + 72) / 2))),
        "社会情绪": max(30, min(92, state_summary["participation_score"] + student_offset)),
        "生活适应": max(30, min(92, round((dims["independence"] + dims["consistency"]) / 2))),
    }
    horizons = [("当前", 0.0), ("1个月", 0.8), ("3个月", 1.8), ("6个月", 2.7)]
    domains = []
    for index, (name, value) in enumerate(current.items()):
        support_gain = 2.2 if value < 65 else 1.4 if value < 80 else 0.8
        points = [
            {
                "horizon": horizon,
                "score": max(0, min(100, round(value + support_gain * factor + index * 0.15))),
            }
            for horizon, factor in horizons
        ]
        domains.append(
            {
                "name": name,
                "current_score": value,
                "points": points,
                "direction": "在当前支持策略持续有效的条件下缓慢上升",
            }
        )
    return {
        "model_type": "个体基线约束下的情景趋势推演",
        "evidence_grade": "C级 / 探索性",
        "history_status": "当前仅有少量课程与既有教育资料，尚不足以训练个体长期预测模型。",
        "domains": domains,
        "assumptions": [
            "继续使用已经确认有效的短指令、视觉提示和等待策略",
            "后续课程任务难度与当前个体目标大致连续",
            "每节课关键片段由教师复核，排除误识别和无作答机会",
        ],
        "upgrade_rule": "累计至少6节同类目标课程后，才计算真实斜率和置信区间；低于该门槛只展示情景推演。",
        "boundary": "趋势用于教学计划讨论，不表示医学预后、能力定级或确定的进步/恶化结论。",
    }


def _teacher_review_spec() -> dict[str, Any]:
    return {
        "name": "关键课堂片段教师复核",
        "who": "熟悉该学生并了解本节课任务的任课教师、助教或教研人员",
        "work_unit": "系统预先筛选的关键片段；不要求逐帧标注，也不要求学校剪视频",
        "required_fields": [
            "系统判断是否符合真实情况",
            "学生回答或操作是否正确",
            "学生完成时接受了什么等级的提示",
            "学生出现该表现时教师实际做了什么调整",
            "教师调整后学生出现了什么变化",
            "画面外任务、材料、人员或声音归属等补充情况",
        ],
        "verdicts": {
            "符合": "系统对该时段可见表现的描述基本准确，可保留为证据。",
            "需修正": "系统描述与真实课堂情况不一致，以教师补充说明为准。",
            "不确定": "画面、声音或任务信息不足，不能判断；该片段不计入不会或退步。",
        },
        "completion_rule": "每个关键片段需选择结论、正确性和提示等级，并记录教师调整与学生后续变化；无法判断时选择不确定或未观察到并说明原因。",
    }


def _build_special_education_support(
    student: dict[str, Any],
    mastery: dict[str, Any],
    objectives: list[dict[str, Any]],
) -> dict[str, Any]:
    profile = student["education_profile"]
    effective = profile.get("effective_support", [])
    constraints = profile.get("safety_constraints", [])
    strongest = max(objectives, key=lambda row: row["score"])
    weakest = min(objectives, key=lambda row: row["score"])
    response_channels = ["口语", "指认", "实物操作"]
    profile_text = " ".join(
        profile.get("strengths", [])
        + profile.get("support_needs", [])
        + effective
        + constraints
    )
    if any(keyword in profile_text for keyword in ("手势", "指认", "替代性")):
        response_channels.append("手势")
    if "求助卡" in profile_text:
        response_channels.append("求助卡")
    return {
        "instruction": effective[0] if effective else "一次只呈现一个可观察步骤",
        "wait_time": "每次提示后至少等待6秒；是否延长由教师决定",
        "response_channels": response_channels,
        "prompt_sequence": [
            "先给视觉或材料线索",
            "再给一个简短语言提示",
            "仍未回应时暂停，由教师判断是否示范或结束",
        ],
        "success_opportunity": (
            f"先从“{strongest['label']}”安排一次可独立完成的成功机会，再进入“{weakest['label']}”。"
        ),
        "calm_boundary": constraints or ["避免连续催促", "高影响干预由教师确认"],
        "mastery_note": (
            f"当前掌握初评为{mastery['overall_score']}分；所有支持均保留提示等级，"
            "不把提示后完成记录为独立完成。"
        ),
        "teacher_controlled": True,
    }


def _next_lesson_actions(
    student: dict[str, Any],
    fit: dict[str, Any],
    objectives: list[dict[str, Any]],
) -> list[str]:
    weakest = min(objectives, key=lambda row: row["score"])
    support = student["education_profile"].get("effective_support", [])
    return [
        f"下一课优先巩固“{weakest['label']}”，先设计一次可独立完成的成功机会。",
        fit["recommended_modifications"][0],
        support[0] if support else "使用短指令和视觉提示。",
        "教师抽检两段关键视频，确认回答正确性和实际提示等级。",
    ]


def _build_student_tracking(
    course: dict[str, Any],
    student: dict[str, Any],
    state_summary: dict[str, Any],
    mastery: dict[str, Any],
    key_interactions: list[dict[str, Any]],
    next_actions: list[str],
) -> dict[str, Any]:
    profile = student["education_profile"]
    support_windows = state_summary["review_required_count"]
    total = state_summary["window_count"]
    return {
        "student_profile": {
            "student_id": student["student_id"],
            "baseline_status": "个体课堂基线持续建立中",
            "profile_status": f"已接入{profile.get('source', 'IEP')}、课堂视频、课程目标和上次课程表现。",
            "support_constraint": "优先采用个体档案中的有效支持方式；证据不足时不自动干预。",
        },
        "lesson_conclusion": {
            "summary": (
                f"本节《{course['course_name']}》中，{student['display_name']}的参与指数为"
                f"{state_summary['participation_score']}分，学习掌握初评为{mastery['overall_score']}分（{mastery['band']}）。"
                f"系统从{total}个状态窗口中筛出{support_windows}个建议复核的支持时刻。"
            ),
            "not_a_diagnosis": "这是课堂教育支持分析，不是医学诊断或能力定级。",
            "data_status": "单节课用于更新个体基线；进步或退步需要多节同类任务和教师复核记录共同判断。",
        },
        "growth_indicators": [
            {
                "name": "参与稳定性",
                "level": "good" if state_summary["participation_score"] >= 70 else "watch",
                "current": f"参与指数{state_summary['participation_score']}分，稳定参与/回应约{state_summary['engaged_ratio']:.0%}。",
                "evidence": "后续与同一学生的同类课程比较，不与其他学生横向排名。",
            },
            {
                "name": "需要支持的时刻",
                "level": "support" if support_windows else "good",
                "current": f"共{support_windows}/{total}个窗口建议教师复核。",
                "evidence": "用于区分等待、思考、低回应、遮挡和真实支持需求。",
            },
            {
                "name": "任务独立程度",
                "level": "good" if mastery["dimensions"]["independence"] >= 70 else "support",
                "current": f"当前独立程度初评{mastery['dimensions']['independence']}分。",
                "evidence": "正式值由教师确认独立、简单提示、示范协助或完整协助等级。",
            },
            {
                "name": "知识迁移",
                "level": "good" if mastery["dimensions"]["transfer"] >= 70 else "watch",
                "current": f"新材料或新情境迁移初评{mastery['dimensions']['transfer']}分。",
                "evidence": "需要在不同材料或下一节课中再次观察，不能由一次回答定论。",
            },
        ],
        "key_moments": [
            {
                **moment,
                "title": f"{moment['observed_state']}复核片段",
                "why_it_matters": "该片段可用于确认学生是否真正获得学习机会，以及支持方式是否合适。",
                "teacher_review_question": "当时学生收到什么任务、是否正确回应、使用了哪一级提示？",
            }
            for moment in key_interactions
        ],
        "next_support_plan": next_actions,
        "support_profile_summary": {
            "available": True,
            "source": profile.get("source", "IEP/个体化教育资料"),
            "strengths": profile.get("strengths", []),
            "support_needs": profile.get("support_needs", []),
            "effective_support": profile.get("effective_support", []),
            "safety_constraints": profile.get("safety_constraints", []),
            "boundary": "个体资料只用于教学支持和动作安全约束，不输出医学诊断。",
        },
        "source_context": {
            "lesson_title": course["course_name"],
            "subject": course["subject"],
            "individual_target": course["individual_targets"].get(student["student_id"], ""),
        },
    }


def _build_teacher_effectiveness(
    course: dict[str, Any],
    student_results: list[dict[str, Any]],
    windows: list[dict[str, Any]],
) -> dict[str, Any]:
    participation = round(mean(item["state_summary"]["participation_score"] for item in student_results))
    individualized_fit = round(mean(item["course_fit"]["fit_score"] for item in student_results))
    mastery_evidence = round(mean(item["mastery"]["overall_score"] for item in student_results))
    uncertain_ratio = mean(item["state_summary"]["uncertain_ratio"] for item in student_results)
    low_disruption = round(max(35, 100 - uncertain_ratio * 100))

    challenges = 0
    recoveries = 0
    for result in student_results:
        states = [window["students"][result["student_id"]]["state"] for window in windows]
        for index, state in enumerate(states):
            if state not in {"low_response", "uncertain"}:
                continue
            challenges += 1
            if any(next_state in {"engaged", "active_response"} for next_state in states[index + 1 : index + 3]):
                recoveries += 1
    recovery = round(recoveries / challenges * 100) if challenges else 80
    metrics = [
        _teacher_metric(
            "student_engagement",
            "三人参与维持度",
            participation,
            20,
            "三名学生的稳定参与与回应窗口综合结果。",
            f"三人课堂参与指数均值为{participation}分。",
        ),
        _teacher_metric(
            "teacher_student_contingency",
            "互动调整有效度",
            recovery,
            30,
            "学生出现低回应或证据不足后，后续60秒重新出现参与线索的比例；需结合教师机确认实际调整。",
            f"{challenges}个需关注窗口中，{recoveries}个在后续两个窗口内出现恢复线索，形成师生互动复核候选。",
        ),
        _teacher_metric(
            "individualized_fit",
            "个体化目标适配度",
            individualized_fit,
            20,
            "本课目标与三名学生上次表现及个体支持资料的匹配程度。",
            f"三人课程目标适配均值为{individualized_fit}分。",
        ),
        _teacher_metric(
            "learning_evidence",
            "学习结果证据度",
            mastery_evidence,
            20,
            "正确性、独立性、一致性和迁移四维初评的综合结果。",
            f"三人学习掌握初评均值为{mastery_evidence}分，仍需教师抽检答案和提示等级。",
        ),
        _teacher_metric(
            "low_disruption_support",
            "低干扰支持环境",
            low_disruption,
            10,
            "证据不足片段越少，越有利于持续观察；本项不用于追责。",
            f"三人平均证据不足比例约{uncertain_ratio:.0%}。",
        ),
    ]
    overall = round(sum(item["score"] * item["weight"] for item in metrics) / 100)
    if overall >= 85:
        band = {"key": "excellent", "label": "支持效果稳定", "tone": "good"}
    elif overall >= 70:
        band = {"key": "good", "label": "支持效果较好", "tone": "good"}
    elif overall >= 55:
        band = {"key": "watch", "label": "建议针对性复盘", "tone": "watch"}
    else:
        band = {"key": "review", "label": "需要人工重点复核", "tone": "support"}
    weakest = min(metrics, key=lambda item: item["score"])
    strongest = max(metrics, key=lambda item: item["score"])
    return {
        "overall_score": overall,
        "band": band,
        "headline": f"本节课对三名重点学生的支持效果：{band['label']}",
        "summary": (
            f"本节《{course['course_name']}》的三人参与指数均值为{participation}分，支持效果指数为{overall}/100。"
            "该指数用于课后复盘学生是否从教学支持中受益，不评价教师个人能力。"
        ),
        "metrics": metrics,
        "strengths": [f"{strongest['name']}：{strongest['evidence']}"],
        "improvement_focus": [f"优先复盘{weakest['name']}：{weakest['evidence']}"],
        "review_questions": [
            "低回应窗口中，学生是在思考、等待，还是没有理解当前指令？",
            "学生出现特殊表现时，教师具体改变了什么表达、等待、材料或提示方式？",
            "教师调整后，学生是否在60秒内回到任务并减少了提示依赖？",
            "三名学生是否都获得了与各自目标相匹配的独立作答或操作机会？",
        ],
        "rubric": {
            "excellent": "85-100：学生受益证据稳定，仍需抽样复核。",
            "good": "70-84：整体支持较好，个别环节需要优化。",
            "watch": "55-69：建议重点复盘低回应、恢复和目标适配。",
            "review": "0-54：证据不足或差距较大，应由教师结合课堂情境确认。",
        },
        "boundary": "只评估本节课对三名学生的支持效果，不评价教师个人能力，不作为绩效考核结论。",
    }


def _teacher_metric(
    key: str,
    name: str,
    score: int,
    weight: int,
    benchmark: str,
    evidence: str,
) -> dict[str, Any]:
    level = "good" if score >= 75 else "watch" if score >= 60 else "support"
    return {
        "key": key,
        "name": name,
        "score": max(0, min(100, score)),
        "weight": weight,
        "level": level,
        "benchmark": benchmark,
        "evidence": evidence,
        "interpretation": "保持当前做法并抽样验证。" if level == "good" else "建议结合关键片段复盘并调整下一课策略。",
    }


def _build_report_summary(
    course: dict[str, Any],
    meta: dict[str, Any],
    student_results: list[dict[str, Any]],
    windows: list[dict[str, Any]],
) -> dict[str, Any]:
    phase_counts = Counter(window["lesson_phase"] for window in windows)
    class_participation = round(mean(item["state_summary"]["participation_score"] for item in student_results))
    class_mastery = round(mean(item["mastery"]["overall_score"] for item in student_results))
    return {
        "available": True,
        "title": course["course_name"],
        "metadata": {
            "学科": course["subject"],
            "课程时长": f"{meta['duration_min']}分钟",
            "分析对象": "三名校方确认学生",
            "学生机视频": meta["file_name"],
        },
        "student_metrics": {
            "三人参与指数均值": f"{class_participation}分",
            "三人掌握初评均值": f"{class_mastery}分",
            "教师复核要求": "关键回答、提示等级与不确定片段",
        },
        "behavior_distribution": {
            phase: f"约{count * meta['window_sec'] // 60}分{count * meta['window_sec'] % 60}秒"
            for phase, count in phase_counts.items()
        },
        "question_metrics": {
            "说话人归属": "远场音频不强制绑定学生",
            "回答正确性": "教师抽检后确认",
            "提示等级": "独立/简单提示/示范协助/完整协助",
        },
        "source": "校方授权课堂视频、课程教案、IEP与上次课程表现记录",
    }


def _build_course_analysis(
    course: dict[str, Any],
    meta: dict[str, Any],
    student_results: list[dict[str, Any]],
    teacher_effectiveness: dict[str, Any],
) -> dict[str, Any]:
    class_mastery = round(mean(item["mastery"]["overall_score"] for item in student_results))
    class_participation = round(
        mean(item["state_summary"]["participation_score"] for item in student_results)
    )
    student_lines = []
    for item in student_results:
        weakest = min(item["mastery"]["objectives"], key=lambda row: row["score"])
        student_lines.append(
            f"{item['display_name']}掌握初评{item['mastery']['overall_score']}分、参与指数"
            f"{item['state_summary']['participation_score']}分，当前为“{item['mastery']['band']}”。"
            f"需重点核对“{weakest['label']}”，下一课先安排一次可独立完成的同类任务。"
        )
    text = "\n\n".join(
        [
            (
                f"一、课程说明。本报告对应{course['subject']}《{course['course_name']}》，"
                f"课堂时长约{meta['duration_min']}分钟，分析对象为三名由校方确认身份和固定座位的学生。"
                f"学校课程标准为：{course['lesson_standard']}。考核口径为："
                f"{course['school_assessment_standard']}。系统只分析本节课实际出现的学习机会，不把安静、"
                "动作多少或单次表情直接解释为学会、不会。"
            ),
            (
                f"二、班级整体情况。三名学生的掌握初评均值为{class_mastery}分，课堂参与信号均值为"
                f"{class_participation}分。参与信号只表示画面中出现看向材料、操作或回应线索；答案是否正确、"
                "是否独立完成，仍由教师结合任务复核。遮挡、声音归属不清或没有明确作答机会时记为U，不计入不会。"
            ),
            "三、三名学生的初步结果。" + "".join(student_lines),
            (
                f"四、教学支持效果。本节课对三名重点学生的支持效果指数为"
                f"{teacher_effectiveness['overall_score']}分，结论为“{teacher_effectiveness['band']['label']}”。"
                f"这一指标评价的是本节课目标适配、回应恢复、学习证据和低干扰支持，不评价教师个人能力。"
                f"建议优先复盘：{'；'.join(teacher_effectiveness['improvement_focus'])}。低分项目需回到片段，"
                "区分任务难度、指令长度、等待时间、提示方式和证据不足等原因。"
            ),
            (
                "五、教师复核与下一课安排。系统已为每名学生筛选少量关键片段，并标明课程、学生、"
                "时间段、系统观察和复核原因。教师确认描述是否符合、回答或操作是否正确、完成时的提示等级，"
                "并补充画面外情况。“需修正”以教师说明为准；“不确定”不计入不会或退步。下一课为每名学生"
                "保留一个可成功完成的任务，一次只给一个短指令，提示后等待，允许口语、指认、手势或实物操作，"
                "再逐步撤除提示。屏幕、语音或机器人只执行低刺激、无接触、可关闭的支持动作。"
            ),
            (
                "六、结论边界。本报告是一节课、一个学校场景下的课程级教育支持分析，用于课程复盘、"
                "学生个体支持和下一课设计，不构成医学诊断、能力定级或教师绩效结论。单节课只形成当前基线；"
                "多节同类任务采用一致口径并经教师复核后，才能讨论独立完成增加、提示减少、稳定性和知识迁移。"
            ),
        ]
    )
    if len(text) < 950:
        text += (
            "\n\n补充说明：正式试点时，每条结论均应保留课程编号、匿名学生编号、片段起止时间、"
            "系统版本、教师复核人和修正记录，确保学校可以回到原始证据检查报告来源。"
        )
    if len(text) > 1200:
        text = text[:1198].rsplit("。", 1)[0] + "。"
    return {
        "title": f"{course['subject']}《{course['course_name']}》课程分析",
        "audience": "学校与任课教师",
        "scope": "一节课 / 一个学校 / 三名重点学生",
        "target_char_count": 1000,
        "char_count": len(text),
        "text": text,
        "review_status": "系统初评，关键片段经教师复核后定稿",
        "boundary": "不构成医学诊断、学生能力定级或教师绩效结论。",
    }


def _robot_action(student: dict[str, Any], mastery_band: str) -> dict[str, Any]:
    support = student["education_profile"].get("effective_support", [])
    if mastery_band == "独立掌握":
        return {
            "action_id": "advance_with_specific_feedback",
            "screen": "保持当前任务，轻量显示下一步",
            "speech": "这一步完成了，我们试试下一种材料。",
            "motion": "slow_nod",
            "teacher_confirmation_required": False,
        }
    if mastery_band == "支持下掌握":
        return {
            "action_id": "reduce_prompt_gradually",
            "screen": "保留关键词或单步视觉提示",
            "speech": "先看这一处，想好以后告诉我。",
            "motion": "slow_turn_to_target",
            "teacher_confirmation_required": False,
        }
    return {
        "action_id": "repeat_one_step_and_handoff",
        "screen": "只显示当前一步和两个可选答案",
        "speech": support[0] if support else "我们先完成第一步。",
        "motion": "hold_position_no_touch",
        "teacher_confirmation_required": True,
    }


def _build_feedback(
    course: dict[str, Any],
    student: dict[str, Any],
    fit: dict[str, Any],
    mastery: dict[str, Any],
    state: dict[str, Any],
    objectives: list[dict[str, Any]],
    actions: list[str],
) -> str:
    strongest = max(objectives, key=lambda row: row["score"])
    weakest = min(objectives, key=lambda row: row["score"])
    strengths = student["education_profile"].get("strengths", [])
    needs = student["education_profile"].get("support_needs", [])
    paragraphs = [
        (
            f"一、课程与评价说明。本次分析对象为{student['display_name']}，课程为《{course['course_name']}》。"
            f"课程核心标准是：{course['lesson_standard']}系统结合教案、学生机画面、固定座位身份和既有教育资料形成初评。"
            "掌握度与参与状态分开计算；安静不等于学会，动作较多也不等于没有学习。没有明确机会、画面遮挡或音频归属不清的片段均标记为待复核。"
        ),
        (
            f"二、课程目标适配性。结合上次课程记录与本次目标，课程适配分为{fit['fit_score']}分，结论为“{fit['fit_level']}”。"
            f"当前最大跨度集中在“{fit['largest_gap_objective']}”。{fit['conclusion']}本节课设置的个别化目标是："
            f"{course['individual_targets'].get(student['student_id'], '')}。实施时应把任务拆成可观察的小步骤，明确提示类型和等待时间，避免把提示后完成记为独立掌握。"
        ),
        (
            f"三、课堂参与和状态证据。系统在全课30秒窗口中估计稳定参与或出现回应信号的比例为{state['engaged_ratio']:.0%}，"
            f"回应信号较低的比例为{state['low_response_ratio']:.0%}，因画面遮挡或证据不足而无法判断的比例为{state['uncertain_ratio']:.0%}，"
            f"课堂参与指数为{state['participation_score']}分，平均证据质量为{state['evidence_quality']:.2f}。"
            "回应信号表示讲解、提问或操作阶段出现可见反应，不能单独证明回答正确。请教师复核关键片段中的任务、答案和提示等级。"
        ),
        (
            f"四、学习掌握初评。系统给出的综合初评分为{mastery['overall_score']}分，暂定为“{mastery['band']}”，置信度为"
            f"{mastery['confidence']:.2f}。表现相对较好的目标是“{strongest['label']}”，初评分{strongest['score']}分；"
            f"当前最需要继续观察和巩固的是“{weakest['label']}”，初评分{weakest['score']}分。"
            f"从正确性、独立程度、重复表现一致性和迁移四个维度看，当前分别为{mastery['dimensions']['accuracy']}、"
            f"{mastery['dimensions']['independence']}、{mastery['dimensions']['consistency']}和{mastery['dimensions']['transfer']}分。"
            f"按统一10分制换算，本节综合初评为{mastery['assessment']['overall_score'] if mastery['assessment']['overall_score'] is not None else '未形成'}分，6分为及格；"
            "这些数值用于组织证据，不应脱离视频和教师记录单独作为学业结论。"
        ),
        (
            f"五、个体化解释。既有资料显示，该生的优势包括：{'；'.join(strengths[:3])}。当前需要重点支持：{'；'.join(needs[:3])}。"
            "评价应记录学生是在独立、简单提示、示范还是完整协助下完成。"
            f"本节课建议：{'；'.join(fit['recommended_modifications'])}。若提示后能完成，下次应逐步撤除提示；若仍无响应，先核对指令和材料。"
        ),
        (
            f"六、后续教学与复核建议。{'；'.join(actions)}。机器人或屏幕端只执行低刺激支持：当前建议为"
            f"“{_robot_action(student, mastery['band'])['screen']}”，语音提示为“{_robot_action(student, mastery['band'])['speech']}”，"
            "不主动触碰，也不在证据不足时连续提醒。教师复核后，系统保存正确性、提示等级和任务结果，用于更新下节课起点。"
            "跨课比较优先看独立完成是否提高、提示是否减少、同类任务能否迁移，而不只比较总分。本结果属于教育支持记录，不构成医学判断或教师绩效评价。"
        ),
    ]
    feedback = "\n\n".join(paragraphs)
    if len(feedback) < 900:
        feedback += "\n\n补充说明：正式使用时，每个结论应保留对应时间段、教师任务、学生反应、提示等级和复核人，确保报告可以追溯。"
    return feedback


def _write_course_assets(
    course: dict[str, Any], students: list[dict[str, Any]], meta: dict[str, Any]
) -> dict[str, Any]:
    course_dir = OUTPUT_DIR / course["course_id"]
    course_dir.mkdir(parents=True, exist_ok=True)
    group_path = course_dir / "group_reference.jpg"
    portraits = {student["student_id"]: course_dir / f"{student['student_id']}_portrait.jpg" for student in students}
    try:
        cv2 = _import_cv2()
        from PIL import Image, ImageDraw, ImageFont

        cap = cv2.VideoCapture(str(Path(course["student_video"])))
        cap.set(cv2.CAP_PROP_POS_MSEC, float(course.get("reference_sec", 600) * 1000))
        ok, frame = cap.read()
        cap.release()
        if ok:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            image = Image.fromarray(rgb)
            draw = ImageDraw.Draw(image)
            font_path = Path("C:/Windows/Fonts/msyh.ttc")
            font = ImageFont.truetype(str(font_path), 28) if font_path.exists() else ImageFont.load_default()
            colors = [(31, 111, 235), (10, 143, 96), (196, 96, 22)]
            for student, color in zip(students, colors):
                roi = student["roi"]
                x1, y1 = roi["x"], roi["y"]
                x2, y2 = x1 + roi["w"], y1 + roi["h"]
                draw.rectangle((x1, y1, x2, y2), outline=color, width=5)
                label = student["display_name"]
                box = draw.textbbox((0, 0), label, font=font)
                label_w = box[2] - box[0] + 24
                label_h = box[3] - box[1] + 18
                draw.rounded_rectangle((x1, max(0, y1 - label_h), x1 + label_w, y1), radius=5, fill=color)
                draw.text((x1 + 12, max(0, y1 - label_h + 5)), label, fill="white", font=font)
                crop = image.crop((max(0, x1), max(0, y1), min(image.width, x2), min(image.height, y2)))
                crop.save(portraits[student["student_id"]], quality=92)
            image.save(group_path, quality=92)
    except Exception:
        pass
    return {
        "group_image_url": f"/assets/seewo_demo2/{course['course_id']}/group_reference.jpg" if group_path.exists() else "",
        "portraits": {
            student_id: f"/assets/seewo_demo2/{course['course_id']}/{path.name}" if path.exists() else ""
            for student_id, path in portraits.items()
        },
        "asset_note": "群像和人像均来自校方确认身份后的固定座位课堂画面。",
    }


def _mastery_band(score: int) -> str:
    if score >= 88:
        return "独立掌握"
    if score >= 70:
        return "支持下掌握"
    if score >= 50:
        return "正在学习"
    return "尚未表现"


def _lesson_phase(sec: float, duration: float) -> str:
    ratio = sec / max(duration, 1)
    if ratio < 0.12:
        return "导入与目标说明"
    if ratio < 0.35:
        return "教师示范"
    if ratio < 0.68:
        return "引导练习"
    if ratio < 0.90:
        return "个别练习与迁移"
    return "总结与回顾"


def _teacher_activity(sec: float, duration: float) -> str:
    phase = _lesson_phase(sec, duration)
    return {
        "导入与目标说明": "呈现课程目标与关键材料",
        "教师示范": "讲解、示范并提供首次作答机会",
        "引导练习": "提问、等待、提示和反馈",
        "个别练习与迁移": "个别任务、材料变化与支持撤除",
        "总结与回顾": "回顾目标并确认学生表现",
    }[phase]


def _state_evidence(state: str) -> str:
    return {
        "engaged": "座位区域出现持续但不过度的活动信号，可作为参与证据之一。",
        "active_response": "座位区域出现较明显的动作或操作变化，需要结合教师任务确认是否为有效回应。",
        "low_response": "该窗口活动信号较低，需要区分倾听、等待、遮挡或未参与。",
        "not_observed": "当前教学阶段未识别到明确作答机会，学生没有作答不计入不会或退步。",
        "uncertain": "画面质量、遮挡或信号不足，不触发自动结论。",
    }[state]


def _crop(gray: np.ndarray, roi: dict[str, int]) -> np.ndarray:
    height, width = gray.shape[:2]
    x1 = max(0, min(width, int(roi["x"])))
    y1 = max(0, min(height, int(roi["y"])))
    x2 = max(x1, min(width, x1 + int(roi["w"])))
    y2 = max(y1, min(height, y1 + int(roi["h"])))
    return gray[y1:y2, x1:x2]


def _clip01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _format_time(sec: float) -> str:
    sec = max(0, int(sec))
    return f"{sec // 60:02d}:{sec % 60:02d}"


def _import_cv2():
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError("OpenCV is required to rebuild Demo2 video features") from exc
    return cv2


def render_seewo_demo2_html() -> str:
    payload = json.dumps(load_seewo_demo2(), ensure_ascii=False).replace("</", "<\\/")
    return _HTML_TEMPLATE.replace("__PAYLOAD__", payload)


_HTML_TEMPLATE = r'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="theme-color" content="#f3f6f4" />
  <meta name="description" content="面向辅读学校的课堂学习证据、教师复核与个体支持工作台" />
  <title>课堂学习证据台 · RehabAffect</title>
  <style>
    :root {
      --bg:#eef2f6; --panel:#fff; --soft:#f7f9fc; --ink:#17212b; --muted:#667085;
      --line:#d7dee7; --blue:#2563eb; --teal:#087f8c; --green:#16834a; --amber:#a96300;
      --red:#b83b35; --purple:#7048b6; --shadow:0 12px 30px rgba(25,39,60,.08);
    }
    * { box-sizing:border-box; }
    body { margin:0; background:var(--bg); color:var(--ink); font-family:"Microsoft YaHei","Segoe UI",Arial,sans-serif; }
    button,input,textarea,select { font:inherit; }
    button { cursor:pointer; }
    header { position:sticky; top:0; z-index:10; background:#fff; border-bottom:1px solid var(--line); }
    .topbar { max-width:1560px; margin:auto; padding:12px 22px; display:flex; align-items:center; gap:18px; }
    .brand { min-width:300px; }
    .brand strong { display:block; font-size:18px; }
    .brand span { color:var(--muted); font-size:12px; }
    .top-actions { margin-left:auto; display:flex; align-items:center; gap:10px; }
    .status { font-size:12px; color:var(--green); font-weight:700; }
    .course-select { min-width:250px; border:1px solid var(--line); padding:9px 12px; background:#fff; }
    .ghost-link { color:var(--blue); text-decoration:none; font-size:13px; }
    main { max-width:1560px; margin:auto; padding:18px 22px 40px; }
    .section { background:var(--panel); border:1px solid var(--line); margin-bottom:16px; }
    .section-head { padding:14px 18px; border-bottom:1px solid var(--line); display:flex; align-items:center; gap:12px; }
    .section-head h2 { margin:0; font-size:16px; }
    .section-head p { margin:0; color:var(--muted); font-size:12px; }
    .section-body { padding:18px; }
    .input-grid { display:grid; grid-template-columns:.8fr 1.05fr 1.45fr 1.45fr; gap:14px; }
    label { display:block; color:var(--muted); font-size:12px; margin-bottom:6px; }
    input,textarea,select { width:100%; border:1px solid var(--line); background:#fff; color:var(--ink); padding:10px 11px; border-radius:4px; }
    textarea { min-height:92px; resize:vertical; line-height:1.55; }
    .action-row { display:flex; gap:10px; margin-top:14px; align-items:center; }
    .action-row .hint { min-width:0; overflow-wrap:anywhere; word-break:break-word; }
    .primary { border:1px solid var(--blue); background:var(--blue); color:white; padding:9px 15px; border-radius:4px; font-weight:700; }
    .secondary { border:1px solid var(--line); background:white; color:var(--ink); padding:9px 15px; border-radius:4px; }
    .hint { color:var(--muted); font-size:12px; }
    .fit-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; margin-top:16px; }
    .fit-item { border-left:4px solid var(--blue); background:var(--soft); padding:12px 14px; min-height:126px; }
    .fit-item.warn { border-left-color:var(--amber); }
    .fit-top { display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; }
    .fit-top strong { font-size:14px; }
    .fit-score { font-size:24px; font-weight:800; color:var(--blue); }
    .fit-item.warn .fit-score { color:var(--amber); }
    .fit-item p { margin:6px 0; color:#344054; font-size:12px; line-height:1.55; }
    .workbench { display:grid; grid-template-columns:minmax(0,1.45fr) minmax(390px,.8fr); min-height:650px; }
    .visual-pane { border-right:1px solid var(--line); background:#151b23; display:flex; flex-direction:column; min-width:0; }
    .visual-toolbar { background:#fff; border-bottom:1px solid var(--line); padding:10px 14px; display:flex; align-items:center; gap:10px; }
    .segmented { display:inline-flex; border:1px solid var(--line); background:var(--soft); }
    .segmented button { border:0; border-right:1px solid var(--line); background:transparent; padding:7px 13px; color:var(--muted); }
    .segmented button:last-child { border-right:0; }
    .segmented button.active { background:#fff; color:var(--blue); font-weight:700; }
    .visual-note { margin-left:auto; color:var(--muted); font-size:12px; }
    .stage { flex:1; display:grid; place-items:center; min-height:540px; overflow:hidden; }
    .stage img { width:100%; height:100%; max-height:620px; object-fit:contain; display:block; }
    .student-pane { background:#fff; min-width:0; }
    .student-tabs { display:grid; grid-template-columns:repeat(3,1fr); border-bottom:1px solid var(--line); }
    .student-tab { border:0; border-right:1px solid var(--line); background:#fff; text-align:left; padding:13px; min-height:86px; }
    .student-tab:last-child { border-right:0; }
    .student-tab.active { box-shadow:inset 0 -3px var(--blue); background:#f8fbff; }
    .student-tab strong { display:block; font-size:14px; }
    .student-tab span { font-size:11px; color:var(--muted); }
    .student-detail { padding:16px; }
    .student-title { display:flex; gap:14px; align-items:center; }
    .portrait { width:84px; height:104px; object-fit:cover; border:1px solid var(--line); background:var(--soft); }
    .student-title h3 { margin:0 0 5px; font-size:20px; }
    .student-title p { margin:3px 0; color:var(--muted); font-size:12px; }
    .score-row { display:grid; grid-template-columns:110px 1fr; gap:14px; margin:16px 0; align-items:center; }
    .score-ring { width:104px; height:104px; border-radius:50%; display:grid; place-items:center; background:conic-gradient(var(--blue) var(--score),#e8edf4 0); position:relative; }
    .score-ring::after { content:""; width:78px; height:78px; border-radius:50%; background:#fff; position:absolute; }
    .score-ring strong { position:relative; z-index:1; font-size:25px; }
    .metric-list { display:grid; gap:8px; }
    .metric { display:grid; grid-template-columns:76px 1fr 34px; gap:7px; align-items:center; font-size:11px; }
    .bar { height:6px; background:#e8edf4; overflow:hidden; }
    .bar i { display:block; height:100%; background:var(--teal); }
    .callout { background:#eff6ff; border-left:4px solid var(--blue); padding:10px 12px; font-size:12px; line-height:1.6; margin:12px 0; }
    .mini-actions { display:grid; grid-template-columns:repeat(2,1fr); gap:8px; }
    .mini-actions div { background:var(--soft); border:1px solid var(--line); padding:9px; font-size:11px; line-height:1.5; }
    .dim-chips { display:flex; flex-wrap:wrap; gap:5px; }
    .dim-chip { display:inline-flex; gap:4px; align-items:center; padding:2px 7px; border:1px solid var(--line); border-radius:3px; font-size:11px; background:var(--soft); }
    .dim-chip b { font-weight:600; }
    .trend-empty { color:var(--muted); font-size:12px; padding:10px 0; margin:0; }
    .student-strip { display:grid; grid-template-columns:repeat(3,1fr); gap:12px; }
    .student-card { border:1px solid var(--line); padding:14px; background:#fff; min-width:0; text-align:left; color:var(--ink); }
    .student-card:hover,.student-card.active { border-color:var(--blue); background:#f8fbff; }
    .student-card header { position:static; border:0; display:flex; justify-content:space-between; align-items:center; }
    .student-card h3 { margin:0; font-size:15px; }
    .student-card .big { font-size:30px; font-weight:800; color:var(--blue); }
    .student-card p { color:var(--muted); font-size:12px; line-height:1.6; }
    .tabs { display:flex; flex-wrap:wrap; border-bottom:1px solid var(--line); background:var(--soft); }
    .tab-cluster { display:flex; align-items:stretch; border-right:1px solid var(--line); }
    .tab-cluster > span { display:flex; align-items:center; padding:0 9px; background:#e8edf4; color:#475467; font-size:10px; font-weight:700; }
    .tabs button { border:0; background:transparent; padding:11px 13px; color:var(--muted); }
    .tabs button.active { color:var(--blue); background:#fff; font-weight:700; box-shadow:inset 0 -3px var(--blue); }
    .tab-body { padding:18px; min-height:350px; }
    table { width:100%; border-collapse:collapse; font-size:12px; }
    th,td { padding:10px 9px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; }
    th { background:var(--soft); color:#344054; }
    .level { font-weight:700; color:var(--blue); }
    .evidence-list { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; }
    .evidence { border:1px solid var(--line); padding:12px; }
    .evidence strong { display:block; margin-bottom:5px; }
    .evidence span,.evidence p { font-size:12px; color:var(--muted); line-height:1.55; margin:4px 0; }
    .review-row { display:flex; gap:7px; margin-top:10px; }
    .review-row button { border:1px solid var(--line); background:#fff; padding:6px 9px; border-radius:3px; font-size:11px; }
    .review-row button.selected { border-color:var(--green); color:var(--green); background:#effaf4; }
    .review-editor { display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-top:9px; }
    .review-editor input,.review-editor select { padding:7px 8px; font-size:11px; }
    .review-editor input { grid-column:1/-1; }
    .save-review { grid-column:1/-1; justify-self:start; border:1px solid var(--teal); background:#fff; color:var(--teal); padding:6px 10px; font-size:11px; }
    .feedback { white-space:pre-wrap; font-size:13px; line-height:1.9; max-width:1100px; }
    .report-toolbar { display:flex; flex-wrap:wrap; align-items:center; gap:10px; padding:12px; border:1px solid var(--line); background:var(--soft); margin-bottom:14px; }
    .report-status { color:var(--muted); font-size:12px; }
    .report-layout { display:grid; grid-template-columns:230px minmax(0,1fr); gap:16px; align-items:start; }
    .report-nav { position:sticky; top:82px; border:1px solid var(--line); background:#fff; padding:8px; max-height:72vh; overflow:auto; }
    .report-nav button { display:block; width:100%; border:0; background:transparent; text-align:left; color:#475467; padding:8px; font-size:11px; }
    .report-nav button:hover { background:#eff6ff; color:var(--blue); }
    .report-document { max-width:1000px; }
    .report-section { border-bottom:1px solid var(--line); padding:4px 6px 22px; margin-bottom:18px; }
    .report-figure { margin:16px 0 22px; padding:14px 16px; border:1px solid var(--line); background:#f8fbfe; border-radius:8px; max-width:560px; }
    .report-figure figcaption { display:flex; justify-content:space-between; gap:12px; margin-bottom:8px; color:#244c45; font-size:12px; }
    .report-figure figcaption span { color:#607985; font-weight:400; }
    .report-figure svg { display:block; width:100%; height:auto; }
    .report-section h3 { color:#174ea6; font-size:17px; margin:0 0 12px; }
    .report-section p { margin:0; white-space:pre-wrap; color:#344054; font-size:13px; line-height:1.95; }
    .entry-gate { position:fixed; inset:0; z-index:50; background:#eef2f6; overflow:auto; padding:36px 18px; }
    .entry-shell { width:min(1080px,100%); margin:auto; background:#fff; border:1px solid var(--line); box-shadow:0 20px 55px rgba(25,39,60,.14); }
    .entry-head { padding:22px 26px; border-bottom:1px solid var(--line); display:flex; justify-content:space-between; gap:18px; }
    .entry-head h1 { margin:0 0 6px; font-size:24px; }
    .entry-head p { margin:0; color:var(--muted); font-size:13px; }
    .entry-step { color:var(--blue); font-size:12px; font-weight:800; white-space:nowrap; }
    .entry-body { padding:24px 26px 28px; }
    .entry-grid { display:grid; grid-template-columns:.8fr 1.2fr; gap:14px; }
    .entry-grid .wide { grid-column:1/-1; }
    .entry-grid textarea { min-height:105px; }
    .confirm-check { display:flex; align-items:flex-start; gap:9px; margin:16px 0; padding:12px; background:#fff8eb; border-left:4px solid var(--amber); color:#6f4b11; font-size:12px; line-height:1.6; }
    .confirm-check input { width:auto; margin-top:3px; }
    .summary-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; margin-bottom:14px; }
    .summary-box { border:1px solid var(--line); border-top:3px solid var(--teal); padding:12px; background:#fff; }
    .summary-box strong { display:block; font-size:22px; margin-top:5px; }
    .summary-box span { color:var(--muted); font-size:11px; }
    .scroll-table { max-height:560px; overflow:auto; border:1px solid var(--line); }
    .scroll-table thead { position:sticky; top:0; z-index:2; }
    .action-stack,.tracking-grid,.teacher-grid,.profile-grid,.report-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }
    .info-block { border:1px solid var(--line); padding:13px; background:#fff; min-width:0; }
    .info-block h3 { margin:0 0 8px; font-size:14px; }
    .info-block p,.info-block li { color:#475467; font-size:12px; line-height:1.65; }
    .info-block ul,.info-block ol { margin:8px 0 0; padding-left:20px; }
    .teacher-score { font-size:42px; font-weight:800; color:var(--blue); line-height:1; }
    .metric-card { border-left:4px solid var(--teal); background:var(--soft); padding:11px 12px; }
    .metric-card.watch { border-left-color:var(--amber); }
    .metric-card.support { border-left-color:var(--red); }
    .metric-card header { position:static; border:0; display:flex; justify-content:space-between; }
    .metric-card p { margin:6px 0 0; color:var(--muted); font-size:11px; line-height:1.55; }
    .state-tag { display:inline-block; min-width:78px; font-weight:700; color:var(--teal); }
    .source-line { display:flex; gap:8px; padding:7px 0; border-bottom:1px solid var(--line); font-size:12px; }
    .source-line b { min-width:110px; }
    .result-summary { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); border-bottom:1px solid var(--line); background:#fff; }
    .result-stat { padding:12px 16px; border-right:1px solid var(--line); }
    .result-stat:last-child { border-right:0; }
    .result-stat span { display:block; color:var(--muted); font-size:10px; }
    .result-stat strong { display:block; margin-top:3px; font-size:18px; }
    .review-progress { margin-left:auto; color:var(--teal); font-size:11px; font-weight:700; }
    .window-inspector { display:grid; grid-template-columns:1.05fr 1fr; border:1px solid var(--line); margin-bottom:14px; }
    .window-inspector > div { padding:13px; min-width:0; }
    .window-inspector > div + div { border-left:1px solid var(--line); background:var(--soft); }
    .window-inspector h3 { margin:0 0 7px; font-size:14px; }
    .window-inspector p { margin:5px 0; color:#475467; font-size:12px; line-height:1.55; }
    .inline-command { border:1px solid var(--blue); color:var(--blue); background:#fff; padding:6px 9px; font-size:11px; }
    tr.selectable { cursor:pointer; }
    tr.selectable:hover,tr.selectable.selected { background:#eff6ff; }
    .filter-row { display:flex; justify-content:space-between; align-items:center; gap:10px; margin:12px 0 8px; }
    .filter-row h3 { margin:0; }
    .tick.selected { outline:3px solid var(--blue); outline-offset:-3px; }
    pre { margin:0; background:#111827; color:#dbeafe; padding:15px; overflow:auto; font:12px/1.55 Consolas,monospace; }
    .timeline { display:flex; gap:3px; overflow-x:auto; padding-bottom:8px; }
    .tick { min-width:42px; height:54px; border:0; background:#e7edf5; position:relative; }
    .tick.engaged { background:#bfe4d0; }
    .tick.active_response { background:#9fd6df; }
    .tick.low_response { background:#f3d3a6; }
    .tick.uncertain { background:#d9dce3; }
    .tick:hover::after { content:attr(data-tip); position:absolute; bottom:58px; left:0; width:190px; background:#111827; color:#fff; padding:7px; font-size:10px; z-index:5; }
    .privacy { padding:12px 16px; background:#fff8eb; border:1px solid #efd9a9; color:#6f4b11; font-size:12px; line-height:1.6; }
    /* Demo2 v5: calm, evidence-first special-education operations workspace. */
    :root {
      --bg:#f3f6f8; --panel:#ffffff; --soft:#f6f8fb; --ink:#142033; --muted:#5e6c80;
      --line:#ccd6e2; --blue:#1e40af; --blue-2:#2563eb; --teal:#0f766e; --green:#157347;
      --amber:#b45309; --red:#b42318; --purple:#6d28d9; --navy:#10233f;
      --shadow:0 8px 22px rgba(20,32,51,.07);
    }
    html { scroll-behavior:smooth; }
    body { min-width:320px; font-family:"Microsoft YaHei UI","Microsoft YaHei","Segoe UI",sans-serif; line-height:1.5; }
    h1,h2,h3,.brand strong,.fit-score,.big,.teacher-score,.result-stat strong { font-family:"Bahnschrift SemiBold","Microsoft YaHei UI",sans-serif; letter-spacing:0; }
    button,input,textarea,select { border-radius:6px; }
    button { min-height:40px; transition:background-color .18s ease,border-color .18s ease,color .18s ease,box-shadow .18s ease; }
    button:focus-visible,input:focus-visible,textarea:focus-visible,select:focus-visible,a:focus-visible { outline:3px solid rgba(37,99,235,.28); outline-offset:2px; }
    input:focus,textarea:focus,select:focus { border-color:var(--blue-2); box-shadow:0 0 0 3px rgba(37,99,235,.10); }
    header { background:#fff; box-shadow:0 1px 0 rgba(16,35,63,.05); }
    .topbar { max-width:1480px; min-height:72px; padding:10px 24px; }
    .brand { min-width:340px; padding-left:14px; border-left:4px solid var(--blue); }
    .brand strong { font-size:19px; color:var(--navy); }
    .brand span { display:block; margin-top:2px; }
    .top-actions { min-width:0; }
    .status { max-width:220px; color:var(--teal); line-height:1.4; }
    .course-select { min-height:44px; border-color:#b9c7d7; }
    .ghost-link { min-height:40px; display:inline-flex; align-items:center; padding:0 8px; font-weight:700; }
    main { max-width:1480px; padding:20px 24px 48px; }
    .section { border:0; background:transparent; margin-bottom:22px; }
    .section-head { padding:8px 0 12px; border:0; align-items:center; }
    .section-head > div:not(.section-index) { min-width:0; }
    .section-head h2 { color:var(--navy); font-size:18px; }
    .section-head p { margin-top:2px; font-size:13px; }
    .section-index { flex:0 0 auto; width:38px; height:38px; display:grid; place-items:center; background:var(--navy); color:#fff; font:700 12px/1 "Bahnschrift",sans-serif; border-radius:6px; }
    .section-body,.workbench,.result-summary,.tabs,.tab-body { background:var(--panel); border:1px solid var(--line); }
    .section-body { padding:18px; box-shadow:var(--shadow); }
    .input-grid { grid-template-columns:.75fr 1fr 1.5fr 1.5fr; }
    label { color:#46566d; font-weight:600; }
    input,textarea,select { min-height:44px; border-color:#b9c7d7; }
    .primary { min-height:42px; border-color:var(--blue); background:var(--blue); padding:9px 16px; }
    .primary:hover { background:#17368f; border-color:#17368f; }
    .secondary { min-height:42px; border-color:#aab8ca; font-weight:700; }
    .secondary:hover,.inline-command:hover { border-color:var(--blue); color:var(--blue); background:#eff6ff; }
    .fit-grid { gap:10px; }
    .fit-item { border:1px solid var(--line); border-left:4px solid var(--blue); background:#fff; border-radius:6px; }
    .fit-item p { color:#46566d; }
    .workbench { border-radius:8px; overflow:hidden; box-shadow:var(--shadow); }
    .visual-pane { background:#111c2b; }
    .visual-toolbar { min-height:52px; }
    .segmented { border-radius:6px; overflow:hidden; }
    .segmented button { min-height:38px; }
    .segmented button.active { color:var(--blue); box-shadow:inset 0 -2px var(--blue); }
    .student-tab { min-height:88px; }
    .student-tab:hover { background:#f5f8fc; }
    .student-tab.active { box-shadow:inset 0 -4px var(--blue); background:#eef5ff; }
    .student-detail { padding:18px; }
    .portrait { width:88px; height:108px; border-radius:6px; }
    .score-ring { background:conic-gradient(var(--blue) var(--score),#e4eaf1 0); }
    .mini-actions { gap:7px; }
    .mini-actions div { border-radius:6px; background:#f7f9fc; }
    .student-strip { gap:10px; }
    .student-card { min-height:184px; border-radius:6px; box-shadow:0 2px 8px rgba(20,32,51,.04); }
    .student-card:hover { transform:translateY(-1px); box-shadow:0 7px 18px rgba(20,32,51,.08); }
    .student-card.active { border-color:var(--blue); box-shadow:inset 0 0 0 1px var(--blue); }
    .tabs { position:sticky; top:72px; z-index:8; overflow-x:auto; flex-wrap:nowrap; border-top:0; }
    .tab-cluster { flex:0 0 auto; }
    .tab-cluster > span { padding:0 10px; color:#526178; background:#e8edf4; }
    .tabs button { min-height:46px; padding:11px 14px; white-space:nowrap; }
    .tabs button:hover { color:var(--blue); background:#edf4ff; }
    .tab-body { border-top:0; padding:20px; min-height:430px; }
    .section,.workbench,.tab-body { scroll-margin-top:130px; }
    .result-summary { border-bottom:0; }
    .result-stat { min-height:70px; }
    .result-stat strong { font-size:19px; color:var(--navy); }
    .review-progress { margin-left:auto; padding:7px 10px; color:#0b625b; background:#e7f6f2; border:1px solid #b8ddd6; border-radius:6px; white-space:nowrap; }
    .summary-box { border-radius:6px; }
    table { font-size:13px; }
    th { color:#35445a; background:#eef2f7; }
    th,td { padding:11px 10px; }
    .scroll-table { border-radius:6px; }
    .callout { border-radius:0 6px 6px 0; background:#eef5ff; }
    .window-inspector { border-radius:6px; overflow:hidden; }
    .window-inspector > div + div { background:#f5f8fc; }
    .timeline { padding:5px 2px 12px; }
    .tick { min-width:34px; height:42px; border-radius:4px; }
    .tick:focus-visible { z-index:3; }
    .evidence-list { grid-template-columns:1fr; gap:14px; }
    .evidence { padding:0; border:1px solid var(--line); border-left:5px solid var(--amber); border-radius:6px; overflow:hidden; box-shadow:0 4px 13px rgba(20,32,51,.04); }
    .clip-heading { display:flex; align-items:center; justify-content:space-between; gap:12px; padding:13px 15px; background:#f7f9fc; border-bottom:1px solid var(--line); }
    .clip-heading > div { display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
    .clip-heading strong { margin:0; font-size:14px; color:var(--navy); }
    .clip-heading time { font:700 13px/1 "Bahnschrift","Microsoft YaHei UI",sans-serif; color:var(--blue); }
    .clip-id { display:inline-flex; align-items:center; min-height:26px; padding:0 8px; background:var(--navy); color:#fff !important; border-radius:4px; font:700 10px/1 "Bahnschrift",sans-serif; }
    .clip-context { display:flex; gap:8px; padding:10px 15px 0; }
    .clip-context span { padding:4px 8px; color:#40516a; background:#edf1f6; border-radius:4px; }
    .evidence > p,.judgement,.review-fieldset,.review-editor { margin-left:15px; margin-right:15px; }
    .judgement { margin-top:12px; padding:11px 12px; background:#eef5ff; border-left:3px solid var(--blue); }
    .judgement p { color:#34465f; margin:4px 0 0; }
    .review-reason { padding:9px 10px; color:#7a4500 !important; background:#fff6e8; }
    .locate-clip { margin:0 15px 2px; min-height:34px; padding:6px 10px; color:var(--blue); border:1px solid #a9bee3; background:#f4f8ff; font-size:11px; font-weight:700; }
    .locate-clip:hover { border-color:var(--blue); background:#e9f1ff; }
    .review-guide { display:grid; grid-template-columns:minmax(0,1fr) minmax(420px,.85fr); gap:18px; align-items:center; padding:16px 18px; margin-bottom:14px; background:var(--navy); color:#fff; border-radius:6px; }
    .review-guide h3 { margin:4px 0; font-size:18px; }
    .review-guide p { margin:0; color:#d7e3f2; font-size:12px; }
    .review-export { min-height:40px; margin-top:10px; padding:7px 10px; color:#fff; border:1px solid #7890ad; background:transparent; font-size:11px; font-weight:700; }
    .review-export:hover { border-color:#fff; background:rgba(255,255,255,.09); }
    .review-guide ol { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:7px 16px; margin:0; padding-left:24px; color:#e8eef7; font-size:12px; }
    .eyebrow { color:#8ed8cd; font-size:11px; font-weight:800; }
    .review-fieldset { border:0; padding:12px 0 0; }
    .review-fieldset legend { padding:0; color:#283a52; font-size:12px; font-weight:800; }
    .review-row { gap:8px; }
    .review-row button { min-width:88px; min-height:40px; border-radius:6px; font-weight:700; }
    .review-row button:hover { border-color:var(--blue); background:#eff6ff; }
    .review-row button.selected { border-color:var(--green); color:var(--green); background:#eaf8ef; box-shadow:inset 0 0 0 1px var(--green); }
    .review-row button.selected.correct { border-color:var(--red); color:var(--red); background:#fff1f0; box-shadow:inset 0 0 0 1px var(--red); }
    .review-row button.selected.uncertain { border-color:var(--amber); color:#8a4300; background:#fff5e7; box-shadow:inset 0 0 0 1px var(--amber); }
    .field-help { color:#607086 !important; font-size:11px !important; }
    .review-editor { grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; padding:13px 0 16px; border-top:1px solid #e5eaf0; }
    .review-editor label { margin:0; font-size:11px; }
    .review-editor select,.review-editor input { margin-top:6px; min-height:42px; font-size:12px; }
    .review-note-label { grid-column:1/-1; }
    .review-editor input { grid-column:auto; width:100%; }
    .save-review { min-height:40px; margin-top:2px; padding:7px 12px; border-radius:6px; font-weight:700; }
    .course-report-head,.support-banner { display:flex; justify-content:space-between; align-items:center; gap:16px; padding:16px 18px; margin-bottom:14px; background:var(--navy); color:#fff; border-radius:6px; }
    .course-report-head h3,.support-banner h3 { margin:3px 0; font-size:19px; }
    .course-report-head p,.support-banner p { margin:0; color:#d6e1ef; font-size:12px; }
    .course-report-head .secondary,.support-banner .secondary { color:#fff; border-color:#7890ad; background:transparent; white-space:nowrap; }
    .course-report { max-width:980px; margin:auto; padding:26px 30px; border:1px solid var(--line); border-top:5px solid var(--blue); background:#fff; box-shadow:var(--shadow); }
    .course-report p { margin:0; white-space:pre-wrap; color:#2d3e56; font-size:14px; line-height:2; }
    .support-tool-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; margin-bottom:12px; }
    .support-tool { min-height:178px; padding:15px; border:1px solid var(--line); border-top:4px solid var(--teal); border-radius:6px; background:#fff; }
    .support-tool:nth-child(2) { border-top-color:var(--blue); }
    .support-tool:nth-child(3) { border-top-color:var(--purple); }
    .support-tool:nth-child(4) { border-top-color:var(--amber); }
    .support-tool > span { color:#5d6c80; font-size:11px; font-weight:800; }
    .support-tool h3 { margin:9px 0 7px; color:var(--navy); font-size:15px; line-height:1.55; }
    .support-tool h3 b { display:inline-block; margin:0 5px 5px 0; padding:4px 7px; border-radius:4px; background:#edf1f6; font-size:11px; }
    .support-tool p { color:#5b6a7f; font-size:12px; }
    .safety-block { border-left:4px solid var(--amber); background:#fffaf2; }
    .support-controls { display:flex; align-items:center; gap:10px; margin:0 0 12px; padding:12px; border:1px solid var(--line); background:#f5f8fc; }
    .support-controls button { min-height:38px; padding:7px 11px; border:1px solid #aab8ca; background:#fff; color:var(--navy); font-weight:700; }
    .support-controls button:hover { border-color:var(--blue); color:var(--blue); }
    .support-controls output { min-width:180px; color:var(--teal); font-weight:800; }
    .info-block,.metric-card { border-radius:6px; }
    .entry-gate { background:#e9eef4; padding:28px 18px; }
    .entry-shell { width:min(1120px,100%); border-radius:8px; overflow:hidden; box-shadow:0 24px 64px rgba(16,35,63,.18); }
    .entry-head { background:var(--navy); color:#fff; }
    .entry-head p { color:#cbd8e8; }
    .entry-step { color:#a8e2da; }
    .entry-body { background:#fff; }
    .confirm-check { border-radius:0 6px 6px 0; }
    @media (prefers-reduced-motion:reduce) {
      *,*::before,*::after { scroll-behavior:auto !important; transition:none !important; animation:none !important; }
    }
    @media (max-width:1050px) {
      .input-grid,.fit-grid,.student-strip { grid-template-columns:1fr; }
      .workbench { grid-template-columns:1fr; }
      .visual-pane { border-right:0; border-bottom:1px solid var(--line); }
      .stage { min-height:400px; }
      .tab-cluster { flex:1 1 auto; }
      .review-guide { grid-template-columns:1fr; }
      .support-tool-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
    }
    @media (max-width:680px) {
      header { position:static; }
      .topbar { padding:10px 12px; flex-wrap:wrap; }
      .brand { min-width:0; width:100%; }
      .top-actions { margin-left:0; width:100%; }
      .course-select { min-width:0; }
      main { padding:12px; }
      .stage { min-height:0; aspect-ratio:16/9; }
      .stage img { max-height:none; }
      .section-body,.tab-body { padding:12px; }
      .student-tabs { grid-template-columns:1fr; }
      .student-tab { border-right:0; border-bottom:1px solid var(--line); }
      .evidence-list { grid-template-columns:1fr; }
      .score-row { grid-template-columns:1fr; }
      .summary-grid,.action-stack,.tracking-grid,.teacher-grid,.profile-grid,.report-grid { grid-template-columns:1fr; }
      .report-layout { grid-template-columns:1fr; }
      .report-nav { position:static; max-height:none; }
      .entry-grid { grid-template-columns:1fr; }
      .entry-grid .wide { grid-column:auto; }
      .result-summary,.window-inspector { grid-template-columns:1fr; }
      .result-stat { border-right:0; border-bottom:1px solid var(--line); }
      .window-inspector > div + div { border-left:0; border-top:1px solid var(--line); }
      .tabs { position:static; }
      .tab-cluster { width:auto; flex:0 0 auto; border-right:1px solid var(--line); border-bottom:0; }
      .section-head { align-items:flex-start; }
      .review-progress { margin-left:0; }
      .review-guide ol { grid-template-columns:1fr; }
      .review-editor,.support-tool-grid { grid-template-columns:1fr; }
      .review-note-label { grid-column:auto; }
      .clip-heading,.course-report-head,.support-banner { align-items:flex-start; flex-direction:column; }
      .course-report { padding:18px; }
      .top-actions { flex-wrap:wrap; }
      .status { width:100%; max-width:none; }
      .support-controls { align-items:stretch; flex-direction:column; }
      .support-controls output { min-width:0; }
    }

    /* Demo2 v6: video-first classroom evidence studio. */
    :root {
      --bg:#f1f3f1; --panel:#ffffff; --soft:#f5f7f6; --ink:#172321; --muted:#63706d;
      --line:#d8dfdc; --blue:#3157a4; --blue-2:#4169b5; --teal:#147d73; --green:#187153;
      --amber:#b55b1e; --red:#b33a32; --purple:#6a4c93; --navy:#173d3a;
      --charcoal:#1d2529; --coral:#d65e3f; --lime:#b9d36b;
      --shadow:0 14px 38px rgba(28,47,43,.08);
    }
    html { background:var(--bg); }
    body { background:var(--bg); color:var(--ink); font-family:"Noto Sans SC","Microsoft YaHei UI","Microsoft YaHei",sans-serif; font-size:14px; }
    h1,h2,h3,.brand strong,.fit-score,.big,.teacher-score,.result-stat strong { font-family:"Noto Sans SC","Microsoft YaHei UI",sans-serif; }
    button,input,textarea,select { font-family:inherit; }
    button { border-radius:4px; }
    input,textarea,select { border-radius:4px; background:#fff; }
    a,button { -webkit-tap-highlight-color:transparent; }
    .eyebrow { display:block; margin-bottom:5px; color:var(--teal); font-size:10px; font-weight:800; line-height:1.2; letter-spacing:.12em; }

    header { position:sticky; top:0; z-index:20; background:rgba(255,255,255,.97); border-bottom:1px solid var(--line); box-shadow:none; }
    .topbar { max-width:1600px; min-height:68px; padding:9px 28px; }
    .brand { min-width:330px; display:flex; align-items:center; gap:12px; padding:0; border:0; }
    .brand-mark { width:39px; height:39px; display:grid !important; place-items:center; flex:0 0 auto; margin:0 !important; color:#fff !important; background:var(--navy); border-radius:4px; font:800 12px/1 "Segoe UI",sans-serif; letter-spacing:.04em; }
    .brand strong { font-size:17px; color:var(--ink); line-height:1.2; }
    .brand div > span { margin-top:3px; color:#73807c; font-size:10px; }
    .top-actions { gap:12px; }
    .status { max-width:280px; display:inline-flex; align-items:center; gap:7px; padding:6px 10px; color:#315c53; background:#eef6f2; border:1px solid #d0e5dc; border-radius:999px; font-size:11px; }
    .status i,.section-status i { width:7px; height:7px; flex:0 0 auto; background:#2d9a72; border-radius:50%; box-shadow:0 0 0 3px rgba(45,154,114,.13); }
    .course-select { min-width:280px; min-height:42px; border-color:#cbd4d0; background:#fff; font-size:13px; }
    .ghost-link { color:#36564f; font-size:12px; text-decoration:none; border-bottom:1px solid transparent; }
    .ghost-link:hover { color:var(--teal); border-bottom-color:var(--teal); }

    main { max-width:1600px; padding:30px 28px 54px; }
    .page-intro { display:flex; justify-content:space-between; align-items:flex-end; gap:32px; margin:0 0 24px; padding:0 2px; }
    .page-intro h1 { margin:0; color:#153733; font-family:"Noto Serif SC","Songti SC",serif; font-size:35px; font-weight:700; line-height:1.25; }
    .page-intro p { max-width:850px; margin:8px 0 0; color:#687572; font-size:13px; line-height:1.7; }
    .page-intro-note { min-width:250px; display:grid; grid-template-columns:auto auto; gap:5px 12px; padding:12px 14px; border-left:3px solid var(--coral); background:#fff; }
    .page-intro-note b { grid-column:1/-1; color:#344743; font-size:11px; }
    .page-intro-note span { color:#6d7876; font-size:10px; }

    .section { margin-bottom:28px; }
    .section-head { min-height:68px; padding:14px 18px; border:0; }
    .section-head h2,.analysis-heading h2 { margin:0; color:#183d39; font-size:20px; line-height:1.3; }
    .section-head p,.analysis-heading p { margin:4px 0 0; color:#6b7774; font-size:12px; }
    .course-foundation { overflow:hidden; background:#fff; border:1px solid var(--line); border-radius:5px; box-shadow:0 5px 16px rgba(28,47,43,.04); }
    .course-foundation summary { cursor:pointer; list-style:none; }
    .course-foundation summary::-webkit-details-marker { display:none; }
    .course-foundation .section-head { justify-content:space-between; }
    .course-foundation .section-head::after { content:"+"; width:30px; height:30px; display:grid; place-items:center; flex:0 0 auto; margin-left:8px; color:#315c53; border:1px solid #c8d6d1; border-radius:50%; font-size:18px; font-weight:400; }
    .course-foundation[open] .section-head::after { content:"−"; }
    .disclosure-label { margin-left:auto; color:#61706c; font-size:11px; white-space:nowrap; }
    .course-foundation .section-body { border:0; border-top:1px solid var(--line); box-shadow:none; }
    .section-status { margin-left:auto; display:inline-flex; align-items:center; gap:8px; color:#49615c; font-size:11px; white-space:nowrap; }

    .observation-section { background:#fff; border:1px solid #cfd8d4; border-radius:5px; box-shadow:var(--shadow); overflow:hidden; }
    .observation-section > .section-head { border-bottom:1px solid var(--line); }
    .workbench { grid-template-columns:minmax(0,1.62fr) minmax(420px,.78fr); min-height:680px; border:0; border-radius:0; box-shadow:none; }
    .visual-pane { border-right:1px solid #394247; background:var(--charcoal); }
    .visual-toolbar { min-height:54px; padding:9px 16px; color:#e8edeb; background:#252e32; border-color:#3a4448; }
    .visual-toolbar .segmented { border-color:#4c575b; background:#1d2529; }
    .visual-toolbar .segmented button { color:#aeb9b6; border-color:#4c575b; }
    .visual-toolbar .segmented button.active { color:#fff; background:#147d73; box-shadow:none; }
    .visual-note { color:#aeb9b6; }
    .stage { min-height:620px; background:#172024; }
    .stage img { max-height:690px; }
    .student-pane { display:flex; flex-direction:column; background:#fbfcfb; }
    .student-tabs { flex:0 0 auto; background:#f0f3f1; }
    .student-tab { min-height:82px; padding:13px 14px; border-color:#d8dfdc; }
    .student-tab:hover { background:#fff; }
    .student-tab.active { color:#123d38; background:#fff; box-shadow:inset 0 -4px var(--coral); }
    .student-tab strong { font-size:13px; }
    .student-tab span { margin-top:5px; display:block; font-size:10px; line-height:1.45; }
    .student-detail { flex:1; padding:24px; }
    .portrait { width:78px; height:98px; border:0; border-radius:4px; box-shadow:0 0 0 1px #cfd8d4; }
    .student-title { align-items:flex-start; }
    .student-title h3 { color:#173d3a; font-family:"Noto Serif SC","Songti SC",serif; font-size:22px; }
    .score-row { grid-template-columns:108px 1fr; margin:23px 0; }
    .score-ring { width:104px; height:104px; background:conic-gradient(var(--coral) var(--score),#e5eae7 0); }
    .score-ring strong { font-size:27px; font-variant-numeric:tabular-nums; }
    .metric { grid-template-columns:74px 1fr 32px; font-size:10px; }
    .bar { height:7px; border-radius:999px; background:#e2e8e5; }
    .bar i { background:var(--teal); border-radius:999px; }
    .student-detail .callout { margin:18px 0; background:#edf5f1; border-color:var(--teal); }
    .mini-actions { grid-template-columns:1fr 1fr; gap:8px; }
    .mini-actions div { min-height:76px; padding:11px; background:#fff; border-color:#d6dedb; }

    .analysis-studio { background:transparent; }
    .analysis-heading { display:flex; justify-content:space-between; align-items:flex-end; gap:20px; padding:0 2px 14px; }
    .review-progress { margin-left:auto; padding:8px 12px; color:#74401b; background:#fff5eb; border:1px solid #edceb8; border-radius:999px; }
    .student-strip { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:0; margin:0 0 12px; border:1px solid var(--line); background:#fff; border-radius:5px; overflow:hidden; }
    .student-card { min-height:126px; padding:17px 18px; border:0; border-right:1px solid var(--line); border-radius:0; box-shadow:none; }
    .student-card:last-child { border-right:0; }
    .student-card:hover { transform:none; background:#f4f8f6; box-shadow:none; }
    .student-card.active { border-color:transparent; background:#edf5f1; box-shadow:inset 0 -4px var(--teal); }
    .student-card header { background:transparent; }
    .student-card h3 { color:#183d39; font-size:14px; }
    .student-card .big { color:var(--coral); font-size:30px; font-variant-numeric:tabular-nums; }
    .student-card p { margin:5px 0 0; color:#64716e; font-size:11px; }

    .analysis-layout { display:grid; grid-template-columns:215px minmax(0,1fr); align-items:start; border:1px solid #cfd8d4; border-radius:5px; background:#fff; box-shadow:var(--shadow); overflow:visible; }
    .tabs { position:sticky; top:86px; z-index:7; display:block; max-height:calc(100vh - 110px); overflow:auto; padding:10px; background:#1f302e; border:0; border-radius:0; }
    .tab-cluster { display:block; border:0; }
    .tab-cluster + .tab-cluster { margin-top:9px; padding-top:9px; border-top:1px solid #3d4c49; }
    .tab-cluster > span { display:block; padding:5px 10px; color:#93a39f; background:transparent; font-size:9px; letter-spacing:.11em; }
    .tabs button { width:100%; min-height:39px; display:block; padding:8px 10px; border-radius:3px; color:#d2d9d7; text-align:left; font-size:12px; }
    .tabs button:hover { color:#fff; background:#314440; }
    .tabs button.active { color:#163c38; background:#c8ded6; box-shadow:none; font-weight:800; }
    .analysis-content { min-width:0; background:#fff; }
    .result-summary { grid-template-columns:repeat(4,minmax(0,1fr)); border:0; border-bottom:1px solid var(--line); background:#f6f8f7; }
    .result-stat { min-height:76px; padding:14px 16px; border-color:var(--line); }
    .result-stat span { color:#71807c; font-size:9px; letter-spacing:.05em; }
    .result-stat strong { color:#173d3a; font-size:17px; }
    .tab-body { min-height:520px; padding:24px; border:0; background:#fff; }
    .tab-body > h3 { margin:22px 0 10px; color:#173d3a; font-size:15px; }
    .tab-body > h3:first-child { margin-top:0; }
    table { font-size:12px; }
    th { color:#435450; background:#f0f3f1; }
    th,td { padding:12px 11px; }
    .scroll-table { border-color:#d5ddda; border-radius:4px; }
    .callout { color:#38534d; background:#eff6f3; border-color:var(--teal); border-radius:0 4px 4px 0; }
    .info-block { border-color:#d8dfdc; border-radius:4px; background:#fff; }
    .info-block h3 { color:#173d3a; }
    .metric-card { border-radius:4px; }
    .summary-box { border-radius:4px; }
    .course-report-head,.support-banner,.review-guide { background:#193d3a; border-radius:4px; }
    .course-report { border-top-color:var(--coral); }
    .review-guide { box-shadow:none; }
    .review-export { border-color:#8aa7a0; }
    .clip-id { background:#244b46; }
    .evidence { border-left-color:var(--coral); border-radius:4px; }
    .judgement { background:#eef4fb; border-color:var(--blue); }
    .review-reason { background:#fff3e9; }
    .review-row button.selected { border-color:var(--teal); color:var(--teal); background:#edf7f3; box-shadow:inset 0 0 0 1px var(--teal); }
    .support-tool { border-radius:4px; }
    pre { border-radius:4px; background:#182522; color:#dbe9e4; }
    .privacy { color:#684321; background:#fff7ef; border-color:#efd8c4; border-radius:4px; }

    .entry-gate { display:grid; place-items:center; padding:28px; background:#dde5e2; }
    .entry-shell { width:min(1180px,100%); min-height:760px; display:grid; grid-template-columns:390px minmax(0,1fr); margin:auto; overflow:hidden; background:#fff; border:0; border-radius:6px; box-shadow:0 28px 80px rgba(23,61,58,.20); }
    .entry-head { min-width:0; display:flex; flex-direction:column; justify-content:space-between; padding:48px 40px 38px; background:#173d3a; color:#fff; border:0; }
    .entry-kicker { display:block; color:#b9d36b; font-size:9px; font-weight:800; letter-spacing:.17em; }
    .entry-head h1 { margin:26px 0 18px; color:#fff; font-family:"Noto Serif SC","Songti SC",serif; font-size:36px; font-weight:700; line-height:1.5; }
    .entry-head h1 em { color:#d9e6a4; font-style:normal; }
    .entry-head > div > p { max-width:300px; color:#cfddda; font-size:13px; line-height:1.85; }
    .entry-flow { display:grid; gap:0; margin:30px 0; }
    .entry-flow div { position:relative; display:grid; grid-template-columns:42px 1fr; grid-template-rows:auto auto; column-gap:12px; min-height:68px; color:#a8bab6; }
    .entry-flow div:not(:last-child)::after { content:""; position:absolute; left:15px; top:31px; bottom:0; width:1px; background:#54706a; }
    .entry-flow span { grid-row:1/3; width:31px; height:31px; display:grid; place-items:center; color:#a9b9b6; border:1px solid #607873; border-radius:50%; font:700 9px/1 "Segoe UI",sans-serif; }
    .entry-flow b { align-self:end; color:#d4dfdc; font-size:13px; }
    .entry-flow small { color:#8fa39e; font-size:10px; }
    .entry-flow .active span { color:#173d3a; background:#c9dc7d; border-color:#c9dc7d; }
    .entry-flow .active b { color:#fff; }
    .entry-boundary { margin:0 !important; padding-top:18px; color:#a9bbb7 !important; border-top:1px solid #42605a; font-size:10px !important; line-height:1.7 !important; }
    .entry-body { padding:42px 46px 34px; background:#fff; overflow:auto; }
    .entry-body-head { margin-bottom:24px; }
    .entry-body-head h2 { margin:7px 0 5px; color:#173d3a; font-family:"Noto Serif SC","Songti SC",serif; font-size:28px; }
    .entry-body-head p { margin:0; color:#74817e; font-size:12px; }
    .entry-step { color:var(--teal); font-size:10px; letter-spacing:.08em; }
    .entry-grid { grid-template-columns:.9fr 1.1fr; gap:13px 14px; }
    .entry-grid label { font-size:11px; }
    .entry-grid input,.entry-grid select { min-height:42px; }
    .entry-grid textarea { min-height:88px; }
    .confirm-check { margin:15px 0 13px; padding:11px 12px; color:#684321; background:#fff5eb; border-left-color:var(--coral); border-radius:0 4px 4px 0; }
    .entry-body .action-row { margin-top:10px; }
    .entry-body .primary { background:var(--coral); border-color:var(--coral); }
    .entry-body .primary:hover { background:#bd4c31; border-color:#bd4c31; }

    @media (max-width:1120px) {
      .page-intro { align-items:flex-start; }
      .workbench { grid-template-columns:1fr; }
      .visual-pane { border-right:0; border-bottom:1px solid #394247; }
      .stage { min-height:520px; }
      .student-pane { display:block; }
      .student-detail { min-height:460px; }
      .analysis-layout { grid-template-columns:190px minmax(0,1fr); }
      .result-summary { grid-template-columns:repeat(2,minmax(0,1fr)); }
      .result-stat:nth-child(2) { border-right:0; }
      .result-stat:nth-child(-n+2) { border-bottom:1px solid var(--line); }
    }
    @media (max-width:820px) {
      header { position:static; }
      .topbar { flex-wrap:wrap; padding:10px 16px; }
      .brand { width:100%; min-width:0; }
      .top-actions { width:100%; margin:0; flex-wrap:wrap; }
      .course-select { flex:1; min-width:210px; }
      main { padding:22px 14px 42px; }
      .page-intro { display:block; }
      .page-intro h1 { font-size:29px; }
      .page-intro-note { margin-top:16px; }
      .section-head { align-items:flex-start; }
      .section-status { margin-top:4px; }
      .student-strip { grid-template-columns:1fr; }
      .student-card { min-height:112px; border-right:0; border-bottom:1px solid var(--line); }
      .student-card:last-child { border-bottom:0; }
      .student-card.active { box-shadow:inset 4px 0 var(--teal); }
      .analysis-layout { grid-template-columns:1fr; overflow:hidden; }
      .tabs { position:static; max-height:none; display:flex; overflow-x:auto; padding:8px; background:#1f302e; }
      .tab-cluster { display:flex; flex:0 0 auto; }
      .tab-cluster + .tab-cluster { margin:0 0 0 8px; padding:0 0 0 8px; border-top:0; border-left:1px solid #3d4c49; }
      .tab-cluster > span { display:flex; align-items:center; width:48px; padding:4px 7px; }
      .tabs button { width:auto; min-width:78px; text-align:center; white-space:nowrap; }
      .analysis-heading { align-items:flex-start; flex-direction:column; }
      .review-progress { margin:0; }
      .entry-gate { display:block; padding:18px; }
      .entry-shell { min-height:0; grid-template-columns:1fr; }
      .entry-head { min-height:360px; padding:34px 30px 28px; }
      .entry-head h1 { font-size:30px; }
      .entry-flow { grid-template-columns:repeat(3,1fr); gap:8px; }
      .entry-flow div { grid-template-columns:34px 1fr; min-height:52px; }
      .entry-flow div::after { display:none; }
      .entry-body { padding:30px; }
    }
    @media (max-width:560px) {
      body { font-size:13px; }
      .topbar { padding:9px 12px; }
      .status { width:100%; max-width:none; }
      .course-select { width:100%; min-width:0; }
      .page-intro h1 { font-size:27px; }
      .page-intro-note { min-width:0; }
      .section-head { padding:14px; }
      .section-head h2,.analysis-heading h2 { font-size:18px; }
      .disclosure-label { display:none; }
      .workbench { min-height:0; }
      .stage { min-height:0; aspect-ratio:16/9; }
      .student-tabs { grid-template-columns:1fr; }
      .student-tab { min-height:68px; border-right:0; border-bottom:1px solid var(--line); }
      .student-tab.active { box-shadow:inset 4px 0 var(--coral); }
      .student-detail { min-height:0; padding:18px 16px; }
      .student-title h3 { font-size:19px; }
      .score-row { grid-template-columns:92px 1fr; }
      .score-ring { width:88px; height:88px; }
      .score-ring::after { width:66px; height:66px; }
      .score-ring strong { font-size:23px; }
      .mini-actions { grid-template-columns:1fr; }
      .analysis-heading { padding-left:0; padding-right:0; }
      .result-summary { grid-template-columns:1fr 1fr; }
      .result-stat { min-height:82px; padding:12px; }
      .result-stat strong { font-size:15px; }
      .tab-body { min-height:420px; padding:16px 13px; }
      .tabs { margin:0; }
      .summary-grid,.action-stack,.tracking-grid,.teacher-grid,.profile-grid,.report-grid,.support-tool-grid { grid-template-columns:1fr; }
      .entry-gate { padding:0; background:#fff; }
      .entry-shell { width:100%; border-radius:0; box-shadow:none; }
      .entry-head { min-height:360px; padding:32px 22px 25px; }
      .entry-head h1 { margin:20px 0 14px; font-size:28px; }
      .entry-head > div > p { font-size:12px; }
      .entry-flow { display:grid; grid-template-columns:1fr; margin:20px 0; }
      .entry-flow div { min-height:50px; }
      .entry-flow div:not(:last-child)::after { display:block; left:15px; top:31px; }
      .entry-body { padding:25px 18px 30px; }
      .entry-body-head h2 { font-size:24px; }
      .entry-grid { grid-template-columns:1fr; }
      .entry-grid .wide { grid-column:auto; }
      .entry-body .action-row { align-items:stretch; flex-direction:column; }
      .entry-body .primary { width:100%; }
      .course-report-head,.support-banner,.clip-heading { align-items:flex-start; flex-direction:column; }
      .review-editor { grid-template-columns:1fr; }
      .review-note-label { grid-column:auto; }
    }

    /* Demo2 v7: blue-and-white, child-friendly evidence workspace. */
    :root {
      --bg:#f4f9ff; --panel:#ffffff; --soft:#f1f7ff; --ink:#18324a; --muted:#61768a;
      --line:#d7e7f6; --blue:#2f80ed; --blue-2:#5aa2f2; --teal:#39a98e; --green:#2c946c;
      --amber:#d69216; --red:#d95c58; --purple:#7d6bd6; --navy:#1d4f86;
      --charcoal:#17324d; --coral:#f07872; --lime:#f1c552;
      --shadow:0 10px 28px rgba(46,105,166,.10);
    }
    html,body { background:var(--bg); }
    body { color:var(--ink); font-family:"Microsoft YaHei UI","PingFang SC","Microsoft YaHei",sans-serif; font-size:14px; }
    h1,h2,h3,.brand strong,.fit-score,.big,.teacher-score,.result-stat strong {
      font-family:"Microsoft YaHei UI","PingFang SC","Microsoft YaHei",sans-serif;
    }
    button,input,textarea,select { border-radius:8px; }
    button { min-height:44px; }
    .primary { background:var(--blue); border-color:var(--blue); border-radius:8px; box-shadow:0 4px 12px rgba(47,128,237,.18); }
    .primary:hover { background:#216fce; border-color:#216fce; }
    .secondary { color:#28547f; border-color:#b9d5ef; border-radius:8px; }
    .secondary:hover,.inline-command:hover { color:#1e6fc5; background:#eef6ff; border-color:#79afe2; }

    header { background:#fff; border-bottom-color:#dceafa; }
    .topbar { max-width:1540px; min-height:72px; padding:10px 24px; }
    .brand { gap:11px; }
    .brand-mark { width:42px; height:42px; color:#fff !important; background:var(--blue); border-radius:8px; box-shadow:inset 0 -3px rgba(20,85,155,.14); }
    .brand strong { color:#204c78; font-size:17px; }
    .brand div > span { color:#74899d; font-size:11px; }
    .status { color:#217a60; background:#eefaf6; border-color:#cdece2; border-radius:999px; }
    .course-select { border-color:#c9dff2; border-radius:8px; }
    .ghost-link { color:#3977b3; }
    main { max-width:1540px; padding:28px 24px 56px; }

    .page-intro { align-items:center; margin-bottom:18px; }
    .page-intro h1 { color:#1f5488; font-family:inherit; font-size:34px; line-height:1.3; }
    .page-intro p { color:#657b90; }
    .page-intro-note { border:1px solid #d6e6f5; border-left:5px solid var(--lime); border-radius:8px; background:#fff; box-shadow:0 5px 16px rgba(46,105,166,.06); }
    .page-intro-note b { color:#244d73; }
    .eyebrow { display:inline-flex; width:max-content; margin-bottom:7px; padding:5px 8px; color:#2b70af; background:#e8f3ff; border-radius:6px; letter-spacing:.08em; }
    .layer-ribbon { display:grid; grid-template-columns:1fr 18px 1fr 18px 1fr 18px 1fr; align-items:center; margin:0 0 24px; padding:14px 16px; background:#fff; border:1px solid var(--line); border-radius:8px; box-shadow:0 6px 18px rgba(46,105,166,.06); }
    .layer-ribbon div { min-width:0; padding:4px 8px; }
    .layer-ribbon b,.layer-ribbon span { display:block; }
    .layer-ribbon b { color:#285d91; font-size:13px; }
    .layer-ribbon span { margin-top:3px; color:#7a8d9e; font-size:10px; }
    .layer-ribbon i { height:2px; background:#b8d8f5; position:relative; }
    .layer-ribbon i::after { content:""; position:absolute; right:0; top:-3px; width:0; height:0; border-left:6px solid #83b9ea; border-top:4px solid transparent; border-bottom:4px solid transparent; }

    .section { margin-bottom:24px; }
    .course-foundation,.observation-section,.analysis-layout { border-color:var(--line); border-radius:8px; background:#fff; box-shadow:var(--shadow); }
    .course-foundation .section-head,.observation-section > .section-head { min-height:68px; padding:14px 18px; background:#fff; }
    .section-head h2,.analysis-heading h2 { color:#245987; }
    .course-foundation .section-head::after { color:#377ab8; border-color:#b9d6ef; }
    .section-status { color:#3c7183; }
    .fit-item { border-color:#d8e7f5; border-left-color:var(--blue); border-radius:8px; background:#f8fbff; }
    .fit-item.warn { border-left-color:var(--amber); }

    .workbench { grid-template-columns:minmax(0,1.58fr) minmax(410px,.82fr); min-height:660px; }
    .visual-pane { background:#132d46; border-right-color:#234564; }
    .visual-toolbar { color:#dcecff; background:#183854; border-color:#2a4d6a; }
    .visual-toolbar .segmented { background:#102b43; border-color:#3a5f7d; border-radius:8px; }
    .visual-toolbar .segmented button { color:#c6d9e9; border-color:#3a5f7d; }
    .visual-toolbar .segmented button.active { color:#174d7f; background:#dceeff; }
    .visual-note { color:#c5d9ea; }
    .stage { min-height:590px; background:#102840; }
    .student-pane { background:#fbfdff; }
    .student-tabs { background:#eef6ff; }
    .student-tab { border-color:#d4e5f4; }
    .student-tab:hover { background:#f8fbff; }
    .student-tab.active { color:#225b8f; background:#fff; box-shadow:inset 0 -4px var(--blue); }
    .portrait { border-radius:8px; box-shadow:0 0 0 1px #cbdff1; }
    .student-title h3 { color:#245987; font-family:inherit; }
    .score-ring { background:conic-gradient(var(--blue) var(--score),#e6f0fa 0); }
    .bar { background:#e4eff8; }
    .bar i { background:var(--teal); }
    .student-detail .callout { color:#345c77; background:#eef7ff; border-color:var(--blue); }
    .mini-actions div { min-height:74px; border-color:#d7e7f6; border-radius:8px; background:#fff; }

    .analysis-heading { align-items:center; }
    .review-progress { color:#92610b; background:#fff8e6; border-color:#efdca4; }
    .student-strip { gap:10px; padding:10px; border-color:var(--line); border-radius:8px; background:#eef6ff; }
    .student-card { min-height:132px; border:1px solid #d4e5f4; border-radius:8px; background:#fff; }
    .student-card:last-child { border-right:1px solid #d4e5f4; }
    .student-card:hover { background:#f8fbff; }
    .student-card.active { border-color:#76b3eb; background:#eaf5ff; box-shadow:inset 0 -4px var(--blue); }
    .student-card h3 { color:#285d91; }
    .student-card .big { color:var(--blue); }
    .analysis-layout { grid-template-columns:220px minmax(0,1fr); overflow:visible; }
    .tabs { background:#f3f8fe; border-right:1px solid var(--line); }
    .tab-cluster + .tab-cluster { border-top-color:#d6e6f4; }
    .tab-cluster > span { color:#6a8297; background:transparent; }
    .tabs button { color:#496a87; border-radius:7px; }
    .tabs button:hover { color:#1f69ad; background:#e7f3ff; }
    .tabs button.active { color:#fff; background:var(--blue); box-shadow:0 4px 10px rgba(47,128,237,.17); }
    .analysis-content,.tab-body { background:#fff; }
    .result-summary { background:#f7fbff; }
    .result-stat { border-color:var(--line); }
    .result-stat strong { color:#245987; }
    th { color:#3f617e; background:#edf6ff; }
    th,td { border-color:#dce9f5; }
    tr.selectable:hover,tr.selectable.selected { background:#eef7ff; }
    .callout { color:#345d78; background:#eef7ff; border-color:var(--blue); border-radius:0 8px 8px 0; }
    .info-block { border-color:#d7e7f6; border-radius:8px; background:#fff; }
    .info-block h3 { color:#285d91; }
    .metric-card { border-radius:8px; }
    .metric-card:nth-child(2n) { background:#f7fbff; }
    .course-report-head,.support-banner,.review-guide { color:#214d75; background:#eaf5ff; border:1px solid #cfe4f7; border-radius:8px; }
    .course-report-head p,.support-banner p,.review-guide p,.review-guide ol { color:#58758e; }
    .course-report-head .secondary,.support-banner .secondary,.review-export { color:#2b6fac; border-color:#8fbee7; background:#fff; }
    .course-report { border-top-color:var(--blue); }
    .clip-id { background:#397fbc; border-radius:6px; }
    .evidence { border-color:#d4e5f4; border-left-color:var(--amber); border-radius:8px; }
    .clip-heading { background:#f3f8fe; }
    .judgement { background:#eef7ff; }
    .review-reason { background:#fff8e8; }
    .interaction-chain { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; margin:12px 15px; }
    .interaction-step { min-height:132px; padding:12px; border:1px solid #d6e6f4; border-radius:8px; background:#fff; position:relative; }
    .interaction-step + .interaction-step::before { content:""; position:absolute; left:-11px; top:32px; width:10px; height:2px; background:#9bc8ed; }
    .interaction-step span { color:#2e76b6; font-size:10px; font-weight:800; }
    .interaction-step p { color:#4e6b84; }
    .interaction-result { display:flex; align-items:center; justify-content:space-between; gap:12px; margin:0 15px 14px; padding:10px 12px; color:#2e6c58; background:#eefaf6; border:1px solid #cceadf; border-radius:8px; }
    .interaction-result strong { font-size:13px; }
    .interaction-result b { min-width:44px; color:#2475bc; font-size:20px; }
    .tick.not_observed { background:#e9eef5; border:1px dashed #9eb1c4; }
    .tick.uncertain { background:#ded8f0; }
    .state-tag { color:#2b739f; }

    .person-hero { display:grid; grid-template-columns:auto minmax(0,1fr) auto; gap:16px; align-items:center; margin-bottom:16px; padding:16px; background:#eef7ff; border:1px solid #d5e7f7; border-radius:8px; }
    .person-hero img { width:72px; height:90px; object-fit:cover; border-radius:8px; }
    .person-hero h3 { margin:0; color:#245987; font-size:20px; }
    .person-hero p { margin:5px 0 0; color:#657c91; }
    .person-score { text-align:right; }
    .person-score strong,.person-score span { display:block; }
    .person-score strong { color:var(--blue); font-size:30px; }
    .person-score span { color:#72879a; font-size:10px; }
    .case-path { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:8px; margin-bottom:16px; }
    .case-path div { padding:10px; border-left:4px solid var(--blue); background:#f7fbff; border-radius:0 8px 8px 0; }
    .case-path b,.case-path span { display:block; }
    .case-path b { color:#2d6598; font-size:12px; }
    .case-path span { margin-top:4px; color:#75899b; font-size:10px; }

    .growth-head { display:flex; justify-content:space-between; gap:18px; margin-bottom:14px; padding:14px 16px; background:#eef7ff; border:1px solid #d5e7f7; border-radius:8px; }
    .growth-head h3 { margin:0 0 5px; color:#245987; }
    .growth-head p { margin:0; color:#617990; }
    .evidence-grade { min-width:120px; align-self:center; padding:8px 10px; color:#8c620f; background:#fff7dc; border:1px solid #ead58e; border-radius:8px; text-align:center; font-weight:800; }
    .growth-chart { padding:14px; border:1px solid #d7e7f6; border-radius:8px; background:#fff; overflow:auto; }
    .growth-chart svg { display:block; width:100%; min-width:680px; height:auto; }
    .growth-legend { display:flex; flex-wrap:wrap; gap:8px 16px; margin-top:10px; }
    .growth-legend span { display:inline-flex; align-items:center; gap:6px; color:#5c748a; font-size:11px; }
    .growth-legend i { width:16px; height:3px; border-radius:2px; }

    .entry-gate { display:grid; place-items:center; padding:28px; background:#eaf4ff; }
    .entry-shell { width:min(1080px,100%); min-height:650px; grid-template-columns:340px minmax(0,1fr); border:1px solid #cfe2f4; border-radius:8px; box-shadow:0 22px 62px rgba(46,105,166,.17); }
    .entry-head { padding:42px 32px 32px; color:#214e78; background:#dceeff; border-right:1px solid #c6dff3; }
    .entry-kicker { color:#2c77b8; }
    .entry-head h1 { color:#215482; font-family:inherit; font-size:32px; line-height:1.48; }
    .entry-head h1 em { color:#d18114; }
    .entry-head > div > p { color:#57758e; }
    .entry-flow div { color:#7991a5; }
    .entry-flow div:not(:last-child)::after { background:#a8cbe7; }
    .entry-flow span { color:#6687a2; border-color:#9fc4e2; }
    .entry-flow b { color:#4d6f89; }
    .entry-flow small { color:#7690a5; }
    .entry-flow .active span { color:#fff; background:var(--blue); border-color:var(--blue); }
    .entry-flow .active b { color:#245987; }
    .entry-boundary { color:#5f7a90 !important; border-top-color:#b6d3e9; }
    .entry-body { padding:38px 44px 32px; }
    .entry-body-head { margin-bottom:16px; }
    .entry-body-head h2 { color:#245987; font-family:inherit; font-size:26px; }
    .entry-step { color:#2e78b9; }
    .entry-progress { height:8px; margin:0 0 26px; overflow:hidden; background:#e4f0fa; border-radius:999px; }
    .entry-progress i { display:block; width:14.285%; height:100%; background:var(--blue); border-radius:999px; transition:width .22s ease-out; }
    .entry-pages { min-height:270px; }
    .entry-page { display:none; }
    .entry-page.active { display:block; }
    .entry-page > label:first-child { margin-bottom:10px; color:#285d91; font-size:17px; font-weight:800; }
    .entry-page input,.entry-page select,.entry-page textarea { min-height:50px; border-color:#bdd8ee; font-size:14px; }
    .entry-page textarea { min-height:150px; }
    .entry-page > p { margin:9px 2px 0; color:#778c9f; font-size:12px; }
    .entry-page .confirm-check { margin-top:16px; color:#5a7186; background:#f5faff; border-left-color:var(--lime); }
    .entry-actions { margin-top:18px; }
    .entry-actions .hint { flex:1; text-align:right; }
    .entry-body .primary { color:#fff; background:var(--blue); border-color:var(--blue); }
    .entry-body .primary:hover { background:#216fce; border-color:#216fce; }
    #enterDemoButton { display:none; }

    @media (max-width:1120px) {
      .workbench { grid-template-columns:1fr; }
      .interaction-chain { grid-template-columns:1fr; }
      .interaction-step { min-height:auto; padding:15px 0; }
      .interaction-step + .interaction-step { border-left:0; border-top:1px solid #e0e7e4; }
      .interaction-step + .interaction-step::before { display:none; }
      .case-path { grid-template-columns:repeat(2,minmax(0,1fr)); }
    }
    @media (max-width:820px) {
      .layer-ribbon { grid-template-columns:1fr 1fr; gap:8px; }
      .layer-ribbon i { display:none; }
      .analysis-layout { grid-template-columns:1fr; }
      .tabs { border-right:0; border-bottom:1px solid var(--line); }
      .tab-cluster + .tab-cluster { border-left-color:#c9deef; }
      .entry-shell { grid-template-columns:1fr; }
      .entry-head { min-height:300px; border-right:0; border-bottom:1px solid #c6dff3; }
    }
    @media (max-width:560px) {
      main { padding:20px 12px 42px; }
      .page-intro h1 { font-size:28px; }
      .layer-ribbon { grid-template-columns:1fr; }
      .student-strip { grid-template-columns:1fr; }
      .person-hero { grid-template-columns:auto 1fr; }
      .person-score { grid-column:1/-1; text-align:left; }
      .case-path { grid-template-columns:1fr; }
      .growth-head { flex-direction:column; }
      .evidence-grade { align-self:flex-start; }
      .entry-head { min-height:0; padding:26px 22px 24px; }
      .entry-head h1 { font-size:27px; }
      .entry-head > div > p { margin-bottom:0; line-height:1.7; }
      .entry-flow,.entry-boundary { display:none; }
      .entry-body { padding:26px 18px 30px; }
      .entry-pages { min-height:290px; }
      .entry-actions { align-items:stretch; flex-wrap:wrap; }
      .entry-actions .hint { width:100%; text-align:left; }
    }

    /* Demo2 v8: evidence atelier. A quiet, high-trust workspace for teachers. */
    :root {
      --canvas:#f2f5f7;
      --paper:#ffffff;
      --paper-warm:#fbfaf7;
      --ink:#13283a;
      --muted:#647684;
      --line:#d8e1e7;
      --line-strong:#b9c9d3;
      --navy:#12364b;
      --navy-deep:#0b293b;
      --blue:#2d6cdf;
      --blue-2:#4b82e4;
      --teal:#178b91;
      --green:#2f8369;
      --amber:#c98518;
      --red:#c9544c;
      --purple:#7565ae;
      --coral:#e66e5b;
      --lime:#e7be55;
      --shadow:0 8px 28px rgba(19,45,63,.08);
      --shadow-strong:0 24px 70px rgba(15,43,61,.16);
    }
    * { scrollbar-color:#aebdc7 transparent; }
    html { scroll-behavior:smooth; }
    html,body { background:var(--canvas); }
    body {
      min-width:320px;
      color:var(--ink);
      font-family:"Segoe UI","HarmonyOS Sans SC","MiSans","Microsoft YaHei UI","Microsoft YaHei",sans-serif;
      font-size:14px;
      line-height:1.55;
      text-rendering:optimizeLegibility;
    }
    h1,h2,h3,.entry-head h1,.page-intro h1 {
      font-family:"Noto Serif SC","Source Han Serif SC","STZhongsong","Songti SC",serif;
      letter-spacing:0;
    }
    button,input,textarea,select { font-family:inherit; }
    button { min-height:40px; border-radius:4px; transition:background-color .18s ease,border-color .18s ease,color .18s ease,box-shadow .18s ease; }
    button:focus-visible,a:focus-visible,input:focus-visible,textarea:focus-visible,select:focus-visible {
      outline:3px solid rgba(45,108,223,.24);
      outline-offset:2px;
    }
    input,textarea,select {
      border:1px solid var(--line-strong);
      border-radius:4px;
      background:#fff;
      color:var(--ink);
      box-shadow:0 1px 0 rgba(15,42,59,.02);
    }
    input:hover,textarea:hover,select:hover { border-color:#8ea8b9; }
    input:focus,textarea:focus,select:focus { border-color:var(--blue); box-shadow:0 0 0 3px rgba(45,108,223,.10); }
    .primary {
      min-height:42px;
      padding:9px 17px;
      border:1px solid var(--blue);
      border-radius:4px;
      background:var(--blue);
      color:#fff;
      box-shadow:0 4px 12px rgba(45,108,223,.16);
    }
    .primary:hover { border-color:#245fc9; background:#245fc9; box-shadow:0 6px 16px rgba(45,108,223,.22); }
    .secondary,.inline-command {
      border:1px solid var(--line-strong);
      border-radius:4px;
      background:#fff;
      color:#31526a;
    }
    .secondary:hover,.inline-command:hover { border-color:#7ea0b5; background:#f6f9fb; color:var(--navy); }

    header { position:sticky; top:0; z-index:30; border-bottom:0; background:var(--navy-deep); box-shadow:0 1px 0 rgba(255,255,255,.08); }
    .topbar { max-width:1480px; min-height:66px; margin:auto; padding:9px 24px; gap:22px; }
    .brand { min-width:285px; gap:12px; padding:0; border:0; }
    .brand-mark {
      width:40px;
      height:40px;
      display:grid;
      place-items:center;
      flex:0 0 40px;
      border:1px solid rgba(255,255,255,.24);
      border-radius:5px;
      background:rgba(255,255,255,.08);
      color:#fff !important;
      box-shadow:none;
    }
    .brand-mark svg { width:21px; height:21px; stroke:currentColor; }
    .brand strong { color:#fff; font-size:16px; font-weight:700; }
    .brand div > span { color:#a8c2d2; font-size:11px; }
    .top-actions { gap:9px; }
    .status {
      min-height:34px;
      display:inline-flex;
      align-items:center;
      padding:5px 10px;
      border:1px solid rgba(118,214,187,.30);
      border-radius:4px;
      background:rgba(52,147,118,.14);
      color:#a9e4d1;
      font-size:11px;
      font-weight:650;
    }
    .status i { background:#70d1ae; }
    .course-select {
      min-width:300px;
      height:40px;
      border-color:#4d6879;
      border-radius:4px;
      background:#fff;
      color:var(--ink);
    }
    .ghost-link { min-height:40px; display:inline-flex; align-items:center; padding:0 4px; color:#c6d9e5; font-size:12px; }
    .ghost-link:hover { color:#fff; }

    main { max-width:1480px; padding:30px 24px 64px; }
    .page-intro {
      display:grid;
      grid-template-columns:minmax(0,1fr) 290px;
      gap:34px;
      align-items:end;
      margin:0 0 24px;
      padding:8px 0 24px;
      border-bottom:1px solid var(--line-strong);
    }
    .page-intro h1 { margin:6px 0 7px; color:var(--navy); font-size:39px; font-weight:700; line-height:1.2; }
    .page-intro p { max-width:760px; margin:0; color:var(--muted); font-size:14px; }
    .page-intro-note {
      display:grid;
      grid-template-columns:1fr 1fr;
      gap:8px 18px;
      padding:0 0 2px 18px;
      border:0;
      border-left:3px solid var(--coral);
      border-radius:0;
      background:transparent;
      box-shadow:none;
    }
    .page-intro-note b { grid-column:1/-1; color:var(--navy); font-size:12px; }
    .page-intro-note span { color:var(--muted); font-size:11px; }
    .eyebrow {
      display:inline-flex;
      width:max-content;
      margin:0 0 5px;
      padding:0;
      border:0;
      border-radius:0;
      background:transparent;
      color:var(--teal);
      font-family:"Segoe UI",sans-serif;
      font-size:10px;
      font-weight:750;
      letter-spacing:.13em;
      text-transform:uppercase;
    }

    .layer-ribbon {
      display:grid;
      grid-template-columns:repeat(4,minmax(0,1fr));
      gap:0;
      margin:0 0 26px;
      padding:0;
      overflow:hidden;
      border:1px solid var(--line);
      border-radius:5px;
      background:var(--paper);
      box-shadow:0 2px 9px rgba(20,51,70,.04);
    }
    .layer-ribbon div { min-height:68px; padding:13px 18px 11px; position:relative; }
    .layer-ribbon div + div { border-left:1px solid var(--line); }
    .layer-ribbon div::after { content:""; position:absolute; left:18px; bottom:0; width:42px; height:3px; background:var(--line-strong); }
    .layer-ribbon div:nth-of-type(1)::after { background:var(--blue); }
    .layer-ribbon div:nth-of-type(2)::after { background:var(--teal); }
    .layer-ribbon div:nth-of-type(3)::after { background:var(--coral); }
    .layer-ribbon div:nth-of-type(4)::after { background:var(--lime); }
    .layer-ribbon b { color:var(--navy); font-size:12px; }
    .layer-ribbon span { margin-top:4px; color:#748592; font-size:10px; }
    .layer-ribbon i { display:none; }

    .section { margin-bottom:26px; }
    .course-foundation,.observation-section,.analysis-layout {
      border:1px solid var(--line);
      border-radius:5px;
      background:var(--paper);
      box-shadow:0 3px 14px rgba(17,47,65,.045);
    }
    .course-foundation { overflow:hidden; }
    .course-foundation .section-head,.observation-section > .section-head {
      min-height:72px;
      padding:15px 20px;
      border-bottom:1px solid var(--line);
      background:var(--paper);
    }
    .section-head h2,.analysis-heading h2 { color:var(--navy); font-size:20px; line-height:1.25; }
    .section-head p,.analysis-heading p { color:var(--muted); font-size:12px; }
    .course-foundation .section-head::after { border-color:var(--line-strong); color:var(--navy); }
    .course-foundation[open] .section-body { border-top:0; }
    .fit-grid { gap:10px; }
    .fit-item { min-height:118px; border:1px solid var(--line); border-left:3px solid var(--teal); border-radius:4px; background:#fff; }
    .fit-item.warn { border-left-color:var(--coral); }

    .observation-section { overflow:hidden; }
    .section-status { color:var(--green); font-size:11px; }
    .workbench { grid-template-columns:minmax(0,1.72fr) minmax(390px,.78fr); min-height:650px; }
    .visual-pane { border-right:1px solid #294b60; background:var(--navy-deep); }
    .visual-toolbar { min-height:52px; padding:8px 14px; border-color:#2a4d62; background:var(--navy); color:#dbe8ef; }
    .visual-toolbar .segmented { border-color:#4c6878; border-radius:4px; background:#0d2c3f; }
    .visual-toolbar .segmented button { min-height:34px; padding:5px 13px; border-color:#4c6878; color:#afc6d4; }
    .visual-toolbar .segmented button.active { background:#f4f8fa; color:var(--navy); box-shadow:none; }
    .visual-note { color:#aec5d2; font-size:11px; }
    .stage { min-height:590px; background:#0a2536; }
    .stage img { max-height:650px; object-fit:contain; }
    .student-pane { border:0; background:#f8fafb; }
    .student-tabs { border-bottom:1px solid var(--line); background:#eef3f5; }
    .student-tab { min-height:82px; padding:12px 11px; border-color:var(--line); background:transparent; }
    .student-tab:hover { background:#fff; }
    .student-tab.active { background:#fff; color:var(--navy); box-shadow:inset 0 -3px var(--coral); }
    .student-tab strong { font-size:13px; }
    .student-tab span { color:#728592; font-size:10px; }
    .student-detail { padding:18px; }
    .portrait { width:76px; height:94px; border:1px solid var(--line); border-radius:4px; box-shadow:none; }
    .student-title h3 { color:var(--navy); font-size:21px; }
    .score-row { grid-template-columns:94px 1fr; gap:16px; margin:18px 0; }
    .score-ring { width:90px; height:90px; background:conic-gradient(var(--teal) var(--score),#dfe9ed 0); }
    .score-ring::after { width:68px; height:68px; }
    .score-ring strong { font-size:23px; }
    .bar { height:5px; background:#dce7eb; border-radius:0; }
    .bar i { background:var(--teal); }
    .student-detail .callout { border:0; border-left:3px solid var(--coral); border-radius:0; background:#fff; color:#3e586a; }
    .mini-actions { gap:7px; }
    .mini-actions div { min-height:68px; border:1px solid var(--line); border-radius:4px; background:#fff; }

    .analysis-studio { margin-top:34px; }
    .analysis-heading { align-items:end; margin:0 0 15px; padding:0 2px 14px; border-bottom:1px solid var(--line-strong); }
    .review-progress { min-height:32px; display:inline-flex; align-items:center; padding:4px 10px; border:1px solid #ead29c; border-radius:4px; background:#fff8e9; color:#9a6511; }
    .student-strip {
      grid-template-columns:repeat(3,minmax(0,1fr));
      gap:0;
      margin:0;
      padding:0;
      overflow:hidden;
      border:1px solid var(--line);
      border-bottom:0;
      border-radius:5px 5px 0 0;
      background:#eef3f5;
    }
    .student-card {
      min-height:112px;
      padding:13px 16px;
      border:0;
      border-right:1px solid var(--line);
      border-radius:0;
      background:#f8fafb;
    }
    .student-card:last-child { border-right:0; }
    .student-card:hover { background:#fff; }
    .student-card.active { border-color:transparent; background:#fff; box-shadow:inset 0 4px var(--coral); }
    .student-card h3 { color:var(--navy); font-size:14px; }
    .student-card .big { color:var(--navy); font-size:27px; }
    .student-card p { margin:5px 0; color:#647987; font-size:11px; line-height:1.45; }

    .analysis-layout {
      grid-template-columns:218px minmax(0,1fr);
      align-items:start;
      overflow:visible;
      border-radius:0 0 5px 5px;
      box-shadow:0 8px 26px rgba(19,48,66,.06);
    }
    .tabs {
      position:sticky;
      top:78px;
      display:block;
      max-height:calc(100vh - 96px);
      margin:0;
      overflow:auto;
      border:0;
      border-right:1px solid #24485d;
      border-radius:0 0 0 4px;
      background:var(--navy);
    }
    .tab-cluster { display:block; padding:11px 10px 12px; border:0; }
    .tab-cluster + .tab-cluster { border-top:1px solid rgba(255,255,255,.10); }
    .tab-cluster > span {
      display:block;
      padding:3px 10px 6px;
      border:0;
      background:transparent;
      color:#7fa4b9;
      font-size:9px;
      font-weight:700;
      letter-spacing:.12em;
    }
    .tabs button {
      width:100%;
      min-height:38px;
      display:block;
      margin:2px 0;
      padding:8px 11px;
      border:0;
      border-left:3px solid transparent;
      border-radius:3px;
      background:transparent;
      color:#c6d7e1;
      text-align:left;
      font-size:12px;
    }
    .tabs button:hover { border-left-color:#6daab2; background:rgba(255,255,255,.07); color:#fff; }
    .tabs button.active { border-left-color:var(--coral); background:rgba(255,255,255,.12); color:#fff; box-shadow:none; }
    .analysis-content,.tab-body { background:#fff; }
    .result-summary { border-bottom:1px solid var(--line); background:#f6f8f9; }
    .result-stat { min-height:74px; padding:13px 16px; border-color:var(--line); }
    .result-stat span { color:#71838f; font-size:9px; letter-spacing:.04em; }
    .result-stat strong { color:var(--navy); font-family:inherit; font-size:17px; }
    .tab-body { min-height:520px; padding:22px 24px 28px; }
    .callout { border:0; border-left:3px solid var(--teal); border-radius:0; background:#f1f7f6; color:#395a5b; }
    .info-block { border:1px solid var(--line); border-radius:4px; background:#fff; box-shadow:none; }
    .info-block h3 { color:var(--navy); font-family:inherit; }
    .summary-box { border:1px solid var(--line); border-top:2px solid var(--teal); border-radius:3px; }
    .metric-card { border:1px solid var(--line); border-left:3px solid var(--teal); border-radius:3px; background:#fff; }
    .metric-card:nth-child(2n) { background:#f8fafb; }
    .metric-card.watch { border-left-color:var(--amber); }
    .metric-card.support { border-left-color:var(--coral); }
    th { background:#edf2f4; color:#385267; }
    th,td { border-color:var(--line); }
    tr.selectable:hover,tr.selectable.selected { background:#eef6f6; }
    .course-report-head,.support-banner,.review-guide,.growth-head {
      border:1px solid var(--line);
      border-left:4px solid var(--teal);
      border-radius:4px;
      background:#f3f7f7;
      color:var(--navy);
    }
    .course-report-head p,.support-banner p,.review-guide p,.review-guide ol,.growth-head p { color:#607985; }
    .course-report {
      max-width:940px;
      padding:34px 42px;
      border:1px solid #deded7;
      border-top:4px solid var(--navy);
      border-radius:0;
      background:var(--paper-warm);
      box-shadow:0 12px 36px rgba(44,43,35,.07);
    }
    .course-report p,.feedback { color:#283a43; font-family:"Noto Serif SC","Source Han Serif SC","Songti SC",serif; }
    .clip-id { border-radius:3px; background:var(--navy); }
    .evidence { border:1px solid var(--line); border-left:3px solid var(--coral); border-radius:4px; background:#fff; box-shadow:none; }
    .clip-heading { border-bottom:1px solid var(--line); background:#f5f7f8; }
    .judgement { border-left:3px solid var(--blue); background:#f1f5fb; }
    .review-reason { background:#fff6e5; }
    .interaction-step { border:1px solid var(--line); border-radius:4px; background:#fff; }
    .interaction-step + .interaction-step::before { background:#91b4bd; }
    .interaction-step span { color:var(--teal); }
    .interaction-result { border:1px solid #cce1db; border-radius:4px; background:#eef7f4; }
    .evidence-grade { border:1px solid #e2c67b; border-radius:4px; background:#fff7dd; }
    .person-hero { border:1px solid var(--line); border-left:4px solid var(--coral); border-radius:4px; background:#f5f8f9; }
    .person-hero img { border-radius:3px; }
    .person-hero h3 { color:var(--navy); }
    .person-score strong { color:var(--teal); }
    .case-path div { border:1px solid var(--line); border-left:3px solid var(--teal); border-radius:3px; background:#fff; }
    .case-path b { color:var(--navy); }
    .growth-chart { border:1px solid var(--line); border-radius:4px; }
    .timeline { gap:4px; }
    .tick { min-width:38px; height:48px; border-radius:2px; }
    .tick.selected { outline:2px solid var(--navy); outline-offset:1px; }
    .tick.not_observed { background:#e5eaed; border-color:#97a8b3; }
    .privacy { border:1px solid #e3ce9f; border-radius:4px; background:#fff8e9; color:#755318; }

    .entry-gate { padding:34px; background:#e8eef1; }
    .entry-shell {
      width:min(1120px,100%);
      min-height:680px;
      grid-template-columns:390px minmax(0,1fr);
      overflow:hidden;
      border:1px solid #c5d1d8;
      border-radius:6px;
      background:#fff;
      box-shadow:var(--shadow-strong);
    }
    .entry-head {
      min-height:680px;
      padding:46px 38px 34px;
      border:0;
      border-right:1px solid #315264;
      background:var(--navy);
      color:#fff;
    }
    .entry-kicker { color:#86bbc3; font-size:10px; letter-spacing:.17em; }
    .entry-head h1 { margin:28px 0 18px; color:#fff; font-size:37px; font-weight:700; line-height:1.4; }
    .entry-head h1 em { color:#f2c261; font-style:normal; }
    .entry-head > div > p { max-width:300px; color:#bfd1da; font-size:13px; line-height:1.9; }
    .entry-flow { margin:36px 0 22px; }
    .entry-flow div { min-height:68px; color:#83a3b4; }
    .entry-flow div:not(:last-child)::after { background:#58798a; }
    .entry-flow span { border-color:#6f91a2; color:#a5c0cd; }
    .entry-flow b { color:#dbe7ec; }
    .entry-flow small { color:#83a3b4; }
    .entry-flow .active span { border-color:var(--coral); background:var(--coral); color:#fff; }
    .entry-flow .active b { color:#fff; }
    .entry-boundary { color:#91adbb !important; border-top-color:#466a7c; }
    .entry-body { padding:48px 52px 38px; background:#fff; }
    .entry-body-head { margin-bottom:16px; }
    .entry-step { color:var(--teal); font-size:10px; letter-spacing:.08em; }
    .entry-body-head h2 { margin:9px 0 6px; color:var(--navy); font-size:29px; }
    .entry-body-head p { color:#72838e; }
    .entry-progress { height:4px; margin:0 0 34px; border-radius:0; background:#e2e8ec; }
    .entry-progress i { border-radius:0; background:var(--coral); }
    .entry-pages { min-height:280px; }
    .entry-page > label:first-child { color:var(--navy); font-size:15px; }
    .entry-page input,.entry-page select,.entry-page textarea { min-height:52px; border-color:#b9c9d3; border-radius:4px; font-size:14px; }
    .entry-page > p { color:#748691; }
    .entry-page .confirm-check { border-left-color:var(--coral); border-radius:0; background:#fff7ee; color:#6d5144; }
    .entry-actions { padding-top:16px; border-top:1px solid var(--line); }
    .entry-actions .hint { color:#7b8a94; }
    .entry-body .primary { border-color:var(--blue); background:var(--blue); }
    .entry-body .primary:hover { border-color:#245fc9; background:#245fc9; }

    /* Demo2 v9: quiet Swiss-style evidence workspace. */
    :root {
      --canvas:#f3f6f4;
      --paper:#ffffff;
      --paper-warm:#fafaf7;
      --ink:#1d2e2d;
      --muted:#60706c;
      --line:#dbe3df;
      --line-strong:#c5d1cc;
      --navy:#244744;
      --navy-deep:#173633;
      --blue:#436b66;
      --blue-2:#5f807b;
      --teal:#4b766f;
      --green:#4f7c69;
      --amber:#a7782b;
      --red:#b75d55;
      --purple:#6f777f;
      --coral:#cf715f;
      --lime:#899b76;
      --shadow:0 12px 34px rgba(31,56,51,.055);
      --shadow-strong:0 34px 90px rgba(28,50,47,.16);
    }
    body {
      color:var(--ink);
      font-family:"Helvetica Neue","Aptos","Segoe UI","PingFang SC","HarmonyOS Sans SC","Microsoft YaHei UI",sans-serif;
      font-size:14px;
      line-height:1.65;
    }
    h1,h2,h3,.entry-head h1,.page-intro h1 {
      font-family:"Helvetica Neue","Aptos Display","Segoe UI","PingFang SC","Microsoft YaHei UI",sans-serif;
      font-weight:650;
    }
    button { border-radius:3px; }
    button:focus-visible,a:focus-visible,input:focus-visible,textarea:focus-visible,select:focus-visible {
      outline-color:rgba(79,124,117,.25);
    }
    input:focus,textarea:focus,select:focus { border-color:var(--teal); box-shadow:0 0 0 3px rgba(79,124,117,.10); }
    label { color:#425b56; }
    .fit-item p { color:var(--muted); }
    .primary {
      border-color:var(--navy-deep);
      background:var(--navy-deep);
      box-shadow:none;
    }
    .primary:hover { border-color:#0f2c2a; background:#0f2c2a; box-shadow:none; }
    .secondary,.inline-command { color:var(--navy); }

    header {
      border-bottom:1px solid rgba(197,209,204,.9);
      background:rgba(250,252,251,.96);
      box-shadow:0 6px 24px rgba(27,49,45,.035);
      backdrop-filter:blur(18px);
    }
    .topbar { min-height:68px; padding:10px 28px; }
    .brand { min-width:268px; }
    .brand-mark {
      width:40px;
      height:40px;
      border:0;
      border-radius:50%;
      background:var(--navy-deep);
      color:#fff !important;
    }
    .brand strong { color:var(--ink); font-size:15px; font-weight:700; }
    .brand div > span { color:#60706c; font-size:10px; }
    .status {
      min-height:36px;
      border-color:#cedbd6;
      border-radius:18px;
      background:#edf4f1;
      color:#3b635c;
      font-size:11px;
    }
    .status i { background:#5c8a79; }
    .course-select {
      min-width:320px;
      border-color:#cbd6d2;
      background:#fff;
      color:var(--ink);
    }
    .ghost-link { color:#526560; }
    .ghost-link:hover { color:var(--ink); }
    .ghost-link svg { width:16px; height:16px; margin-right:4px; }

    main { max-width:1420px; padding:42px 30px 72px; }
    .page-intro {
      grid-template-columns:minmax(0,1fr) 310px;
      gap:54px;
      margin-bottom:28px;
      padding:10px 0 30px;
      border-color:#ced8d4;
    }
    .page-intro h1 {
      margin:8px 0 10px;
      color:var(--ink);
      font-size:42px;
      font-weight:560;
      line-height:1.12;
    }
    .page-intro p { color:#61716e; font-size:14px; line-height:1.7; }
    .page-intro-note {
      gap:7px 20px;
      padding:2px 0 2px 22px;
      border-left:1px solid #98aaa5;
    }
    .page-intro-note b { color:var(--ink); font-size:12px; font-weight:650; }
    .page-intro-note span { color:#60706c; font-size:11px; }
    .eyebrow {
      color:#4f756d;
      font-family:inherit;
      font-size:9px;
      font-weight:700;
      letter-spacing:.12em;
    }

    .layer-ribbon {
      margin-bottom:30px;
      border-width:1px 0;
      border-color:#ccd7d3;
      border-radius:0;
      background:transparent;
      box-shadow:none;
    }
    .layer-ribbon div { min-height:76px; padding:17px 18px 14px; }
    .layer-ribbon div + div { border-color:#dce4e1; }
    .layer-ribbon div::after { left:18px; width:28px; height:2px; background:#78918b !important; }
    .layer-ribbon div:nth-of-type(3)::after { background:var(--coral) !important; }
    .layer-ribbon b { color:var(--ink); font-size:12px; font-weight:650; }
    .layer-ribbon span { color:#60706c; font-size:11px; }

    .course-foundation,.observation-section,.analysis-layout {
      border-color:#d6dfdc;
      border-radius:4px;
      box-shadow:var(--shadow);
    }
    .course-foundation .section-head,.observation-section > .section-head {
      min-height:86px;
      padding:20px 24px;
    }
    .section-head h2,.analysis-heading h2 { color:var(--ink); font-size:21px; font-weight:620; }
    .section-head p,.analysis-heading p { color:#60706c; font-size:12px; }
    .course-foundation .section-head::after {
      content:"";
      width:9px;
      height:9px;
      border:0;
      border-right:1.5px solid #49655f;
      border-bottom:1.5px solid #49655f;
      border-radius:0;
      transform:rotate(45deg) translateY(-2px);
      transition:transform .2s ease;
    }
    .course-foundation[open] .section-head::after {
      content:"";
      transform:rotate(225deg) translate(-2px,-2px);
    }
    .disclosure-label { color:#5e716c; font-size:11px; }
    .fit-item { border-color:#dbe3df; border-left-color:#789a92; }
    .fit-item.warn { border-left-color:var(--coral); }

    .workbench { grid-template-columns:minmax(0,1.65fr) minmax(390px,.72fr); min-height:650px; }
    .visual-pane { border-right-color:#294743; background:#173633; }
    .visual-toolbar { min-height:56px; padding:9px 18px; border-color:#3e5b57; background:#244744; }
    .visual-toolbar .segmented { border-color:#6b827d; border-radius:3px; background:transparent; }
    .visual-toolbar .segmented button {
      min-height:40px;
      display:inline-flex;
      align-items:center;
      gap:7px;
      color:#cad7d4;
    }
    .visual-toolbar .segmented button svg { width:16px; height:16px; stroke:currentColor; }
    .visual-toolbar .segmented button.active { background:#f7faf8; color:#203e3b; }
    .visual-note { color:#b7c8c4; }
    .stage { background:#112d2b; }
    .student-pane { background:#fbfcfb; }
    .student-tabs { background:#f0f4f2; }
    .student-tab { min-height:86px; padding:14px 13px; }
    .student-tab.active { box-shadow:inset 0 -2px var(--teal); }
    .student-tab strong { color:var(--ink); font-size:13px; }
    .student-tab span { color:#60706c; font-size:10px; }
    .student-detail { padding:22px; }
    .student-title h3 { color:var(--ink); font-size:22px; }
    .score-ring {
      width:88px;
      height:88px;
      border:1px solid #cbd9d4;
      background:conic-gradient(var(--teal) var(--score),#e5ece9 0);
    }
    .score-ring::after { width:70px; height:70px; background:#fff; }
    .metric span,.metric b { font-size:11px; }
    .bar { background:#e2eae7; }
    .student-detail .callout { border-left-width:2px; border-left-color:var(--coral); background:#f8faf9; color:#425b56; }
    .mini-actions { grid-template-columns:1fr 1fr; }
    .mini-actions div { min-height:72px; padding:12px; border-color:#dde5e2; background:#fff; }

    .analysis-studio { margin-top:42px; scroll-margin-top:88px; }
    .analysis-heading { margin-bottom:18px; padding-bottom:18px; }
    .review-progress {
      min-height:34px;
      border-color:#dfc7be;
      border-radius:17px;
      background:#fbf3f0;
      color:#955346;
    }
    .student-strip { border-color:#d7e0dd; background:#f0f4f2; }
    .student-card { min-height:122px; padding:17px 19px; border-color:#dbe3e0; background:#f8faf9; }
    .student-card.active { box-shadow:inset 0 3px var(--teal); }
    .student-card h3 { color:var(--ink); font-size:15px; }
    .student-card .big { color:var(--ink); font-size:31px; font-weight:560; }
    .student-card p { color:#63746f; font-size:12px; line-height:1.55; }

    .analysis-layout { grid-template-columns:232px minmax(0,1fr); }
    .tabs {
      top:82px;
      border-right-color:#d5dfdb;
      background:#eef3f0;
    }
    .tab-cluster { padding:14px 12px 15px; }
    .tab-cluster + .tab-cluster { border-top-color:#d8e1de; }
    .tab-cluster > span {
      padding:3px 11px 8px;
      color:#5f716c;
      font-size:9px;
      letter-spacing:.08em;
    }
    .tabs button {
      min-height:42px;
      display:flex;
      align-items:center;
      gap:10px;
      border-left-width:2px;
      color:#425b56;
      font-size:12px;
    }
    .tabs button svg { width:17px; height:17px; flex:0 0 17px; stroke:currentColor; }
    .tabs button:hover { border-left-color:#8aa29c; background:rgba(255,255,255,.68); color:var(--ink); }
    .tabs button.active { border-left-color:var(--teal); background:#fff; color:var(--ink); box-shadow:0 4px 16px rgba(42,69,63,.04); }
    .result-summary { background:#fafbfa; }
    .result-stat { min-height:82px; padding:16px 18px; }
    .result-stat span { color:#60706c; font-size:10px; letter-spacing:0; }
    .result-stat strong { color:var(--ink); font-size:18px; font-weight:620; }
    .tab-body { min-height:560px; padding:28px 30px 36px; }
    .analysis-content p,.analysis-content li,.analysis-content td,.analysis-content th {
      font-size:12px;
      line-height:1.65;
    }
    .analysis-content h3 { color:var(--ink); font-size:16px; font-weight:650; }
    .analysis-content ol,.analysis-content ul { padding-left:21px; }
    .callout { border-left-width:2px; background:#f2f7f5; color:#405e58; }
    .info-block { border-color:#dce4e1; }
    .summary-box { border-color:#dbe3e0; border-top-color:#789b93; }
    .summary-box strong { color:var(--ink); font-weight:560; }
    .metric-card { border-color:#dce4e1; border-left-width:2px; border-left-color:#7a9b94; }
    .metric-card:nth-child(2n) { background:#fafbfa; }
    .teacher-score { color:#456f68; font-weight:560; }
    th { background:#f0f4f2; color:#3e5752; font-weight:650; }
    tr.selectable:hover,tr.selectable.selected { background:#f0f6f3; }
    .course-report-head,.support-banner,.review-guide,.growth-head {
      border-color:#d7e1dd;
      border-left-width:2px;
      border-left-color:#75968e;
      background:#f5f8f6;
    }
    .course-report { border-color:#dedfd9; border-top-color:#496c66; background:#fbfbf8; }
    .course-report p {
      margin:0;
      color:#334744;
      font-size:14px;
      line-height:2;
      white-space:pre-line;
    }
    .report-actions { display:flex; flex-wrap:wrap; justify-content:flex-end; gap:8px; }
    .report-actions button,.report-toolbar button { display:inline-flex; align-items:center; gap:7px; }
    .report-actions svg,.report-toolbar button svg { width:16px; height:16px; flex:0 0 16px; }
    .course-report-head .secondary,.support-banner .secondary,.review-export {
      border-color:#9fb3ad;
      background:#fff;
      color:#355d56;
      box-shadow:none;
    }
    .course-report-head .secondary:hover,.support-banner .secondary:hover,.review-export:hover {
      border-color:#587b74;
      background:#edf4f1;
      color:#21433d;
    }
    .report-toolbar {
      margin-bottom:16px;
      padding:14px;
      border-color:#d7e1dd;
      background:#f2f6f4;
    }
    .report-status { color:#60706c; font-size:12px; }
    .report-layout { gap:22px; }
    .report-nav {
      top:90px;
      padding:10px;
      border-color:#d8e2de;
      background:#f7f9f8;
    }
    .report-nav button {
      min-height:42px;
      padding:9px 10px;
      color:#4d625d;
      font-size:12px;
      line-height:1.45;
    }
    .report-nav button:hover { background:#fff; color:#244c45; }
    .report-section { margin-bottom:22px; padding:6px 6px 24px; }
    .report-section h3 { color:var(--ink); font-size:18px; }
    .report-section p { color:#344945; font-size:14px; line-height:1.95; }
    .support-controls {
      padding:12px 14px;
      border-color:#d7e1dd;
      background:#f3f6f5;
    }
    .support-controls button {
      min-height:40px;
      border-color:#aabdb7;
      background:#fff;
      color:#315a53;
      box-shadow:none;
    }
    .support-controls button:hover { border-color:#557b73; background:#edf4f1; color:#21453e; }
    .support-controls output { color:#4d746c; }
    .support-tool,.support-tool:nth-child(2),.support-tool:nth-child(3),.support-tool:nth-child(4) {
      border-color:#d9e2df;
      border-top:2px solid #6f928a;
      border-radius:3px;
    }
    .support-tool > span { color:#617771; }
    .support-tool h3 { color:var(--ink); }
    .support-tool h3 b { border-radius:2px; background:#edf3f1; color:#355e56; }
    .support-tool p { color:#637570; }
    .motion-code {
      display:inline-block;
      margin-left:6px;
      padding:1px 5px;
      border:1px solid #d4dfdb;
      border-radius:2px;
      background:#f4f7f6;
      color:#536a65;
      font-family:"Cascadia Code","SFMono-Regular",Consolas,monospace;
      font-size:10px;
      white-space:nowrap;
    }
    .tab-body > pre {
      max-height:700px;
      margin:0;
      overflow:auto;
      border:1px solid #27423e;
      border-radius:3px;
      scrollbar-color:#68817b #132825;
    }
    .clip-id { background:#284c47; }
    .evidence {
      border-color:#d9e2df;
      border-left-width:2px;
      border-left-color:#c87b6d;
      background:#fff;
    }
    .clip-heading { min-height:58px; padding:13px 17px; background:#f7f9f8; }
    .clip-heading strong { font-size:13px; }
    .review-clip > summary { cursor:pointer; list-style:none; }
    .review-clip > summary::-webkit-details-marker { display:none; }
    .review-clip > summary .clip-heading-meta { display:flex; align-items:center; gap:12px; margin-left:auto; }
    .clip-review-state {
      min-width:54px;
      padding:3px 7px;
      border:1px solid #d9c8bd;
      border-radius:12px;
      background:#fbf6f1;
      color:#8c5a4d;
      text-align:center;
      font-size:10px;
      font-weight:650;
    }
    .clip-chevron { width:17px; height:17px; flex:0 0 17px; color:#607a74; transition:transform .18s ease; }
    .review-clip[open] > summary .clip-chevron { transform:rotate(180deg); }
    .review-clip[open] > summary { border-bottom:1px solid #dce4e1; }
    .judgement { border-left-width:2px; border-left-color:#78948e; background:#f3f6f5; }
    .review-reason { background:#fbf5ef; }
    .locate-clip {
      min-height:40px;
      border-color:#a8bcb6;
      background:#fff;
      color:#355e57;
      box-shadow:none;
    }
    .locate-clip:hover { border-color:#557b73; background:#edf4f1; color:#21453e; }
    .review-fieldset {
      margin:0 18px;
      padding:18px 0 14px;
      border-top:1px solid #e0e7e4;
    }
    .review-fieldset legend { color:var(--ink); font-size:13px; font-weight:650; }
    .review-row {
      width:max-content;
      max-width:100%;
      gap:0;
      margin-top:12px;
      padding:3px;
      border:1px solid #ccd8d4;
      border-radius:4px;
      background:#f3f6f5;
    }
    .review-row button {
      min-width:86px;
      min-height:40px;
      border:0;
      border-radius:2px;
      background:transparent;
      color:#536762;
      font-weight:600;
    }
    .review-row button:hover { border:0; background:#fff; color:var(--ink); }
    .review-row button.selected {
      border:0;
      background:#456f68;
      color:#fff;
      box-shadow:none;
    }
    .review-row button.selected.correct { border:0; background:#b86658; color:#fff; box-shadow:none; }
    .review-row button.selected.uncertain { border:0; background:#8d7347; color:#fff; box-shadow:none; }
    .field-help { color:#60706c !important; font-size:11px !important; }
    .filter-row .segmented button { min-height:40px; }
    .review-editor {
      grid-template-columns:repeat(2,minmax(0,1fr));
      gap:16px;
      margin:0 18px;
      padding:20px 0 22px;
      border-top:1px solid #e0e7e4;
    }
    .review-editor label { color:#415652; font-size:12px; font-weight:600; }
    .review-editor select,.review-editor input { min-height:46px; margin-top:7px; font-size:13px; font-weight:400; }
    .review-note-label { grid-column:1/-1; }
    .save-review {
      grid-column:1/-1;
      min-height:42px;
      padding:8px 15px;
      border-color:var(--navy-deep);
      border-radius:3px;
      background:var(--navy-deep);
      color:#fff;
      font-weight:650;
    }
    .save-review:hover { background:#0f2c2a; }
    .interaction-chain {
      gap:0;
      margin:0;
      padding:20px 18px;
      border-top:1px solid #e0e7e4;
    }
    .interaction-step {
      min-height:126px;
      padding:4px 22px;
      border:0;
      border-radius:0;
      background:transparent;
    }
    .interaction-step + .interaction-step { border-left:1px solid #dfe6e3; }
    .interaction-step + .interaction-step::before { display:none; }
    .interaction-step span { color:#567c75; font-size:10px; letter-spacing:.04em; }
    .interaction-step p { color:#354c47; font-size:13px; line-height:1.75; }
    .interaction-result { margin:0 18px 18px; border-color:#d2e1dc; background:#eef5f2; }
    .evidence-grade { border-color:#d9c8bd; background:#fbf6f1; color:#8b5e4f; }
    .person-hero { border-color:#dbe3e0; border-left-width:2px; border-left-color:#789b93; background:#f6f9f7; }
    .person-hero h3 { color:var(--ink); }
    .person-score strong { color:#456f68; }
    .case-path div { border-color:#dce4e1; border-left-width:2px; border-left-color:#7c9c95; }
    .growth-chart { border-color:#dbe3e0; background:#fff; }
    .privacy { border-color:#dfd1c7; background:#faf6f2; color:#765d53; }

    .entry-gate { padding:34px; background:#e9efec; }
    .entry-shell {
      width:min(1160px,100%);
      min-height:700px;
      grid-template-columns:410px minmax(0,1fr);
      border-color:#c8d4cf;
      border-radius:4px;
      box-shadow:var(--shadow-strong);
    }
    .entry-head {
      min-height:700px;
      padding:52px 42px 38px;
      border-right-color:#496660;
      background:#294c47;
    }
    .entry-kicker { color:#acc4be; letter-spacing:.10em; }
    .entry-head h1 { margin:36px 0 19px; font-size:39px; font-weight:520; line-height:1.38; }
    .entry-head h1 em { color:#dce9e5; font-style:normal; }
    .entry-head > div > p { color:#c9d9d5; font-size:13px; line-height:1.95; }
    .entry-flow { margin-top:44px; }
    .entry-flow div { color:#b5cbc5; }
    .entry-flow div:not(:last-child)::after { background:#607d77; }
    .entry-flow span { border-color:#73918a; color:#bad0cb; }
    .entry-flow b { color:#e1ebe8; }
    .entry-flow small { color:#b5cbc5; }
    .entry-flow .active span { border-color:#fff; background:#fff; color:#294c47; }
    .entry-boundary { color:#adc2bd !important; border-top-color:#54716b; }
    .entry-body { padding:54px 58px 42px; }
    .entry-step { color:#5c7d76; letter-spacing:.04em; }
    .entry-body-head h2 { margin-top:11px; color:var(--ink); font-size:30px; font-weight:600; }
    .entry-progress { height:2px; background:#e2e8e5; }
    .entry-progress i { background:#537a73; }
    .entry-page > label:first-child { color:var(--ink); }
    .entry-page .confirm-check { border-left-color:var(--coral); background:#fbf5f1; }
    .entry-page .confirm-check input {
      width:17px;
      height:17px;
      min-height:0;
      flex:0 0 17px;
      margin:2px 0 0;
      accent-color:#315e57;
      box-shadow:none;
    }
    .entry-body .primary { border-color:var(--navy-deep); background:var(--navy-deep); }
    .entry-body .primary:hover { border-color:#0f2c2a; background:#0f2c2a; }

    .record-page-head,.storage-page-head {
      display:flex;
      justify-content:space-between;
      align-items:flex-start;
      gap:24px;
      padding:4px 0 20px;
      border-bottom:1px solid #dbe4e1;
    }
    .record-page-head h3,.storage-page-head h3 { margin:5px 0 7px; color:var(--ink); font-size:21px; }
    .record-page-head p,.storage-page-head p { max-width:760px; margin:0; color:#536762; font-size:13px; line-height:1.75; }
    .record-status {
      flex:0 0 auto;
      padding:8px 11px;
      border:1px solid #b7d7cf;
      border-radius:3px;
      background:#edf7f3;
      color:#315f57;
      font-size:11px;
      font-weight:650;
    }
    .record-layout { display:grid; grid-template-columns:minmax(0,1.05fr) minmax(340px,.95fr); gap:26px; margin-top:24px; }
    .record-column { min-width:0; }
    .record-section { padding:0 0 26px; }
    .record-section + .record-section { padding-top:24px; border-top:1px solid #dfe7e4; }
    .record-section h4 { margin:0 0 5px; color:var(--ink); font-size:15px; }
    .record-section > p { margin:0 0 16px; color:#60736e; font-size:12px; line-height:1.7; }
    .record-form-grid { display:grid; grid-template-columns:1fr 1fr; gap:14px; }
    .record-form-grid .wide { grid-column:1/-1; }
    .record-form-grid textarea { min-height:94px; }
    .file-field {
      min-height:118px;
      padding:18px;
      border:1px dashed #96ada7;
      background:#f7faf9;
    }
    .file-field input[type="file"] { min-height:44px; padding:8px; background:#fff; }
    .file-field small { display:block; margin-top:8px; color:#687b76; line-height:1.55; }
    .authorization-check { display:flex; align-items:flex-start; gap:9px; margin:14px 0; color:#485d58; font-size:12px; line-height:1.6; }
    .authorization-check input { width:17px; height:17px; min-height:0; margin:2px 0 0; accent-color:#315e57; }
    .document-list { display:grid; gap:9px; }
    .document-row { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:14px; padding:13px 0; border-bottom:1px solid #e0e7e4; }
    .document-row:first-child { border-top:1px solid #e0e7e4; }
    .document-row h5 { margin:0 0 5px; color:#243b36; font-size:13px; overflow-wrap:anywhere; }
    .document-row p { margin:3px 0; color:#657873; font-size:11px; line-height:1.55; }
    .document-actions { display:flex; align-items:center; gap:7px; }
    .document-actions a,.document-actions button { min-height:38px; padding:7px 10px; font-size:11px; text-decoration:none; }
    .danger-command { border:1px solid #d6b7af; background:#fff; color:#9b4f43; border-radius:3px; }
    .danger-command:hover { border-color:#b86658; background:#fbf4f1; }
    .parse-preview { margin-top:8px; padding:9px 10px; border-left:2px solid #8ba69f; background:#f5f8f7; color:#526964; font-size:11px; line-height:1.6; }
    .record-empty { padding:24px 0; border-top:1px solid #e0e7e4; border-bottom:1px solid #e0e7e4; color:#657873; font-size:12px; }
    .loading-line { min-height:240px; display:grid; place-items:center; color:#61746f; font-size:13px; }

    .storage-location {
      flex:0 1 520px;
      padding:11px 13px;
      border-left:3px solid #557f77;
      background:#f1f6f4;
    }
    .storage-location b,.storage-location code { display:block; }
    .storage-location b { margin-bottom:5px; color:#345a53; font-size:11px; }
    .storage-location code { color:#405650; font:11px/1.55 "Cascadia Code",Consolas,monospace; overflow-wrap:anywhere; }
    .storage-metrics { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); margin:22px 0; border:1px solid #d8e2de; }
    .storage-metric { min-height:92px; padding:15px; background:#fff; }
    .storage-metric + .storage-metric { border-left:1px solid #d8e2de; }
    .storage-metric span { display:block; color:#657873; font-size:10px; }
    .storage-metric strong { display:block; margin:6px 0 3px; color:#294c47; font-size:22px; }
    .storage-metric small { color:#758681; font-size:10px; }
    .lifecycle-band { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); margin-bottom:26px; border-top:1px solid #dbe4e1; border-bottom:1px solid #dbe4e1; }
    .lifecycle-band div { position:relative; padding:14px 18px; }
    .lifecycle-band div + div { border-left:1px solid #dbe4e1; }
    .lifecycle-band b,.lifecycle-band span { display:block; }
    .lifecycle-band b { color:#315e57; font-size:12px; }
    .lifecycle-band span { margin-top:4px; color:#687a75; font-size:10px; line-height:1.5; }
    .storage-grid { display:grid; grid-template-columns:minmax(0,1.2fr) minmax(320px,.8fr); gap:28px; }
    .storage-section { min-width:0; }
    .storage-section h4 { margin:0 0 5px; font-size:15px; }
    .storage-section > p { margin:0 0 14px; color:#657873; font-size:12px; line-height:1.65; }
    .policy-list { border-top:1px solid #d9e2df; }
    .policy-row { display:grid; grid-template-columns:minmax(180px,1fr) 108px 106px 90px; gap:10px; align-items:center; padding:13px 0; border-bottom:1px solid #d9e2df; }
    .policy-row b,.policy-row small { display:block; }
    .policy-row b { color:#314b45; font-size:12px; }
    .policy-row small { margin-top:3px; color:#74857f; font-size:10px; }
    .policy-row input[type="number"] { min-height:40px; }
    .policy-check { display:flex; align-items:center; gap:6px; margin:0; color:#596d67; font-size:11px; }
    .policy-check input { width:16px; height:16px; min-height:0; accent-color:#315e57; }
    .policy-save { min-height:40px; border:1px solid #9eb3ad; border-radius:3px; background:#fff; color:#315e57; font-size:11px; font-weight:650; }
    .policy-save:hover { border-color:#557b73; background:#edf4f1; }
    .inventory-list { border-top:1px solid #d9e2df; }
    .inventory-row { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:10px; padding:11px 0; border-bottom:1px solid #d9e2df; }
    .inventory-row b { display:block; color:#354d48; font-size:11px; overflow-wrap:anywhere; }
    .inventory-row span { display:block; margin-top:3px; color:#74857f; font-size:10px; }
    .inventory-row a { align-self:center; color:#315e57; font-size:11px; font-weight:650; }
    .cloud-note { margin-top:22px; padding:15px 17px; border:1px solid #d8cbc0; border-left:3px solid #b97967; background:#fbf7f3; }
    .cloud-note b { display:block; margin-bottom:5px; color:#7e5044; font-size:12px; }
    .cloud-note p { margin:0; color:#705d56; font-size:11px; line-height:1.7; }
    .channel-overview { display:grid; grid-template-columns:minmax(0,1fr) 340px; gap:24px; align-items:end; padding:4px 0 22px; border-bottom:1px solid #dbe4e1; }
    .channel-overview h3 { margin:5px 0 7px; font-size:21px; }
    .channel-overview p { margin:0; color:#566c66; font-size:13px; line-height:1.75; }
    .channel-rule { padding:13px 15px; border-left:3px solid #557f77; background:#f1f6f4; color:#49635d; font-size:11px; line-height:1.7; }
    .channel-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:16px; margin-top:22px; }
    .channel-card { border:1px solid #d4dfdb; border-radius:4px; background:#fff; overflow:hidden; }
    .channel-card > header { position:static; display:flex; justify-content:space-between; align-items:center; min-height:58px; padding:12px 15px; border:0; border-bottom:1px solid #dce5e2; background:#f5f8f7; }
    .channel-card > header h4 { margin:0; color:#294c47; font-size:14px; }
    .channel-card > header span { color:#6c7e79; font-size:10px; }
    .channel-number { width:30px; height:30px; display:grid; place-items:center; border:1px solid #aac0ba; border-radius:50%; color:#315e57; font:650 11px/1 "Bahnschrift",sans-serif; }
    .channel-form { display:grid; grid-template-columns:1fr 1fr; gap:11px; padding:15px; }
    .channel-form .wide { grid-column:1/-1; }
    .channel-form label { margin-bottom:4px; }
    .channel-form input,.channel-form select { min-height:40px; padding:8px 9px; font-size:12px; }
    .channel-upload-command { grid-column:1/-1; display:flex; align-items:center; gap:10px; }
    .channel-upload-command button { flex:0 0 auto; }
    .channel-upload-command span { color:#667b75; font-size:10px; line-height:1.5; }
    .upload-progress { grid-column:1/-1; height:6px; overflow:hidden; background:#e4ebe8; }
    .upload-progress i { display:block; width:0; height:100%; background:#4f7c74; transition:width .2s ease; }
    .channel-tasks { padding:0 15px 15px; }
    .channel-tasks h5 { margin:0 0 7px; color:#526762; font-size:11px; }
    .channel-task { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:9px; padding:9px 0; border-top:1px solid #e0e7e4; }
    .channel-task b { display:block; color:#354d48; font-size:11px; overflow-wrap:anywhere; }
    .channel-task span { display:block; margin-top:3px; color:#758681; font-size:9px; line-height:1.5; }
    .channel-task a { align-self:center; color:#315e57; font-size:10px; font-weight:650; }
    .channel-empty { padding:10px 0; border-top:1px solid #e0e7e4; color:#758681; font-size:10px; }
    .channel-architecture { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); margin-top:24px; border-top:1px solid #d8e2de; border-bottom:1px solid #d8e2de; }
    .channel-architecture div { padding:13px 12px; }
    .channel-architecture div + div { border-left:1px solid #d8e2de; }
    .channel-architecture b,.channel-architecture span { display:block; }
    .channel-architecture b { color:#315e57; font-size:11px; }
    .channel-architecture span { margin-top:4px; color:#6b7d78; font-size:9px; line-height:1.5; }

    @media (max-width:980px) {
      .record-layout,.storage-grid { grid-template-columns:1fr; }
      .channel-overview { grid-template-columns:1fr; align-items:start; }
      .channel-grid { grid-template-columns:1fr; }
      .channel-architecture { grid-template-columns:1fr 1fr; }
      .channel-architecture div:nth-child(odd) { border-left:0; }
      .channel-architecture div:nth-child(n+3) { border-top:1px solid #d8e2de; }
      .storage-metrics { grid-template-columns:1fr 1fr; }
      .storage-metric:nth-child(3) { border-left:0; border-top:1px solid #d8e2de; }
      .storage-metric:nth-child(4) { border-top:1px solid #d8e2de; }
      .lifecycle-band { grid-template-columns:1fr 1fr; }
      .lifecycle-band div:nth-child(3) { border-left:0; border-top:1px solid #dbe4e1; }
      .lifecycle-band div:nth-child(4) { border-top:1px solid #dbe4e1; }
    }
    @media (max-width:600px) {
      .record-page-head,.storage-page-head { display:block; }
      .record-status,.storage-location { margin-top:14px; }
      .record-form-grid { grid-template-columns:1fr; }
      .record-form-grid .wide { grid-column:auto; }
      .document-row { grid-template-columns:1fr; }
      .document-actions { justify-content:flex-start; }
      .storage-metrics,.lifecycle-band { grid-template-columns:1fr; }
      .storage-metric + .storage-metric { border-left:0; border-top:1px solid #d8e2de; }
      .lifecycle-band div + div { border-left:0; border-top:1px solid #dbe4e1; }
      .policy-row { grid-template-columns:1fr 90px; }
      .policy-check { grid-column:1; }
      .policy-save { grid-column:2; grid-row:2; }
      .channel-form { grid-template-columns:1fr; }
      .channel-form .wide,.channel-upload-command { grid-column:auto; }
      .channel-upload-command { align-items:stretch; flex-direction:column; }
      .channel-architecture { grid-template-columns:1fr; }
      .channel-architecture div + div { border-left:0; border-top:1px solid #d8e2de; }
    }

    /* Demo2 v10: blue-white school workspace with semantic support colors. */
    :root {
      --canvas:#f4f8fc;
      --paper:#ffffff;
      --paper-warm:#fbfdff;
      --ink:#17324d;
      --muted:#5d7185;
      --line:#dbe7f2;
      --line-strong:#bfd2e5;
      --navy:#1e4f8a;
      --navy-deep:#153b70;
      --blue:#2563eb;
      --blue-2:#5b8fdb;
      --teal:#0c6f9c;
      --green:#2f8f75;
      --amber:#c77816;
      --red:#c85d5d;
      --purple:#6b6ecf;
      --coral:#e37d6f;
      --lime:#5d9d8c;
      --shadow:0 14px 36px rgba(32,91,145,.075);
      --shadow-strong:0 30px 82px rgba(24,71,119,.18);
    }
    html,body { background:var(--canvas); }
    body {
      color:var(--ink);
      font-family:"Microsoft YaHei UI","PingFang SC","Segoe UI Variable","Segoe UI",sans-serif;
    }
    h1,h2,h3,.entry-head h1,.page-intro h1 { font-family:"Microsoft YaHei UI","PingFang SC","Segoe UI Variable",sans-serif; }
    button:focus-visible,a:focus-visible,input:focus-visible,textarea:focus-visible,select:focus-visible { outline-color:rgba(37,99,235,.28); }
    input:focus,textarea:focus,select:focus { border-color:#4a8de0; box-shadow:0 0 0 3px rgba(37,99,235,.10); }
    label { color:#31516f; }
    .primary { border-color:var(--blue); background:var(--blue); }
    .primary:hover { border-color:#1d4ed8; background:#1d4ed8; }
    .secondary,.inline-command { border-color:#9dbfe1; color:#1d5ca1; background:#fff; }
    .secondary:hover,.inline-command:hover { border-color:#4e8ed0; background:#f0f7ff; color:#174c82; }

    header { border-bottom-color:#d6e5f1; background:rgba(255,255,255,.97); box-shadow:0 5px 22px rgba(34,83,130,.055); }
    .brand-mark { border-radius:9px; background:#1e5ba1; box-shadow:inset 0 0 0 1px rgba(255,255,255,.16); }
    .brand strong { color:#183650; }
    .brand div > span { color:#668096; }
    .status { border-color:#bcded5; background:#eefaf7; color:#247660; }
    .status i { background:#36a181; }
    .course-select { border-color:#c6d9ea; color:#183650; }
    .ghost-link { color:#40698e; }
    .ghost-link:hover { color:#164e86; }

    .page-intro { border-color:#cadae8; }
    .page-intro h1 { color:#173b61; }
    .page-intro p,.page-intro-note span { color:#617a90; }
    .page-intro-note { border-left-color:#91b6d8; }
    .page-intro-note b { color:#204b73; }
    .eyebrow { color:#2873bd; }
    .layer-ribbon { border-color:#c9dceb; }
    .layer-ribbon div + div { border-color:#dce8f2; }
    .layer-ribbon div::after { background:#5d96cf !important; }
    .layer-ribbon div:nth-of-type(3)::after { background:#2aa0c9 !important; }
    .layer-ribbon div:nth-of-type(4)::after { background:#5d9d8c !important; }
    .layer-ribbon b { color:#214665; }
    .layer-ribbon span { color:#60798e; }

    .course-foundation,.observation-section,.analysis-layout { border-color:#d3e2ee; background:#fff; box-shadow:var(--shadow); }
    .course-foundation .section-head,.observation-section > .section-head { border-color:#deEaf3; background:#fbfdff; }
    .course-foundation .section-head::after { border-color:#3979b4; }
    .disclosure-label { color:#5c7891; }
    .fit-item { border-color:#dce8f2; border-left-color:#5c99d1; }
    .fit-item.warn { border-left-color:#e3a04c; }
    .visual-pane { border-right-color:#234f7c; background:#123b66; }
    .visual-toolbar { border-color:#39658d; background:#1b4a76; }
    .visual-toolbar .segmented { border-color:#6f95b7; }
    .visual-toolbar .segmented button { color:#d2e4f1; }
    .visual-toolbar .segmented button.active { background:#fff; color:#194b79; }
    .visual-note { color:#bed4e5; }
    .stage { background:#0f3154; }
    .student-pane { background:#fbfdff; }
    .student-tabs { background:#edf5fb; }
    .student-tab.active { box-shadow:inset 0 -3px #2f7bd0; }
    .student-tab strong { color:#1c3e5c; }
    .student-tab span { color:#607b92; }
    .score-ring { border-color:#c8ddef; background:conic-gradient(#2e80d5 var(--score),#e4eef6 0); }
    .student-detail .callout { border-left-color:#e49a45; background:#f7fbff; color:#365b79; }
    .mini-actions div { border-color:#d9e7f2; }

    .review-progress { border-color:#f0c9bd; background:#fff5f1; color:#a45142; }
    .student-strip { border-color:#d4e2ee; background:#edf4fa; }
    .student-card { border-color:#dbe7f1; background:#f9fcff; }
    .student-card.active { box-shadow:inset 0 4px #2d78c7; }
    .student-card h3,.student-card .big { color:#173b5a; }
    .student-card p { color:#5d768d; }
    .tabs { border-right-color:#d1e1ed; background:#edf5fb; }
    .tab-cluster + .tab-cluster { border-top-color:#d4e3ef; }
    .tab-cluster > span { color:#52728f; }
    .tabs button { color:#315572; }
    .tabs button:hover { border-left-color:#6fa3d4; background:#f8fbff; color:#174875; }
    .tabs button.active { border-left-color:#2775c5; background:#fff; color:#164c80; box-shadow:0 5px 18px rgba(35,91,145,.07); }
    .result-summary { background:#fbfdff; }
    .result-stat { border-color:#dce8f1; }
    .result-stat span { color:#61798e; }
    .result-stat strong { color:#173b5a; }
    .callout { border-left-color:#3d88cc; background:#f0f7fd; color:#315b7c; }
    .info-block,.summary-box,.metric-card { border-color:#dbe7f1; }
    .summary-box { border-top-color:#4e8fcb; }
    .metric-card { border-left-color:#5f9ad0; background:#f7fbff; }
    .teacher-score,.person-score strong { color:#286fae; }
    th { background:#eef5fb; color:#305675; }
    tr.selectable:hover,tr.selectable.selected { background:#edf6ff; }
    .course-report-head,.support-banner,.review-guide,.growth-head { border-color:#d4e4f0; border-left-color:#4f8eca; background:#f4f9fd; }
    .course-report { border-color:#d5e2ec; border-top-color:#2f6fa8; background:#fcfdff; }
    .course-report p,.report-section p { color:#2e4c64; }
    .course-report-head .secondary,.support-banner .secondary,.review-export { border-color:#9ebfe0; color:#1c5c99; }
    .course-report-head .secondary:hover,.support-banner .secondary:hover,.review-export:hover { border-color:#4c8dce; background:#eff7ff; color:#174d7f; }
    .report-toolbar,.support-controls { border-color:#d5e4ef; background:#eef6fc; }
    .report-nav { border-color:#d6e4ef; background:#f6faff; }
    .report-nav button { color:#486984; }
    .report-nav button:hover { background:#fff; color:#1f5f9a; }
    .support-controls button { border-color:#a7c5df; color:#245f94; }
    .support-controls button:hover { border-color:#4e8dca; background:#edf6ff; color:#174d7d; }
    .support-controls output { color:#2d74ad; }
    .support-tool,.support-tool:nth-child(2),.support-tool:nth-child(3),.support-tool:nth-child(4) { border-color:#d7e5f0; border-top-color:#5e96c7; }
    .support-tool h3 b { background:#eaf3fb; color:#28679d; }
    .motion-code { border-color:#d0e0ec; background:#f3f8fc; color:#456982; }
    .tab-body > pre { border-color:#244b70; scrollbar-color:#7399ba #132f4a; }
    .clip-id { background:#27669f; }
    .evidence { border-color:#d9e6ef; border-left-color:#e08373; }
    .clip-heading { background:#f7fbfe; }
    .review-clip[open] > summary { border-bottom-color:#dce8f1; }
    .judgement { border-left-color:#6696bf; background:#f2f7fb; }
    .locate-clip { border-color:#a5c1d9; color:#245f92; }
    .locate-clip:hover { border-color:#4a88c2; background:#edf6ff; color:#174d7d; }
    .review-fieldset,.review-editor { border-top-color:#dce8f1; }
    .review-row { border-color:#c8dbea; background:#edf5fb; }
    .review-row button { color:#4c6b84; }
    .review-row button.selected { background:#2f73ad; }
    .save-review { border-color:#2563eb; background:#2563eb; }
    .save-review:hover { background:#1d4ed8; }
    .interaction-step + .interaction-step { border-left-color:#dce7f0; }
    .interaction-step span { color:#367ab2; }
    .interaction-step p { color:#2f5069; }
    .interaction-result { border-color:#cfe2ef; background:#eef7fc; }
    .person-hero { border-color:#d8e6f0; border-left-color:#4f8fc8; background:#f5faff; }
    .case-path div { border-color:#d9e6ef; border-left-color:#6197c2; }
    .growth-chart { border-color:#d8e6f0; }
    .privacy { border-color:#eed7b3; background:#fff9ef; color:#78551e; }

    .entry-gate { background:#eaf4ff; }
    .entry-shell { border-color:#bfd8ee; box-shadow:var(--shadow-strong); }
    .entry-head { border-right-color:#2e659a; background:#1d5c96; }
    .entry-kicker { color:#bfe1f5; }
    .entry-head h1 em { color:#fff; }
    .entry-head > div > p { color:#d2e7f4; }
    .entry-flow div { color:#b7d2e4; }
    .entry-flow div:not(:last-child)::after { background:#5482aa; }
    .entry-flow span { border-color:#75a0c3; color:#d3e6f2; }
    .entry-flow b { color:#e5f1f8; }
    .entry-flow small { color:#b9d3e4; }
    .entry-flow .active span { border-color:#fff; background:#fff; color:#1d5c96; }
    .entry-boundary { color:#c7ddea !important; border-top-color:#4a7aa3; }
    .entry-step { color:#2e77bb; }
    .entry-body-head h2 { color:#174d7d; }
    .entry-progress { background:#e2eef8; }
    .entry-progress i { background:#2b7bc6; }
    .entry-page > label:first-child { color:#183f62; }
    .entry-page input,.entry-page select,.entry-page textarea { border-color:#bfd6e8; }
    .entry-page .confirm-check { border-left-color:#4f8fca; background:#f2f8fd; color:#365b77; }
    .entry-page .confirm-check input { accent-color:#2563eb; }
    .entry-body .primary { border-color:#2563eb; background:#2563eb; }
    .entry-body .primary:hover { border-color:#1d4ed8; background:#1d4ed8; }
    .security-agreement { max-height:190px; margin:8px 0 12px; padding:15px 17px; overflow:auto; border:1px solid #c9ddec; border-radius:6px; background:#f8fbfe; color:#34546d; }
    .security-agreement b { color:#174f80; font-size:13px; }
    .security-agreement ul { margin:8px 0 7px; padding-left:20px; }
    .security-agreement li { margin:5px 0; font-size:11px; line-height:1.55; }
    .security-agreement span { color:#70879a; font-size:10px; }
    .archive-consent { border-left-color:#5a9b87 !important; background:#f1faf7 !important; }

    .record-page-head,.storage-page-head { border-bottom-color:#d8e6f0; }
    .record-page-head h3,.storage-page-head h3 { color:#173b5a; }
    .record-page-head p,.storage-page-head p { color:#58738a; }
    .record-status { border-color:#aed5c9; background:#effaf6; color:#27745f; }
    .record-section + .record-section { border-top-color:#dce8f1; }
    .record-section > p { color:#5d778d; }
    .file-field { border-color:#8eb7da; background:#f6faff; }
    .authorization-check input { accent-color:#2563eb; }
    .document-row { border-bottom-color:#dce8f1; }
    .document-row:first-child { border-top-color:#dce8f1; }
    .document-row h5 { color:#203f59; }
    .parse-preview { border-left-color:#6098c9; background:#f1f7fc; color:#48677f; }
    .storage-location { border-left-color:#327fc2; background:#eef6fc; }
    .storage-location b { color:#1d5b91; }
    .storage-location code { color:#365d7a; }
    .storage-metrics,.lifecycle-band { border-color:#d5e4ef; }
    .storage-metric + .storage-metric,.lifecycle-band div + div { border-color:#dce8f1; }
    .storage-metric strong { color:#17466f; font-family:"Bahnschrift","Segoe UI",sans-serif; }
    .storage-metric.alert strong { color:#b56d12; }
    .storage-metric.archive strong { color:#24765f; }
    .lifecycle-band b { color:#1f64a2; }
    .policy-list,.inventory-list { border-top-color:#d8e6f0; }
    .policy-row { grid-template-columns:minmax(170px,1fr) 112px 138px 105px 76px; border-bottom-color:#d9e6f0; }
    .policy-row b { color:#244864; }
    .policy-row small { color:#6b8193; }
    .policy-number { display:grid; grid-template-columns:auto minmax(48px,1fr) auto; align-items:center; gap:5px; margin:0; color:#5d7589; font-size:10px; }
    .policy-number span { grid-column:1/-1; }
    .policy-number input { width:100%; min-height:40px; }
    .policy-number em { font-style:normal; }
    .policy-check { color:#587187; }
    .policy-check input { accent-color:#2563eb; }
    .policy-save { border-color:#9cbddd; color:#1e5d98; }
    .policy-save:hover { border-color:#4b8aca; background:#eef7ff; }
    .inventory-row { border-bottom-color:#d9e6f0; }
    .inventory-row b { color:#294b66; }
    .inventory-row a { color:#1f65a4; }
    .security-ledger { display:flex; justify-content:space-between; gap:18px; margin:20px 0; padding:13px 16px; border:1px solid #bcded4; border-left:4px solid #3d9a7e; border-radius:5px; background:#f0faf7; }
    .security-ledger b { color:#246e5a; font-size:12px; }
    .security-ledger span { color:#52776d; font-size:11px; text-align:right; }
    .security-ledger.muted { border-color:#d6e3ed; border-left-color:#8ca9be; background:#f6f9fc; }
    .reminder-panel { display:grid; grid-template-columns:260px minmax(0,1fr); gap:22px; margin:20px 0 26px; padding:18px; border:1px solid #ecd2a8; border-left:4px solid #d58a27; border-radius:5px; background:#fffaf2; }
    .reminder-panel h4 { margin:0 0 5px; color:#8d5917; }
    .reminder-panel p { margin:0; color:#80684b; font-size:11px; line-height:1.6; }
    .reminder-row { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:10px; padding:8px 0; border-bottom:1px solid #eadcc6; }
    .reminder-row:last-child { border-bottom:0; }
    .reminder-row b,.reminder-row span { display:block; }
    .reminder-row b { color:#684c2b; font-size:11px; }
    .reminder-row span { margin-top:3px; color:#8b714f; font-size:10px; }
    .reminder-row a { align-self:center; color:#9c5f10; font-size:10px; }
    .record-empty.compact { padding:10px 0; border:0; }
    .cloud-note { border-color:#c9ddeb; border-left-color:#4f8fc7; background:#f2f8fd; }
    .cloud-note b { color:#245f94; }
    .cloud-note p { color:#4e6d84; }
    .channel-overview { border-bottom-color:#d7e5ef; }
    .channel-overview p { color:#58748b; }
    .channel-rule { border-left-color:#4389c6; background:#eef6fc; color:#3e6380; }
    .channel-card { border-color:#d2e2ee; box-shadow:0 7px 20px rgba(37,93,145,.055); }
    .channel-card > header { border-bottom-color:#d9e7f1; background:#f2f8fd; }
    .channel-card > header h4 { color:#1e527e; }
    .channel-card > header span { color:#668097; }
    .channel-number { border-color:#91b8da; color:#256aa7; background:#fff; }
    .upload-progress { background:#e1edf6; }
    .upload-progress i { background:#2f83ce; }
    .channel-task { border-top-color:#dce8f1; }
    .channel-task b { color:#244763; }
    .channel-task span { color:#6a8194; }
    .channel-task-actions { display:flex; align-items:center; justify-content:flex-end; gap:7px; flex-wrap:wrap; }
    .channel-task-actions a,.archive-command { min-height:34px; padding:6px 8px; border:1px solid #a6c4de; border-radius:3px; background:#fff; color:#1d619e; font-size:10px; font-weight:650; text-decoration:none; }
    .archive-command { border-color:#acd4c8; color:#28745f; }
    .archive-state { color:#2b7b65 !important; font-weight:650; }
    .archive-state.muted { color:#718597 !important; font-weight:400; }
    .retention-state { margin-top:5px !important; color:#3d749e !important; }
    .retention-state.due_soon,.retention-state.expired { color:#aa6715 !important; font-weight:650; }
    .channel-architecture { border-color:#d4e3ef; }
    .channel-architecture div + div { border-color:#dce8f1; }
    .channel-architecture b { color:#2367a4; }

    @media (max-width:1180px) {
      .policy-row { grid-template-columns:minmax(170px,1fr) 104px 128px 100px 72px; gap:7px; }
    }
    @media (max-width:760px) {
      .policy-row { grid-template-columns:1fr 1fr; }
      .policy-row > div:first-child { grid-column:1/-1; }
      .policy-check { grid-column:1; }
      .policy-save { grid-column:2; grid-row:auto; }
      .security-ledger,.reminder-panel { grid-template-columns:1fr; display:grid; }
      .security-ledger span { text-align:left; }
    }
    @media (max-width:600px) {
      .security-agreement { max-height:none; }
      .policy-row { grid-template-columns:1fr; }
      .policy-row > div:first-child,.policy-check,.policy-save { grid-column:auto; }
      .channel-task { grid-template-columns:1fr; }
      .channel-task-actions { justify-content:flex-start; }
    }

    /* Demo2 v11: premium classroom evidence studio. */
    :root {
      --canvas:#f2f7fc;
      --paper:#ffffff;
      --paper-warm:#fbfdff;
      --ink:#102a43;
      --muted:#587086;
      --line:#d7e5f2;
      --line-strong:#b8cee2;
      --navy:#153f6b;
      --navy-deep:#0f3155;
      --blue:#1769d2;
      --blue-2:#4c94df;
      --teal:#0b6f98;
      --green:#2e8b72;
      --amber:#d18a2f;
      --red:#c95858;
      --coral:#dc796d;
      --shadow:0 16px 42px rgba(28,82,130,.09);
      --shadow-strong:0 28px 72px rgba(25,72,116,.18);
    }
    body {
      background:var(--canvas);
      color:var(--ink);
      font-family:"Segoe UI Variable","Microsoft YaHei UI","PingFang SC","Microsoft YaHei",sans-serif;
      font-size:15px;
      line-height:1.62;
    }
    h1,h2,h3,.entry-head h1,.page-intro h1 { font-family:"Segoe UI Variable","Microsoft YaHei UI","PingFang SC",sans-serif; }
    input,textarea,select { min-height:44px; border-color:#bfd3e5; border-radius:6px; font-size:14px; }
    textarea { line-height:1.65; }
    button { min-height:42px; border-radius:6px; font-weight:650; }
    .primary { padding:9px 18px; border-radius:6px; box-shadow:0 7px 18px rgba(23,105,210,.18); }
    .secondary,.inline-command { border-radius:6px; }

    header {
      border-bottom:1px solid #d8e6f2;
      background:rgba(255,255,255,.98);
      box-shadow:0 6px 24px rgba(25,75,121,.06);
    }
    .topbar { max-width:1540px; min-height:74px; padding:10px 30px; gap:24px; }
    .brand { min-width:248px; }
    .brand-mark {
      width:42px;
      height:42px;
      flex-basis:42px;
      border:0;
      border-radius:8px;
      background:#1769d2;
      box-shadow:0 8px 20px rgba(23,105,210,.20);
    }
    .brand strong { color:#123858; font-size:17px; letter-spacing:0; }
    .brand div > span { margin-top:1px; color:#698196; font-size:11px; }
    .top-actions { gap:12px; }
    .status {
      min-height:38px;
      max-width:220px;
      padding:6px 12px;
      border:1px solid #bfe0d7;
      border-radius:7px;
      background:#f0faf7;
      color:#26745f;
      font-size:11px;
      line-height:1.35;
    }
    .course-select { min-width:360px; height:44px; border-radius:7px; background:#fbfdff; }
    .ghost-link { gap:7px; color:#315d83; font-weight:650; }

    main { max-width:1540px; padding:26px 30px 64px; }
    .page-intro {
      grid-template-columns:minmax(0,1fr) 310px;
      align-items:center;
      gap:34px;
      margin:0 0 18px;
      padding:10px 0 21px;
      border-bottom:1px solid #cbddeb;
    }
    .page-intro > div:first-child { position:relative; padding-left:18px; }
    .page-intro > div:first-child::before {
      content:"";
      position:absolute;
      left:0;
      top:4px;
      width:4px;
      height:calc(100% - 7px);
      border-radius:4px;
      background:#1769d2;
    }
    .page-intro h1 { margin:3px 0 7px; color:#123b62; font-size:34px; font-weight:760; line-height:1.18; }
    .page-intro p { max-width:850px; color:#5b7389; font-size:14px; line-height:1.65; }
    .eyebrow { margin-bottom:3px; color:#1769d2; font-size:10px; font-weight:800; letter-spacing:.1em; }
    .page-intro-note {
      min-height:68px;
      align-content:center;
      gap:6px 14px;
      padding:13px 16px;
      border:1px solid #d2e2ef;
      border-left:4px solid #78aede;
      border-radius:7px;
      background:#f8fbfe;
    }
    .page-intro-note b { color:#19466f; font-size:12px; }
    .page-intro-note span { color:#5e768b; font-size:11px; }

    .layer-ribbon {
      counter-reset:evidence-step;
      position:relative;
      grid-template-columns:repeat(4,minmax(0,1fr));
      gap:0;
      margin:0 0 22px;
      overflow:visible;
      border:0;
      border-radius:8px;
      background:#eaf3fb;
      box-shadow:none;
    }
    .layer-ribbon::before {
      content:"";
      position:absolute;
      left:12.5%;
      right:12.5%;
      top:29px;
      height:2px;
      background:#b9d3e9;
    }
    .layer-ribbon div {
      counter-increment:evidence-step;
      min-height:82px;
      display:grid;
      grid-template-columns:38px minmax(0,1fr);
      grid-template-rows:auto auto;
      align-content:center;
      column-gap:11px;
      padding:14px 18px;
      border:0 !important;
      background:transparent;
    }
    .layer-ribbon div::before {
      content:counter(evidence-step,decimal-leading-zero);
      z-index:1;
      width:34px;
      height:34px;
      grid-row:1/3;
      display:grid;
      place-items:center;
      align-self:center;
      border:2px solid #91b8d9;
      border-radius:50%;
      background:#fff;
      color:#256aa9;
      font-family:"Bahnschrift","Segoe UI",sans-serif;
      font-size:11px;
      font-weight:700;
    }
    .layer-ribbon div:nth-of-type(3)::before { border-color:#56add0; color:#087798; }
    .layer-ribbon div:nth-of-type(4)::before { border-color:#78b3a4; color:#287761; }
    .layer-ribbon div::after { display:none; }
    .layer-ribbon b { align-self:end; color:#173e62; font-size:13px; font-weight:720; }
    .layer-ribbon span { align-self:start; margin:1px 0 0; color:#607990; font-size:11px; }
    .layer-ribbon i { display:none; }

    .section { margin-bottom:24px; }
    .course-foundation,.observation-section {
      overflow:hidden;
      border:1px solid #d2e2ef;
      border-radius:8px;
      background:#fff;
      box-shadow:var(--shadow);
    }
    .course-foundation .section-head,.observation-section > .section-head {
      min-height:80px;
      padding:16px 22px;
      border-bottom:1px solid #dbe8f2;
      background:#fff;
    }
    .course-foundation .section-head { min-height:76px; background:#f9fcff; }
    .section-head h2,.analysis-heading h2 { color:#123b62; font-size:22px; font-weight:730; }
    .section-head p,.analysis-heading p { margin-top:4px; color:#5d758a; font-size:13px; }
    .section-status {
      min-height:34px;
      display:inline-flex;
      align-items:center;
      padding:5px 10px;
      border:1px solid #c8e5dc;
      border-radius:6px;
      background:#f1faf7;
      color:#27765f;
      font-size:11px;
      font-weight:650;
    }
    .disclosure-label { color:#24639c; font-size:12px; font-weight:650; }
    .fit-grid { gap:12px; }
    .fit-item { min-height:112px; border:1px solid #dce8f2; border-top:3px solid #5796d0; border-left:1px solid #dce8f2; border-radius:6px; background:#fbfdff; }
    .fit-item.warn { border-top-color:#d9953b; border-left-color:#dce8f2; }

    .workbench { grid-template-columns:minmax(0,1.7fr) minmax(410px,.76fr); min-height:680px; }
    .visual-pane { border-right:1px solid #274f74; background:#102f50; }
    .visual-toolbar {
      min-height:58px;
      padding:9px 16px;
      border-bottom:1px solid #326087;
      background:#17466f;
    }
    .visual-toolbar .segmented { padding:3px; border:1px solid #7397b7; border-radius:7px; background:#123b60; }
    .visual-toolbar .segmented button { min-height:36px; gap:7px; padding:6px 14px; border:0; border-radius:5px; color:#c8dceb; }
    .visual-toolbar .segmented button.active { background:#fff; color:#164b79; box-shadow:0 4px 12px rgba(5,26,46,.18); }
    .visual-note { color:#c1d6e6; font-size:11px; }
    .stage { min-height:620px; background:#0d2a47; }
    .stage img { max-height:700px; }
    .student-pane { border:0; background:#f8fbfe; }
    .student-tabs { gap:0; border-bottom:1px solid #d7e5f1; background:#edf5fb; }
    .student-tab { min-height:90px; padding:14px 13px; border-color:#d5e4ef; background:transparent; }
    .student-tab:hover { background:#f8fbfe; }
    .student-tab.active { background:#fff; color:#123c63; box-shadow:inset 0 -4px #1769d2; }
    .student-tab strong { color:#153d61; font-size:14px; }
    .student-tab span { margin-top:3px; color:#607a91; font-size:11px; line-height:1.4; }
    .student-detail { padding:24px; }
    .portrait { width:82px; height:104px; border:2px solid #fff; border-radius:7px; box-shadow:0 8px 22px rgba(25,73,116,.16); }
    .student-title h3 { color:#123858; font-size:23px; font-weight:740; }
    .student-title p { color:#60768a; }
    .score-row { grid-template-columns:104px 1fr; gap:20px; margin:22px 0; }
    .score-ring { width:98px; height:98px; border:1px solid #cee0ee; }
    .score-ring::after { width:73px; height:73px; }
    .score-ring strong { color:#123b60; font-family:"Bahnschrift","Segoe UI",sans-serif; font-size:27px; }
    .bar { height:7px; border-radius:5px; background:#e1ebf2; }
    .bar i { border-radius:5px; background:#2082bb; }
    .student-detail .callout { margin:20px 0; padding:14px 16px; border-left:4px solid #d89237; border-radius:0 6px 6px 0; background:#fff9ef; color:#4e6578; }
    .mini-actions { gap:10px; }
    .mini-actions div { min-height:74px; padding:12px 13px; border:1px solid #d8e6f1; border-radius:6px; background:#fff; }

    .analysis-studio { margin-top:38px; }
    .analysis-heading { align-items:center; margin:0 0 16px; padding:0 2px 15px; border-bottom:1px solid #cbdde9; }
    .review-progress { min-height:36px; padding:6px 11px; border:1px solid #efcf9f; border-radius:6px; background:#fff8ed; color:#97601d; font-size:11px; }
    .student-strip {
      grid-template-columns:repeat(3,minmax(0,1fr));
      gap:10px;
      margin:0 0 12px;
      padding:0;
      overflow:visible;
      border:0;
      border-radius:0;
      background:transparent;
    }
    .student-card {
      min-height:118px;
      padding:14px 16px;
      border:1px solid #d4e3ef !important;
      border-radius:7px;
      background:#fff;
      box-shadow:0 7px 20px rgba(35,83,126,.05);
    }
    .student-card:hover { border-color:#a9c7df !important; background:#fbfdff; transform:translateY(-1px); }
    .student-card.active { border-color:#4f91cf !important; background:#f3f9ff; box-shadow:inset 4px 0 #1769d2,0 9px 22px rgba(31,94,151,.08); }
    .student-card h3 { color:#153b5d; font-size:15px; }
    .student-card .big { color:#154a78; font-family:"Bahnschrift","Segoe UI",sans-serif; font-size:29px; }
    .student-card p { color:#60788e; font-size:11px; }
    .student-card-top { display:grid; grid-template-columns:46px minmax(0,1fr); gap:11px; align-items:center; margin-bottom:8px; }
    .student-card-top img { width:46px; height:46px; grid-row:1/3; border:2px solid #fff; border-radius:7px; object-fit:cover; box-shadow:0 4px 12px rgba(31,75,113,.14); }
    .student-card-top header { min-width:0; align-self:end; }
    .student-card-top > span { align-self:start; color:#5b7690; font-size:10px; line-height:1.35; }
    .student-card > p { margin:3px 0; padding-left:57px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }

    .analysis-layout {
      grid-template-columns:238px minmax(0,1fr);
      gap:14px;
      align-items:start;
      overflow:visible;
      border:0;
      border-radius:0;
      background:transparent;
      box-shadow:none;
    }
    .tabs {
      position:sticky;
      top:88px;
      max-height:calc(100vh - 108px);
      padding:10px;
      overflow:auto;
      border:1px solid #d2e2ee;
      border-radius:8px;
      background:#fff;
      box-shadow:0 12px 30px rgba(28,77,120,.07);
    }
    .tab-cluster { padding:8px 0 10px; }
    .tab-cluster + .tab-cluster { border-top:1px solid #e2ebf3; }
    .tab-cluster > span { padding:4px 11px 6px; color:#74899c; font-size:10px; font-weight:800; letter-spacing:.08em; }
    .tabs button {
      min-height:42px;
      display:flex;
      align-items:center;
      gap:10px;
      margin:2px 0;
      padding:8px 10px;
      border:1px solid transparent;
      border-left:0;
      border-radius:6px;
      color:#355b79;
      font-size:13px;
      font-weight:620;
    }
    .tabs button svg {
      width:28px;
      height:28px;
      flex:0 0 28px;
      padding:5px;
      border-radius:6px;
      background:#edf5fb;
      color:#3977ad;
    }
    .tabs button:hover { border:1px solid #d7e7f2; border-left:0; background:#f7fbfe; color:#174b78; }
    .tabs button.active { border:1px solid #c7dded; border-left:0; background:#eaf4fc; color:#114e82; box-shadow:inset 3px 0 #1769d2; }
    .tabs button.active svg { background:#1769d2; color:#fff; }
    .tab-cluster:nth-child(2) .tabs button svg,.tab-cluster:nth-child(2) button svg { background:#e9f6fa; color:#147b9e; }
    .tab-cluster:nth-child(3) .tabs button svg,.tab-cluster:nth-child(3) button svg { background:#edf8f4; color:#2d866e; }
    .tab-cluster:nth-child(4) .tabs button svg,.tab-cluster:nth-child(4) button svg { background:#fff6e8; color:#b87725; }
    .tab-cluster:nth-child(5) .tabs button svg,.tab-cluster:nth-child(5) button svg { background:#f1f3f8; color:#64738d; }
    .tab-cluster:nth-child(2) button.active svg,.tab-cluster:nth-child(3) button.active svg,.tab-cluster:nth-child(4) button.active svg,.tab-cluster:nth-child(5) button.active svg { background:#1769d2; color:#fff; }
    .analysis-content {
      min-width:0;
      overflow:hidden;
      border:1px solid #d3e2ee;
      border-radius:8px;
      background:#fff;
      box-shadow:var(--shadow);
    }
    .result-summary { grid-template-columns:repeat(4,minmax(0,1fr)); border-bottom:1px solid #dbe7f1; background:#f5f9fd; }
    .result-stat { min-height:86px; padding:15px 18px; border-color:#dce8f1; }
    .result-stat span { color:#647d91; font-size:10px; font-weight:700; letter-spacing:.04em; }
    .result-stat strong { margin-top:4px; color:#153b5d; font-family:"Bahnschrift","Microsoft YaHei UI",sans-serif; font-size:20px; line-height:1.3; }
    .tab-body { min-height:580px; padding:26px 28px 34px; background:#fff; }
    .analysis-content p,.analysis-content li,.analysis-content td,.analysis-content th { font-size:13px; line-height:1.7; }
    .analysis-content h3 { color:#153b5d; font-size:17px; font-weight:720; }
    .callout { padding:14px 16px; border-left:4px solid #3b88c7; border-radius:0 6px 6px 0; background:#f0f7fd; }
    .info-block,.summary-box,.metric-card { border-color:#d8e6f1; border-radius:6px; }
    .summary-box { border-top:3px solid #3f88c4; }
    .metric-card { border-left:4px solid #5a96c8; border-radius:6px; background:#fbfdff; }
    .course-report-head,.support-banner,.review-guide,.growth-head { border-radius:6px; }
    .course-report { max-width:980px; padding:42px 50px; border-top:5px solid #215f96; background:#fff; box-shadow:0 18px 42px rgba(38,73,105,.08); }
    .course-report p,.course-report .feedback { color:#263f54; font-family:"Microsoft YaHei UI","PingFang SC",sans-serif; font-size:14px; line-height:2; }
    .report-section h3 { padding-bottom:9px; border-bottom:1px solid #dfeaf3; color:#154c79; font-size:18px; }
    th { background:#edf5fb; color:#294f6d; }
    th,td { padding:11px 12px; }
    .evidence { border-radius:6px; }
    .clip-heading { background:#f5f9fc; }
    .interaction-step,.interaction-result,.evidence-grade,.person-hero,.case-path div,.growth-chart { border-radius:6px; }

    .record-page-head,.storage-page-head { padding-bottom:18px; }
    .record-page-head h3,.storage-page-head h3 { color:#123b5f; font-size:23px; }
    .record-status { border-radius:6px; }
    .file-field { border-radius:7px; background:#f8fbfe; }
    .document-row { min-height:66px; }
    .parse-preview,.storage-location,.cloud-note { border-radius:0 6px 6px 0; }
    .storage-metrics,.lifecycle-band { overflow:hidden; border-radius:7px; background:#f8fbfe; }
    .storage-metric { min-height:104px; padding:18px; }
    .storage-metric strong { font-size:26px; }
    .policy-row { min-height:74px; }
    .security-ledger,.reminder-panel { border-radius:7px; }
    .channel-grid { gap:18px; }
    .channel-card { overflow:hidden; border-radius:7px; box-shadow:0 10px 26px rgba(32,83,128,.07); }
    .channel-card > header { min-height:62px; background:#f4f9fd; }
    .channel-number { width:34px; height:34px; border-radius:7px; background:#edf6fd; }
    .channel-task-actions a,.archive-command { min-height:36px; border-radius:6px; }

    .entry-gate { padding:34px; background:#edf5fc; }
    .entry-shell {
      width:min(1160px,100%);
      min-height:700px;
      grid-template-columns:400px minmax(0,1fr);
      border:1px solid #bfd6e9;
      border-radius:8px;
      background:#fff;
      box-shadow:0 32px 90px rgba(29,82,130,.18);
    }
    .entry-head {
      min-height:700px;
      padding:50px 42px 36px;
      border-right:1px solid #1f5d91;
      background:#15548d;
    }
    .entry-kicker { color:#c7e5f7; font-size:10px; font-weight:800; letter-spacing:.13em; }
    .entry-head h1 { margin:30px 0 18px; font-size:39px; font-weight:730; line-height:1.42; }
    .entry-head h1 em { color:#fff; }
    .entry-head > div > p { max-width:318px; color:#d7e9f5; font-size:14px; line-height:1.9; }
    .entry-flow { margin:38px 0 24px; }
    .entry-flow div { min-height:74px; }
    .entry-flow span { width:34px; height:34px; border-color:#7eacd0; font-family:"Bahnschrift","Segoe UI",sans-serif; }
    .entry-flow b { font-size:13px; }
    .entry-flow small { font-size:10px; }
    .entry-flow .active span { border-color:#fff; background:#fff; color:#15548d; box-shadow:0 7px 17px rgba(11,44,73,.20); }
    .entry-boundary { padding-top:20px; color:#c9deeb !important; font-size:11px; line-height:1.75; }
    .entry-body { padding:50px 56px 40px; background:#fff; }
    .entry-body-head { margin-bottom:20px; }
    .entry-step { color:#1c70b9; font-size:11px; font-weight:800; }
    .entry-body-head h2 { margin-top:8px; color:#123e66; font-size:30px; font-weight:740; }
    .entry-body-head p { color:#667d90; font-size:12px; }
    .entry-progress { height:3px; margin-bottom:30px; border-radius:3px; }
    .entry-progress i { border-radius:3px; }
    .entry-page > label:first-child { color:#143d61; font-size:14px; font-weight:720; }
    .security-agreement { max-height:210px; padding:18px 20px; border-color:#c9ddeb; border-radius:7px; background:#f8fbfe; }
    .security-agreement b { font-size:14px; }
    .security-agreement li { margin:7px 0; font-size:12px; }
    .entry-page .confirm-check { min-height:48px; padding:11px 13px; border:1px solid #d6e5f1; border-left:4px solid #4a91ce; border-radius:0 6px 6px 0; background:#f3f8fd; font-size:12px; }
    .entry-page .archive-consent { border-color:#d2e6df; border-left-color:#4b9a83 !important; }
    .entry-actions { padding-top:16px; }

    @media (max-width:1120px) {
      .page-intro { grid-template-columns:1fr 280px; }
      .workbench { grid-template-columns:1fr; }
      .stage { min-height:0; aspect-ratio:16/9; }
      .stage img { height:100%; max-height:none; object-fit:contain; }
      .student-pane { border-top:1px solid var(--line); }
      .tabs { top:84px; }
    }
    @media (max-width:860px) {
      .topbar { padding:10px 16px; }
      .page-intro { grid-template-columns:1fr; gap:14px; }
      .page-intro-note { max-width:none; }
      .layer-ribbon { grid-template-columns:1fr 1fr; }
      .layer-ribbon::before { display:none; }
      .layer-ribbon div:nth-of-type(3),.layer-ribbon div:nth-of-type(4) { border-top:1px solid #d2e2ef !important; }
      .analysis-layout { grid-template-columns:1fr; gap:10px; }
      .tabs { position:static; display:flex; max-height:none; padding:8px; overflow-x:auto; border-radius:7px; background:#fff; }
      .tab-cluster { display:flex; flex:0 0 auto; padding:0; }
      .tab-cluster + .tab-cluster { border-top:0; border-left:1px solid #dde8f1; }
      .tab-cluster > span { display:none; }
      .tabs button { width:auto; min-width:max-content; margin:0 2px; }
      .tabs button:hover,.tabs button.active { border-left:1px solid #c7dded; box-shadow:none; }
      .entry-shell { grid-template-columns:1fr; }
      .entry-head { min-height:auto; padding:30px; border-right:0; border-bottom:1px solid #1f5d91; }
      .entry-head h1 { margin:18px 0 10px; font-size:31px; }
      .entry-head > div > p { max-width:680px; }
      .entry-flow { display:none; }
      .entry-body { padding:36px 32px; }
    }
    @media (max-width:600px) {
      main { padding:20px 12px 42px; }
      header { background:#fff; }
      .topbar { padding:9px 12px; }
      .brand-mark { width:38px; height:38px; flex-basis:38px; }
      .course-select { min-width:0; height:42px; }
      .page-intro { padding:4px 0 17px; }
      .page-intro > div:first-child { padding-left:13px; }
      .page-intro h1 { font-size:28px; }
      .layer-ribbon { grid-template-columns:1fr; }
      .layer-ribbon div { min-height:70px; padding:11px 14px; }
      .layer-ribbon div + div { border-top:1px solid #d2e2ef !important; }
      .student-tabs { grid-template-columns:repeat(3,minmax(145px,1fr)); }
      .student-strip { grid-template-columns:repeat(3,minmax(250px,1fr)); overflow-x:auto; }
      .result-summary { grid-template-columns:1fr 1fr; }
      .tab-body { min-height:0; padding:20px 15px 26px; }
      .analysis-content p,.analysis-content li,.analysis-content td,.analysis-content th { font-size:12px; }
      .entry-gate { padding:0; background:#fff; }
      .entry-shell { min-height:100vh; border:0; border-radius:0; box-shadow:none; }
      .entry-head { padding:26px 22px 22px; }
      .entry-head h1 { font-size:27px; }
      .entry-body { padding:28px 20px 30px; }
      .entry-body-head h2 { font-size:25px; }
    }

    @media (prefers-reduced-motion:reduce) {
      html { scroll-behavior:auto; }
      *,*::before,*::after { animation-duration:.01ms !important; transition-duration:.01ms !important; }
    }
    @media print {
      @page { size:A4; margin:16mm 17mm; }
      * { -webkit-print-color-adjust:exact; print-color-adjust:exact; }
      html,body { background:#fff; }
      header,.entry-gate,.page-intro,.layer-ribbon,.course-foundation,.observation-section,
      .analysis-heading,.student-strip,.tabs,.result-summary,.privacy,.report-toolbar,
      .report-actions,.report-nav { display:none !important; }
      main { width:auto; max-width:none; margin:0; padding:0; }
      .analysis-studio { margin:0; }
      .analysis-layout { display:block; border:0; box-shadow:none; }
      .analysis-content,.tab-body { min-height:0; padding:0; border:0; }
      .course-report-head { display:block; margin:0 0 10mm; padding:0 0 5mm; border:0; border-bottom:1px solid #9aaba6; background:#fff; }
      .course-report { max-width:none; padding:0; border:0; box-shadow:none; }
      .course-report p,.report-section p { color:#1d2e2d; font-size:10.5pt; line-height:1.8; }
      .report-layout { display:block; }
      .report-document { max-width:none; }
      .report-section { break-inside:auto; }
      .report-section h3 { break-after:avoid; }
      .callout { margin-top:8mm; break-inside:avoid; }
    }
    @media (max-width:1120px) {
      .page-intro { grid-template-columns:1fr 250px; }
      .workbench { grid-template-columns:1fr; }
      .stage { min-height:0; aspect-ratio:16/9; }
      .stage img { height:100%; max-height:none; object-fit:contain; }
      .student-pane { border-top:1px solid var(--line); }
      .tabs { top:74px; }
      .interaction-chain { grid-template-columns:1fr; }
      .interaction-step + .interaction-step::before { display:none; }
    }
    @media (max-width:860px) {
      .topbar { align-items:flex-start; flex-wrap:wrap; }
      .brand { min-width:0; }
      .top-actions { width:100%; margin-left:0; }
      .course-select { flex:1; min-width:180px; }
      .page-intro { grid-template-columns:1fr; gap:18px; }
      .page-intro-note { max-width:440px; }
      .layer-ribbon { grid-template-columns:1fr 1fr; }
      .layer-ribbon div:nth-of-type(3) { border-left:0; border-top:1px solid var(--line); }
      .layer-ribbon div:nth-of-type(4) { border-top:1px solid var(--line); }
      .analysis-layout { grid-template-columns:1fr; }
      .tabs { position:static; display:flex; max-height:none; padding:8px 12px; overflow-x:auto; border-right:0; border-bottom:1px solid #d5dfdb; border-radius:0; background:#eef3f0; scrollbar-width:none; scroll-padding-inline:24px; scroll-snap-type:x proximity; }
      .tabs::-webkit-scrollbar { display:none; }
      .tab-cluster { display:flex; flex:0 0 auto; padding:0; }
      .tab-cluster + .tab-cluster { border-top:0; border-left:1px solid #d8e1de; }
      .tab-cluster > span { display:none; }
      .tabs button { width:auto; min-width:max-content; margin:0 2px; border-left:0; border-bottom:3px solid transparent; }
      .tabs button { scroll-snap-align:center; }
      .tabs button:hover,.tabs button.active { border-left:0; border-bottom-color:var(--teal); }
      .entry-shell { grid-template-columns:1fr; }
      .entry-head { min-height:auto; padding:30px 30px 24px; border-right:0; border-bottom:1px solid #315264; }
      .entry-head h1 { margin:18px 0 10px; font-size:31px; }
      .entry-head > div > p { max-width:680px; }
      .entry-flow { display:none; }
      .entry-boundary { margin-top:20px; }
      .entry-body { padding:34px 30px; }
    }
    @media (max-width:600px) {
      main { padding:22px 12px 44px; }
      .topbar { padding:10px 12px; }
      .brand div > span,.status,.ghost-link { display:none; }
      header { background:#f9fbfa; }
      .brand-mark { width:36px; height:36px; flex-basis:36px; }
      .brand strong { color:var(--ink); }
      .top-actions { flex-wrap:nowrap; }
      .course-select { width:100%; min-width:0; }
      .page-intro { padding-bottom:18px; }
      .page-intro h1 { font-size:30px; }
      .page-intro-note { grid-template-columns:1fr; }
      .layer-ribbon { grid-template-columns:1fr; }
      .layer-ribbon div + div { border-left:0; border-top:1px solid var(--line); }
      .student-tabs { grid-template-columns:repeat(3,minmax(132px,1fr)); overflow-x:auto; }
      .student-tab { min-height:68px; border-right:1px solid var(--line); border-bottom:0; }
      .student-strip { grid-template-columns:repeat(3,minmax(245px,1fr)); overflow-x:auto; }
      .student-card { min-height:108px; border-right:1px solid var(--line); border-bottom:0; }
      .result-summary { grid-template-columns:1fr 1fr; }
      .result-stat:nth-child(2) { border-right:0; }
      .result-stat:nth-child(-n+2) { border-bottom:1px solid var(--line); }
      .tab-body { padding:18px 14px 24px; }
      .interaction-step { min-height:auto; padding:15px 0; }
      .interaction-step + .interaction-step { border-left:0; border-top:1px solid #e0e7e4; }
      .review-fieldset,.review-editor { margin-left:0; margin-right:0; }
      .review-editor { grid-template-columns:1fr; }
      .review-note-label { grid-column:auto; }
      .save-review { grid-column:auto; width:100%; }
      .review-row { width:100%; }
      .review-row button { flex:1; min-width:0; }
      .review-clip > summary .clip-heading-meta { gap:7px; }
      .clip-review-state { display:none; }
      .entry-gate { padding:0; background:#fff; }
      .entry-shell { min-height:100vh; border:0; border-radius:0; box-shadow:none; }
      .entry-head { padding:25px 22px 22px; }
      .entry-head h1 { font-size:27px; }
      .entry-boundary { display:none; }
      .entry-body { padding:28px 20px 30px; }
      .entry-body-head h2 { font-size:25px; }
      .entry-pages { min-height:310px; }
      .entry-actions { align-items:stretch; flex-wrap:wrap; }
      .entry-actions .primary { flex:1; }
      .entry-actions .hint { width:100%; text-align:left; }
      .case-path { grid-template-columns:1fr; }
    }
  </style>
</head>
<body>
<section class="entry-gate" id="entryGate">
  <div class="entry-shell">
    <aside class="entry-head">
      <div>
        <span class="entry-kicker">REHABAFFECT / 课堂观察工作室</span>
        <h1>让一节课留下<br><em>可复核的学习证据</em></h1>
        <p>从课程目标出发，对齐课堂视频、师生互动和个体档案，再形成教师可确认的学习结论与支持动作。</p>
      </div>
      <div class="entry-flow" aria-label="课堂分析流程">
        <div class="active"><span>01</span><b>安全授权</b><small>用途、期限与下载范围</small></div>
        <div><span>02</span><b>确认课程</b><small>目标与评价口径</small></div>
        <div><span>03</span><b>教师复核</b><small>形成可信结论</small></div>
      </div>
      <p class="entry-boundary">系统只提供课堂状态辅助观察，不做医学诊断，也不以动作多少直接判断学生是否学会。</p>
    </aside>
    <div class="entry-body">
      <div class="entry-body-head">
        <span class="entry-step" id="entryStepLabel">安全与课程配置 · 第 1/8 步</span>
        <h2 id="entryQuestionTitle">准备进入课堂分析</h2>
        <p id="entryQuestionHint">一次只确认一件事，填写过程会自动保留。</p>
      </div>
      <div class="entry-progress" id="entryProgress" role="progressbar" aria-label="安全与课程配置进度" aria-valuemin="1" aria-valuemax="8" aria-valuenow="1"><i id="entryProgressBar"></i></div>
      <div class="entry-pages">
        <section class="entry-page active" data-entry-step="0"><p>接下来确认课程内容、学习目标和考核标准。</p><details class="security-agreement"><summary>数据安全与上传授权</summary><p>课堂资料须获得校方授权，仅用于课堂分析与教育支持。新上传原始视频保存60天，到期前 15 天提醒。下载仅限获授权人员；原视频默认不进入公司长期资源库。</p><label for="entryCompanyArchive">脱敏结构化结果长期归档</label><select id="entryCompanyArchive"><option value="no">不允许，仅用于本次课堂分析</option><option value="yes">已获校方授权，允许复核后的脱敏结构化结果归档（不含原视频和姓名）</option></select></details><p class="hint">点击“同意并继续”确认本次资料已获授权，并同意<a href="/demo2/privacy" target="_blank" rel="noopener">数据安全与隐私说明</a>。</p></section>
        <section class="entry-page" data-entry-step="1"><label for="entryCourseSelect">本次要分析哪一节课？</label><select id="entryCourseSelect"></select><p>选择后将载入课程已有目标和校方考核口径。</p></section>
        <section class="entry-page" data-entry-step="2"><label for="entryCourseType">这是一门什么课程？</label><input id="entryCourseType" placeholder="例如：生活数学、生活语文" /><p>填写学校日常使用的课程类型或学科名称。</p></section>
        <section class="entry-page" data-entry-step="3"><label for="entryCourseName">这节课叫什么？</label><input id="entryCourseName" placeholder="输入课程名称" /><p>报告、教师复核表和学生档案都会使用这个名称。</p></section>
        <section class="entry-page" data-entry-step="4"><label for="entryLessonStandard">学校希望学生学会什么？</label><textarea id="entryLessonStandard" placeholder="填写学校官方教案要求与课程标准"></textarea><p>尽量写成可观察、可核对的学习目标。</p></section>
        <section class="entry-page" data-entry-step="5"><label for="entryPlanRequirement">这节课准备怎样教？</label><textarea id="entryPlanRequirement">依据教案识别导入、示范、引导练习、个别练习和总结阶段；记录明确学习机会、提示等级、学生回应与迁移表现。</textarea><p>填写关键教学步骤、材料、提示方式和作答机会。</p></section>
        <section class="entry-page" data-entry-step="6"><label for="entryAssessment">怎样才算学生完成了？</label><textarea id="entryAssessment" placeholder="填写校方考核标准"></textarea><p>建议区分独立完成、提示后完成、未观察到和证据不足。</p></section>
        <section class="entry-page" data-entry-step="7"><label for="entryConfirmedBy">最后由谁确认本次课程信息？</label><input id="entryConfirmedBy" value="校方演示确认" /><label class="confirm-check"><input type="checkbox" id="entryConfirmed" />我已确认课程信息与校方要求一致。关键学习结论仍由教师复核。</label></section>
      </div>
      <div class="action-row entry-actions"><button class="secondary" id="entryBackButton" type="button">上一步</button><button class="primary" id="entryNextButton" type="button">下一步</button><button class="primary" id="enterDemoButton" type="button">确认并进入分析</button><span class="hint" id="entryError">课程信息仅用于本次分析。</span></div>
    </div>
  </div>
</section>
<header>
  <div class="topbar">
    <div class="brand"><span class="brand-mark" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M2 4.5a3 3 0 0 1 3-1.5h4a3 3 0 0 1 3 3v15a3 3 0 0 0-3-3H5a3 3 0 0 0-3 1.5z"/><path d="M22 4.5A3 3 0 0 0 19 3h-4a3 3 0 0 0-3 3v15a3 3 0 0 1 3-3h4a3 3 0 0 1 3 1.5z"/><path d="m16 9 1.5 1.5L20 8"/></svg></span><div><strong>RehabAffect</strong><span>课堂学习证据工作台</span></div></div>
    <div class="top-actions">
      <span class="status" id="runStatus" role="status" aria-live="polite"><i></i>本地授权数据 · 分析已完成</span>
      <select class="course-select" id="courseSelect" aria-label="切换课程"></select>
      <a class="ghost-link" href="/seewo_student_demo"><svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="m15 18-6-6 6-6"/><path d="M9 12h10"/></svg>返回 Demo1</a>
    </div>
  </div>
</header>
<main>
  <div class="page-intro">
    <div><span class="eyebrow">课堂观察 · 教师复核 · 长期追踪</span><h1>课堂学习证据台</h1><p>把三名学生的课堂表现、教师调整、学习结果和长期成长放进同一条可复核证据链。</p></div>
    <div class="page-intro-note"><b>当前分析边界</b><span>初评不等于定论</span><span>关键片段需教师复核</span></div>
  </div>
  <div class="layer-ribbon" aria-label="分析结构">
    <div><b>01 学生资料</b><span>档案与历史基线</span></div><i></i>
    <div><b>02 课堂证据</b><span>视频与师生互动</span></div><i></i>
    <div><b>03 教学决策</b><span>目标、卡点与支持</span></div><i></i>
    <div><b>04 成长轨迹</b><span>跨课趋势与留档</span></div>
  </div>

  <details class="section course-foundation" id="courseSetup" aria-label="课程与评价依据">
    <summary class="section-head"><div><span class="eyebrow">课程与评价依据</span><h2>课程基线与评价口径</h2><p>已在进入分析前确认，需要时可展开修改。</p></div><span class="disclosure-label">查看课程设置</span></summary>
    <div class="section-body">
      <div class="input-grid">
        <div><label for="courseType">课程类型</label><input id="courseType" /></div>
        <div><label for="courseName">课程名称</label><input id="courseName" /></div>
        <div><label for="lessonStandard">课程标准</label><textarea id="lessonStandard"></textarea></div>
        <div><label for="assessmentStandard">校方考核标准</label><textarea id="assessmentStandard"></textarea></div>
      </div>
      <div class="action-row">
        <button class="primary" id="fitButton">生成适配建议</button>
        <button class="secondary" id="startButton">开始检测</button>
        <span class="hint" id="courseDecision"></span>
      </div>
      <div class="fit-grid" id="fitGrid"></div>
    </div>
  </details>

  <section class="section observation-section" id="workbench">
    <div class="section-head"><div><span class="eyebrow">课堂证据画面</span><h2>三人同步课堂证据</h2><p>群像用于核对座位与互动关系，人像用于查看个体证据；身份由校方确认。</p></div><div class="section-status"><i></i>录像分析完成</div></div>
    <div class="workbench">
      <div class="visual-pane">
        <div class="visual-toolbar">
          <div class="segmented" role="group" aria-label="课堂画面模式"><button id="groupMode" class="active" aria-pressed="true"><svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>群像</button><button id="portraitMode" aria-pressed="false"><svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>人像</button></div>
          <span class="visual-note" id="visualCaption"></span>
        </div>
        <div class="stage"><img id="classImage" alt="课堂身份复核画面" /></div>
      </div>
      <aside class="student-pane">
        <div class="student-tabs" id="studentTabs"></div>
        <div class="student-detail" id="studentDetail"></div>
      </aside>
    </div>
  </section>

  <section class="section analysis-studio">
    <div class="analysis-heading">
      <div><span class="eyebrow">从证据到支持</span><h2>学生结论与支持决策</h2><p>选择学生，再沿着学习、复核、支持和留档四类证据查看。</p></div>
      <span class="review-progress" id="reviewProgress" role="status" aria-live="polite"></span>
    </div>
    <div class="student-strip" id="studentStrip"></div>
    <div class="analysis-layout">
      <nav class="tabs" id="resultTabs" role="tablist" aria-label="分析功能">
        <div class="tab-cluster"><span>学生资料</span><button data-tab="profile" data-icon="profile" title="一人一案证据页">一人一案</button><button data-tab="tracking" data-icon="history" title="跨课历史记录">历史记录</button><button data-tab="profileImport" data-icon="upload" title="导入IEP与专业支持资料">资料导入</button></div>
        <div class="tab-cluster"><span>课堂证据</span><button data-tab="state" data-icon="activity" title="完整状态分析">状态时间线</button><button data-tab="interaction" data-icon="messages" title="学生与教师双视角">师生互动</button><button data-tab="evidence" data-icon="clipboard" title="教师复核关键片段">教师复核</button><button data-tab="teacher" data-icon="gauge" title="教师支持效果">支持效果</button></div>
        <div class="tab-cluster"><span>教学决策</span><button data-tab="mastery" data-icon="target" class="active" title="当前学习掌握度">学习判断</button><button data-tab="specialSupport" data-icon="support" title="特殊教育个体支持">支持工具</button><button data-tab="action" data-icon="bot" title="具身动作方案">动作方案</button></div>
        <div class="tab-cluster"><span>成长轨迹</span><button data-tab="growth" data-icon="trend" title="五大能力情景趋势">五域趋势</button><button data-tab="courseReport" data-icon="file" title="一节课一份学校分析">课程分析</button><button data-tab="feedback" data-icon="report" title="约一千字综合报告">深度报告</button><button data-tab="summary" data-icon="database" title="课堂汇总">数据来源</button><button data-tab="json" data-icon="code" title="结构化 JSON">结构化数据</button></div>
        <div class="tab-cluster"><span>数据治理</span><button data-tab="videoUpload" data-icon="video" title="四个主体独立上传与结果下载">四路上传</button><button data-tab="storage" data-icon="storage" title="数据库、保存周期与文件下载">数据存储</button></div>
      </nav>
      <div class="analysis-content">
        <div class="result-summary" id="resultSummary"></div>
        <div class="tab-body" id="tabBody" role="tabpanel" tabindex="0"></div>
      </div>
    </div>
  </section>

  <div class="privacy" id="privacyNote"></div>
</main>
<script>
const DATA = __PAYLOAD__;
let courseIndex = 0;
let activeStudentId = DATA.students[0].student_id;
let viewMode = 'group';
let activeTab = 'mastery';
let activeWindowIndex = 0;
let stateFilter = 'all';
let trendView = 'lesson';
let entryStep = 0;
let reviews = {...(DATA.saved_reviews || {})};
let longReports = {};
let courseContexts = {};
let studentRecordCache = {};
let studentRecordLoading = new Set();
let storageState = null;
let storageLoading = false;
let videoChannelState = null;
let videoChannelLoading = false;
const $ = (id) => document.getElementById(id);
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const NAV_ICON_PATHS = {
  profile:'<path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
  history:'<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l3 2"/>',
  upload:'<path d="M12 16V4"/><path d="m7 9 5-5 5 5"/><path d="M5 20h14"/>',
  activity:'<path d="M3 12h4l2-7 4 14 2-7h6"/>',
  messages:'<path d="M21 15a4 4 0 0 1-4 4H8l-5 3v-5a4 4 0 0 1-1-2V7a4 4 0 0 1 4-4h11a4 4 0 0 1 4 4z"/><path d="M8 10h.01M12 10h.01M16 10h.01"/>',
  clipboard:'<rect width="14" height="18" x="5" y="3" rx="2"/><path d="M9 3V1h6v2M9 12l2 2 4-4"/>',
  gauge:'<path d="M20.4 15a9 9 0 1 0-16.8 0"/><path d="M12 12l4-4"/><path d="M7 19h10"/>',
  target:'<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/>',
  support:'<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="3"/><path d="m5.6 5.6 4.3 4.3m4.2 4.2 4.3 4.3m0-12.8-4.3 4.3m-4.2 4.2-4.3 4.3"/>',
  bot:'<rect width="16" height="13" x="4" y="8" rx="2"/><path d="M9 12h.01M15 12h.01M9 17h6M12 8V4M8 4h8"/>',
  trend:'<path d="M3 3v18h18"/><path d="m7 16 4-5 3 3 5-7"/>',
  file:'<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M8 17v-3m4 3v-6m4 6v-8"/>',
  report:'<path d="M6 2h9l5 5v15H6z"/><path d="M14 2v6h6M9 13h6M9 17h6"/><path d="M3 6v15h12"/>',
  database:'<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/>',
  storage:'<path d="M4 5h16v14H4z"/><path d="M4 9h16"/><path d="M8 14h4"/><circle cx="17" cy="14" r="1"/>',
  video:'<path d="M3 6h14v12H3z"/><path d="m17 10 4-3v10l-4-3z"/><path d="M7 10h6M7 14h4"/>',
  code:'<path d="m8 9-3 3 3 3m8-6 3 3-3 3m-3-9-2 12"/>'
};
function decorateNavigation() {
  document.querySelectorAll('#resultTabs [data-icon]').forEach(button => {
    const paths = NAV_ICON_PATHS[button.dataset.icon];
    if (!paths || button.querySelector('svg')) return;
    button.setAttribute('role','tab');
    button.setAttribute('aria-controls','tabBody');
    button.insertAdjacentHTML('afterbegin', `<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${paths}</svg>`);
  });
}
const course = () => DATA.courses[courseIndex];
const result = () => course().student_results.find(item => item.student_id === activeStudentId);
const student = () => DATA.students.find(item => item.student_id === activeStudentId);
const levelLabel = (value) => ({4:'独立完成',3:'简单提示',2:'示范/协助',1:'尚未表现'}[Math.round(value)] || '待复核');
const ROBOT_MOTION_LABELS = {
  idle_or_soft_nod:'保持站位，轻微点头',
  slow_nod:'缓慢点头',
  slow_turn_to_target:'缓慢转向目标',
  slow_turn_to_screen:'缓慢转向屏幕',
  slow_turn_to_screen_and_nod:'缓慢转向屏幕并点头',
  no_motion:'保持静止',
  hold_position_no_touch:'原地等待，不主动接触',
  keep_distance:'保持安全距离',
  step_back_and_hold:'缓慢后退并保持位置',
  teacher_handoff:'保持静止，交由教师处理'
};
const motionLabel = (value) => ROBOT_MOTION_LABELS[value] || String(value || '').replaceAll('_',' ');
const motionHtml = (value) => `${esc(motionLabel(value))}<code class="motion-code">${esc(value)}</code>`;
const PRINT_ICON = '<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9V2h12v7"/><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><rect width="12" height="8" x="6" y="14"/></svg>';
const ENTRY_QUESTIONS = [
  ['准备进入课堂分析','确认课程内容与学习目标，整理本节课的学习证据。'],
  ['先选择要分析的课程','选择后会载入已有目标、视频和校方考核口径。'],
  ['这是一门什么课程？','使用学校日常叫法，方便后续按学科比较。'],
  ['这节课叫什么？','课程名称会写入报告、复核表和学生长期档案。'],
  ['学校希望学生学会什么？','把目标写成能在课堂中观察和复核的行为。'],
  ['这节课准备怎样教？','说明教学步骤、材料、提示和作答机会。'],
  ['怎样才算学生完成了？','请区分独立、提示后完成、未观察到和证据不足。'],
  ['确认后开始分析','请由了解课程要求的教师或教研人员确认。'],
];
let entrySecurityAccepted = false;

function renderEntryWizard() {
  document.querySelectorAll('[data-entry-step]').forEach(page => page.classList.toggle('active', Number(page.dataset.entryStep) === entryStep));
  const [title,hint] = ENTRY_QUESTIONS[entryStep];
  $('entryStepLabel').textContent = `安全与课程配置 · 第 ${entryStep + 1}/${ENTRY_QUESTIONS.length} 步`;
  $('entryQuestionTitle').textContent = title;
  $('entryQuestionHint').textContent = hint;
  $('entryProgressBar').style.width = `${((entryStep + 1) / ENTRY_QUESTIONS.length) * 100}%`;
  $('entryProgress').setAttribute('aria-valuenow',String(entryStep + 1));
  $('entryBackButton').style.visibility = entryStep === 0 ? 'hidden' : 'visible';
  $('entryNextButton').style.display = entryStep === ENTRY_QUESTIONS.length - 1 ? 'none' : 'inline-flex';
  $('entryNextButton').textContent = entryStep === 0 ? '同意并继续' : '下一步';
  $('enterDemoButton').style.display = entryStep === ENTRY_QUESTIONS.length - 1 ? 'inline-flex' : 'none';
  document.querySelectorAll('.entry-flow > div').forEach((node,index) => node.classList.toggle('active', index === Math.min(2, Math.floor(entryStep / 3))));
}

function entryValueForStep(step) {
  return [
    entrySecurityAccepted,
    $('entryCourseSelect').value,
    $('entryCourseType').value.trim(),
    $('entryCourseName').value.trim(),
    $('entryLessonStandard').value.trim(),
    $('entryPlanRequirement').value.trim(),
    $('entryAssessment').value.trim(),
    $('entryConfirmedBy').value.trim(),
  ][step];
}

function changeEntryStep(delta) {
  if (delta > 0 && entryStep === 0) entrySecurityAccepted = true;
  if (delta > 0 && !entryValueForStep(entryStep)) {
    $('entryError').textContent = '请先完成这一题，再进入下一步。';
    return;
  }
  entryStep = Math.max(0, Math.min(ENTRY_QUESTIONS.length - 1, entryStep + delta));
  $('entryError').textContent = '安全协议和课程确认会写入本地审计记录。';
  renderEntryWizard();
}

function initCourseSelect() {
  const requestedCourseId = new URLSearchParams(window.location.search).get('course_id') || '';
  const requestedCourseIndex = DATA.courses.findIndex(item => item.course_id === requestedCourseId);
  if (requestedCourseIndex >= 0) courseIndex = requestedCourseIndex;
  $('courseSelect').innerHTML = DATA.courses.map((item, index) => `<option value="${index}">${esc(item.subject)} · ${esc(item.course_name)}</option>`).join('');
  $('entryCourseSelect').innerHTML = $('courseSelect').innerHTML;
  $('courseSelect').value = String(courseIndex);
  $('courseSelect').addEventListener('change', event => { courseIndex = Number(event.target.value); activeStudentId = DATA.students[0].student_id; activeWindowIndex = 0; stateFilter = 'all'; entryStep = 0; populateEntryForm(); entrySecurityAccepted=false; $('entryCompanyArchive').value='no'; $('entryConfirmed').checked=false; $('entryGate').style.display='grid'; renderAll(); });
  $('entryCourseSelect').addEventListener('change', event => { courseIndex = Number(event.target.value); $('courseSelect').value = String(courseIndex); populateEntryForm(); });
  populateEntryForm();
  if (requestedCourseId && requestedCourseIndex < 0) {
    $('runStatus').textContent = `课程批次 ${requestedCourseId} 的视频已接收，正在等待后台分析；当前页面先展示已有示例结果。`;
  }
}

function populateEntryForm() {
  const item = course();
  const context = courseContexts[item.course_id] || {};
  $('entryCourseSelect').value = String(courseIndex);
  $('entryCourseType').value = context.course_type || item.subject;
  $('entryCourseName').value = context.course_name || item.course_name;
  $('entryLessonStandard').value = context.lesson_standard || item.lesson_standard;
  $('entryAssessment').value = context.school_assessment_standard || item.school_assessment_standard;
  $('entryPlanRequirement').value = context.lesson_plan_requirement || '依据教案识别导入、示范、引导练习、个别练习和总结阶段；记录明确学习机会、提示等级、学生回应与迁移表现。';
  renderEntryWizard();
}

function currentCourseContext() {
  return courseContexts[course().course_id] || {
    course_type: course().subject,
    course_name: course().course_name,
    lesson_standard: course().lesson_standard,
    school_assessment_standard: course().school_assessment_standard,
    lesson_plan_requirement: '依据学校教案组织教学阶段、任务机会、提示等级和课后复核。',
    confirmed_by: '演示人员'
  };
}

async function confirmCourseEntry() {
  const fields = {
    course_type:$('entryCourseType').value.trim(),
    course_name:$('entryCourseName').value.trim(),
    lesson_standard:$('entryLessonStandard').value.trim(),
    lesson_plan_requirement:$('entryPlanRequirement').value.trim(),
    school_assessment_standard:$('entryAssessment').value.trim(),
    confirmed_by:$('entryConfirmedBy').value.trim()
  };
  const missing = Object.entries(fields).filter(([,value]) => !value).map(([key]) => key);
  if (missing.length || !entrySecurityAccepted || !$('entryConfirmed').checked) {
    $('entryError').textContent = missing.length ? '请补全课程类型、名称、教案要求、考核标准和确认人。' : '请先确认数据安全协议和课程使用边界。';
    return;
  }
  const previousText = $('enterDemoButton').textContent;
  $('enterDemoButton').disabled = true;
  $('enterDemoButton').textContent = '正在记录授权';
  try {
    const result = await apiJson('/api/seewo_demo2/security_acceptance', {
      method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
        course_id:course().course_id,
        course_name:fields.course_name,
        confirmed_by:fields.confirmed_by,
        security_confirmed:true,
        allow_company_archive:$('entryCompanyArchive').value==='yes',
        agreement_version:'2026-09-08',
      }),
    });
    fields.security_acceptance_id = result.acceptance.acceptance_id;
    fields.allow_company_archive = result.acceptance.allow_company_archive;
  } catch (error) {
    $('entryError').textContent = `安全协议记录失败：${error.message}`;
    return;
  } finally {
    $('enterDemoButton').disabled = false;
    $('enterDemoButton').textContent = previousText;
  }
  courseContexts[course().course_id] = fields;
  sessionStorage.setItem('seewoDemo2CourseContexts', JSON.stringify(courseContexts));
  $('entryGate').style.display = 'none';
  $('runStatus').innerHTML = `<i></i>安全协议已记录 · ${esc(fields.course_type)} · ${esc(fields.course_name)}`;
  renderAll();
}

function selectStudent(studentId) {
  activeStudentId = studentId;
  activeWindowIndex = 0;
  stateFilter = 'all';
  trendView = 'lesson';
  renderWorkbench();
  renderStudentStrip();
  renderResults();
}

function renderCourseSetup() {
  const item = course();
  const context = currentCourseContext();
  $('courseType').value = context.course_type;
  $('courseName').value = context.course_name;
  $('lessonStandard').value = context.lesson_standard;
  $('assessmentStandard').value = context.school_assessment_standard;
  $('courseDecision').textContent = `综合适配 ${item.course_fit.overall_fit_score} 分 · ${item.course_fit.overall_level}`;
  $('fitGrid').innerHTML = item.course_fit.students.map(fit => `
    <article class="fit-item ${fit.fit_score < 82 ? 'warn' : ''}">
      <div class="fit-top"><strong>${esc(fit.display_name)}</strong><span class="fit-score">${fit.fit_score}</span></div>
      <p><b>${esc(fit.fit_level)}</b> · 上次平均等级 ${fit.previous_average}</p>
      <p>最大差距：${esc(fit.largest_gap_objective)}</p>
      <p>${esc(fit.recommended_modifications[0])}</p>
    </article>`).join('');
}

function renderStudentTabs() {
  $('studentTabs').innerHTML = course().student_results.map(item => `
    <button class="student-tab ${item.student_id === activeStudentId ? 'active' : ''}" data-student="${item.student_id}" aria-pressed="${item.student_id === activeStudentId}">
      <strong>${esc(item.display_name)}</strong><span>${esc(item.seat_label)} · ${esc(item.mastery.assessment?.band?.label || item.mastery.band)} · ${item.mastery.assessment?.overall_score ?? '—'}/10</span>
    </button>`).join('');
  document.querySelectorAll('[data-student]').forEach(button => button.addEventListener('click', () => selectStudent(button.dataset.student)));
}

function renderWorkbench() {
  renderStudentTabs();
  const item = result();
  const profile = item.education_profile;
  const imageUrl = viewMode === 'group' ? course().assets.group_image_url : item.portrait_url;
  $('classImage').src = imageUrl;
  $('classImage').alt = viewMode === 'group' ? '三名学生群像身份复核画面' : `${item.display_name}课堂人像`;
  $('visualCaption').textContent = viewMode === 'group' ? '校方确认身份 · 固定座位ROI' : `${item.display_name} · ${item.seat_label}`;
  $('groupMode').classList.toggle('active', viewMode === 'group');
  $('portraitMode').classList.toggle('active', viewMode === 'portrait');
  $('groupMode').setAttribute('aria-pressed',String(viewMode === 'group'));
  $('portraitMode').setAttribute('aria-pressed',String(viewMode === 'portrait'));
  const dims = item.mastery.dimensions;
  $('studentDetail').innerHTML = `
    <div class="student-title">
      <img class="portrait" src="${item.portrait_url}" alt="${esc(item.display_name)}课堂人像" />
      <div><h3>${esc(item.display_name)}</h3><p>${esc(item.seat_label)} · 身份状态：校方已确认</p><p>${esc(profile.profile_label)}</p></div>
    </div>
    <div class="score-row">
      <div class="score-ring" style="--score:${item.mastery.overall_score}%"><strong>${item.mastery.assessment?.overall_score ?? '—'}</strong></div>
      <div class="metric-list">
        ${[['正确性',dims.accuracy],['独立程度',dims.independence],['重复一致性',dims.consistency],['迁移',dims.transfer]].map(([label,value]) => `<div class="metric"><span>${label}</span><div class="bar"><i style="width:${value}%"></i></div><b>${(value / 10).toFixed(1)}</b></div>`).join('')}
      </div>
    </div>
    <div class="callout"><b>${esc(item.mastery.assessment?.band?.label || item.mastery.band)}</b> · ${item.mastery.assessment?.overall_score ?? '—'}/10（6分及格） · ${esc(item.mastery.review_status)}<br>${esc(item.individual_target)}</div>
    <div class="mini-actions">
      <div><b>屏幕</b><br>${esc(item.robot_action.screen)}</div>
      <div><b>语音</b><br>${esc(item.robot_action.speech)}</div>
      <div><b>动作</b><br>${motionHtml(item.robot_action.motion)}</div>
      <div><b>教师确认</b><br>${item.robot_action.teacher_confirmation_required ? '需要' : '低风险动作可执行'}</div>
    </div>`;
}

function renderStudentStrip() {
  $('studentStrip').innerHTML = course().student_results.map(item => {
    const score = item.mastery.assessment?.overall_score ?? '—';
    const pass = typeof score === 'number' ? (score >= 6 ? '及格' : '未及格') : '';
    const passClass = typeof score === 'number' ? (score >= 6 ? '' : ' style="color:var(--coral)"') : '';
    const reviewStatus = esc(item.mastery.review_status || '系统初评');
    return `<button class="student-card ${item.student_id === activeStudentId ? 'active' : ''}" data-overview-student="${item.student_id}" aria-pressed="${item.student_id === activeStudentId}">
      <div class="student-card-top"><img src="${item.portrait_url}" alt="" /><header><h3>${esc(item.display_name)}</h3><span class="big">${score}</span></header><span>${esc(item.seat_label)} · 初评 ${score}/10（6分及格）</span></div>
      <p><b>${esc(item.mastery.assessment?.band?.label || item.mastery.band)}</b><span${passClass}> · ${pass}</span> · 参与指数 ${item.state_summary.participation_score}</p>
      <p>复核：${reviewStatus}</p>
      <p>下一步：${esc(item.next_lesson_actions[0])}</p>
    </button>`;
  }).join('');
  document.querySelectorAll('[data-overview-student]').forEach(button => button.addEventListener('click', () => selectStudent(button.dataset.overviewStudent)));
}

function masteryHtml(item) {
  const score = item.mastery.assessment?.overall_score ?? '—';
  const reviewStatus = esc(item.mastery.review_status || '系统初评');
  const passLabel = typeof score === 'number' ? (score >= 6 ? '及格' : '未及格（6分及格）') : '6分及格';
  const longitudinal = item.mastery.longitudinal || {};
  const trendLabels = {lesson:'逐课',week:'逐周',month:'逐月',rolling_60_days:'近60天均值'};
  const trendRows = {
    lesson: (longitudinal.lesson || []).map(p => `<tr><td>${esc(p.date)}</td><td>${p.score}</td><td>${esc(p.band?.label ?? p.band ?? '')}</td></tr>`),
    week: (longitudinal.week || []).map(p => `<tr><td>${esc(p.period)}</td><td>${p.score}</td><td>${p.sessions}节</td></tr>`),
    month: (longitudinal.month || []).map(p => `<tr><td>${esc(p.period)}</td><td>${p.score}</td><td>${p.sessions}节</td></tr>`),
    rolling_60_days: (() => {
      const r = longitudinal.rolling_60_days;
      if (!r || r.sessions === 0) return [];
      return [`<tr><td>${esc(r.from)} — ${esc(r.to)}</td><td>${r.score ?? '—'}</td><td>${r.sessions}节</td></tr>`];
    })(),
  };
  const activeTrendRows = trendRows[trendView] || [];
  const trendBody = activeTrendRows.length === 0
    ? `<p class="trend-empty">暂无足够历史课次</p>`
    : `<div class="scroll-table"><table><thead><tr><th>${trendView === 'lesson' ? '日期' : '周期'}</th><th>分数</th><th>${trendView === 'lesson' ? '等级' : '课次'}</th></tr></thead><tbody>${activeTrendRows.join('')}</tbody></table></div>`;
  return `<div class="callout">
    <b>综合初评：${score}/10 · ${passLabel}</b> · 复核状态：${reviewStatus}<br>
    <span class="dim-chips">
      <span class="dim-chip"><b>正确性</b> 35%</span>
      <span class="dim-chip"><b>独立程度</b> 30%</span>
      <span class="dim-chip"><b>一致性</b> 20%</span>
      <span class="dim-chip"><b>迁移</b> 15%</span>
    </span>
  </div>
  <table><thead><tr><th>课程目标</th><th>上次</th><th>本次初评</th><th>机会/观察</th><th>独立/提示</th><th>状态</th></tr></thead><tbody>
    ${item.mastery.objectives.map(row => `<tr><td>${esc(row.label)}</td><td>${levelLabel(row.previous_level)}</td><td><span class="level">${levelLabel(row.provisional_level)} · ${row.score_10}/10</span></td><td>${row.opportunities}/${row.observed}</td><td>${row.independent}/${row.prompted}</td><td>${esc(row.review_status)}</td></tr>`).join('')}
    </tbody></table>
  <div class="callout">答案正确性、提示等级和迁移表现需要教师抽检片段确认；未观察不计入“不会”。</div>
  <div class="filter-row"><h3>历史得分趋势</h3><div class="segmented">${Object.entries(trendLabels).map(([key,label]) => `<button class="${trendView === key ? 'active' : ''}" data-trend-view="${key}">${label}</button>`).join('')}</div></div>
  ${trendBody}
  <h3>下一节课建议</h3><ol>${item.next_lesson_actions.map(action => `<li>${esc(action)}</li>`).join('')}</ol>`;
}

function windowInspectorHtml(item) {
  const row = item.state_timeline[Math.min(activeWindowIndex, item.state_timeline.length - 1)];
  const action = row.recommended_action;
  return `<div class="window-inspector">
    <div><h3>${esc(row.time_label)} · ${esc(row.scene)} · ${esc(row.state_zh)}</h3><p>${esc(row.evidence)}</p><p><b>解释：</b>${esc(row.interpretation)}</p><p>置信度 ${Math.round(row.confidence * 100)}% · 证据质量 ${Math.round(row.evidence_quality * 100)}% · 风险 ${esc(row.human_state_json.risk_level)}</p></div>
    <div><h3>该时段建议动作</h3><p><b>屏幕：</b>${esc(action.screen)}</p><p><b>语音：</b>${esc(action.speech)}</p><p><b>机器人：</b>${motionHtml(action.robot_motion)} · ${action.teacher_alert ? '先提醒教师复核' : '保持低刺激执行'}</p><button class="inline-command" data-open-tab="action">查看完整动作方案</button></div>
  </div>`;
}

function evidenceHtml(item) {
  const spec = course().teacher_review_spec;
  const cards = item.key_interactions.map((row,index) => {
    const key = `${course().course_id}:${item.student_id}:${index}`;
    const review = reviews[key] || {verdict:'待复核',correctness:'未标注',prompt_level:'未标注',teacher_adjustment:'',student_follow_up:'',note:''};
    const windowIndex = course().timeline.findIndex(window => window.start_sec === row.start_sec);
    return `<details class="evidence review-clip" ${index === 0 ? 'open' : ''}>
      <summary class="clip-heading"><div><span class="clip-id">${esc(row.clip_id)}</span><strong>${esc(course().course_name)} · ${esc(item.display_name)}</strong></div><div class="clip-heading-meta"><time>${esc(row.time_label)}</time><span class="clip-review-state" data-review-state="${key}">${esc(review.verdict)}</span><svg class="clip-chevron" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg></div></summary>
      <div class="clip-context"><span>${esc(row.lesson_phase)}</span><span>${esc(row.teacher_activity)}</span></div>
      <div class="judgement"><b>系统判断</b><p>${esc(row.system_judgement)}</p></div>
      <p><b>画面证据：</b>${esc(row.evidence)}</p><p class="review-reason"><b>为什么请老师确认：</b>${esc(row.review_reason)}</p><button type="button" class="locate-clip" data-jump-window="${windowIndex}">定位到完整时间线核对</button>
      <div class="interaction-chain">
        <div class="interaction-step"><span>学生触发</span><p>${esc(row.interaction_chain.student_trigger)}</p></div>
        <div class="interaction-step"><span>教师调整</span><p>${esc(row.interaction_chain.teacher_response)}</p></div>
        <div class="interaction-step"><span>后续结果</span><p>${esc(row.interaction_chain.student_follow_up)}</p></div>
      </div>
      <div class="interaction-result"><strong>${esc(row.interaction_chain.effect_label)} · 双视角关联度</strong><b>${row.interaction_chain.link_score}</b></div>
      <fieldset class="review-fieldset"><legend>第1步：系统判断符合真实情况吗？</legend><div class="review-row" data-key="${key}">${['符合','需修正','不确定'].map(choice => `<button type="button" class="${review.verdict === choice ? 'selected '+(choice === '需修正' ? 'correct' : choice === '不确定' ? 'uncertain' : '') : ''}" data-review="${choice}" title="${esc(spec.verdicts[choice])}">${choice}</button>`).join('')}</div><p class="field-help">符合：描述基本准确；需修正：以教师说明为准；不确定：不计入不会或退步。</p></fieldset>
      <div class="review-editor" data-review-editor="${key}">
        <label>第2步：回答或操作是否正确？<select data-review-field="correctness" aria-label="回答或操作正确性"><option>未标注</option><option ${review.correctness === '正确' ? 'selected' : ''}>正确</option><option ${review.correctness === '部分正确' ? 'selected' : ''}>部分正确</option><option ${review.correctness === '不正确' ? 'selected' : ''}>不正确</option><option ${review.correctness === '未观察到有效作答机会' ? 'selected' : ''}>未观察到有效作答机会</option><option ${review.correctness === '无法判断' ? 'selected' : ''}>无法判断</option></select></label>
        <label>第3步：学生在什么支持下完成？<select data-review-field="prompt_level" aria-label="完成时提示等级"><option value="未标注">未标注</option><option value="独立完成" ${review.prompt_level === '独立完成' ? 'selected' : ''}>4级 · 独立完成</option><option value="简单提示" ${review.prompt_level === '简单提示' ? 'selected' : ''}>3级 · 简单语言/视觉提示</option><option value="示范或部分协助" ${review.prompt_level === '示范或部分协助' ? 'selected' : ''}>2级 · 示范或部分协助</option><option value="完整协助" ${review.prompt_level === '完整协助' ? 'selected' : ''}>1级 · 完整协助</option><option value="无法判断" ${review.prompt_level === '无法判断' ? 'selected' : ''}>U · 无法判断</option></select></label>
        <label>第4步：教师实际做了什么调整？<input data-review-field="teacher_adjustment" value="${esc(review.teacher_adjustment || '')}" placeholder="例如：缩短指令、延长等待、改用图卡" /></label>
        <label>第5步：学生随后有什么变化？<input data-review-field="student_follow_up" value="${esc(review.student_follow_up || '')}" placeholder="例如：重新看向材料并独立完成一步" /></label>
        <label class="review-note-label">第6步：补充任务、材料、声音归属或画面外情况<input data-review-field="note" value="${esc(review.note || '')}" placeholder="例如：声音来自旁边学生；教师在画面外给了图片提示" /></label>
        <button class="save-review" data-save-review="${key}">保存本片段复核</button>
      </div></details>`;
  }).join('');
  const ticks = course().timeline.map((row,index) => { const state = row.students[item.student_id]; const label=`${row.time_label} ${row.lesson_phase} ${state.state_zh}`; return `<button class="tick ${state.state} ${index === activeWindowIndex ? 'selected' : ''}" data-window-index="${index}" data-tip="${esc(label)}" aria-label="${esc(label)}"></button>`; }).join('');
  return `<div class="review-guide"><div><span class="eyebrow">教师只需复核系统筛出的关键片段</span><h3>${esc(spec.name)}</h3><p>${esc(spec.work_unit)}。建议由${esc(spec.who)}完成。</p><button type="button" class="review-export" id="downloadReviewSheet">导出整课复核清单 CSV</button></div><ol><li>看清课程、学生和时间段</li><li>判断系统描述是否符合</li><li>确认正确性和提示等级</li><li>补充画面外情况并保存</li></ol></div>${windowInspectorHtml(item)}<div class="timeline" aria-label="完整课堂状态时间线">${ticks}</div><div class="evidence-list">${cards}</div>`;
}

function interactionHtml(item) {
  const chains = item.key_interactions.map(row => `<article class="evidence">
    <div class="clip-heading"><div><span class="clip-id">${esc(row.clip_id)}</span><strong>${esc(item.display_name)} · ${esc(row.lesson_phase)}</strong></div><time>${esc(row.time_label)}</time></div>
    <div class="interaction-chain">
      <div class="interaction-step"><span>01 学生当时的表现</span><p>${esc(row.interaction_chain.student_trigger)}</p></div>
      <div class="interaction-step"><span>02 教师的表达或行为</span><p>${esc(row.interaction_chain.teacher_response)}</p></div>
      <div class="interaction-step"><span>03 学生之后的变化</span><p>${esc(row.interaction_chain.student_follow_up)}</p></div>
    </div>
    <div class="interaction-result"><div><strong>${esc(row.interaction_chain.effect_label)}</strong><p>${esc(row.interaction_chain.evidence_basis)}</p></div><b>${row.interaction_chain.link_score}</b></div>
  </article>`).join('');
  return `<div class="growth-head"><div><span class="eyebrow">学生表现 · 教师支持 · 后续变化</span><h3>师生双视角互动链</h3><p>不是只陈列学生动作，而是检查学生表现出现后，教师做了什么调整，以及学生随后是否出现有效变化。</p></div><div class="evidence-grade">教师复核后生效</div></div><div class="evidence-list">${chains}</div>`;
}

function csvCell(value) {
  return `"${String(value ?? '').replaceAll('"','""')}"`;
}

function downloadReviewSheet() {
  const headers = ['课程','学生','片段编号','开始秒','结束秒','时间段','教学环节','课堂活动','系统判断','复核原因','教师结论','回答或操作正确性','提示等级','教师实际调整','学生后续变化','补充说明'];
  const rows = [];
  course().student_results.forEach(studentResult => studentResult.key_interactions.forEach((clip,index) => {
    const key = `${course().course_id}:${studentResult.student_id}:${index}`;
    const review = reviews[key] || {};
    rows.push([course().course_name,studentResult.display_name,clip.clip_id,clip.start_sec,clip.end_sec,clip.time_label,clip.lesson_phase,clip.teacher_activity,clip.system_judgement,clip.review_reason,review.verdict || '待复核',review.correctness || '未标注',review.prompt_level || '未标注',review.teacher_adjustment || '',review.student_follow_up || '',review.note || '']);
  }));
  const csv = [headers,...rows].map(row => row.map(csvCell).join(',')).join('\n');
  const url = URL.createObjectURL(new Blob(['\ufeff',csv],{type:'text/csv;charset=utf-8'}));
  const link = document.createElement('a');
  link.href = url;
  link.download = `${course().course_name}_教师复核清单.csv`;
  link.click();
  URL.revokeObjectURL(url);
  $('runStatus').textContent = `已导出${rows.length}条关键片段复核清单`;
}

async function persistReviews() {
  const response = await fetch('/api/seewo_demo2_reviews', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({course_id:course().course_id,reviews})});
  if (!response.ok) throw new Error('教师复核保存失败');
  const data = await response.json();
  reviews = {...reviews,...data.reviews};
  return data;
}

function stateHtml(item) {
  const summary = item.state_summary;
  const counts = summary.state_counts || {};
  const rows = item.state_timeline.map((row,index) => ({row,index})).filter(({row}) => stateFilter === 'all' || ['low_response','uncertain'].includes(row.state));
  return `<div class="summary-grid">
    <div class="summary-box"><span>30秒状态窗口</span><strong>${summary.window_count}</strong></div>
    <div class="summary-box"><span>参与指数</span><strong>${summary.participation_score}</strong></div>
    <div class="summary-box"><span>主要状态</span><strong style="font-size:17px">${esc(summary.top_state_zh)}</strong></div>
    <div class="summary-box"><span>建议复核窗口</span><strong>${summary.review_required_count}</strong></div>
  </div>
  <div class="callout">状态分布：稳定参与 ${counts.engaged || 0}；回应/操作 ${counts.active_response || 0}；回应线索较低 ${counts.low_response || 0}；未观察到有效作答机会 ${counts.not_observed || 0}；证据不足 ${counts.uncertain || 0}。未作答但没有明确机会时，不计入“不会”、拒绝或退步。</div>
  ${windowInspectorHtml(item)}
  <div class="filter-row"><h3>完整30秒动作/状态窗口</h3><div class="segmented"><button class="${stateFilter === 'all' ? 'active' : ''}" data-state-filter="all">全部</button><button class="${stateFilter === 'review' ? 'active' : ''}" data-state-filter="review">只看待复核</button></div></div>
  <div class="scroll-table"><table><thead><tr><th>时间</th><th>课堂阶段</th><th>状态</th><th>置信度</th><th>证据</th><th>解释</th></tr></thead><tbody>
    ${rows.map(({row,index}) => `<tr class="selectable ${index === activeWindowIndex ? 'selected' : ''}" data-window-index="${index}"><td>${esc(row.time_label)}</td><td>${esc(row.scene)}</td><td><span class="state-tag">${esc(row.state_zh)}</span></td><td>${Math.round(row.confidence * 100)}%</td><td>${esc(row.evidence)}</td><td>${esc(row.interpretation)}</td></tr>`).join('')}
  </tbody></table></div>`;
}

function actionHtml(item) {
  return `${windowInspectorHtml(item)}<div class="callout"><b>课后个体支持动作</b>：屏幕“${esc(item.robot_action.screen)}”；语音“${esc(item.robot_action.speech)}”；机器人动作 ${motionHtml(item.robot_action.motion)}。高影响动作始终需要教师确认。</div>
  <div class="scroll-table"><table><thead><tr><th>时间</th><th>状态</th><th>屏幕</th><th>语音</th><th>机器人动作</th><th>教师端</th></tr></thead><tbody>
    ${item.state_timeline.map((row,index) => { const action = row.recommended_action; return `<tr class="selectable ${index === activeWindowIndex ? 'selected' : ''}" data-window-index="${index}"><td>${esc(row.time_label)}</td><td>${esc(row.state_zh)}</td><td>${esc(action.screen)}</td><td>${esc(action.speech)}</td><td>${motionHtml(action.robot_motion)}</td><td>${action.teacher_alert ? '提醒复核' : '保持观察'}</td></tr>`; }).join('')}
  </tbody></table></div>`;
}

function trackingHtml(item) {
  const tracking = item.student_tracking;
  return `<div class="callout"><b>${esc(tracking.student_profile.baseline_status)}</b><br>${esc(tracking.lesson_conclusion.summary)}<br>${esc(tracking.lesson_conclusion.data_status)}</div>
  <div class="tracking-grid">
    ${tracking.growth_indicators.map(metric => `<article class="info-block"><h3>${esc(metric.name)}</h3><p><b>${esc(metric.current)}</b></p><p>${esc(metric.evidence)}</p></article>`).join('')}
  </div>
  <h3>关键追踪时刻</h3>
  <div class="tracking-grid">${tracking.key_moments.map(moment => `<article class="info-block"><h3>${esc(moment.time_label)} · ${esc(moment.title)}</h3><p>${esc(moment.why_it_matters)}</p><p><b>教师复核：</b>${esc(moment.teacher_review_question)}</p></article>`).join('')}</div>
  <h3>下一次支持计划</h3><ol>${tracking.next_support_plan.map(action => `<li>${esc(action)}</li>`).join('')}</ol>`;
}

function teacherHtml() {
  const teacher = course().teacher_effectiveness;
  return `<div class="action-stack">
    <article class="info-block"><div class="teacher-score">${teacher.overall_score}</div><h3>${esc(teacher.headline)}</h3><p>${esc(teacher.summary)}</p></article>
    <article class="info-block"><h3>使用边界</h3><p>${esc(teacher.boundary)}</p><h3>优先复盘</h3><p>${esc(teacher.improvement_focus.join('；'))}</p></article>
  </div>
  <h3>确定的量化标准</h3>
  <div class="teacher-grid">${teacher.metrics.map(metric => `<article class="metric-card ${metric.level}"><header><b>${esc(metric.name)}</b><strong>${metric.score}</strong></header><p>权重 ${metric.weight}% · ${esc(metric.benchmark)}</p><p><b>证据：</b>${esc(metric.evidence)}</p></article>`).join('')}</div>
  <h3>教师复核问题</h3><ol>${teacher.review_questions.map(question => `<li>${esc(question)}</li>`).join('')}</ol>`;
}

function profileHtml(item) {
  const profile = item.education_profile;
  const tracking = item.student_tracking;
  return `<div class="person-hero"><img src="${item.portrait_url}" alt="${esc(item.display_name)}课堂人像" /><div><span class="eyebrow">一名学生 · 一条可复核证据链</span><h3>${esc(item.display_name)}的一人一案证据页</h3><p>${esc(item.seat_label)} · ${esc(profile.profile_label)} · 来源：${esc(profile.source)}</p></div><div class="person-score"><strong>${item.mastery.overall_score}</strong><span>本节学习初评 / 待教师复核</span></div></div>
  <div class="case-path"><div><b>学生资料</b><span>优势、支持需要和安全边界</span></div><div><b>课堂证据</b><span>${item.state_summary.window_count}个状态窗口、${item.key_interactions.length}个关键片段</span></div><div><b>教学决策</b><span>${esc(item.next_lesson_actions[0])}</span></div><div><b>成长轨迹</b><span>${esc(item.growth_projection.evidence_grade)}，累计更多同类课后升级</span></div></div>
  <div class="profile-grid"><article class="info-block"><h3>可利用的优势</h3><ul>${(profile.strengths || []).map(row => `<li>${esc(row)}</li>`).join('')}</ul></article><article class="info-block"><h3>当前支持需要</h3><ul>${(profile.support_needs || []).map(row => `<li>${esc(row)}</li>`).join('')}</ul></article><article class="info-block"><h3>本节证据结论</h3><p>${esc(tracking.lesson_conclusion.summary)}</p><p>${esc(tracking.lesson_conclusion.data_status)}</p></article><article class="info-block"><h3>已经验证的支持与安全边界</h3><ul>${[...(profile.effective_support || []),...(profile.safety_constraints || [])].map(row => `<li>${esc(row)}</li>`).join('')}</ul></article></div>
  <div class="callout"><b>定位：</b>这不是新的IEP填写页，而是把现有个体资料与每节课的可复核证据连接起来，为教师下一步教学提供数据支持。</div>`;
}

const formatBytes = value => {
  const bytes = Number(value || 0);
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
};
const formatDateTime = value => {
  if (!value) return '未记录';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? esc(value) : date.toLocaleString('zh-CN',{year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'});
};

async function apiJson(url, options={}) {
  const response = await fetch(url, options);
  const payload = await response.json();
  if (!response.ok || payload.error) throw new Error(payload.error || '操作失败');
  return payload;
}

async function loadStudentRecord(studentId, force=false) {
  if (!force && studentRecordCache[studentId]) return studentRecordCache[studentId];
  studentRecordLoading.add(studentId);
  try {
    const payload = await apiJson(`/api/seewo_demo2/student_record?student_id=${encodeURIComponent(studentId)}`);
    studentRecordCache[studentId] = payload;
    return payload;
  } finally {
    studentRecordLoading.delete(studentId);
  }
}

function profileImportHtml(item) {
  const record = studentRecordCache[item.student_id];
  if (!record) return `<div class="loading-line">正在读取${esc(item.display_name)}的本地资料档案…</div>`;
  const profile = record.support_profile || {};
  const typeOptions = Object.entries(record.document_types || {}).map(([value,label]) => `<option value="${esc(value)}">${esc(label)}</option>`).join('');
  const documents = record.documents || [];
  const documentRows = documents.length ? documents.map(document => `<article class="document-row">
    <div><h5>${esc(document.original_filename)}</h5><p>${esc(document.document_type_label)} · ${formatBytes(document.byte_size)} · ${esc(document.parse_status)}</p><p>来源：${esc(document.source_org || '未填写')} · 上传：${formatDateTime(document.created_at)} · 到期：${formatDateTime(document.expires_at)}</p>${document.extracted_preview ? `<div class="parse-preview">${esc(document.extracted_preview)}</div>` : ''}</div>
    <div class="document-actions"><a class="secondary" href="${esc(document.download_url)}">下载</a><button type="button" class="danger-command" data-delete-document="${esc(document.document_id)}">删除</button></div>
  </article>`).join('') : `<div class="record-empty">还没有上传资料。原文件上传后会保存在本地受控目录，并记录来源、哈希值和到期时间。</div>`;
  return `<div class="record-page-head"><div><span class="eyebrow">学生档案 · 教师确认后入库</span><h3>${esc(item.display_name)}的资料导入</h3><p>上传 IEP、五大领域和专业评估原文件，再把其中可用于课堂支持的内容整理为结构化摘要。原文件与摘要分开保存，系统不根据资料名称或障碍类别自动判断学生能力。</p></div><span class="record-status">SQLite 本地档案已启用</span></div>
  <div class="record-layout">
    <div class="record-column">
      <section class="record-section"><h4>上传校方已有资料</h4><p>支持 DOCX、PDF、Excel、CSV、JSON、TXT 和常见图片，单个文件不超过 10MB。</p>
        <div class="record-form-grid">
          <div><label for="documentType">资料类型</label><select id="documentType">${typeOptions}</select></div>
          <div><label for="documentDate">资料形成日期</label><input id="documentDate" type="date" /></div>
          <div class="wide"><label for="sourceOrg">资料来源</label><input id="sourceOrg" placeholder="例如：学校、医院或专业评估机构" /></div>
          <div class="wide file-field"><label for="studentDocumentFile">选择资料文件</label><input id="studentDocumentFile" type="file" accept=".docx,.pdf,.xlsx,.xls,.csv,.json,.txt,.png,.jpg,.jpeg" /><small>DOCX、TXT、CSV 和 JSON 可提取文本预览；PDF、Excel 和图片先保存原件，再由教师填写结构化摘要。</small></div>
          <div class="wide"><label for="documentNote">补充说明</label><textarea id="documentNote" placeholder="说明资料版本、适用范围或需要特别核对的内容"></textarea></div>
        </div>
        <label class="authorization-check"><input id="documentAuthorized" type="checkbox" />我确认该资料已获得校方授权，只用于学生教育支持与安全约束。</label>
        <div class="action-row"><button type="button" class="primary" id="uploadStudentDocument">上传并登记</button><span class="hint" id="documentUploadStatus">上传后可随时下载或由管理员删除。</span></div>
      </section>
      <section class="record-section"><h4>已登记原文件</h4><p>文件删除会同步删除受控目录中的副本，并保留删除审计记录。</p><div class="document-list">${documentRows}</div></section>
    </div>
    <div class="record-column">
      <section class="record-section"><h4>教师确认的结构化支持摘要</h4><p>这里记录校方或专业机构已经明确的内容，不要求教师重新作医学判断。</p>
        <div class="record-form-grid">
          <div class="wide"><label for="professionalConclusion">已有专业结论摘要</label><textarea id="professionalConclusion" placeholder="仅摘录已存在的专业结论；不由系统生成诊断">${esc(profile.professional_conclusion || '')}</textarea></div>
          <div class="wide"><label for="supportSummary">IEP 与当前教育目标摘要</label><textarea id="supportSummary" placeholder="优势、当前目标、需要的教学支持">${esc(profile.support_summary || '')}</textarea></div>
          <div class="wide"><label for="effectiveSupport">已验证有效的支持方式</label><textarea id="effectiveSupport" placeholder="例如：短句指令、视觉提示、等待6秒、实物操作">${esc(profile.effective_support || '')}</textarea></div>
          <div class="wide"><label for="safetyConstraints">刺激禁忌与安全边界</label><textarea id="safetyConstraints" placeholder="例如：避免突然大声、强光、主动触碰或快速靠近">${esc(profile.safety_constraints || '')}</textarea></div>
          <div class="wide"><label for="profileUpdatedBy">确认人</label><input id="profileUpdatedBy" value="${esc(profile.updated_by || '')}" placeholder="任课教师、班主任或校方教研人员" /></div>
        </div>
        <div class="action-row"><button type="button" class="primary" id="saveSupportProfile">教师确认并保存</button><span class="hint">最近更新：${formatDateTime(profile.updated_at)}</span></div>
      </section>
      <div class="callout"><b>使用边界：</b>${esc(record.boundary)} 专业资料可以限制提示强度、接近距离和交互方式，但不能直接替代课堂证据判断“学会或不会”。</div>
    </div>
  </div>`;
}

function readFileAsDataUrl(file) {
  return new Promise((resolve,reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error('文件读取失败'));
    reader.readAsDataURL(file);
  });
}

async function uploadStudentDocument() {
  const fileInput = $('studentDocumentFile');
  const file = fileInput?.files?.[0];
  if (!file) throw new Error('请先选择资料文件');
  if (!$('documentAuthorized').checked) throw new Error('请先确认资料授权范围');
  const button = $('uploadStudentDocument');
  button.disabled = true;
  button.textContent = '正在上传…';
  try {
    await apiJson('/api/seewo_demo2/student_document', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        student_id:activeStudentId,
        document_type:$('documentType').value,
        filename:file.name,
        mime_type:file.type,
        content_base64:await readFileAsDataUrl(file),
        source_org:$('sourceOrg').value.trim(),
        document_date:$('documentDate').value,
        note:$('documentNote').value.trim(),
      }),
    });
    await loadStudentRecord(activeStudentId,true);
    storageState = null;
    $('runStatus').textContent = `${student().display_name}的资料已上传并登记`;
    renderResults();
  } finally {
    if (button.isConnected) {
      button.disabled = false;
      button.textContent = '上传并登记';
    }
  }
}

async function saveSupportProfile() {
  const updatedBy = $('profileUpdatedBy').value.trim();
  if (!updatedBy) throw new Error('请填写确认人');
  await apiJson('/api/seewo_demo2/support_profile', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({
      student_id:activeStudentId,
      professional_conclusion:$('professionalConclusion').value.trim(),
      support_summary:$('supportSummary').value.trim(),
      effective_support:$('effectiveSupport').value.trim(),
      safety_constraints:$('safetyConstraints').value.trim(),
      updated_by:updatedBy,
    }),
  });
  await loadStudentRecord(activeStudentId,true);
  storageState = null;
  $('runStatus').textContent = `${student().display_name}的结构化支持摘要已保存`;
  renderResults();
}

async function deleteStudentDocument(documentId) {
  if (!window.confirm('确认删除这份本地资料吗？删除后文件不可在页面恢复。')) return;
  await apiJson('/api/seewo_demo2/document_delete', {
    method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({document_id:documentId}),
  });
  await loadStudentRecord(activeStudentId,true);
  storageState = null;
  $('runStatus').textContent = '资料已从本地受控目录删除';
  renderResults();
}

async function loadVideoChannels(force=false) {
  if (videoChannelState && !force) return videoChannelState;
  videoChannelLoading = true;
  try {
    videoChannelState = await apiJson('/api/seewo_demo2/video_channels');
    return videoChannelState;
  } finally {
    videoChannelLoading = false;
  }
}

function videoUploadHtml() {
  if (!videoChannelState) return `<div class="loading-line">正在读取四路上传任务…</div>`;
  const data = videoChannelState;
  const subjectOptions = [`<option value="">群像 / 暂不绑定学生</option>`,...DATA.students.map(person => `<option value="${esc(person.student_id)}">${esc(person.display_name)}</option>`)].join('');
  const sessionValue = `${course().course_id}-${new Date().toISOString().slice(0,10)}`;
  const cards = data.channels.map(channel => {
    const tasks = channel.tasks.length ? channel.tasks.map(task => {
      const archiveAction = task.archive_status
        ? `<span class="archive-state">已进入授权归档队列</span>`
        : task.result_download_url && task.archive_authorized
          ? `<button type="button" class="archive-command" data-archive-task="${esc(task.task_id)}">授权归档</button>`
          : task.result_download_url ? `<span class="archive-state muted">未授权长期归档</span>` : '';
      return `<div class="channel-task"><div><b>${esc(task.original_filename)}</b><span>${esc(task.uploader_name)} · ${esc(task.course_name)} · 上传${task.progress_percent}% · ${esc(task.analysis_status)}</span><span class="retention-state ${esc(task.retention_state)}">${esc(task.retention_label)} · 到期前 ${task.reminder_days} 天提醒</span></div><div class="channel-task-actions">${task.result_download_url ? `<a href="${esc(task.result_download_url)}">下载结果</a>` : ''}${archiveAction}</div></div>`;
    }).join('') : `<div class="channel-empty">该通道还没有上传任务。</div>`;
    return `<article class="channel-card" data-channel-card="${esc(channel.channel_id)}"><header><div><h4>${esc(channel.channel_name)}</h4><span>独立任务、独立权限、独立结果</span></div><i class="channel-number">${channel.channel_no}</i></header>
      <div class="channel-form">
        <div><label>上传主体</label><input aria-label="${esc(channel.channel_name)}上传主体" data-channel-uploader placeholder="教师、班级或设备名称" /></div>
        <div><label>观察对象</label><select aria-label="${esc(channel.channel_name)}观察对象" data-channel-subject>${subjectOptions}</select></div>
        <div><label>课程名称</label><input aria-label="${esc(channel.channel_name)}课程名称" data-channel-course value="${esc(course().course_name)}" /></div>
        <div><label>课堂批次号</label><input aria-label="${esc(channel.channel_name)}课堂批次号" data-channel-session value="${esc(sessionValue)}" /></div>
        <div class="wide"><label>选择视频</label><input aria-label="${esc(channel.channel_name)}视频文件" type="file" accept="video/mp4,video/quicktime,video/x-msvideo,video/x-matroska,video/webm,.mp4,.mov,.avi,.mkv,.webm" data-channel-file /></div>
        <div class="channel-upload-command"><button type="button" class="primary" data-upload-channel="${esc(channel.channel_id)}">开始上传</button><span data-channel-status>单文件最大 ${formatBytes(data.max_video_bytes)}，自动按 ${formatBytes(data.chunk_size_bytes)} 分片。</span></div>
        <div class="upload-progress" aria-label="${esc(channel.channel_name)}上传进度"><i data-channel-progress></i></div>
      </div><div class="channel-tasks"><h5>最近任务</h5>${tasks}</div></article>`;
  }).join('');
  return `<div class="channel-overview"><div><span class="eyebrow">四个主体 · 一个平台 · 相互隔离</span><h3>四路视频上传与独立分析</h3><p>四个上传通道不是四套系统。每个主体分别提交视频并获得自己的任务编号、上传进度、预检结果和下载文件；只有相同课堂批次且获得授权时，系统才允许进行多视角时间对齐。</p></div><div class="channel-rule"><b>默认规则：</b>${esc(data.fusion_rule)}<br><b>当前分析边界：</b>${esc(data.analysis_boundary)}</div></div>
  <div class="channel-grid">${cards}</div>
  <div class="channel-architecture"><div><b>浏览器分片</b><span>大文件拆分上传，单次请求不占满内存</span></div><div><b>四路任务隔离</b><span>上传主体、权限和结果分别记录</span></div><div><b>后台任务队列</b><span>正式版由 CPU/GPU 工作节点异步分析</span></div><div><b>结果复核</b><span>质量预检后再进入课堂状态与教师复核</span></div><div><b>60 天本地周期</b><span>到期前 15 天提醒；脱敏结果另行授权归档</span></div></div>`;
}

async function archiveVideoResult(taskId) {
  await apiJson('/api/seewo_demo2/archive_video_result', {
    method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
      task_id:taskId,
      course_id:course().course_id,
      created_by:currentCourseContext().confirmed_by || '校方确认人员',
    }),
  });
  storageState = null;
  await loadVideoChannels(true);
  $('runStatus').textContent = '脱敏结构化结果已进入长期资源授权队列；原始视频未归档';
  renderResults();
}

async function uploadVideoChannel(channelId) {
  const card = document.querySelector(`[data-channel-card="${channelId}"]`);
  const file = card.querySelector('[data-channel-file]').files[0];
  const uploader = card.querySelector('[data-channel-uploader]').value.trim();
  const courseName = card.querySelector('[data-channel-course]').value.trim();
  const sessionId = card.querySelector('[data-channel-session]').value.trim();
  const subjectId = card.querySelector('[data-channel-subject]').value;
  const status = card.querySelector('[data-channel-status]');
  const progress = card.querySelector('[data-channel-progress]');
  const button = card.querySelector('[data-upload-channel]');
  if (!file) throw new Error('请先选择视频文件');
  if (!uploader || !courseName || !sessionId) throw new Error('请填写上传主体、课程名称和课堂批次号');
  if (file.size > videoChannelState.max_video_bytes) throw new Error('视频超过当前 5GB 上限');
  const chunkSize = videoChannelState.chunk_size_bytes;
  const totalChunks = Math.ceil(file.size / chunkSize);
  button.disabled = true;
  button.textContent = '正在上传';
  try {
    const created = await apiJson('/api/seewo_demo2/video_task', {
      method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
        channel_id:channelId,
        session_id:sessionId,
        uploader_name:uploader,
        course_id:course().course_id,
        course_name:courseName,
        subject_id:subjectId,
        filename:file.name,
         mime_type:file.type,
         byte_size:file.size,
         total_chunks:totalChunks,
         security_confirmed:true,
         allow_company_archive:Boolean(currentCourseContext().allow_company_archive),
       }),
    });
    let task = created.task;
    for (let index=0; index<totalChunks; index += 1) {
      const chunk = file.slice(index * chunkSize, Math.min(file.size,(index + 1) * chunkSize));
      const uploaded = await apiJson('/api/seewo_demo2/video_chunk', {
        method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
           task_id:task.task_id,
           course_id:course().course_id,
           chunk_index:index,
          content_base64:await readFileAsDataUrl(chunk),
        }),
      });
      task = uploaded.task;
      progress.style.width = `${task.progress_percent}%`;
      status.textContent = task.progress_percent < 100 ? `已上传 ${task.progress_percent}%` : '上传完成，质量预检已生成';
    }
    storageState = null;
    await loadVideoChannels(true);
    $('runStatus').textContent = `${uploader}的视频已完成上传，可下载独立预检结果`;
    renderResults();
  } finally {
    if (button.isConnected) {
      button.disabled = false;
      button.textContent = '开始上传';
    }
  }
}

async function loadStorageState(force=false) {
  if (storageState && !force) return storageState;
  storageLoading = true;
  try {
    storageState = await apiJson('/api/seewo_demo2/storage');
    return storageState;
  } finally {
    storageLoading = false;
  }
}

function storageHtml() {
  if (!storageState) return `<div class="loading-line">正在读取本地数据库与保存策略…</div>`;
  const data = storageState;
  const policyRows = data.policies.map(policy => `<div class="policy-row" data-policy="${esc(policy.data_type)}"><div><b>${esc(policy.label)}</b><small>${esc(policy.storage_backend)} · 可下载${policy.downloadable ? '是' : '否'}</small></div><label class="policy-number"><span>保存</span><input type="number" min="2" max="3650" value="${policy.retention_days}" aria-label="${esc(policy.label)}保存天数" data-policy-days /><em>天</em></label><label class="policy-number"><span>提前提醒</span><input type="number" min="1" max="365" value="${policy.reminder_days}" aria-label="${esc(policy.label)}提前提醒天数" data-policy-reminder /><em>天</em></label><label class="policy-check"><input type="checkbox" data-policy-auto ${policy.auto_delete ? 'checked' : ''} />到期自动删除</label><button type="button" class="policy-save" data-save-policy="${esc(policy.data_type)}">保存</button></div>`).join('');
  const documents = data.recent_documents.length ? data.recent_documents.map(document => `<div class="inventory-row"><div><b>${esc(document.original_filename)}</b><span>${esc(document.document_type_label)} · ${formatBytes(document.byte_size)} · 到期 ${formatDateTime(document.expires_at)}</span></div><a href="${esc(document.download_url)}">下载</a></div>`).join('') : `<div class="record-empty">暂无通过资料导入页登记的文件。</div>`;
  const reports = data.reports.length ? data.reports.map(report => `<div class="inventory-row"><div><b>${esc(report.filename)}</b><span>${formatBytes(report.byte_size)} · ${formatDateTime(report.updated_at)}</span></div><a href="${esc(report.download_url)}">下载</a></div>`).join('') : `<div class="record-empty">尚未生成可下载的深度报告文件。</div>`;
  const reminders = data.expiry_reminders.length ? data.expiry_reminders.map(task => `<div class="reminder-row ${esc(task.retention_state)}"><div><b>${esc(task.original_filename)}</b><span>${esc(task.channel_id)} · ${esc(task.retention_label)} · ${formatDateTime(task.expires_at)}</span></div>${task.result_download_url ? `<a href="${esc(task.result_download_url)}">先下载结果</a>` : ''}</div>`).join('') : `<div class="record-empty compact">当前没有进入提前 15 天提醒期的视频。</div>`;
  const archives = data.archive_records.length ? data.archive_records.map(resource => `<div class="inventory-row"><div><b>${esc(resource.source_type)} · ${esc(resource.subject_ref)}</b><span>${esc(resource.status_label)} · ${formatDateTime(resource.created_at)}</span></div></div>`).join('') : `<div class="record-empty compact">尚无经授权的脱敏长期资源。</div>`;
  const acceptance = data.latest_security_acceptance;
  const acceptanceHtml = acceptance ? `<div class="security-ledger"><b>最近安全协议：${esc(acceptance.confirmed_by)}</b><span>${formatDateTime(acceptance.accepted_at)} · ${esc(acceptance.course_name)} · 长期资源${acceptance.allow_company_archive ? '已授权' : '未授权'}</span></div>` : `<div class="security-ledger muted"><b>尚无安全协议记录</b><span>教师完成课程开始前确认后，这里会显示审计信息。</span></div>`;
  return `<div class="storage-page-head"><div><span class="eyebrow">校内数据治理 · 当前真实状态</span><h3>数据存储与保存周期</h3><p>${esc(data.scope_note)} 页面展示的是本机实际路径和数据库统计，不把“未来云端能力”冒充为已经上线。</p></div><div class="storage-location"><b>${esc(data.database.status)} · ${esc(data.database.engine)}</b><code>${esc(data.database.location)}</code></div></div>
  <div class="storage-metrics"><div class="storage-metric"><span>学生档案</span><strong>${data.counts.students}</strong><small>${data.counts.profiles} 份结构化支持摘要</small></div><div class="storage-metric"><span>四路视频任务</span><strong>${data.counts.video_tasks}</strong><small>${formatBytes(data.video_task_storage.byte_size)}</small></div><div class="storage-metric alert"><span>15 天到期提醒</span><strong>${data.expiry_reminders.length}</strong><small>下载、延期或按策略删除</small></div><div class="storage-metric archive"><span>长期资源授权队列</span><strong>${data.counts.archive_records}</strong><small>${data.counts.security_acceptances} 次安全协议确认</small></div></div>
  <div class="lifecycle-band"><div><b>01 授权上传</b><span>教师选择学生、资料类型与来源</span></div><div><b>02 本地受控保存</b><span>文件目录与 SQLite 元数据分开管理</span></div><div><b>03 分析与报告</b><span>结构化摘要进入课堂支持证据链</span></div><div><b>04 到期处理</b><span>提醒、下载、延长或按策略删除</span></div></div>
  ${acceptanceHtml}<div class="reminder-panel"><div><h4>即将到期的视频</h4><p>新上传原始视频本地保存 60 天，进入最后 15 天时在这里集中提醒。</p></div><div class="reminder-list">${reminders}</div></div>
  <div class="storage-grid"><section class="storage-section"><h4>分类保存策略</h4><p>原始音视频默认保存 60 天，并提前 15 天提醒。其他资料可按学校制度分别配置。</p><div class="policy-list">${policyRows}</div><div class="callout"><b>重要：</b>策略修改影响之后的新任务；正式试点还需配置自动到期任务和受控删除复核。</div></section>
  <section class="storage-section"><h4>公司长期资源授权队列</h4><p>仅收集经校方单独授权的脱敏结构化结果；原始学生视频、音频和姓名默认不进入。</p><div class="inventory-list">${archives}</div><h4 style="margin-top:24px">已登记学生资料</h4><div class="inventory-list">${documents}</div><h4 style="margin-top:24px">已生成报告</h4><div class="inventory-list">${reports}</div></section></div>
  <div class="cloud-note"><b>公司数据库尚未连接</b><p>${esc(data.cloud.status)}。当前“授权归档”只进入本地待同步队列；正式接入后还需 PostgreSQL、对象存储、HTTPS、角色权限、访问日志和学校独立租户。</p></div>
  <div class="action-row"><button type="button" class="secondary" id="refreshStorage">刷新存储状态</button><span class="hint">资料目录：${esc(data.document_storage.location)} · 报告目录：${esc(data.report_storage.location)}</span></div>`;
}

async function saveStoragePolicy(button) {
  const row = button.closest('[data-policy]');
  const dataType = row.dataset.policy;
  button.disabled = true;
  button.textContent = '保存中';
  try {
    await apiJson('/api/seewo_demo2/storage_policy', {
      method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
        data_type:dataType,
        retention_days:Number(row.querySelector('[data-policy-days]').value),
        reminder_days:Number(row.querySelector('[data-policy-reminder]').value),
        auto_delete:row.querySelector('[data-policy-auto]').checked,
      }),
    });
    await loadStorageState(true);
    $('runStatus').textContent = '数据保存策略已更新';
    renderResults();
  } finally {
    if (button.isConnected) {
      button.disabled = false;
      button.textContent = '保存';
    }
  }
}

function growthHtml(item) {
  const projection = item.growth_projection;
  const colors = ['#315d58','#527970','#75938c','#6d8595','#9a7968'];
  const x = [70,250,430,610];
  const y = value => 250 - value * 2.05;
  const grid = [40,60,80,100].map(value => `<line x1="54" y1="${y(value)}" x2="640" y2="${y(value)}" stroke="#dce9f5" stroke-width="1"/><text x="16" y="${y(value)+4}" fill="#7890a4" font-size="11">${value}</text>`).join('');
  const series = projection.domains.map((domain,index) => {
    const points = domain.points.map((point,i) => `${x[i]},${y(point.score)}`).join(' ');
    const dots = domain.points.map((point,i) => `<circle cx="${x[i]}" cy="${y(point.score)}" r="4" fill="${colors[index]}"/>`).join('');
    return `<polyline points="${points}" fill="none" stroke="${colors[index]}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>${dots}`;
  }).join('');
  const labels = projection.domains[0].points.map((point,i) => `<text x="${x[i]}" y="274" text-anchor="middle" fill="#637d93" font-size="11">${esc(point.horizon)}</text>`).join('');
  return `<div class="growth-head"><div><span class="eyebrow">跨课证据 · 五域成长观察</span><h3>${esc(item.display_name)} · 五大能力情景趋势</h3><p>${esc(projection.history_status)}</p></div><div class="evidence-grade">${esc(projection.evidence_grade)}</div></div>
  <div class="growth-chart"><svg viewBox="0 0 670 290" role="img" aria-label="五大能力当前与未来六个月情景趋势">${grid}${series}${labels}</svg><div class="growth-legend">${projection.domains.map((domain,index) => `<span><i style="background:${colors[index]}"></i>${esc(domain.name)}</span>`).join('')}</div></div>
  <div class="scroll-table" style="margin-top:14px"><table><thead><tr><th>能力领域</th><th>当前</th><th>1个月</th><th>3个月</th><th>6个月</th><th>解释</th></tr></thead><tbody>${projection.domains.map(domain => `<tr><td><b>${esc(domain.name)}</b></td>${domain.points.map(point => `<td>${point.score}</td>`).join('')}<td>${esc(domain.direction)}</td></tr>`).join('')}</tbody></table></div>
  <div class="action-stack" style="margin-top:14px"><article class="info-block"><h3>成立条件</h3><ul>${projection.assumptions.map(row => `<li>${esc(row)}</li>`).join('')}</ul></article><article class="info-block"><h3>什么时候升级为真实趋势</h3><p>${esc(projection.upgrade_rule)}</p><p>${esc(projection.boundary)}</p></article></div>`;
}

function specialSupportHtml(item) {
  const support = item.special_education_support;
  return `<div class="support-banner"><div><span class="eyebrow">教师控制 · 低刺激 · 不主动接触</span><h3>${esc(item.display_name)}本节课支持工具</h3><p>${esc(support.mastery_note)}</p></div><button class="secondary" data-open-tab="action">查看具身动作</button></div>
  <div class="support-controls"><button type="button" id="startWaitTimer">开始6秒等待</button><output id="waitTimerValue">提示后先等待，不自动催促</output><button type="button" id="copySupportCard">复制单步支持卡</button></div>
  <div class="support-tool-grid">
    <article class="support-tool"><span>短指令</span><h3>${esc(support.instruction)}</h3><p>一次只呈现一个步骤，避免多重口令叠加。</p></article>
    <article class="support-tool"><span>等待时间</span><h3>${esc(support.wait_time)}</h3><p>页面只做倒计时建议，不自动连续催促。</p></article>
    <article class="support-tool"><span>替代表达</span><h3>${support.response_channels.map(channel => `<b>${esc(channel)}</b>`).join('')}</h3><p>不只依赖清晰口语，也允许指认、手势或实物操作。</p></article>
    <article class="support-tool"><span>成功机会</span><h3>${esc(support.success_opportunity)}</h3><p>先建立可完成体验，再进入困难目标。</p></article>
  </div>
  <div class="action-stack"><article class="info-block"><h3>提示顺序</h3><ol>${support.prompt_sequence.map(step => `<li>${esc(step)}</li>`).join('')}</ol></article><article class="info-block safety-block"><h3>刺激与安全约束</h3><ul>${support.calm_boundary.map(rule => `<li>${esc(rule)}</li>`).join('')}</ul><p>所有调整由教师确认，可随时暂停。</p></article></div>`;
}

function startSupportWaitTimer() {
  const output = $('waitTimerValue');
  const button = $('startWaitTimer');
  let remaining = 6;
  button.disabled = true;
  output.textContent = `安静等待 ${remaining} 秒`;
  const timer = window.setInterval(() => {
    remaining -= 1;
    output.textContent = remaining > 0 ? `安静等待 ${remaining} 秒` : '等待完成，请教师观察后决定下一步';
    if (remaining <= 0) {
      window.clearInterval(timer);
      button.disabled = false;
      button.textContent = '再次等待6秒';
    }
  }, 1000);
}

async function copySupportCard() {
  const support = result().special_education_support;
  const text = `单步指令：${support.instruction}\n等待：${support.wait_time}\n允许回应：${support.response_channels.join('、')}\n提示顺序：${support.prompt_sequence.join('；')}\n所有调整由教师确认。`;
  await navigator.clipboard.writeText(text);
  $('runStatus').textContent = '单步支持卡已复制';
}

function courseReportHtml() {
  const report = course().course_analysis;
  return `<div class="course-report-head"><div><span class="eyebrow">一节课 · 一个学校 · 一份课程级报告</span><h3>${esc(report.title)}</h3><p>${esc(report.review_status)} · ${report.char_count}字</p></div><div class="report-actions"><button class="secondary" id="printCourseReport">${PRINT_ICON}打印 / 导出 PDF</button><button class="secondary" id="copyCourseReport">复制课程分析</button></div></div><article class="course-report"><p>${esc(report.text)}</p></article><div class="callout"><b>使用边界：</b>${esc(report.boundary)} 深度报告页会将教师复核、支持动作和使用边界整理成约一千字的分章节版本。</div>`;
}

function summaryHtml() {
  const report = course().report_summary;
  const source = course().data_source;
  const entryLines = (object) => Object.entries(object || {}).map(([key,value]) => `<div class="source-line"><b>${esc(key)}</b><span>${esc(value)}</span></div>`).join('');
  return `<div class="report-grid">
    <article class="info-block"><h3>课程资料摘要</h3>${entryLines(report.metadata)}</article>
    <article class="info-block"><h3>三人课堂指标</h3>${entryLines(report.student_metrics)}</article>
    <article class="info-block"><h3>课堂阶段分布</h3>${entryLines(report.behavior_distribution)}</article>
    <article class="info-block"><h3>问答与测评口径</h3>${entryLines(report.question_metrics)}</article>
  </div>
  <h3>数据来源</h3><div class="info-block">${entryLines(source)}<p>${esc(report.source)}</p></div>`;
}

function reportHtml() {
  const report = longReports[course().course_id];
  const writer = DATA.report_writer || {};
  if (!report) return `<div class="report-toolbar">
    <button class="primary" id="generateReport">生成约一千字综合报告</button>
    <label style="display:flex;align-items:center;gap:7px;margin:0"><input id="useLlm" type="checkbox" style="width:auto" ${writer.llm_configured ? '' : 'disabled'} /> 使用LLM辅助整理</label>
    <span class="report-status">当前：本地证据模板${writer.llm_configured ? '；也可调用 '+esc(writer.llm_model) : '；未配置LLM也可完整生成'}</span>
  </div><div class="callout"><b>报告组成</b>：课程确认、数据质量、班级总览、三名学生个体分析、教师支持复盘、复核标注、机器人动作和下一课计划。报告生成前会自动保存当前教师标注。</div>`;
  const summary = report.review_summary;
  const assessment = result().mastery.assessment || {};
  const dimensions = assessment.dimensions || {};
  const labels = {accuracy:'正确性', independence:'独立程度', consistency:'一致性', transfer:'迁移'};
  const chartRows = Object.entries(dimensions).map(([key, row], index) => {
    const score = Number(row.score || 0);
    const y = 34 + index * 34;
    return `<text x="0" y="${y + 12}" fill="#486984" font-size="11">${labels[key] || key}</text><rect x="76" y="${y}" width="${score * 22}" height="18" rx="3" fill="#4f8eca"></rect><text x="${82 + score * 22}" y="${y + 13}" fill="#244c45" font-size="11">${score.toFixed(1)}</text>`;
  }).join('');
  const assessmentFigure = `<figure class="report-figure"><figcaption><b>量化证据：${esc(result().display_name)}本节掌握初评</b><span>0--10分，6分及格 · ${esc(assessment.review_status || '待教师复核')}</span></figcaption><svg viewBox="0 0 330 180" role="img" aria-label="四维评分柱状图"><line x1="208" y1="22" x2="208" y2="164" stroke="#d8903f" stroke-dasharray="4 4"></line>${chartRows}<text x="76" y="174" fill="#607985" font-size="10">0</text><text x="208" y="174" fill="#607985" font-size="10">6及格</text><text x="296" y="174" fill="#607985" font-size="10">10</text></svg></figure>`;
  return `<div class="report-toolbar">
    <button class="primary" id="generateReport">重新生成报告</button>
    <button class="secondary" id="printDeepReport">${PRINT_ICON}打印 / 导出 PDF</button>
    <button class="secondary" id="copyReport">复制全文</button>
    <span class="report-status">${report.char_count}字 · ${esc(report.engine_note)} · 复核${summary.reviewed}/${summary.total}</span>
  </div>
  <div class="callout"><b>${esc(summary.report_status)}</b> · ${esc(report.boundary)}</div>${assessmentFigure}
  <div class="report-layout"><nav class="report-nav">${report.sections.map((section,index) => `<button data-report-section="reportSection${index}">${esc(section.title)}</button>`).join('')}</nav>
  <div class="report-document">${report.sections.map((section,index) => `<section class="report-section" id="reportSection${index}"><h3>${esc(section.title)}</h3><p>${esc(section.content)}</p></section>`).join('')}</div></div>`;
}

async function generateLongReport() {
  $('runStatus').textContent = '正在保存复核并生成报告…';
  await persistReviews();
  const useLlm = Boolean($('useLlm') && $('useLlm').checked);
  const response = await fetch('/api/seewo_demo2_long_report', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({course_id:course().course_id,course_context:currentCourseContext(),reviews,use_llm:useLlm})});
  const payload = await response.json();
  if (!response.ok || payload.error) throw new Error(payload.error || '报告生成失败');
  longReports[course().course_id] = payload;
  $('runStatus').textContent = `报告已生成 · ${payload.char_count}字`;
  renderResults();
}

function renderResultSummary() {
  const item = result();
  const prefix = `${course().course_id}:`;
  const reviewed = Object.entries(reviews).filter(([key,value]) => key.startsWith(prefix) && ['符合','需修正','不确定'].includes(value.verdict || value)).length;
  const total = course().student_results.reduce((sum,row) => sum + row.key_interactions.length, 0);
  $('resultSummary').innerHTML = `
    <div class="result-stat"><span>${esc(item.display_name)} · 掌握初评</span><strong>${item.mastery.overall_score} · ${esc(item.mastery.band)}</strong></div>
    <div class="result-stat"><span>课堂状态</span><strong>${item.state_summary.participation_score} · ${esc(item.state_summary.top_state_zh)}</strong></div>
    <div class="result-stat"><span>当前学生待复核</span><strong>${item.state_summary.review_required_count} 个窗口</strong></div>
    <div class="result-stat"><span>三人支持效果</span><strong>${course().teacher_effectiveness.overall_score} · ${esc(course().teacher_effectiveness.band.label)}</strong></div>`;
  $('reviewProgress').textContent = `教师复核进度 ${reviewed}/${total}`;
}

function renderResults() {
  const item = result();
  renderResultSummary();
  document.querySelectorAll('#resultTabs button').forEach(button => {
    const isActive = button.dataset.tab === activeTab;
    button.classList.toggle('active',isActive);
    button.setAttribute('aria-selected',String(isActive));
    button.setAttribute('tabindex',isActive ? '0' : '-1');
  });
  if (window.innerWidth <= 860) {
    window.requestAnimationFrame(() => {
      const tabs = $('resultTabs');
      const activeButton = tabs.querySelector('button.active');
      if (!activeButton) return;
      tabs.scrollTo({left:activeButton.offsetLeft - (tabs.clientWidth - activeButton.offsetWidth) / 2,behavior:'smooth'});
    });
  }
  if (activeTab === 'mastery') $('tabBody').innerHTML = masteryHtml(item);
  if (activeTab === 'state') $('tabBody').innerHTML = stateHtml(item);
  if (activeTab === 'action') $('tabBody').innerHTML = actionHtml(item);
  if (activeTab === 'tracking') $('tabBody').innerHTML = trackingHtml(item);
  if (activeTab === 'interaction') $('tabBody').innerHTML = interactionHtml(item);
  if (activeTab === 'evidence') $('tabBody').innerHTML = evidenceHtml(item);
  if (activeTab === 'courseReport') $('tabBody').innerHTML = courseReportHtml();
  if (activeTab === 'specialSupport') $('tabBody').innerHTML = specialSupportHtml(item);
  if (activeTab === 'teacher') $('tabBody').innerHTML = teacherHtml();
  if (activeTab === 'profile') $('tabBody').innerHTML = profileHtml(item);
  if (activeTab === 'profileImport') $('tabBody').innerHTML = profileImportHtml(item);
  if (activeTab === 'growth') $('tabBody').innerHTML = growthHtml(item);
  if (activeTab === 'summary') $('tabBody').innerHTML = summaryHtml();
  if (activeTab === 'feedback') $('tabBody').innerHTML = reportHtml();
  if (activeTab === 'videoUpload') $('tabBody').innerHTML = videoUploadHtml();
  if (activeTab === 'storage') $('tabBody').innerHTML = storageHtml();
  if (activeTab === 'json') $('tabBody').innerHTML = `<pre>${esc(JSON.stringify({course_id:course().course_id,course_name:course().course_name,report_summary:course().report_summary,teacher_effectiveness:course().teacher_effectiveness,student_result:item},null,2))}</pre>`;
  if (activeTab === 'profileImport' && !studentRecordCache[item.student_id] && !studentRecordLoading.has(item.student_id)) {
    loadStudentRecord(item.student_id).then(() => { if (activeTab === 'profileImport' && activeStudentId === item.student_id) renderResults(); }).catch(error => { $('tabBody').innerHTML = `<div class="callout"><b>资料读取失败：</b>${esc(error.message)}</div>`; });
  }
  if (activeTab === 'storage' && !storageState && !storageLoading) {
    loadStorageState().then(() => { if (activeTab === 'storage') renderResults(); }).catch(error => { $('tabBody').innerHTML = `<div class="callout"><b>存储信息读取失败：</b>${esc(error.message)}</div>`; });
  }
  if (activeTab === 'videoUpload' && !videoChannelState && !videoChannelLoading) {
    loadVideoChannels().then(() => { if (activeTab === 'videoUpload') renderResults(); }).catch(error => { $('tabBody').innerHTML = `<div class="callout"><b>上传通道读取失败：</b>${esc(error.message)}</div>`; });
  }
  document.querySelectorAll('[data-review]').forEach(button => button.addEventListener('click', () => {
    const row = button.parentElement;
    const key = row.dataset.key;
    const current = reviews[key] || {};
    reviews[key] = {...current,verdict:button.dataset.review};
    row.querySelectorAll('[data-review]').forEach(choice => choice.classList.toggle('selected',choice === button));
    const state = document.querySelector(`[data-review-state="${key}"]`);
    if (state) state.textContent = button.dataset.review;
    renderResultSummary();
  }));
  document.querySelectorAll('[data-save-review]').forEach(button => button.addEventListener('click', async () => { const key=button.dataset.saveReview; const editor=document.querySelector(`[data-review-editor="${key}"]`); const current=reviews[key]||{verdict:'待复核'}; editor.querySelectorAll('[data-review-field]').forEach(field => current[field.dataset.reviewField]=field.value); current.updated_at=new Date().toISOString(); reviews[key]=current; button.textContent='保存中…'; try { await persistReviews(); button.textContent='已保存'; renderResultSummary(); } catch(error) { button.textContent='保存失败'; } }));
  document.querySelectorAll('[data-window-index]').forEach(element => element.addEventListener('click', () => { activeWindowIndex = Number(element.dataset.windowIndex); renderResults(); }));
  document.querySelectorAll('[data-jump-window]').forEach(button => button.addEventListener('click', () => { activeWindowIndex = Math.max(0,Number(button.dataset.jumpWindow)); activeTab = 'state'; renderResults(); $('tabBody').scrollIntoView({behavior:'smooth',block:'start'}); }));
  document.querySelectorAll('[data-state-filter]').forEach(button => button.addEventListener('click', () => { stateFilter = button.dataset.stateFilter; renderResults(); }));
  document.querySelectorAll('[data-trend-view]').forEach(button => button.addEventListener('click', () => { trendView = button.dataset.trendView; renderResults(); }));
  document.querySelectorAll('[data-open-tab]').forEach(button => button.addEventListener('click', () => { activeTab = button.dataset.openTab; renderResults(); }));
  if ($('generateReport')) $('generateReport').addEventListener('click', () => generateLongReport().catch(error => { $('runStatus').textContent = error.message; }));
  if ($('copyReport')) $('copyReport').addEventListener('click', async () => { await navigator.clipboard.writeText(longReports[course().course_id].full_text); $('runStatus').textContent='报告全文已复制'; });
  if ($('copyCourseReport')) $('copyCourseReport').addEventListener('click', async () => { await navigator.clipboard.writeText(course().course_analysis.text); $('runStatus').textContent='课程分析已复制'; });
  if ($('printCourseReport')) $('printCourseReport').addEventListener('click', () => window.print());
  if ($('printDeepReport')) $('printDeepReport').addEventListener('click', () => window.print());
  if ($('downloadReviewSheet')) $('downloadReviewSheet').addEventListener('click', downloadReviewSheet);
  if ($('startWaitTimer')) $('startWaitTimer').addEventListener('click', startSupportWaitTimer);
  if ($('copySupportCard')) $('copySupportCard').addEventListener('click', () => copySupportCard().catch(() => { $('runStatus').textContent='复制失败，请检查浏览器权限'; }));
  if ($('uploadStudentDocument')) $('uploadStudentDocument').addEventListener('click', () => uploadStudentDocument().catch(error => { $('documentUploadStatus').textContent=error.message; $('runStatus').textContent=error.message; }));
  if ($('saveSupportProfile')) $('saveSupportProfile').addEventListener('click', () => saveSupportProfile().catch(error => { $('runStatus').textContent=error.message; }));
  document.querySelectorAll('[data-delete-document]').forEach(button => button.addEventListener('click', () => deleteStudentDocument(button.dataset.deleteDocument).catch(error => { $('runStatus').textContent=error.message; })));
  document.querySelectorAll('[data-save-policy]').forEach(button => button.addEventListener('click', () => saveStoragePolicy(button).catch(error => { $('runStatus').textContent=error.message; })));
  if ($('refreshStorage')) $('refreshStorage').addEventListener('click', () => loadStorageState(true).then(renderResults).catch(error => { $('runStatus').textContent=error.message; }));
  document.querySelectorAll('[data-upload-channel]').forEach(button => button.addEventListener('click', () => uploadVideoChannel(button.dataset.uploadChannel).catch(error => { const card=button.closest('[data-channel-card]'); const status=card?.querySelector('[data-channel-status]'); if (status) status.textContent=error.message; $('runStatus').textContent=error.message; })));
  document.querySelectorAll('[data-archive-task]').forEach(button => button.addEventListener('click', () => archiveVideoResult(button.dataset.archiveTask).catch(error => { $('runStatus').textContent=error.message; })));
  document.querySelectorAll('[data-report-section]').forEach(button => button.addEventListener('click', () => $(button.dataset.reportSection).scrollIntoView({behavior:'smooth',block:'start'})));
}

function renderPrivacy() {
  const boundary = DATA.review_boundary;
  $('privacyNote').innerHTML = `<b>使用边界：</b>${esc(boundary.mastery)} ${esc(boundary.identity)} ${esc(boundary.medical)} ${esc(boundary.teacher_review)}`;
}

function renderAll() { renderCourseSetup(); renderWorkbench(); renderStudentStrip(); renderResults(); renderPrivacy(); }

$('groupMode').addEventListener('click', () => { viewMode = 'group'; renderWorkbench(); });
$('portraitMode').addEventListener('click', () => { viewMode = 'portrait'; renderWorkbench(); });
$('fitButton').addEventListener('click', () => { const context=currentCourseContext(); context.course_type=$('courseType').value.trim(); context.course_name=$('courseName').value.trim(); context.lesson_standard=$('lessonStandard').value.trim(); context.school_assessment_standard=$('assessmentStandard').value.trim(); courseContexts[course().course_id]=context; sessionStorage.setItem('seewoDemo2CourseContexts',JSON.stringify(courseContexts)); $('courseDecision').textContent = `已根据上次课程数据重新评估：${course().course_fit.overall_level}（${course().course_fit.overall_fit_score}分）`; $('runStatus').textContent = '课程适配建议已更新'; });
$('startButton').addEventListener('click', () => { $('runStatus').textContent = '课堂检测结果已载入'; $('workbench').scrollIntoView({behavior:'smooth'}); });
$('entryBackButton').addEventListener('click', () => changeEntryStep(-1));
$('entryNextButton').addEventListener('click', () => changeEntryStep(1));
$('enterDemoButton').addEventListener('click', confirmCourseEntry);
document.querySelectorAll('#resultTabs button').forEach(button => button.addEventListener('click', () => { activeTab = button.dataset.tab; renderResults(); }));
$('resultTabs').addEventListener('keydown', event => {
  if (!['ArrowRight','ArrowLeft','Home','End'].includes(event.key)) return;
  const tabs = [...document.querySelectorAll('#resultTabs [role="tab"]')];
  const currentIndex = Math.max(0,tabs.indexOf(document.activeElement));
  const nextIndex = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : event.key === 'ArrowRight' ? (currentIndex + 1) % tabs.length : (currentIndex - 1 + tabs.length) % tabs.length;
  event.preventDefault();
  tabs[nextIndex].focus();
  tabs[nextIndex].click();
});
try { courseContexts = JSON.parse(sessionStorage.getItem('seewoDemo2CourseContexts') || '{}'); } catch(error) { courseContexts = {}; }
decorateNavigation(); initCourseSelect(); renderAll();
</script>
</body>
</html>'''
