"""Student-only person screening for the per-person classroom result.

The tracker keeps every recurring face track.  This module decides, with
explainable rules, which tracks are shown as students, which look like an
adult/teacher (large face, standing height, walking range, long presence) and
which are blank picks (too few / low-confidence / tiny / blurry faces).

It is an assistive filter, not identity recognition: every decision is
reversible by the teacher (``restore`` / ``mark_teacher``), and the overrides
are re-applied whenever the analysis is presented.  Logs never contain face
images, names or coordinates of individual frames.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
import logging
import math
import os
from pathlib import Path
import re
import threading
from typing import Any, Iterable

# v2 (2026-11-01): real wide-angle classrooms track 10–12 px faces at the 768 px
# analysis size; v1's absolute 24 px / 0.70 floors excluded every student there.
FILTER_VERSION = "person_filter_v2"
DEBUG_LOG_DIR_ENV = "REHAB_DEMO2_PERSON_FILTER_DEBUG_LOG_DIR"
ENV_PREFIX = "REHAB_DEMO2_PERSON_FILTER_"
DEBUG_LOGGER = logging.getLogger("rehab_affect.person_filter")

STATUS_STUDENT = "student"
STATUS_TEACHER = "teacher"
STATUS_BLANK = "blank"
# Teacher unticked 「纳入本课检测」: the person stays a candidate but leaves every downstream view.
STATUS_EXCLUDED = "excluded_by_teacher"
STATUSES = (STATUS_STUDENT, STATUS_TEACHER, STATUS_BLANK, STATUS_EXCLUDED)
STATUS_LABELS = {STATUS_STUDENT: "学生", STATUS_TEACHER: "疑似老师", STATUS_BLANK: "无效人选",
                 STATUS_EXCLUDED: "未纳入本课检测"}
DECISIONS = {"restore": STATUS_STUDENT, "include": STATUS_STUDENT,
             "mark_teacher": STATUS_TEACHER, "exclude": STATUS_EXCLUDED}
DECISION_OPERATIONS = {"restore": "person_restore", "include": "person_include",
                       "mark_teacher": "person_mark_teacher", "exclude": "person_exclude"}
# 每节课至少需要检测的学生数；低于它时页面必须说明原因并引导手动画框。
MIN_EXPECTED_STUDENTS = 3

REASON_LABELS = {
    "few_face_frames": "有效人脸帧过少",
    "low_face_ratio": "有效人脸帧占比过低",
    "low_confidence": "人脸置信度偏低",
    "small_face": "人脸尺寸过小",
    "blurry_face": "头像始终不清晰",
    "large_face": "人脸明显大于学生",
    "standing_height": "位置明显高于坐姿学生",
    "wide_movement": "横向走动范围大",
    "long_presence": "全片持续出现且频繁走动",
    "manual_teacher": "教师手动标记为老师/非学生",
    "manual_restore": "教师手动恢复为学生",
    "manual_excluded": "教师取消纳入本课检测",
}
_MANUAL_REASONS = ("manual_teacher", "manual_restore", "manual_excluded")

# name: (default, minimum, maximum, cast)
_CONFIG_SPEC: dict[str, tuple[float, float, float, type]] = {
    "max_candidates": (8, 1, 16, int),
    "min_face_frames": (3, 1, 100, int),
    "min_face_ratio": (0.05, 0.0, 1.0, float),
    "min_mean_score": (0.64, 0.0, 1.0, float),
    "min_face_px": (8, 4, 400, int),
    # A face far smaller than the rest of the class (same camera) is a background pick.
    "relative_small_ratio": (0.45, 0.1, 0.9, float),
    "min_sharpness": (25.0, 0.0, 5000.0, float),
    "teacher_threshold": (0.55, 0.05, 1.0, float),
    "teacher_size_ratio": (1.6, 1.05, 6.0, float),
    "teacher_height_offset": (0.08, 0.005, 0.8, float),
    "teacher_motion_range": (0.15, 0.01, 1.0, float),
    "teacher_presence_ratio": (0.6, 0.05, 1.0, float),
    "avatar_expand": (0.40, 0.0, 2.0, float),
    "avatar_side": (192, 160, 512, int),
    "max_track_points": (240, 20, 2000, int),
}
# Weighted teacher evidence; the large-face or standing-height cue is
# required, so a student who simply moves a lot is never auto-excluded.
TEACHER_WEIGHTS = {"size": 0.35, "height": 0.25, "motion": 0.25, "presence": 0.15}

_LOCK = threading.Lock()


def person_filter_config() -> dict[str, Any]:
    """Defaults with bounded environment overrides (REHAB_DEMO2_PERSON_FILTER_<NAME>)."""
    config: dict[str, Any] = {}
    for name, (default, low, high, cast) in _CONFIG_SPEC.items():
        raw = os.getenv(ENV_PREFIX + name.upper(), "").strip()
        value: Any = default
        if raw:
            try:
                parsed = cast(float(raw)) if cast is int else float(raw)
                if math.isfinite(float(parsed)) and low <= parsed <= high:
                    value = parsed
            except (TypeError, ValueError, OverflowError):
                value = default
        config[name] = value
    return config


# ---------------------------------------------------------------- features --

def _median(values: list[float]) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * fraction
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def track_features(face_points: list[dict[str, Any]], *, detection_attempts: int,
                   frame_width: int, frame_height: int, duration: float,
                   total_samples: int) -> dict[str, Any]:
    """Summarise one face track (only samples with a confirmed face box)."""
    count = len(face_points)
    scores = [float(p.get("score", 0.0)) for p in face_points]
    widths = [float(p["bbox"]["width"]) for p in face_points]
    heights = [float(p["bbox"]["height"]) for p in face_points]
    cx = [float(p["bbox"]["x"]) + float(p["bbox"]["width"]) / 2 for p in face_points]
    cy = [float(p["bbox"]["y"]) + float(p["bbox"]["height"]) / 2 for p in face_points]
    sharpness = [float(p.get("sharpness", 0.0)) for p in face_points]
    times = [float(p["time"]) for p in face_points]
    span = (max(times) - min(times)) if times else 0.0
    return {
        "face_frames": count,
        "detection_attempts": int(max(detection_attempts, 0)),
        "total_samples": int(max(total_samples, 0)),
        "face_ratio": round(count / max(1, detection_attempts), 4),
        "mean_score": round(sum(scores) / count, 4) if count else 0.0,
        "median_face_width": round(_median(widths), 5),
        "median_face_height": round(_median(heights), 5),
        "median_face_px": round(_median(widths) * max(frame_width, 1), 1),
        "median_cx": round(_median(cx), 5),
        "median_cy": round(_median(cy), 5),
        "x_range": round(_percentile(cx, .9) - _percentile(cx, .1), 5) if count else 0.0,
        "presence_ratio": round(min(1.0, span / max(duration, 1e-6)), 4) if count else 0.0,
        "best_sharpness": round(max(sharpness), 2) if sharpness else 0.0,
        "frame_width": int(frame_width), "frame_height": int(frame_height),
    }


def _ramp(value: float, start: float, end: float) -> float:
    if end <= start:
        return 1.0 if value >= end else 0.0
    return max(0.0, min(1.0, (value - start) / (end - start)))


def blank_reasons(features: dict[str, Any], config: dict[str, Any]) -> list[str]:
    reasons = []
    face_frames = int(features.get("face_frames", 0))
    if face_frames < int(config["min_face_frames"]):
        reasons.append("few_face_frames")
    if float(features.get("face_ratio", 0.0)) < float(config["min_face_ratio"]):
        reasons.append("low_face_ratio")
    if face_frames and float(features.get("mean_score", 0.0)) < float(config["min_mean_score"]):
        reasons.append("low_confidence")
    if float(features.get("median_face_px", 0.0)) < float(config["min_face_px"]):
        reasons.append("small_face")
    if float(features.get("best_sharpness", 0.0)) < float(config["min_sharpness"]):
        reasons.append("blurry_face")
    return reasons


def classify_candidates(features_list: list[dict[str, Any]],
                        config: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Return one ``person_filter`` dict per track (same order as the input)."""
    config = config or person_filter_config()
    results: list[dict[str, Any]] = []
    for features in features_list:
        reasons = blank_reasons(features, config)
        results.append({"version": FILTER_VERSION, "auto_status": STATUS_BLANK if reasons else STATUS_STUDENT,
                        "reasons": reasons, "scores": {}, "teacher_score": 0.0})
    valid = [i for i, item in enumerate(results) if item["auto_status"] == STATUS_STUDENT]
    if len(valid) >= 3:
        for index in list(valid):
            others = [float(features_list[j].get("median_face_px", 0.0)) for j in valid if j != index]
            group_px = _median(others)
            if group_px and float(features_list[index].get("median_face_px", 0.0)) < group_px * float(
                    config["relative_small_ratio"]):
                results[index].update(auto_status=STATUS_BLANK, reasons=["small_face"])
        valid = [i for i, item in enumerate(results) if item["auto_status"] == STATUS_STUDENT]
    # A teacher is only "larger / higher" relative to a seated group.
    if len(valid) >= 2:
        for index in valid:
            others = [features_list[j] for j in valid if j != index]
            own = features_list[index]
            group_width = _median([float(o["median_face_width"]) for o in others]) or 1e-6
            group_cy = _median([float(o["median_cy"]) for o in others])
            group_presence = _median([float(o["presence_ratio"]) for o in others])
            size_ratio = float(own["median_face_width"]) / group_width
            height_offset = group_cy - float(own["median_cy"])
            scores = {
                "size": round(_ramp(size_ratio, 1.15, float(config["teacher_size_ratio"])), 3),
                "height": round(_ramp(height_offset, 0.0, float(config["teacher_height_offset"])), 3),
                "motion": round(_ramp(float(own["x_range"]), 0.0, float(config["teacher_motion_range"])), 3),
                "presence": round(
                    _ramp(float(own["presence_ratio"]), 0.0, float(config["teacher_presence_ratio"]))
                    * (1.0 if float(own["presence_ratio"]) >= group_presence * .8 else .5)
                    * (1.0 if float(own["x_range"]) >= float(config["teacher_motion_range"]) * .3 else .3), 3),
            }
            total = round(sum(TEACHER_WEIGHTS[key] * scores[key] for key in TEACHER_WEIGHTS), 3)
            reasons = []
            if scores["size"] >= .5:
                reasons.append("large_face")
            if scores["height"] >= .5:
                reasons.append("standing_height")
            if scores["motion"] >= .5:
                reasons.append("wide_movement")
            if scores["presence"] >= .5:
                reasons.append("long_presence")
            item = results[index]
            item.update(scores=dict(scores, size_ratio=round(size_ratio, 3),
                                    height_offset=round(height_offset, 4)),
                        teacher_score=total)
            if total >= float(config["teacher_threshold"]) and (scores["size"] >= .5 or scores["height"] >= .5):
                item.update(auto_status=STATUS_TEACHER, reasons=reasons)
    for item in results:
        item["status"] = item["auto_status"]
        item["manual"] = False
    return results


# ------------------------------------------------------------- presentation --

def _all_candidates(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    people = [p for p in analysis.get("persons") or [] if isinstance(p, dict)]
    people += [p for p in analysis.get("excluded_persons") or [] if isinstance(p, dict)]
    return sorted(people, key=lambda p: (int(p.get("candidate_index", 0)), str(p.get("person_id", ""))))


def has_filter(analysis: Any) -> bool:
    return isinstance(analysis, dict) and any(
        isinstance(p, dict) and isinstance(p.get("person_filter"), dict)
        for p in (analysis.get("persons") or []) + (analysis.get("excluded_persons") or []))


def apply_person_filter(analysis: Any, overrides: dict[str, str] | None = None) -> Any:
    """Split candidates into students and excluded people; renumber students.

    Idempotent: excluded people are merged back before re-applying overrides.
    Analyses without ``person_filter`` metadata (older versions) are untouched.
    """
    if not has_filter(analysis):
        return analysis
    result = deepcopy(analysis)
    overrides = overrides or {}
    students, excluded = [], []
    counts = {STATUS_TEACHER: 0, STATUS_BLANK: 0, STATUS_EXCLUDED: 0}
    for person in sorted(_all_candidates(result), key=lambda p: (
            float((p.get("anchor_bbox") or {}).get("x", 0)), int(p.get("candidate_index", 0)))):
        info = dict(person.get("person_filter") or {}, version=FILTER_VERSION)
        info.setdefault("auto_status", STATUS_STUDENT)
        info.setdefault("reasons", [])
        decision = overrides.get(str(person.get("person_id")))
        if decision in STATUSES:
            info["status"], info["manual"] = decision, decision != info["auto_status"]
        elif person.get("manual_seat") or info.get("manual_seat"):
            # Teacher-confirmed seat ROIs are authoritative; screening must not
            # quietly remove one of the three selected students.
            info["auto_status"] = STATUS_STUDENT
            info["status"], info["manual"] = STATUS_STUDENT, False
        else:
            info["status"], info["manual"] = info["auto_status"], False
        reasons = [r for r in info.get("reasons", []) if r not in _MANUAL_REASONS]
        if info["manual"]:
            reasons.append({STATUS_TEACHER: "manual_teacher", STATUS_EXCLUDED: "manual_excluded"}
                           .get(info["status"], "manual_restore"))
        info["included"] = info["status"] == STATUS_STUDENT
        info["reasons"] = reasons
        info["reason_labels"] = [REASON_LABELS.get(r, r) for r in reasons]
        info["status_zh"] = STATUS_LABELS.get(info["status"], info["status"])
        person["person_filter"] = info
        if info["status"] == STATUS_STUDENT:
            students.append(person)
        else:
            counts[info["status"] if info["status"] in counts else STATUS_BLANK] += 1
            excluded.append(person)
    for number, person in enumerate(students, 1):
        person["display_name"] = f"学生 {number}"
        person["student_number"] = number
    teacher_no = blank_no = unticked_no = 0
    for person in excluded:
        if person["person_filter"]["status"] == STATUS_TEACHER:
            teacher_no += 1
            person["display_name"] = f"疑似老师 {teacher_no}"
        elif person["person_filter"]["status"] == STATUS_EXCLUDED:
            unticked_no += 1
            person["display_name"] = f"未纳入人物 {unticked_no}"
        else:
            blank_no += 1
            person["display_name"] = f"无效人选 {blank_no}"
        person.pop("student_number", None)
    result["persons"] = students
    result["excluded_persons"] = excluded
    manual = sum(1 for p in students + excluded if p["person_filter"].get("manual"))
    unticked_note = f"、教师取消纳入 {counts[STATUS_EXCLUDED]} 人" if counts[STATUS_EXCLUDED] else ""
    if not excluded:
        notice = "未排除任何人物候选。"
    elif manual:
        notice = (f"当前已排除疑似老师 {counts[STATUS_TEACHER]} 人、无效人选 {counts[STATUS_BLANK]} 个{unticked_note}"
                  f"（含教师调整 {manual} 处），可在下方恢复。")
    else:
        notice = f"已自动排除疑似老师 {counts[STATUS_TEACHER]} 人、无效人选 {counts[STATUS_BLANK]} 个，可在下方恢复。"
    result["person_filter_summary"] = {
        "version": FILTER_VERSION, "candidate_count": len(students) + len(excluded),
        "student_count": len(students), "excluded_teacher": counts[STATUS_TEACHER],
        "excluded_blank": counts[STATUS_BLANK],
        "excluded_by_teacher": counts[STATUS_EXCLUDED],
        "manual_overrides": manual,
        "min_expected_students": MIN_EXPECTED_STUDENTS,
        "low_student_notice": low_student_notice(len(students), len(students) + len(excluded), counts,
                                                   manual_seats=sum(1 for p in students if p.get("manual_seat"))),
        "notice": notice,
        "boundary": ("学生筛查为辅助功能：按人脸尺寸、位置、走动范围、出现时长与清晰度等规则自动判断，"
                     "需教师复核；不代表识别准确性已验证，也不识别姓名。"),
    }
    if not students:
        result["available_students"] = False
    return result


def low_student_notice(student_count: int, candidate_count: int,
                       counts: dict[str, int], manual_seats: int = 0) -> dict[str, Any] | None:
    """Explain why fewer than MIN_EXPECTED_STUDENTS students are shown (None when enough).

    The page must never silently show a single student: it states how many faces
    were tracked, how many were excluded and why, and points to manual boxing.
    """
    # A teacher-confirmed one-to-one/small-group lesson is not a "missing students"
    # error: manual seats are the explicit scope of the lesson.
    if manual_seats and student_count <= 2:
        return None
    if student_count >= MIN_EXPECTED_STUDENTS:
        return None
    reasons: list[dict[str, Any]] = []
    if candidate_count < MIN_EXPECTED_STUDENTS:
        reasons.append({"code": "few_faces", "count": candidate_count,
                        "text": f"画面中只持续检出 {candidate_count} 张人脸（人物候选）"
                                if candidate_count else "画面中没有检出可持续观察的人脸"})
    if counts.get(STATUS_TEACHER):
        reasons.append({"code": "excluded_teacher", "count": counts[STATUS_TEACHER],
                        "text": f"已排除 {counts[STATUS_TEACHER]} 个疑似老师"})
    if counts.get(STATUS_BLANK):
        reasons.append({"code": "excluded_blank", "count": counts[STATUS_BLANK],
                        "text": f"已排除 {counts[STATUS_BLANK]} 个空白/无效候选（人脸太少、太小或不清晰）"})
    if counts.get(STATUS_EXCLUDED):
        reasons.append({"code": "excluded_by_teacher", "count": counts[STATUS_EXCLUDED],
                        "text": f"教师取消纳入 {counts[STATUS_EXCLUDED]} 人"})
    if not reasons:
        reasons.append({"code": "few_faces", "count": candidate_count,
                        "text": f"画面中只持续检出 {candidate_count} 张人脸（人物候选）"})
    return {
        "student_count": int(student_count), "candidate_count": int(candidate_count),
        "min_expected": MIN_EXPECTED_STUDENTS,
        "message": f"本视频仅识别到 {student_count} 名学生",
        "reasons": reasons,
        "hint": ("每节课至少需要检测 3 名学生。可在「本课检测学生」中恢复被排除的人物，"
                 "或到身份确认页手动画框添加学生；正脸清晰、遮挡少的视频识别更完整。"),
    }


SWITCH_PAGES = frozenset({"simple_result", "identity", "analysis", "measurement", "course_overview"})


def _valid_box(box: Any) -> bool:
    try:
        return (isinstance(box, dict) and all(math.isfinite(float(box[k])) for k in ("x", "y", "width", "height"))
                and box["x"] >= 0 and box["y"] >= 0 and box["width"] > 0 and box["height"] > 0
                and box["x"] + box["width"] <= 1.0001 and box["y"] + box["height"] <= 1.0001)
    except (KeyError, TypeError, ValueError):
        return False


def switcher_items(analysis: Any) -> list[dict[str, Any]]:
    """Compact per-candidate list shared by every 「切换学生」 strip and the 「本课检测学生」 panel.

    Students come first (学生 1、学生 2… left to right), then excluded candidates.
    ``binding`` is ``bound`` / ``unbound`` / ``excluded``; avatars are the
    tracker's sharpest face (rendered as a 192 px square by /simple-result/frame).
    """
    if not isinstance(analysis, dict):
        return []
    archives = {a.get("person_id"): a for a in analysis.get("lesson_archives") or []
                if isinstance(a, dict) and a.get("candidate_matches_current") is not False}
    items: list[dict[str, Any]] = []
    people = [(p, True) for p in analysis.get("persons") or [] if isinstance(p, dict)]
    people += [(p, False) for p in analysis.get("excluded_persons") or [] if isinstance(p, dict)]
    for person, is_student in people:
        info = person.get("person_filter") if isinstance(person.get("person_filter"), dict) else {}
        status = info.get("status") or (STATUS_STUDENT if is_student else STATUS_BLANK)
        windows = [w for w in person.get("windows") or [] if isinstance(w, dict)]
        avatar = person.get("avatar") if isinstance(person.get("avatar"), dict) else {}
        portrait = next((w for w in windows if w.get("frame") and _valid_box(w.get("bbox"))), {})
        image = ({"frame": avatar["frame"], "bbox": avatar["bbox"], "crop": "avatar",
                  "time_sec": avatar.get("time_sec")}
                 if avatar.get("frame") and _valid_box(avatar.get("bbox")) else
                 {"frame": portrait["frame"], "bbox": portrait["bbox"], "crop": "person",
                  "time_sec": portrait.get("frame_time_sec")} if portrait else None)
        archive = archives.get(person.get("person_id")) if is_student else None
        score = person.get("average_student_score", person.get("average_score"))
        items.append({
            "person_id": person.get("person_id"),
            "display_name": person.get("display_name") or person.get("person_id"),
            "student_number": person.get("student_number"),
            "status": status, "status_zh": info.get("status_zh") or STATUS_LABELS.get(status, status),
            "auto_status": info.get("auto_status") or status,
            "included": bool(is_student), "manual": bool(info.get("manual")),
            "reason_labels": list(info.get("reason_labels") or [])[:6],
            "binding": "excluded" if not is_student else ("bound" if archive else "unbound"),
            "student_id": archive.get("student_id") if archive else None,
            "student_name": archive.get("student_name") if archive else None,
            "avatar": image,
            "anchor_time_sec": (image or {}).get("time_sec"),
            "window_count": len(windows),
            "dominant_state_zh": person.get("dominant_student_state_zh") or person.get("dominant_state_zh") or "",
            "average_score": score if isinstance(score, (int, float)) and not isinstance(score, bool) else None,
        })
    return items


def excluded_person_ids(analysis: Any) -> set[str]:
    if not isinstance(analysis, dict):
        return set()
    return {str(p.get("person_id")) for p in analysis.get("excluded_persons") or [] if isinstance(p, dict)}


def annotate_faces(faces: Iterable[dict[str, Any]], analysis: Any, time_sec: float,
                   *, frame_width: int | None = None,
                   config: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Tag identity-page detections as student / teacher / blank candidates.

    Matching uses the tracker's sampled face boxes near ``time_sec``; a face
    that cannot be matched keeps ``student`` unless it is below the minimum
    face size, so manual review always remains possible.
    """
    config = config or person_filter_config()
    people = _all_candidates(analysis) if isinstance(analysis, dict) else []
    student_widths = [float((p.get("anchor_bbox") or {}).get("width", 0)) for p in people
                      if (p.get("person_filter") or {}).get("status", STATUS_STUDENT) == STATUS_STUDENT]
    student_widths = [w for w in student_widths if w > 0]
    # Same camera: an unmatched face far smaller than the seated class is a background pick.
    relative_floor = (_median(student_widths) * float(config["relative_small_ratio"])
                      if len(student_widths) >= 2 else 0.0)
    tagged = []
    for face in faces:
        if not isinstance(face, dict) or not isinstance(face.get("bbox"), dict):
            continue
        item = dict(face)
        box = item["bbox"]
        best, best_iou = _match_track(box, people, time_sec, window=3.01)
        if best is None or best_iou < .25:
            # Frames before the tracker's first sample (or in a sampling gap) have no
            # nearby track point: fall back to the whole track, nearest time first.
            best, best_iou = _match_track(box, people, time_sec, window=None)
        status, reasons, matched = STATUS_STUDENT, [], ""
        if best is not None and best_iou >= .25:
            info = best.get("person_filter") or {}
            status = info.get("status", STATUS_STUDENT)
            reasons = list(info.get("reasons") or [])
            matched = str(best.get("display_name") or "")
        width_px = float(box.get("width", 0)) * float(frame_width or 0)
        if frame_width and width_px < float(config["min_face_px"]) and status == STATUS_STUDENT:
            status, reasons = STATUS_BLANK, ["small_face"]
        elif not matched and status == STATUS_STUDENT and float(box.get("width", 0)) < relative_floor:
            status, reasons = STATUS_BLANK, ["small_face"]
        item["filter_status"] = status
        item["filter_status_zh"] = STATUS_LABELS.get(status, status)
        item["filter_reasons"] = [REASON_LABELS.get(r, r) for r in reasons]
        if matched:
            item["matched_person"] = matched
        tagged.append(item)
    return tagged


def _match_track(box: dict[str, Any], people: list[dict[str, Any]], time_sec: float,
                 *, window: float | None) -> tuple[dict[str, Any] | None, float]:
    """Best-overlapping tracked person; ``window=None`` searches the whole track (ties → closest time)."""
    best, best_key = None, (0.0, 0.0)
    for person in people:
        for point in person.get("track_points") or []:
            if not isinstance(point, list) or len(point) < 5:
                continue
            distance = abs(float(point[0]) - float(time_sec))
            if window is not None and distance > window:
                continue
            other = {"x": point[1], "y": point[2], "width": point[3], "height": point[4]}
            key = (round(_iou(box, other), 6), -distance)
            if key > best_key:
                best, best_key = person, key
    return best, best_key[0]


def _iou(first: dict[str, Any], second: dict[str, Any]) -> float:
    try:
        x = max(0.0, min(first["x"] + first["width"], second["x"] + second["width"]) - max(first["x"], second["x"]))
        y = max(0.0, min(first["y"] + first["height"], second["y"] + second["height"]) - max(first["y"], second["y"]))
        intersection = x * y
        union = first["width"] * first["height"] + second["width"] * second["height"] - intersection
        return intersection / union if union > 0 else 0.0
    except (KeyError, TypeError):
        return 0.0


# --------------------------------------------------------------- overrides --

OVERRIDE_TABLE = """CREATE TABLE IF NOT EXISTS demo2_person_filter_overrides (
    task_id TEXT NOT NULL,
    person_id TEXT NOT NULL,
    owner_account_id TEXT NOT NULL,
    decision TEXT NOT NULL CHECK(decision IN ('student', 'teacher', 'excluded_by_teacher')),
    updated_by TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(task_id, person_id)
)"""


SUSPENDED_TABLE = """CREATE TABLE IF NOT EXISTS demo2_person_filter_suspended (
    task_id TEXT NOT NULL,
    person_id TEXT NOT NULL,
    owner_account_id TEXT NOT NULL,
    archives_json TEXT NOT NULL,
    measurement_ids_json TEXT NOT NULL,
    reference_ids_json TEXT NOT NULL,
    binding_ids_json TEXT NOT NULL,
    suspended_by TEXT NOT NULL,
    suspended_at TEXT NOT NULL,
    PRIMARY KEY(task_id, person_id)
)"""


def ensure_table(connection: Any) -> None:
    """Create the override tables; rebuild a pre-``excluded_by_teacher`` table (CHECK cannot be altered)."""
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='demo2_person_filter_overrides'").fetchone()
    if row is not None and "excluded_by_teacher" not in str(row[0]):
        connection.execute("ALTER TABLE demo2_person_filter_overrides RENAME TO demo2_person_filter_overrides_v1")
        connection.execute(OVERRIDE_TABLE)
        connection.execute(
            "INSERT INTO demo2_person_filter_overrides(task_id,person_id,owner_account_id,decision,updated_by,updated_at) "
            "SELECT task_id,person_id,owner_account_id,decision,updated_by,updated_at FROM demo2_person_filter_overrides_v1")
        connection.execute("DROP TABLE demo2_person_filter_overrides_v1")
    else:
        connection.execute(OVERRIDE_TABLE)
    connection.execute(SUSPENDED_TABLE)


def load_overrides(connection: Any, task_id: str) -> dict[str, str]:
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='demo2_person_filter_overrides'").fetchone()
    if not exists:
        return {}
    return {row[0]: row[1] for row in connection.execute(
        "SELECT person_id, decision FROM demo2_person_filter_overrides WHERE task_id=?", (task_id,))}


def valid_person_id(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"person_[0-9]{2,3}", value) is not None


# --------------------------------------------------------------------- logs --

_INT_FIELDS = ("candidate_count", "student_count", "excluded_teacher", "excluded_blank", "face_frames",
               "detection_attempts", "avatar_side", "http_status", "archives_removed", "bindings_revoked",
               "measurements_withdrawn", "references_withdrawn", "candidate_index", "excluded_by_teacher",
               "measurements_restored", "references_restored", "bindings_restored", "archives_restored",
               "person_count", "student_number", "min_expected")
_FLOAT_FIELDS = ("teacher_score", "mean_score", "median_face_px", "best_sharpness", "avatar_sharpness",
                 "max_sharpness", "face_ratio", "x_range", "presence_ratio", "avatar_time_sec", "avatar_face_px")
_ID_FIELDS = ("task_id", "task_short", "person_id", "student_id", "code", "status", "auto_status", "decision",
              "source", "frame", "page", "trigger", "report")
OPERATIONS = frozenset({"person_filter_run", "person_excluded_teacher", "person_excluded_blank",
                        "person_restore", "person_mark_teacher", "person_include", "person_exclude",
                        "avatar_select", "person_switch", "person_list", "low_student_count",
                        "person_filter_error"})


def person_filter_log_dir(store: Any = None, *, run_path: Path | None = None) -> Path:
    configured = os.getenv(DEBUG_LOG_DIR_ENV, "").strip()
    if configured:
        return Path(configured)
    if store is not None:
        from .demo2_upload_debug import log_dir_for_store
        return log_dir_for_store(store)
    if run_path is not None:
        for parent in Path(run_path).resolve().parents:
            if parent.name == "video_tasks":
                return parent.parent / "logs"
    from .demo2_upload_debug import debug_log_dir
    return debug_log_dir()


def _clean(value: Any) -> str:
    text = str(value)
    return text if re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", text) else "<invalid>"


def person_filter_debug_event(operation: str, result: str, *, store: Any = None,
                              run_path: Path | None = None, **fields: Any) -> dict[str, Any]:
    """One JSON line; never blocks analysis.  No images, names or raw boxes."""
    entry: dict[str, Any] = {
        "ts": datetime.now().astimezone().isoformat(timespec="milliseconds"),
        "operation": operation if operation in OPERATIONS else "<invalid>",
        "result": _clean(result),
    }
    if fields.get("task_id") and not fields.get("task_short"):
        fields["task_short"] = str(fields["task_id"])[:8]
    for key, value in fields.items():
        if value is None or value == "":
            continue
        if key in _ID_FIELDS:
            entry[key] = _clean(value)
        elif key in _INT_FIELDS:
            entry[key] = value if isinstance(value, int) and not isinstance(value, bool) else "<invalid>"
        elif key in _FLOAT_FIELDS:
            entry[key] = round(float(value), 4) if isinstance(value, (int, float)) and not isinstance(value, bool) \
                and math.isfinite(float(value)) else "<invalid>"
        elif key == "reasons" and isinstance(value, (list, tuple)):
            entry[key] = [_clean(item) for item in value][:12]
        elif key == "scores" and isinstance(value, dict):
            entry[key] = {_clean(k): round(float(v), 4) for k, v in value.items()
                          if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v))}
    line = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
    DEBUG_LOGGER.debug(line)
    try:
        folder = person_filter_log_dir(store, run_path=run_path)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"person_filter_debug_{entry['ts'][:10].replace('-', '')}.jsonl"
        with _LOCK, path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except (OSError, TypeError, ValueError):
        DEBUG_LOGGER.warning("person filter debug log write failed")
    return entry


def log_analysis(analysis: Any, *, task_id: str = "", run_path: Path | None = None, store: Any = None) -> None:
    """Log one finished tracker result (run summary, exclusions, avatar picks)."""
    if not has_filter(analysis):
        return
    people = _all_candidates(analysis)
    statuses = [(p.get("person_filter") or {}).get("auto_status", STATUS_STUDENT) for p in people]
    common = {"store": store, "run_path": run_path, "task_id": task_id or None}
    person_filter_debug_event(
        "person_filter_run", "ok", candidate_count=len(people),
        student_count=statuses.count(STATUS_STUDENT), excluded_teacher=statuses.count(STATUS_TEACHER),
        excluded_blank=statuses.count(STATUS_BLANK), **common)
    if statuses.count(STATUS_STUDENT) < MIN_EXPECTED_STUDENTS:
        person_filter_debug_event(
            "low_student_count", "below_minimum", candidate_count=len(people),
            student_count=statuses.count(STATUS_STUDENT), excluded_teacher=statuses.count(STATUS_TEACHER),
            excluded_blank=statuses.count(STATUS_BLANK), min_expected=MIN_EXPECTED_STUDENTS, **common)
    for person in people:
        info = person.get("person_filter") or {}
        features = person.get("filter_features") or {}
        status = info.get("auto_status", STATUS_STUDENT)
        if status in (STATUS_TEACHER, STATUS_BLANK):
            person_filter_debug_event(
                "person_excluded_teacher" if status == STATUS_TEACHER else "person_excluded_blank", "excluded",
                person_id=person.get("person_id"), candidate_index=person.get("candidate_index"),
                reasons=info.get("reasons"), scores=info.get("scores"), teacher_score=info.get("teacher_score"),
                face_frames=features.get("face_frames"), detection_attempts=features.get("detection_attempts"),
                mean_score=features.get("mean_score"), median_face_px=features.get("median_face_px"),
                best_sharpness=features.get("best_sharpness"), face_ratio=features.get("face_ratio"),
                x_range=features.get("x_range"), presence_ratio=features.get("presence_ratio"), **common)
        avatar = person.get("avatar") or {}
        if avatar:
            person_filter_debug_event(
                "avatar_select", "selected", person_id=person.get("person_id"), status=status,
                frame=avatar.get("frame"), avatar_time_sec=avatar.get("time_sec"),
                avatar_sharpness=avatar.get("sharpness"), max_sharpness=avatar.get("max_sharpness"),
                avatar_face_px=avatar.get("face_px"), source=avatar.get("selection"), **common)
