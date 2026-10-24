"""Offline fixed-seat observations, reusing Demo1's per-ROI pixel measurements.

Seat anchors never migrate to a neighbour. This is not cross-camera identity or
emotion recognition. A bounded child owns OpenCV; no embeddings or network use.
"""
from __future__ import annotations

import json
from copy import deepcopy
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from typing import Any

VERSION = "simple_student_seats_v3_6"
WINDOW_SEC = 30
MAX_SAMPLES = 10800
TIMEOUT_SEC = 900
MAX_PERSONS = 3
DETECTION_INTERVAL_SEC = 2.0
INITIAL_SEARCH_SAMPLES = 60
REPORT_VERSION = "student_state_report_v5"
MOTION_LABELS = {"movement_high": "动作变化较多", "movement_moderate": "中等动作变化",
                 "movement_low": "动作变化较少"}
STUDENT_STATE_LABELS = {
    "engaged": "稳定参与",
    "active_response": "出现回应或操作",
    "low_response": "回应信号较低",
    "not_observed": "未观察到有效作答机会",
    "uncertain": "证据不足",
}
STUDENT_STATE_ACTIONS = {
    "engaged": {
        "action_id": "continue_current_task", "screen": "保持当前教学画面",
        "speech": "保持当前节奏，必要时给予具体正反馈。", "teacher_alert": False,
    },
    "active_response": {
        "action_id": "continue_and_record_response", "screen": "保留当前任务并记录回应时刻",
        "speech": "保持当前节奏，记录学生的回应或操作。", "teacher_alert": False,
    },
    "low_response": {
        "action_id": "check_response_opportunity", "screen": "保留当前教学画面并观察回应机会",
        "speech": "先确认学生是否正在等待、倾听或准备回应。", "teacher_alert": False,
    },
    "not_observed": {
        "action_id": "do_not_score_without_opportunity", "screen": "不触发学生侧结论",
        "speech": "当前片段没有明确作答机会，不据此判断学生状态。", "teacher_alert": False,
    },
    "uncertain": {
        "action_id": "mark_for_review", "screen": "不触发自动提示",
        "speech": "该片段证据不足，结合原片确认。", "teacher_alert": True,
    },
}
MOTION_SCORE_NOTE = (
    "0–10为各固定区域在本视频内独立归一化的像素变化参考值，数值越大只表示变化越多；"
    "不是动作完成质量、学习、情绪、注意力或教师成绩，不同人物的数值不能横向比较。"
    "区域图像可用率不代表身份连续追踪；跑步和正常体育动作不能单凭动作判为分心。"
)


def build_analysis(segments, run, meta, *, stop_event=None):
    samples = []
    for segment in segments:
        for sample in segment.get("visual", {}).get("samples", []):
            index = len(samples)
            name = Path(str(sample.get("image_path", ""))).name
            if not re.fullmatch(r"frame_[0-9]{6}\.jpg", name):
                name = f"frame_{index:06d}.jpg"
            samples.append({"frame": name, "time": sample.get("timestamp_sec", index)})
    if not samples:
        return unavailable("no_video_samples")
    audio_windows = []
    for segment in segments:
        audio = segment.get("audio") or {}
        if not isinstance(audio, dict):
            continue
        start = segment.get("start_sec")
        end = segment.get("end_sec")
        if type(start) not in (int, float) or type(end) not in (int, float) or end <= start:
            continue
        audio_windows.append({
            "start_sec": float(start), "end_sec": float(end),
            "available": bool(audio.get("available")),
            "energy_activity_ratio": audio.get("energy_activity_ratio"),
            "rms": audio.get("rms"),
        })
    request = {"root": str(Path(run).resolve() / "frames"), "samples": samples,
               "duration": meta.get("duration_sec", 0), "audio_windows": audio_windows}
    env = dict(os.environ, OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1",
               OPENCV_LOG_LEVEL="SILENT", OPENCV_IO_MAX_IMAGE_PIXELS="16000000")
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    child = subprocess.Popen([sys.executable, "-I", "-B", str(Path(__file__).resolve())],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, env=env, **options)
    deadline = time.monotonic() + TIMEOUT_SEC
    payload = json.dumps(request).encode()
    completed, errors = [], []
    def communicate():
        try:
            completed.append(child.communicate(input=payload))
        except Exception as error:
            errors.append(error)
    communication = threading.Thread(target=communicate, daemon=True)
    communication.start()
    try:
        while communication.is_alive():
            if stop_event is not None and stop_event.is_set():
                from .demo2_media_analysis import MediaAnalysisCancelled
                raise MediaAnalysisCancelled()
            if time.monotonic() > deadline:
                raise RuntimeError("student_tracking_timeout")
            communication.join(.1)
        if errors or not completed:
            raise RuntimeError("student_tracking_communication_failed")
        output, _ = completed[0]
        if child.returncode or len(output) > 4 * 1024 * 1024:
            raise RuntimeError("student_tracking_worker_failed")
        result = json.loads(output)
        if result.get("analysis_version") != VERSION:
            raise RuntimeError("student_tracking_invalid_result")
        return result
    finally:
        if child.poll() is None:
            child.kill()
        communication.join(5)


def unavailable(reason):
    return {"available": False, "analysis_version": VERSION, "reason": reason,
            "persons": [], "window_sec": WINDOW_SEC,
            "max_persons": MAX_PERSONS,
            "message": "未取得可持续观察的人物画面；请检查光线、拍摄距离和遮挡。"}


def center(box):
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


def expand(box, *, left=1.15, top=.8, right=1.15, bottom=2.8):
    x = max(0., box["x"] - box["width"] * left)
    y = max(0., box["y"] - box["height"] * top)
    x2 = min(1., box["x"] + box["width"] * (1 + right))
    y2 = min(1., box["y"] + box["height"] * (1 + bottom))
    return dict(x=x, y=y, width=x2-x, height=y2-y)


def crop(image, box):
    h, w = image.shape[:2]
    x1, y1 = max(0, int(box["x"]*w)), max(0, int(box["y"]*h))
    x2 = min(w, max(x1+1, math.ceil((box["x"]+box["width"])*w)))
    y2 = min(h, max(y1+1, math.ceil((box["y"]+box["height"])*h)))
    return image[y1:y2, x1:x2]


def seat_regions(boxes):
    """Immutable head/torso ROIs, clipped at neighbours' seat midpoints."""
    centers = [center(box)[0] for box in boxes]
    result = []
    for i, box in enumerate(boxes):
        roi = expand(box)
        x1 = max(roi["x"], (centers[i-1]+centers[i])/2 if i else 0)
        x2 = min(roi["x"]+roi["width"], (centers[i]+centers[i+1])/2 if i+1 < len(boxes) else 1)
        result.append(dict(roi, x=x1, width=x2-x1))
    return result


def face_in_seat(face, anchor, roi):
    """Allow bounded movement inside an immutable left-to-right seat lane.

    The lane is the identity guard.  The wider distance/size tolerances are
    only for low-frame-rate or moving-camera classroom footage; a candidate
    still cannot cross the midpoint into a neighbour's lane.
    """
    x, y = center(face["bbox"])
    ax, ay = center(anchor)
    return (roi["x"] <= x <= roi["x"]+roi["width"]
            and abs(x-ax) <= max(.12, anchor["width"]*4.0)
            and abs(y-ay) <= max(.12, anchor["height"]*3.5)
            and .30 <= face["bbox"]["width"]/max(anchor["width"], 1e-6) <= 3.5)


def _face_match_cost(face, current, anchor):
    """A bounded cost for matching a detection without transitive drift."""
    current_width = max(current["width"], 1e-6)
    ratio = face["bbox"]["width"] / current_width
    size_cost = abs(math.log(max(ratio, 1e-6)))
    distance = math.dist(center(face["bbox"]), center(current))
    anchor_distance = math.dist(center(face["bbox"]), center(anchor))
    return distance * 1.8 + min(size_cost, 2.0) * .035 + anchor_distance * .25


def _assign_faces(detected, anchors, regions, current_boxes):
    """Assign each detector box at most once, constrained by fixed seat lanes."""
    proposals = []
    for person_index, (anchor, roi, current) in enumerate(zip(anchors, regions, current_boxes)):
        for face_index, face in enumerate(detected):
            if face_in_seat(face, anchor, roi):
                proposals.append((_face_match_cost(face, current, anchor), person_index, face_index))
    assignments = [None] * len(anchors)
    used_people, used_faces = set(), set()
    for _, person_index, face_index in sorted(proposals):
        if person_index in used_people or face_index in used_faces:
            continue
        assignments[person_index] = detected[face_index]
        used_people.add(person_index)
        used_faces.add(face_index)
    return assignments


def _initial_face_set(observations):
    """Choose recurring opening candidates, then order them left to right.

    A single high-score box can be a teacher, a reflection or a false
    positive.  Recurrence across nearby samples is a safer starting signal
    than confidence alone, while the final ordering remains the product's
    explicit left-to-right convention.
    """
    clusters = []
    for sample_index, (_, _, detected) in enumerate(observations):
        for face in detected:
            cx, cy = center(face["bbox"])
            width = face["bbox"]["width"]
            choices = []
            for cluster_index, cluster in enumerate(clusters):
                if sample_index in cluster["sample_indices"]:
                    continue
                ratio = width / max(cluster["width"], 1e-6)
                if (abs(cx - cluster["x"]) <= .028 and abs(cy - cluster["y"]) <= .05
                        and .45 <= ratio <= 2.2):
                    choices.append((math.dist((cx, cy), (cluster["x"], cluster["y"])), cluster_index))
            if choices:
                _, cluster_index = min(choices)
                cluster = clusters[cluster_index]
                cluster["members"].append((sample_index, face))
                cluster["sample_indices"].add(sample_index)
                count = len(cluster["members"])
                cluster["x"] = sum(center(item[1]["bbox"])[0] for item in cluster["members"]) / count
                cluster["y"] = sum(center(item[1]["bbox"])[1] for item in cluster["members"]) / count
                cluster["width"] = sum(item[1]["bbox"]["width"] for item in cluster["members"]) / count
            else:
                clusters.append({"x": cx, "y": cy, "width": width,
                                 "members": [(sample_index, face)],
                                 "sample_indices": {sample_index}})
    recurring = sorted((cluster for cluster in clusters if len(cluster["members"]) >= 2),
                       key=lambda cluster: (cluster["x"], cluster["y"]))[:MAX_PERSONS]
    if len(recurring) < 2:
        return None

    ranked_observations = []
    for sample_index, (sample, image, detected) in enumerate(observations):
        proposals = []
        for cluster_index, cluster in enumerate(recurring):
            for face_index, face in enumerate(detected):
                cx, cy = center(face["bbox"])
                ratio = face["bbox"]["width"] / max(cluster["width"], 1e-6)
                if (abs(cx - cluster["x"]) <= .04 and abs(cy - cluster["y"]) <= .07
                        and .35 <= ratio <= 3.0):
                    cost = (math.dist((cx, cy), (cluster["x"], cluster["y"]))
                            + abs(math.log(max(ratio, 1e-6))) * .035)
                    proposals.append((cost, cluster_index, face_index))
        matches = [None] * len(recurring)
        used_clusters, used_faces = set(), set()
        for _, cluster_index, face_index in sorted(proposals):
            if cluster_index in used_clusters or face_index in used_faces:
                continue
            matches[cluster_index] = detected[face_index]
            used_clusters.add(cluster_index)
            used_faces.add(face_index)
        count = sum(face is not None for face in matches)
        score = sum(float(face.get("score", 0)) for face in matches if face is not None)
        ranked_observations.append((count, score, sample_index, sample, image, matches))
    _, _, sample_index, sample, image, matches = max(
        ranked_observations, key=lambda row: (row[0], row[1], -row[2]),
    )
    faces = [face for face in matches if face is not None]
    # If a recurring person is occluded in the selected reference frame, use
    # its recurring representative box.  The frame itself stays the same, so
    # all anchor coordinates still refer to one real image.
    for cluster, face in zip(recurring, matches):
        if face is None:
            representative = max(cluster["members"], key=lambda item: float(item[1].get("score", 0)))[1]
            faces.append(representative)
    faces.sort(key=lambda face: center(face["bbox"])[0])
    return faces, image, float(sample["time"]), sample_index


class Detector:
    def __init__(self):
        import cv2
        from rehab_affect import demo2_face_detection as face
        if face._validate_model(face.MODEL_PATH):
            raise RuntimeError("face_model_unavailable")
        self.face = face
        self.model = cv2.FaceDetectorYN.create(
            str(face.MODEL_PATH), "", (640, 640), face.TRACKING_SCORE_THRESHOLD, .3, 512,
        )

    def __call__(self, image):
        import cv2
        import numpy as np
        h, w = image.shape[:2]
        candidates = set()
        for i, region in enumerate(self.face._view_regions(
            w, h, fraction=self.face.TRACKING_TILE_FRACTION,
        )):
            x, y, rw, rh = region
            ratio = 640/max(rw, rh)
            if i == 0:
                ratio = min(1., ratio)
            sw, sh = max(1, round(rw*ratio)), max(1, round(rh*ratio))
            px, py = (640-sw)//2, (640-sh)//2
            canvas = np.zeros((640, 640, 3), np.uint8)
            canvas[py:py+sh, px:px+sw] = cv2.resize(image[y:y+rh, x:x+rw], (sw, sh))
            _, raw = self.model.detect(canvas)
            candidates.update(self.face._collect_candidates(
                raw, w, h, sw, sh, px, py, region=region,
                score_threshold=self.face.TRACKING_SCORE_THRESHOLD,
            ))
        return self.face._merge_candidates(
            candidates, score_threshold=self.face.TRACKING_SCORE_THRESHOLD,
        )


def _read(root, name):
    import cv2
    import numpy as np
    if not re.fullmatch(r"frame_[0-9]{6}\.jpg", name):
        raise ValueError("invalid_frame")
    path = root / name
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 8*1024*1024:
        return None
    image = cv2.imdecode(np.frombuffer(path.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
    if image is None or image.shape[0]*image.shape[1] > 16000000:
        return None
    return image


def _appearance(image):
    import cv2
    import numpy as np
    # Head shape and clothing together allow turning/looking down, without
    # treating the nearest neighbouring face as this child's replacement.
    small = cv2.resize(image, (24, 32)).astype(np.float32)/255
    hist = cv2.calcHist([cv2.cvtColor(image, cv2.COLOR_BGR2HSV)], [0, 1], None,
                       [12, 4], [0, 180, 0, 256]).flatten()
    hist /= max(float(hist.sum()), 1.)
    return small, hist


def _similarity(a, b):
    import numpy as np
    pixel = float(np.abs(a[0]-b[0]).mean())
    overlap = float(np.minimum(a[1], b[1]).sum())
    return max(0., min(1., .55*overlap + .45*(1-pixel)))


def _head_texture(image, box):
    import cv2
    import numpy as np
    patch = crop(image, expand(box, left=.6, right=.6, top=.6, bottom=.3))
    gray = cv2.cvtColor(cv2.resize(patch, (24, 24)), cv2.COLOR_BGR2GRAY).astype(np.float32)/255
    return float(gray.std())


def _clock(seconds):
    seconds = max(0, round(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def _audio_for_window(audio_windows, start, end):
    """Return the bounded classroom sound activity overlapping one person window."""
    weighted, total = [], 0.0
    for item in audio_windows or []:
        if not item.get("available"):
            continue
        try:
            left = max(float(start), float(item["start_sec"]))
            right = min(float(end), float(item["end_sec"]))
            activity = float(item.get("energy_activity_ratio"))
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if right <= left or not math.isfinite(activity):
            continue
        duration = right - left
        weighted.append((max(0., min(1., activity)), duration))
        total += duration
    if not weighted or total <= 0:
        return None, 0.0
    return sum(value * duration for value, duration in weighted) / total, min(1., total / max(1., end - start))


def _lesson_phase(sec: float, duration: float) -> str:
    """Return a coarse lesson phase used only to interpret response evidence."""
    duration = max(float(duration), 1.)
    ratio = max(0., min(1., float(sec) / duration))
    if ratio < .15:
        return "导入与示范"
    if ratio < .40:
        return "引导练习"
    if ratio < .78:
        return "个别练习与迁移"
    return "总结与回顾"


def _teacher_activity(sec: float, duration: float) -> str:
    return {
        "导入与示范": "教师讲解、示范或组织注意",
        "引导练习": "教师提问、提示并等待回应",
        "个别练习与迁移": "学生练习，教师巡视或个别支持",
        "总结与回顾": "教师回顾、确认回应或收束课堂",
    }[_lesson_phase(sec, duration)]


def _student_state(
    activity, audio_activity, visibility, quality, motions, expected,
    *, face_presence=0.0, face_motion=None, signal_variance=0.0,
    response_expected=True, lesson_phase="",
):
    """Map local evidence to Demo1-style descriptive classroom state cues.

    This is deliberately a support cue, not a diagnosis or a claim about a
    child's inner attention.  A quiet window with classroom sound is kept as
    "possible prompt needed" instead of being silently discarded.
    """
    enough_evidence = (visibility >= .35 and quality >= .30
                       and len(motions) >= min(3, max(1, expected - 1)))
    if not enough_evidence or activity is None:
        state = "uncertain"
        evidence = "本人物区域的可用画面或人脸核对不足，保留为证据不足，不用旁边人物代替。"
        interpretation = "当前片段需要结合原视频确认，不能据此判断学生是否参与或理解。"
    elif activity >= .62:
        state = "active_response"
        evidence = "本人物固定区域出现较明显的连续局部画面变化，保留为可能的回应或操作线索。"
        interpretation = "更像出现了回应、操作或身体活动；仍需结合课堂任务确认具体含义。"
    elif activity < .24 and not response_expected:
        state = "not_observed"
        evidence = f"本人物固定区域变化较少；当前处于“{lesson_phase or '当前教学'}”，未识别到明确作答机会。"
        interpretation = "学生没有作答不计入不会或退步，需要结合教师当时是否提出任务解释。"
    elif activity < .24:
        state = "low_response"
        evidence = "本人物固定区域变化较少，且当前阶段存在可能的回应机会，保留为回应信号较低线索。"
        interpretation = "需要区分倾听、等待、遮挡或未参与，不能仅凭安静判断分心。"
    else:
        state = "engaged"
        evidence = "本人物区域保持可见并有一定变化，保留为稳定参与线索。"
        interpretation = "当前存在课堂参与线索，继续观察具体任务回应和提示后的变化。"
    base = .42 + quality * .36 + visibility * .18
    if face_presence >= .5:
        base += .04
    if state == "uncertain":
        base = min(base, .48)
    confidence = round(max(.25, min(.92, base)), 3)
    if audio_activity is not None:
        evidence += "；另有整段课堂声音活动记录，但声音未定位到该学生，不作为个人状态依据。"
    return state, STUDENT_STATE_LABELS[state], evidence, interpretation, confidence


def _student_score(state, activity, quality):
    """A non-formal 0-10 participation evidence index for the result page."""
    if state == "uncertain" or activity is None:
        return None
    return round(10 * max(0., min(1., .65 * activity + .35 * quality)), 1)


def _person_report(display_name, anchor, windows, average_score, visibility):
    """Create a distinct, evidence-bound Demo1-style student report."""
    x = center(anchor)[0]
    area = "左侧" if x < 1/3 else "中部" if x < 2/3 else "右侧"
    scored = [w for w in windows if isinstance(w.get("student_score", w.get("score")), (int, float))]
    high = sorted(scored, key=lambda w: (-w.get("student_score", w.get("score", 0)), w["start_sec"]))[:3]
    quiet = sorted(scored, key=lambda w: (w.get("student_score", w.get("score", 0)), w["start_sec"]))[:3]

    def periods(items):
        return "、".join(
            f"{_clock(w['start_sec'])}–{_clock(w['end_sec'])}（{w.get('student_score', w.get('score')):.1f}）"
            for w in items
        ) or "暂无可评分片段"

    count_by_state = {state: sum(w.get("state") == state for w in windows)
                      for state in ("movement_high", "movement_moderate", "movement_low", "uncertain")}
    student_counts = {state: sum(w.get("student_state") == state for w in windows)
                      for state in STUDENT_STATE_LABELS
                      if sum(w.get("student_state") == state for w in windows)}
    student_top = max(student_counts, key=student_counts.get) if student_counts else "uncertain"
    observed = sum(int(w.get("observed_samples", 0)) for w in windows)
    expected = sum(int(w.get("expected_samples", 0)) for w in windows)
    average = f"{average_score:.1f}/10" if average_score is not None else "暂缺"
    report = (
        f"{display_name}是首次检测时位于原画面{area}的匿名人物候选；编号按该时点从左到右分配。"
        f"系统随后独立读取对应固定区域，未把其他人物的截图或数值复制到本区域。全片按30秒整理为{len(windows)}个时间片；"
        f"该区域在{observed}/{expected}个逐秒样本中满足图像可用条件，可用率约{visibility * 100:.0f}%。"
        f"这只表示区域图像可读，不代表本人全程在场或身份连续已获验证；人物离位、交叉或换位时需要回看原片。"
        f"有效时间片的平均学生参与线索参考值为{average}；参考值较高片段为{periods(high)}，"
        f"变化较少片段为{periods(quiet)}。所有时间片中，中等变化{count_by_state['movement_moderate']}段，"
        f"较多变化{count_by_state['movement_high']}段，较少变化{count_by_state['movement_low']}段；"
        f"另有{count_by_state['uncertain']}段证据不足而不评分。该人物以“{STUDENT_STATE_LABELS[student_top]}”线索最多；"
        "0–10是本人物固定区域的参与证据参考值，只用于定位本人物的不同时间段，"
        "不适合与其他人物横向排名，也不等同于学习成绩、情绪或医学判断。"
        "跑步、走位、伸展等正常体育活动不能单凭运动强度判定分心、不配合或扣分；"
        "画面变化还会受到镜头、光照、遮挡、衣物摆动及人物离开固定区域影响。"
        "建议按上述时间点回看原片，并结合当时教学目标、现场指令和人工观察解释；当前没有教案目标或教师标注，"
        "因此不推断专注、情绪、掌握程度、意愿、障碍类型或正式课堂成绩。"
    )
    action = (f"学生状态线索：{STUDENT_STATE_LABELS[student_top]}；参考值较高 {periods(high)}；"
              f"参考值较低 {periods(quiet)}。该结果用于回看和教学复盘，不替代教师判断。")
    return action, {"title": f"{display_name}个人观察报告", "text": report,
                    "character_count": len(report), "basis": "该人物候选对应固定区域的逐秒画面变化与30秒时间片",
                    "formal_score": False}


def present_motion_analysis(analysis):
    """Update known fixed-region motion prose without changing stored evidence.

    v3.2's old active/low response labels used these same motion thresholds.
    Other engines and attention labels must never be reinterpreted as motion.
    This performs no inference, file access, network request or identity change.
    """
    if (not isinstance(analysis, dict) or analysis.get("analysis_version") != VERSION
            or analysis.get("score_kind") != "individual_motion_index"
            or not analysis.get("available") or not analysis.get("persons")):
        return analysis
    aliases = {"active_response": "movement_high", "low_response": "movement_low",
               "engaged": "movement_moderate", "not_observed": "movement_low"}
    supported = set(MOTION_LABELS) | set(aliases) | {"uncertain"}
    people = analysis["persons"]
    if any(not isinstance(p, dict) or not p.get("anchor_bbox") or not p.get("observation_roi")
           or not isinstance(p.get("windows"), list) or not p["windows"]
           or any(w.get("state") not in supported for w in p["windows"]) for p in people):
        return analysis
    result = deepcopy(analysis)
    summaries = []
    for person in result["persons"]:
        windows = person["windows"]
        for window in windows:
            state = aliases.get(window["state"], window["state"])
            window["state"] = state
            if state in MOTION_LABELS:
                window["state_zh"] = MOTION_LABELS[state]
                motion = window.get("movement")
                change = f"；局部画面变化 {motion:.3f}" if isinstance(motion, (int, float)) else ""
                window["evidence"] = (
                    f"此固定区域有 {window.get('observed_samples', 0)}/{window.get('expected_samples', 0)} 个可用采样{change}。"
                    "这是画面变化线索，不表示注意力或掌握程度；区域可用不等于持续确认同一人物。"
                )
            if window.get("student_state") not in STUDENT_STATE_LABELS:
                activity = window.get("motion_signal")
                audio_activity = window.get("audio_activity")
                student_state, student_label, student_evidence, interpretation, confidence = _student_state(
                    activity, audio_activity, float(window.get("visibility", 0)),
                    float(window.get("confidence", 0)),
                    [window.get("movement")] if isinstance(window.get("movement"), (int, float)) else [],
                    int(window.get("expected_samples", 0)),
                    face_presence=float(window.get("face_presence", 0)),
                    response_expected=bool(window.get("response_expected", True)),
                    lesson_phase=window.get("lesson_phase", ""),
                )
                window.update(student_state=student_state, student_state_zh=student_label,
                              student_confidence=confidence, student_evidence=student_evidence,
                              student_interpretation=interpretation,
                              student_score=_student_score(student_state, activity, float(window.get("confidence", 0))))
        counts = {state: sum(w["state"] == state for w in windows)
                  for state in dict.fromkeys(w["state"] for w in windows)}
        dominant = max(counts, key=counts.get)
        person["dominant_state"] = dominant
        person["dominant_state_zh"] = next(w["state_zh"] for w in windows if w["state"] == dominant)
        student_counts = {state: sum(w.get("student_state") == state for w in windows)
                          for state in STUDENT_STATE_LABELS
                          if sum(w.get("student_state") == state for w in windows)}
        dominant_student = max(student_counts, key=student_counts.get)
        person["student_state_counts"] = student_counts
        person["dominant_student_state"] = dominant_student
        person["dominant_student_state_zh"] = STUDENT_STATE_LABELS[dominant_student]
        person["student_summary"] = (f"{STUDENT_STATE_LABELS[dominant_student]}线索最多，共{len(windows)}个时间片；"
                                      "请结合人物截图和原视频确认具体课堂表现。")
        person["action_summary"], person["lesson_report"] = _person_report(
            person["display_name"], person["anchor_bbox"], windows,
            person.get("average_score"), person.get("visibility", 0))
        person["tracking"] = "按首次检测位置固定区域逐秒独立取样；可用率指区域图像，不自动跨区域认人或确认身份连续。"
        summaries.append(f"{person['display_name']}：共{len(windows)}个时间片，{person['dominant_student_state_zh']}线索最多；"
                         f"固定区域图像可用率约{person.get('visibility', 0)*100:.0f}%。")
    report = (
        f"本段视频读取了{result.get('observed_frames', 0)}个采样画面，按30秒一个时间片整理{len(people)}个匿名人物候选的学生状态线索。"
        "候选按首次检测时从左到右编号，各自使用不同的固定区域、截图和时间序列；"
        "编号只用于核对画面，不能证明姓名或全程身份连续。" + "".join(summaries)
        + "状态线索结合每个人物的固定区域变化、画面可用率和有限的课堂声音活动；"
        "不可把不同人物的数值相加、排名或解释为学习成绩、情绪和动作完成质量。"
        "跑步、步移和伸展等正常体育活动不能单凭活动量判为分心，较少变化也可能是正常等待或保持姿势。"
        "固定区域图像可用率不是学生出勤率，也不是身份追踪成功率；镜头、光照、遮挡和人物交叉换位都可能影响结果。"
        "请分别查看各人物的截图、时间轴和个人报告，并结合原片、教学目标及教师现场观察解释，"
        "无法核对的时间段应保留为待确认，不用其他人物的表现填补。"
    )
    result.update(state_policy_version="demo1_student_state_cues_v1", report_version=REPORT_VERSION,
                  score_note=("页面同时展示 Demo1 风格的学生状态线索：稳定参与、出现回应或操作、参与线索较低、"
                              "可能需要一步提示和证据不足；这些是基于视频证据的教学复盘线索，不是医学或正式成绩。"
                              + MOTION_SCORE_NOTE),
                   lesson_report={"title": "全片学生状态线索概览", "text": report, "character_count": len(report),
                                  "basis": "逐秒画面样本、逐人物固定区域、有限课堂声音活动和30秒时间片",
                                 "scope": f"{len(people)}个匿名人物候选", "formal_score": False})
    return result


def analyze(request, detector=None):
    import cv2
    import numpy as np
    cv2.setNumThreads(1)
    root = Path(request["root"])
    samples = request["samples"]
    duration = float(request["duration"])
    audio_windows = request.get("audio_windows", [])
    if not isinstance(audio_windows, list):
        audio_windows = []
    if (not root.is_absolute() or root.is_symlink() or not root.is_dir()
            or not 0 < duration <= MAX_SAMPLES or not 0 < len(samples) <= MAX_SAMPLES):
        raise ValueError("invalid_tracking_request")
    if any(not math.isfinite(float(s["time"])) or not 0 <= float(s["time"]) < duration for s in samples):
        raise ValueError("invalid_sample_time")
    if any(float(a["time"]) >= float(b["time"]) for a, b in zip(samples, samples[1:])):
        raise ValueError("non_monotonic_samples")
    detector = detector or Detector()
    initial = None
    faces = []
    best_initial_rank = None
    detection_count = 0
    opening_observations = []
    # Do not freeze the first blurry frame.  Search a short opening interval
    # and prefer candidates that recur, rather than one accidental high score.
    for sample in samples[:INITIAL_SEARCH_SAMPLES:3]:
        candidate_image = _read(root, sample["frame"])
        if candidate_image is None:
            continue
        candidates = sorted(detector(candidate_image), key=lambda f: center(f["bbox"])[0])[:MAX_PERSONS]
        detection_count += 1
        opening_observations.append((sample, candidate_image, candidates))
        if candidates:
            import cv2
            gray = cv2.cvtColor(candidate_image, cv2.COLOR_BGR2GRAY)
            frame_quality = float(cv2.Laplacian(gray, cv2.CV_64F).var())
            rank = (len(candidates), round(sum(float(f.get("score", 0)) for f in candidates), 6),
                    round(sum(f["bbox"]["width"] * f["bbox"]["height"] for f in candidates), 6),
                    round(min(frame_quality, 10000.) / 10000., 6))
        else:
            rank = None
        if candidates and (best_initial_rank is None or rank > best_initial_rank):
            faces, initial = candidates, candidate_image
            anchor_time = float(sample["time"])
            best_initial_rank = rank
    recurring = _initial_face_set(opening_observations)
    if recurring is not None:
        faces, initial, anchor_time, _ = recurring
    if not faces:
        # A title slide or empty classroom at the start is not the whole lesson.
        for sample in samples[INITIAL_SEARCH_SAMPLES::15]:
            candidate_image = _read(root, sample["frame"])
            if candidate_image is None:
                continue
            candidates = sorted(detector(candidate_image), key=lambda f: center(f["bbox"])[0])[:MAX_PERSONS]
            detection_count += 1
            if candidates:
                faces, initial, anchor_time = candidates, candidate_image, float(sample["time"])
                break
    if not faces or initial is None:
        return unavailable("no_face_candidates")
    anchors = [f["bbox"] for f in faces]
    regions = seat_regions(anchors)
    reference = [_appearance(crop(initial, roi)) for roi in regions]
    head_texture = [_head_texture(initial, box) for box in anchors]
    previous = [None]*len(anchors)
    previous_appearance = [None]*len(anchors)
    previous_face = [None]*len(anchors)
    current_boxes = [dict(box) for box in anchors]
    tracks = [[] for _ in anchors]
    next_detection = anchor_time
    # Fixed background comparison rejects camera cuts; a stationary classroom
    # can be reacquired without letting one student's anchor walk to another.
    previous_scene = None
    for sample in samples:
        t = float(sample["time"])
        image = _read(root, sample["frame"])
        if image is None:
            previous = [None]*len(anchors)
            continue
        scene_view = cv2.resize(image, (80, 45)).astype(float) / 255
        scene_delta = (float(np.abs(scene_view - previous_scene).mean())
                       if previous_scene is not None else 0.)
        previous_scene = scene_view
        # Compare adjacent frames rather than every frame with the opening
        # frame.  Normal reframing, outdoor lighting and gradual camera pans
        # must not erase a student's whole timeline; only an abrupt cut is
        # withheld from scoring until a fresh face match appears.
        # The anchor is only the best reference frame; it does not mean the
        # lesson starts there.  Earlier samples remain valid fixed-seat
        # evidence and must stay in the timeline.
        scene_ok = scene_delta < .32 and image.shape == initial.shape
        detected = []
        if scene_ok and t >= next_detection:
            detected = detector(image)
            detection_count += 1
            next_detection = t + DETECTION_INTERVAL_SEC
        assignments = _assign_faces(detected, anchors, regions, current_boxes) if detected else [None]*len(anchors)
        for i, (anchor, roi) in enumerate(zip(anchors, regions)):
            patch = crop(image, roi)
            patch_appearance = _appearance(patch)
            similarity = _similarity(reference[i], patch_appearance)
            local_similarity = (_similarity(previous_appearance[i], patch_appearance)
                                if previous_appearance[i] is not None else similarity)
            previous_appearance[i] = patch_appearance
            face = assignments[i]
            if face is not None:
                current_boxes[i] = dict(face["bbox"])
            textured_head = (_head_texture(image, current_boxes[i])
                             >= max(.018, head_texture[i]*.28))
            # A current, lane-constrained face detection is stronger evidence
            # than the fixed patch similarity alone, especially after a pan.
            usable = (scene_ok and (face is not None or similarity >= .42 or local_similarity >= .45)
                      and (textured_head or face is not None))
            gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
            small = cv2.resize(gray, (96, 96), interpolation=cv2.INTER_AREA)
            prior = previous[i]
            # Same per-person 96x96 frame-difference measurement as Demo1.
            motion = float(cv2.absdiff(small, prior[1]).mean()/255) if usable and prior and t-prior[0] <= 1.5 else None
            previous[i] = (t, small) if usable else None
            local_motion = max(0.0, motion - min(scene_delta * .65, .22)) if motion is not None else None
            face_motion = None
            if face is not None:
                if previous_face[i] is not None and t - previous_face[i][0] <= DETECTION_INTERVAL_SEC * 2.5:
                    before = previous_face[i][1]
                    displacement = math.dist(center(face["bbox"]), center(before))
                    face_motion = max(0.0, min(1.0, displacement / max(.025, anchors[i]["width"] * 1.8)))
                previous_face[i] = (t, dict(face["bbox"]))
            else:
                if (previous_face[i] is not None
                        and t - previous_face[i][0] > DETECTION_INTERVAL_SEC * 3.0):
                    previous_face[i] = None
            brightness = float(small.mean())
            blur = float(cv2.Laplacian(small, cv2.CV_64F).var())
            quality = min(1., (blur/120)*.62 + (1. if 35 <= brightness <= 225 else .35)*.38)
            face_quality = 0.
            if face is not None:
                face_patch = crop(image, expand(face["bbox"], left=.45, top=.45, right=.45, bottom=.75))
                face_gray = cv2.cvtColor(face_patch, cv2.COLOR_BGR2GRAY)
                face_blur = float(cv2.Laplacian(face_gray, cv2.CV_64F).var())
                face_quality = min(1., .55 * min(1., face_blur / 140.)
                                   + .45 * float(face.get("score", 0.)))
            # On missed face detection, retain the actual same-time seat crop,
            # never a photograph borrowed from another time/person.
            # Demo1's student signal is the local fixed-seat image change.
            # Face displacement is retained for localization diagnostics only:
            # camera tracking jitter must never manufacture a response state.
            movement_signal_raw = local_motion
            tracks[i].append(dict(time=t, frame=sample["frame"], bbox=current_boxes[i],
                                  visible=usable, motion=motion, quality=quality,
                                  appearance=similarity, face_detected=bool(face),
                                  face_quality=face_quality, scene_ok=scene_ok,
                                  scene_motion=scene_delta, local_motion=local_motion,
                                  face_motion=face_motion, movement_signal_raw=movement_signal_raw,
                                  local_similarity=local_similarity))
    persons = []
    for i, items in enumerate(tracks):
        values = [x["movement_signal_raw"] for x in items
                  if isinstance(x.get("movement_signal_raw"), (int, float))]
        low, high = np.percentile(values, [10, 90]) if values else (0., 0.)
        scale = max(.015, float(high-low))
        windows = []
        for start in range(0, math.ceil(duration), WINDOW_SEC):
            end = min(duration, start+WINDOW_SEC)
            group = [x for x in items if start <= x["time"] < end]
            visible = [x for x in group if x["visible"]]
            expected = len([s for s in samples if start <= s["time"] < end])
            motions = [x["movement_signal_raw"] for x in visible
                       if isinstance(x.get("movement_signal_raw"), (int, float))]
            activity = float(np.mean([np.clip((m-low)/scale, 0, 1) for m in motions])) if motions else None
            raw = float(np.mean(motions)) if motions else None
            visibility = len(visible)/max(1, expected)
            face_presence = sum(x["face_detected"] for x in group)/max(1, expected)
            face_motion_values = [x["face_motion"] for x in visible
                                  if isinstance(x.get("face_motion"), (int, float))]
            face_motion = float(np.mean(face_motion_values)) if face_motion_values else None
            signal_variance = float(np.std([np.clip((m-low)/scale, 0, 1) for m in motions])) if len(motions) >= 2 else 0.0
            # Always retain the same-time fixed-seat crop. When a face is not
            # confirmed, the crop is evidence of the observed region only and
            # the window remains unscored; it is never replaced by a neighbour.
            representative = max(visible, key=lambda x: (x["face_detected"], x["face_quality"],
                                                         x["quality"], x["appearance"])) if visible else (
                max(group, key=lambda x: x["quality"]) if group else None)
            nearby_face = any(x["face_detected"] and start-15 <= x["time"] < end+15 for x in items)
            quality = float(np.mean([x["quality"] for x in visible])) if visible else 0.
            state, label, score = "uncertain", "画面证据不足", None
            evidence = "该位置出现遮挡、离位或镜头变化，未使用旁边人物代替。"
            if expected == 0:
                label, evidence = "该时段未采样", "此时间段没有可读取的采样，不等于学生未出现。"
            elif visible and not nearby_face:
                label, evidence = "局部画面 / 人脸未确认", "保留本时段原座位画面；缺少邻近人脸核对，不将区域变化当作已确认的学生状态。"
            elif visibility >= .35 and len(motions) >= min(3, max(1, expected-1)) and quality >= .38:
                if activity >= .6:
                    state, label = "movement_high", "动作变化较多"
                elif activity < .24:
                    state, label = "movement_low", "动作变化较少"
                else:
                    state, label = "movement_moderate", "中等动作变化"
                # Descriptive activity index, not a reward for moving more.
                score = round(10*activity, 1)
                evidence = f"独立观察此人物 {len(visible)}/{expected} 个采样；局部画面变化 {raw:.3f}。这是动作线索，不表示注意力或掌握程度。"
            audio_activity, audio_coverage = _audio_for_window(audio_windows, start, end)
            lesson_phase = _lesson_phase(start, duration)
            teacher_activity = _teacher_activity(start, duration)
            response_expected = lesson_phase in {"引导练习", "个别练习与迁移", "总结与回顾"}
            student_state, student_label, student_evidence, student_interpretation, student_confidence = _student_state(
                activity, audio_activity, visibility, quality, motions, expected,
                face_presence=face_presence, face_motion=face_motion,
                signal_variance=signal_variance,
                response_expected=response_expected, lesson_phase=lesson_phase,
            )
            student_score = _student_score(student_state, activity, quality)
            student_action = dict(STUDENT_STATE_ACTIONS[student_state])
            student_action["teacher_confirmation_required"] = bool(student_action["teacher_alert"])
            w = dict(start_sec=start, end_sec=round(end, 3), state=state, state_zh=label,
                      lesson_phase=lesson_phase, teacher_activity=teacher_activity,
                      response_expected=response_expected,
                     score=score, confidence=round(min(.85, visibility*.5+quality*.2), 3),
                     evidence=evidence, frame=representative["frame"] if representative else "",
                     frame_time_sec=representative["time"] if representative else None,
                     bbox=representative["bbox"] if representative else None,
                     visibility=round(visibility, 3), movement=round(raw, 6) if raw is not None else None,
                     motion_signal=round(activity, 4) if activity is not None else None,
                      face_presence=round(face_presence, 3), face_motion=round(face_motion, 4) if face_motion is not None else None,
                      local_signal_variance=round(signal_variance, 4),
                     observed_samples=len(visible), expected_samples=expected,
                     localization="face_in_fixed_seat" if representative and representative["face_detected"] else "fixed_seat_roi",
                     identity_continuity="seat_region_only_not_biometric_identity",
                     nearby_face_verified=nearby_face,
                      appearance_similarity=round(representative["appearance"], 3) if representative else None,
                      student_state=student_state, student_state_zh=student_label,
                      student_score=student_score, student_confidence=student_confidence,
                      student_evidence=student_evidence, student_interpretation=student_interpretation,
                      recommended_action=student_action,
                      audio_activity=round(audio_activity, 3) if audio_activity is not None else None,
                      audio_coverage=round(audio_coverage, 3),
                      state_basis="Demo1-style individual evidence cue: fixed-seat local image change; face displacement is localization-only")
            windows.append(w)
        scores = [w["score"] for w in windows if w["score"] is not None]
        student_scores = [w["student_score"] for w in windows if w.get("student_score") is not None]
        student_counts = {state: sum(w.get("student_state") == state for w in windows)
                          for state in STUDENT_STATE_LABELS}
        dominant_student = max(student_counts, key=student_counts.get)
        counts = {state:sum(w["state"] == state for w in windows)
                  for state in dict.fromkeys(w["state"] for w in windows)}
        dominant = max(counts, key=counts.get)
        average_score = round(sum(scores)/len(scores), 2) if scores else None
        average_student_score = round(sum(student_scores)/len(student_scores), 2) if student_scores else None
        visibility = round(sum(x["visible"] for x in items)/max(1,len(samples)), 3)
        display_name = f"人物 {i+1}"
        action_summary, person_report = _person_report(display_name, anchors[i], windows, average_student_score, visibility)
        confirmed = [x for x in items if x["face_detected"]]
        reacquisitions = sum(1 for before, after in zip(items, items[1:])
                             if after["face_detected"] and not before["face_detected"])
        persons.append(dict(person_id=f"person_{i+1:02d}", display_name=display_name, anonymous=True,
                            anchor_bbox=anchors[i], observation_roi=regions[i], windows=windows,
                            average_score=average_score, average_student_score=average_student_score,
                            dominant_state=dominant,
                            dominant_state_zh=next(w["state_zh"] for w in windows if w["state"] == dominant),
                            dominant_student_state=dominant_student,
                            dominant_student_state_zh=STUDENT_STATE_LABELS[dominant_student],
                            student_state_counts=student_counts,
                            detected_samples=sum(x["face_detected"] for x in items),
                            face_confirmed_samples=len(confirmed), reacquisition_count=reacquisitions,
                            same_person_continuity=round(len(confirmed) / max(1, len(items)), 3),
                            portrait_bbox=(max(confirmed, key=lambda x: (x["face_quality"], x["quality"]))["bbox"]
                                          if confirmed else anchors[i]),
                            portrait_quality=round(max((x["face_quality"] for x in confirmed), default=0.), 3),
                            observed_samples=sum(x["visible"] for x in items), visibility=visibility,
                            student_summary=(f"{STUDENT_STATE_LABELS[dominant_student]}线索最多，共{len(windows)}个时间片；"
                                             "请结合人物截图和原视频确认具体课堂表现。"),
                            action_summary=action_summary, lesson_report=person_report,
                            tracking="首次从左到右编号；固定人物区域结合每3秒人脸位置复核，禁止跨区域串人"))
    return present_motion_analysis(dict(
        available=True, analysis_version=VERSION, persons=persons, window_sec=WINDOW_SEC,
        detected_samples=detection_count, observed_frames=len(samples), max_persons=MAX_PERSONS,
         score_kind="individual_motion_index", student_score_kind="individual_participation_evidence_index",
         network_used=False,
        tracking_config={"detection_interval_sec": DETECTION_INTERVAL_SEC,
                         "initial_search_samples": INITIAL_SEARCH_SAMPLES,
                         "small_face_threshold": "tracking_only",
                         "scene_motion_suppression": True,
                         "primary_signal": "fixed_seat_local_motion",
                         "face_motion_role": "localization_only",
                         "identity_guard": "left_to_right_lane_plus_current_face_box"}))



if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    raw = sys.stdin.buffer.read(2*1024*1024+1)
    if len(raw) > 2*1024*1024:
        raise SystemExit(2)
    print(json.dumps(analyze(json.loads(raw)), ensure_ascii=True, allow_nan=False))
