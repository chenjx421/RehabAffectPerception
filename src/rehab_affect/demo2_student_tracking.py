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

VERSION = "simple_student_seats_v3_7"
# Stored analyses written before v3.7 keep the older presentation contract.
# Motion-only analyses may still be stored under these versions; semantic
# v3.7 analyses carry their own state cue and are never rewritten.
LEGACY_PRESENTATION_VERSIONS = frozenset({VERSION, "simple_student_seats_v3_6", "simple_student_seats_v3_2"})
WINDOW_SEC = 30
MAX_SAMPLES = 10800
TIMEOUT_SEC = 900
MAX_PERSONS = 3
DETECTION_INTERVAL_SEC = 2.0
INITIAL_SEARCH_SAMPLES = 60
REPORT_VERSION = "demo1_student_state_report_v6"
MOTION_LABELS = {"movement_high": "动作变化较多", "movement_moderate": "中等动作变化",
                 "movement_low": "动作变化较少"}
# Demo1 state vocabulary. The wording is a classroom support cue bound to the
# visible window evidence, never a diagnosis or a claim about the child.
STUDENT_STATE_LABELS = {
    "engaged": "参与",
    "low_attention": "注意力下降",
    "confused_or_stuck": "困惑·停滞",
    "uncertain_adult_interference": "成人干扰下不确定",
    "uncertain": "无法判断",
}
STUDENT_STATE_ACTIONS = {
    "engaged": {
        "action_id": "continue_current_task", "screen": "保持当前教学画面，不额外弹窗",
        "speech": "保持当前节奏，必要时给予具体正反馈。", "teacher_alert": False,
    },
    "low_attention": {
        "action_id": "regain_attention_low_stimulation", "screen": "轻微高亮当前步骤或目标物",
        "speech": "我们先看这里，只做这一步。", "teacher_alert": False,
    },
    "confused_or_stuck": {
        "action_id": "repeat_one_step_with_visual_highlight",
        "screen": "只保留当前一步，弱化无关信息", "speech": "没关系，我们先看第一步。",
        "teacher_alert": True,
    },
    "uncertain_adult_interference": {
        "action_id": "defer_to_teacher_observation", "screen": "不触发学生端强提示",
        "speech": "系统记录为需要人工确认的片段。", "teacher_alert": True,
    },
    "uncertain": {
        "action_id": "mark_for_review", "screen": "不触发自动干预",
        "speech": "该片段画质或遮挡不足，建议人工确认。", "teacher_alert": True,
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


def _crop_bounds(inner, outer, width, height):
    """Pixel bounds of an inner normalised box inside an outer crop."""
    left = max(0, int(round((inner["x"] - outer["x"]) / max(outer["width"], 1e-9) * width)))
    top = max(0, int(round((inner["y"] - outer["y"]) / max(outer["height"], 1e-9) * height)))
    right = min(width, int(round((inner["x"] + inner["width"] - outer["x"]) / max(outer["width"], 1e-9) * width)))
    bottom = min(height, int(round((inner["y"] + inner["height"] - outer["y"]) / max(outer["height"], 1e-9) * height)))
    return left, top, max(left, right), max(top, bottom)


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
    activity, audio_activity, adult_interference, visibility, quality, motions, expected,
    *, face_presence=0.0, response_expected=True, lesson_phase="", previous_activity=None,
):
    """Demo1's five classroom state cues, bound to one window's visible evidence.

    The decision order follows Demo1: sustained local movement means participation,
    a quiet seat next to adult/neighbour movement is deferred to the teacher,
    quiet seat plus classroom sound is treated as possibly stuck, and a plain
    quiet seat is a low-attention cue. Every branch keeps a classroom-level
    caveat: this is a review cue, not a diagnosis or a score.
    """
    enough_evidence = (visibility >= .35 and quality >= .30
                       and len(motions) >= min(3, max(1, expected - 1)))
    adult = float(adult_interference or 0.0)
    audio = float(audio_activity or 0.0)
    if not enough_evidence or activity is None:
        state = "uncertain"
        evidence = (f"本时段可用画面约{visibility:.0%}、清晰度约{quality:.0%}，不足以判断，"
                    "保留为无法判断，不用旁边人物代替。")
        interpretation = "当前片段需要结合原视频确认，不能据此判断学生是否参与或理解。"
        confidence = .35
    elif activity >= .35:
        state = "engaged"
        evidence = "本人物区域有持续可见的局部画面变化，保留为参与线索。"
        interpretation = "更像仍在参与课堂活动；具体任务完成与理解仍需教师确认。"
        confidence = .68 + min(.17, activity * .2)
    elif adult >= .55 and activity < .22:
        state = "uncertain_adult_interference"
        evidence = "本人物相邻区域动作明显，可能有教师或同学靠近、遮挡；本人物自身变化较少。"
        interpretation = "成人靠近或遮挡时优先记录并交给教师确认，不触发学生侧结论。"
        confidence = .52
    elif activity < .14 and audio >= .35 and previous_activity is not None and previous_activity >= .30:
        state = "confused_or_stuck"
        evidence = ("前一时间片仍能看到活动，本时段明显安静下来，而课堂声音仍在，"
                    "更像听指令或等待回应时的停滞。")
        interpretation = "可能不是单纯分心，更像需要一步提示或教师确认；请回看当时指令。"
        confidence = .58
    elif activity < .18:
        state = "low_attention"
        evidence = "本人物区域长时间动作较少，参与线索减弱。"
        interpretation = "可能是倾听、等待、遮挡或未参与；建议低刺激提示，不公开点名提醒。"
        confidence = .55
    else:
        state = "engaged"
        evidence = "本人物区域有一定动作变化，未达到异常阈值。"
        interpretation = "当前维持观察，不额外提示。"
        confidence = .60
    if quality < .45 and state != "uncertain":
        confidence = max(.30, confidence - .08)
        evidence += "画面清晰度偏低，置信度已下调。"
    if state == "uncertain":
        confidence = min(confidence, .48)
    if audio_activity is not None and state == "confused_or_stuck":
        evidence += "；声音为整段课堂活动，未定位到该学生。"
    if lesson_phase:
        evidence += f"当前处于“{lesson_phase}”，状态解释需结合当时教学环节。"
    confidence = round(max(.25, min(.92, confidence)), 3)
    return state, STUDENT_STATE_LABELS[state], evidence, interpretation, confidence


def _student_score(state, activity, quality):
    """A non-formal 0-10 participation evidence index for the result page."""
    if state == "uncertain" or activity is None:
        return None
    return round(10 * max(0., min(1., .65 * activity + .35 * quality)), 1)


def _select_key_moments(windows, limit=6):
    """Demo1-style review shortlist: risky cues first, then participation edges."""
    priority = {"confused_or_stuck": 0, "uncertain_adult_interference": 1,
                "low_attention": 2, "engaged": 3, "uncertain": 4}
    ranked = sorted(windows, key=lambda w: (priority.get(w.get("state"), 9), w["start_sec"]))
    picks = ranked[:limit]
    return [{"start_sec": w["start_sec"], "end_sec": w["end_sec"], "state": w["state"],
             "state_zh": w["state_zh"], "reason": (w.get("interpretation") or "")[:90],
             "frame": w.get("frame"), "frame_time_sec": w.get("frame_time_sec")}
            for w in sorted(picks, key=lambda item: item["start_sec"])]


def _classroom_rhythm(persons, duration):
    """Coarse, explainable lesson-rhythm metrics on the same 30-second windows."""
    import numpy as np
    windows = {}
    for person in persons:
        for window in person.get("windows") or []:
            windows.setdefault(window["start_sec"], []).append(window)
    rows = []
    for start in sorted(windows):
        items = windows[start]
        end = max(float(window.get("end_sec") or start + WINDOW_SEC) for window in items)
        audio = max((float(window.get("audio_activity")) for window in items
                     if isinstance(window.get("audio_activity"), (int, float))), default=0.0)
        activity_values = [float(window.get("motion_signal")) for window in items
                           if isinstance(window.get("motion_signal"), (int, float))]
        adult_values = [float(window.get("adult_interference")) for window in items
                        if isinstance(window.get("adult_interference"), (int, float))]
        rows.append({"start_sec": float(start), "end_sec": end, "audio": audio,
                     "activity": sum(activity_values) / len(activity_values) if activity_values else 0.0,
                     "adult": max(adult_values) if adult_values else 0.0})
    if not rows:
        return {"window_sec": WINDOW_SEC, "window_count": 0, "teacher_talk_seconds": 0.0,
                "teacher_talk_ratio": 0.0, "question_wait_events": 0, "question_wait_seconds": 0.0,
                "individual_support_seconds": 0.0, "individual_support_ratio": 0.0,
                "note": "没有可用于统计的时间片。"}
    total = sum(row["end_sec"] - row["start_sec"] for row in rows) or float(duration or 1)
    teacher = [row for row in rows if row["audio"] >= .35 and row["activity"] < .25]
    support = [row for row in rows if row["adult"] >= .55]
    audio_values = [row["audio"] for row in rows]
    audio_p10 = float(np.percentile(audio_values, 10))
    audio_p20 = float(np.percentile(audio_values, 20))
    audio_p90 = float(np.percentile(audio_values, 90))
    audio_median = float(np.median(audio_values))
    audio_flat = bool((audio_p90 - audio_p10) < .15)
    waits = [] if audio_flat else [
        row for before, row in zip(rows, rows[1:])
        if before["audio"] >= audio_median
        and (before["audio"] - row["audio"]) >= .15
        and row["audio"] <= audio_p20]
    wait_available = bool(waits)

    def seconds(items):
        return round(sum(row["end_sec"] - row["start_sec"] for row in items), 1)

    return {"window_sec": WINDOW_SEC, "window_count": len(rows),
            "teacher_talk_seconds": seconds(teacher),
            "teacher_talk_ratio": round(seconds(teacher) / total, 3),
            "question_wait_events": len(waits),
            "question_wait_seconds": seconds(waits),
            "wait_available": wait_available,
            "individual_support_seconds": seconds(support),
            "individual_support_ratio": round(seconds(support) / total, 3),
            "audio_flat": audio_flat,
            "note": ("本课课堂声音持续较高，无法从能量起伏判断提问-等待；" if audio_flat else "")
                    + "基于30秒时间窗的课堂级近似统计：讲解段=课堂有声音且学生整体安静；"
                    "提问-等待=有声音窗口后接安静窗口；个别支持=相邻区域活跃且本人安静。"
                    "声音未定位到个人，也不是逐句 ASR。"}


def _support_conclusions(persons, rhythm):
    """Three lesson-level conclusions plus next-lesson suggestions (teacher-facing)."""
    total_windows = sum(len(person.get("windows") or []) for person in persons)
    review = sum(person.get("state_summary", {}).get("review_required", 0) for person in persons)
    focus = []
    top = None
    conclusions = []
    if persons:
        top = max(persons, key=lambda person: (
            person["state_summary"]["counts"]["confused_or_stuck"]
            + person["state_summary"]["counts"]["uncertain_adult_interference"],
            person["state_summary"]["counts"]["low_attention"]))
        counts = top["state_summary"]["counts"]
        dominant = max(counts, key=counts.get)
        conclusions.append({
            "title": "本课状态分布",
            "text": f"{len(persons)}个人物候选共{total_windows}个时间片，建议教师确认{review}段；"
                    f"以“{STUDENT_STATE_LABELS[dominant]}”为主的是{top['display_name']}（{counts[dominant]}段）。",
            "basis": "逐人固定区域变化、相邻区域活动、课堂声音与画质"})
        focus_states = ("confused_or_stuck", "uncertain_adult_interference", "low_attention")
        focus = [(window["state"], window["start_sec"], window["end_sec"])
                 for window in top["windows"] if window["state"] in focus_states]
        if focus:
            state, start, end = focus[0]
            stuck = sum(1 for item in focus if item[0] == "confused_or_stuck")
            conclusions.append({
                "title": "优先复核",
                "text": f"{top['display_name']} 在{_clock(start)}–{_clock(end)}出现“{STUDENT_STATE_LABELS[state]}”；"
                        f"本课需要复核的片段共{len(focus)}个，其中困惑·停滞{stuck}个；先回看这些片段再决定支持方式。",
                "basis": f"{top['display_name']}的状态时间片"})
        else:
            conclusions.append({
                "title": "优先复核",
                "text": "本课没有出现困惑·停滞、成人干扰或注意力下降片段，保持观察即可；"
                        "如现场判断不同，以教师观察为准。",
                "basis": "本课状态时间片"})
    if rhythm.get("audio_flat") or not rhythm.get("wait_available", True):
        conclusions.append({
            "title": "课堂节奏",
            "text": "本课课堂声音持续，30秒时间窗内没有出现明显的“有声→安静”间隔，"
                    "无法据此判断提问-等待；"
                    f"相邻区域活跃（可能有人靠近座位）的时段约{rhythm['individual_support_seconds']:.0f}秒。"
                    "建议现场记录提问和等待次数，再与状态时间轴对照。",
            "basis": "30秒时间窗的课堂级近似统计；未检测到可用的声音间隔"})
    else:
        conclusions.append({
            "title": "课堂节奏",
            "text": f"课堂有声音且学生整体安静的时段约{rhythm['teacher_talk_seconds']:.0f}秒"
                    f"（{rhythm['teacher_talk_ratio']:.0%}），声音转安静的等待{rhythm['question_wait_events']}次，"
                    f"相邻区域活跃的时段约{rhythm['individual_support_seconds']:.0f}秒。"
                    "讲解偏长时安静时间片会增多，需要判断是听讲还是掉队。",
            "basis": "30秒时间窗的课堂级近似统计"})
    next_lesson = []
    if top is not None and focus:
        state, start, end = focus[0]
        next_lesson.append({
            "action": f"下节课在类似{_clock(start)}的环节给{top['display_name']}一步提示或视觉提示，"
                      "再观察同一时段是否变化。",
            "reason": "本课该时段出现需要复核的状态线索"})
    if rhythm.get("audio_flat") or not rhythm.get("wait_available", True):
        next_lesson.append({"action": "下一节课现场记录提问-等待次数，用现场记录和状态时间轴对照。",
                            "reason": "本课课堂声音持续，30秒窗内无法自动判断等待"})
    elif rhythm["question_wait_events"] < max(1, rhythm["window_count"] // 4):
        next_lesson.append({"action": "讲解后固定留一次提问-等待，先等 5–10 秒再补充说明。",
                            "reason": "本课声音转安静的等待次数偏少"})
    if rhythm["individual_support_seconds"] > 0:
        next_lesson.append({"action": "把个别支持集中在需要复核的人物，避免同时处理多个座位。",
                            "reason": "本课已出现相邻区域活跃的时段"})
    if not next_lesson:
        next_lesson.append({"action": "保持当前节奏，继续用同一时间段对照状态变化。",
                            "reason": "本课未出现需要调整的明显线索"})
    return {"conclusions": conclusions[:3], "next_lesson": next_lesson[:3],
            "profile": {"attached": False,
                        "note": "本课结论只基于视频证据；绑定学生后可结合已授权的最小 IEP 支持摘要复核，"
                                "系统不自动推断诊断或正式成绩。"}}


def _person_report(display_name, anchor, windows, average_score, visibility):
    """Create a distinct, evidence-bound Demo1-style student report."""
    x = center(anchor)[0]
    area = "左侧" if x < 1/3 else "中部" if x < 2/3 else "右侧"
    counts = {state: sum(w.get("state") == state for w in windows) for state in STUDENT_STATE_LABELS}
    top = max(counts, key=counts.get) if any(counts.values()) else "uncertain"

    def periods(state, limit=3):
        items = [w for w in windows if w.get("state") == state][:limit]
        return "、".join(f"{_clock(w['start_sec'])}–{_clock(w['end_sec'])}" for w in items) or "暂无"

    observed = sum(int(w.get("observed_samples", 0)) for w in windows)
    expected = sum(int(w.get("expected_samples", 0)) for w in windows)
    average = f"{average_score:.1f}/10" if average_score is not None else "暂缺"
    key = _select_key_moments(windows, 4)
    key_text = "、".join(f"{_clock(w['start_sec'])} {w['state_zh']}" for w in key) or "无"
    action_text = STUDENT_STATE_ACTIONS[top]["speech"]
    report = (
        f"{display_name}是首次检测时位于原画面{area}的匿名人物候选；编号按该时点从左到右分配。"
        f"系统随后独立读取对应固定区域，未把其他人物的截图或数值复制到本区域。全片按30秒整理为{len(windows)}个时间片；"
        f"该区域在{observed}/{expected}个逐秒样本中满足图像可用条件，可用率约{visibility * 100:.0f}%。"
        f"这只表示区域图像可读，不代表本人全程在场或身份连续已获验证；人物离位、交叉或换位时需要回看原片。"
        f"时间片状态分布：参与{counts['engaged']}段、注意力下降{counts['low_attention']}段、"
        f"困惑或停滞{counts['confused_or_stuck']}段、成人干扰下不确定{counts['uncertain_adult_interference']}段、"
        f"无法判断{counts['uncertain']}段；本课以“{STUDENT_STATE_LABELS[top]}”线索最多。"
        f"建议优先复核的关键片段：{key_text}。动作参考值平均{average}，"
        "0–10只是本人物固定区域在本视频内独立归一化的画面变化参考值，不是注意力、学习、情绪或教师成绩，"
        "不适合与其他人物横向排名。跑步、走位、伸展等正常体育活动不能单凭运动强度判定分心、不配合或扣分；"
        "镜头、光照、遮挡、衣物摆动和人物离开固定区域都会影响数值。"
        "上述状态是给教师复盘用的线索：注意力下降可能是倾听或等待，困惑·停滞需要结合当时指令判断，"
        "成人干扰下不确定应直接交教师确认；系统不据此推断专注、情绪、掌握程度、意愿、障碍类型或正式课堂成绩。"
        f"下一步建议：{action_text}并回看上述片段；教师确认后的结论才用于教学调整。"
    )
    action = (f"本课以“{STUDENT_STATE_LABELS[top]}”线索最多（{counts[top]}/{len(windows)} 段）；"
              f"优先复核：{key_text}。建议：{action_text}该结果用于教学复盘，不替代教师判断。")
    return action, {"title": f"{display_name}个人观察报告", "text": report,
                    "character_count": len(report), "basis": "该人物候选对应固定区域的逐秒画面变化、相邻区域动作与30秒时间片",
                    "formal_score": False}


def present_motion_analysis(analysis):
    """Re-present stored pre-v3.7 analyses with motion wording only.

    v3.7 analyses already carry Demo1 state cues; this function must never turn
    a motion index into an attention judgement or rewrite another engine's label.
    It performs no inference, file access, network request or identity change.
    """
    if (not isinstance(analysis, dict)
            or analysis.get("analysis_version") not in LEGACY_PRESENTATION_VERSIONS
            or analysis.get("score_kind") != "individual_motion_index"
            or str(analysis.get("state_policy_version", "")).startswith("demo1")
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
            window.pop("recommended_action", None)
            window.pop("interpretation", None)
            if state in MOTION_LABELS:
                window["state_zh"] = MOTION_LABELS[state]
                motion = window.get("movement")
                change = f"；局部画面变化 {motion:.3f}" if isinstance(motion, (int, float)) else ""
                window["evidence"] = (
                    f"此固定区域有 {window.get('observed_samples', 0)}/{window.get('expected_samples', 0)} 个可用采样{change}。"
                    "这是画面变化线索，不表示注意力或掌握程度；区域可用不等于持续确认同一人物。"
                )
        counts = {state: sum(w["state"] == state for w in windows)
                  for state in dict.fromkeys(w["state"] for w in windows)}
        dominant = max(counts, key=counts.get)
        dominant_zh = MOTION_LABELS.get(dominant, "画面证据不足")
        person["dominant_state"] = dominant
        person["dominant_state_zh"] = dominant_zh
        person["student_state"] = "uncertain"
        person["student_state_counts"] = {}
        person["student_summary"] = (
            f"旧版动作证据：共{len(windows)}个时间片，以“{dominant_zh}”为主；"
            "旧版只呈现固定区域画面变化线索，不给出参与/注意力判断，请结合原视频复核。")
        existing = person.get("lesson_report")
        if not isinstance(existing, dict) or not existing.get("text"):
            observed = sum(int(w.get("observed_samples", 0)) for w in windows)
            expected = sum(int(w.get("expected_samples", 0)) for w in windows)
            text = (
                f"该人物为旧版动作证据记录，共{len(windows)}个30秒时间片，"
                f"固定区域有{observed}/{expected}个采样满足图像可用条件。"
                f"时间片以“{dominant_zh}”为主，0–10仅是区域画面变化参考值，不是注意力、学习或教师成绩。"
                "旧版分析没有Demo1状态语义，也没有相邻区域成人干扰判断，因此不补写参与、注意力或困惑结论，"
                "以免把画面变化误标成学生状态。"
                "区域图像可用率不代表本人全程在场，也没有身份连续性验证；人物离位、交叉、遮挡和镜头移动都会影响结果。"
                "旧版只读取本区域逐秒画面变化，没有结合相邻区域活动、课堂声音和教学环节；"
                "单段视频内归一化也使数值只适合同一人物的不同时间段比较，不适合跨人物或跨课程比较。"
                "跑步、走位、伸展等正常体育活动不能单凭运动强度判定分心。"
                "如需参与、注意力、困惑或成人干扰线索，请使用当前版本重新分析该视频，再按关键片段回看原片。"
            )
            person["lesson_report"] = {"title": f"{person.get('display_name', '人物')}旧版动作记录",
                                       "text": text, "character_count": len(text),
                                       "basis": "旧版固定区域画面变化", "formal_score": False}
        person.setdefault("action_summary", f"旧版记录：{dominant_zh}；不提供状态建议。")
        summaries.append(f"{person.get('display_name', '人物')}：{dominant_zh}；")
    result["state_policy_version"] = "legacy_motion_presentation"
    result["lesson_report"] = result.get("lesson_report") or {
        "title": "旧版课堂记录", "text": "".join(summaries) + "旧版只保留动作线索，未包含参与/注意力状态建议。",
        "character_count": len("".join(summaries)) + 30, "basis": "旧版固定区域画面变化", "formal_score": False}
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
    # Demo1's adult-interference cue: activity near the seat, outside the seat.
    rings = [expand(roi, left=1.5, top=.6, right=1.5, bottom=.8) for roi in regions]
    previous_ring = [None]*len(anchors)
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
            previous_ring = [None]*len(anchors)
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
            ring_motion = None
            if scene_ok:
                ring_patch = crop(image, rings[i])
                ring_gray = cv2.cvtColor(ring_patch, cv2.COLOR_BGR2GRAY)
                ring_small = cv2.resize(ring_gray, (64, 64), interpolation=cv2.INTER_AREA)
                if previous_ring[i] is not None:
                    ring_diff = cv2.absdiff(ring_small, previous_ring[i])
                    rx0, ry0, rx1, ry1 = _crop_bounds(roi, rings[i], 64, 64)
                    ring_diff[ry0:ry1, rx0:rx1] = 0
                    ring_motion = float(ring_diff.mean() / 255)
                previous_ring[i] = ring_small
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
                                  local_similarity=local_similarity, ring_motion=ring_motion))
    persons = []
    for i, items in enumerate(tracks):
        values = [x["movement_signal_raw"] for x in items
                  if isinstance(x.get("movement_signal_raw"), (int, float))]
        low, high = np.percentile(values, [10, 90]) if values else (0., 0.)
        scale = max(.015, float(high-low))
        ring_values = [x["ring_motion"] for x in items
                       if isinstance(x.get("ring_motion"), (int, float))]
        ring_low, ring_high = np.percentile(ring_values, [10, 90]) if ring_values else (0., 0.)
        ring_scale = max(.01, float(ring_high - ring_low))
        windows = []
        previous_activity = None
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
            face_in_window = any(x["face_detected"] and start <= x["time"] < end for x in group)
            nearby_face = any(x["face_detected"] and start-45 <= x["time"] < end+45 for x in items)
            quality = float(np.mean([x["quality"] for x in visible])) if visible else 0.
            audio_activity, audio_coverage = _audio_for_window(audio_windows, start, end)
            lesson_phase = _lesson_phase(start, duration)
            teacher_activity = _teacher_activity(start, duration)
            response_expected = lesson_phase in {"引导练习", "个别练习与迁移", "总结与回顾"}
            ring_visible = [x["ring_motion"] for x in visible
                            if isinstance(x.get("ring_motion"), (int, float))]
            adult_interference = (float(np.mean([np.clip((value - ring_low) / ring_scale, 0, 1)
                                                 for value in ring_visible]))
                                  if ring_visible else None)
            score = round(10 * activity, 1) if activity is not None else None
            if expected == 0:
                state, label = "uncertain", STUDENT_STATE_LABELS["uncertain"]
                evidence = "该时段未采样，不等于学生未出现；保留为无法判断。"
                interpretation = "缺少采样，无法给出状态线索。"
                confidence = .30
            elif not visible:
                state, label = "uncertain", STUDENT_STATE_LABELS["uncertain"]
                evidence = "该时段固定区域被遮挡、人员离位或镜头变化，保留为无法判断。"
                interpretation = "该片段需要结合原视频人工确认。"
                confidence = .35
            else:
                state, label, evidence, interpretation, confidence = _student_state(
                    activity, audio_activity, adult_interference, visibility, quality,
                    motions, expected, face_presence=face_presence,
                    response_expected=response_expected, lesson_phase=lesson_phase,
                    previous_activity=previous_activity,
                )
            if state != "uncertain" and not face_in_window:
                confidence = round(max(.25, confidence - (.05 if nearby_face else .08)), 3)
                evidence += ("本人脸只在相邻时段确认，本时段按固定区域判断。" if nearby_face
                             else "本时段未检出本人脸，按固定区域画面判断。")
            student_score = _student_score(state, activity, quality)
            action = dict(STUDENT_STATE_ACTIONS[state])
            action["teacher_confirmation_required"] = bool(action["teacher_alert"])
            w = dict(start_sec=start, end_sec=round(end, 3), state=state, state_zh=label,
                      lesson_phase=lesson_phase, teacher_activity=teacher_activity,
                      response_expected=response_expected,
                     score=score, confidence=confidence,
                     evidence=evidence, interpretation=interpretation,
                     recommended_action=action,
                     frame=representative["frame"] if representative else "",
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
                      adult_interference=round(adult_interference, 3) if adult_interference is not None else None,
                      student_state=state, student_state_zh=label,
                      student_score=student_score, student_confidence=confidence,
                      student_evidence=evidence, student_interpretation=interpretation,
                      audio_activity=round(audio_activity, 3) if audio_activity is not None else None,
                      audio_coverage=round(audio_coverage, 3),
                      state_basis="Demo1 state cue: fixed-seat local image change, nearby-region activity, classroom audio and window quality")
            windows.append(w)
            previous_activity = activity
        scores = [w["score"] for w in windows if w["score"] is not None]
        student_scores = [w["student_score"] for w in windows if w.get("student_score") is not None]
        counts = {state: sum(w["state"] == state for w in windows) for state in STUDENT_STATE_LABELS}
        dominant = max(counts, key=counts.get) if any(counts.values()) else "uncertain"
        key_moments = _select_key_moments(windows)
        review_required = sum(1 for w in windows if (w.get("recommended_action") or {}).get("teacher_alert"))
        state_summary = {"counts": counts, "window_count": len(windows),
                         "ratios": {state: round(value / len(windows), 3)
                                    for state, value in counts.items()},
                         "review_required": review_required}
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
                            dominant_state_zh=STUDENT_STATE_LABELS[dominant],
                            student_state=dominant,
                            dominant_student_state=dominant,
                            dominant_student_state_zh=STUDENT_STATE_LABELS[dominant],
                            student_state_counts=counts,
                            state_summary=state_summary,
                            key_moments=key_moments,
                            detected_samples=sum(x["face_detected"] for x in items),
                            face_confirmed_samples=len(confirmed), reacquisition_count=reacquisitions,
                            same_person_continuity=round(len(confirmed) / max(1, len(items)), 3),
                            portrait_bbox=(max(confirmed, key=lambda x: (x["face_quality"], x["quality"]))["bbox"]
                                          if confirmed else anchors[i]),
                            portrait_quality=round(max((x["face_quality"] for x in confirmed), default=0.), 3),
                            observed_samples=sum(x["visible"] for x in items), visibility=visibility,
                            student_summary=(f"{STUDENT_STATE_LABELS[dominant]}线索最多，共{len(windows)}个时间片；"
                                             f"其中{review_required}个片段建议教师确认后使用。"),
                            action_summary=action_summary, lesson_report=person_report,
                            tracking="首次从左到右编号；固定人物区域结合每3秒人脸位置复核，禁止跨区域串人"))
    rhythm = _classroom_rhythm(persons, duration)
    support = _support_conclusions(persons, rhythm)
    rows = "".join(
        f"{item['display_name']}：{item['dominant_state_zh']}最多"
        f"（参与{item['state_summary']['counts']['engaged']}、"
        f"注意力下降{item['state_summary']['counts']['low_attention']}、"
        f"困惑·停滞{item['state_summary']['counts']['confused_or_stuck']}、"
        f"成人干扰下不确定{item['state_summary']['counts']['uncertain_adult_interference']}、"
        f"无法判断{item['state_summary']['counts']['uncertain']}）；"
        for item in persons
    )
    review_total = sum(item["state_summary"]["review_required"] for item in persons)
    report = (
        f"本段视频读取了{len(samples)}个采样画面，按30秒一个时间片整理{len(persons)}个匿名人物候选的"
        "Demo1 风格课堂状态线索。候选按首次检测时从左到右编号，各自使用不同的固定区域、截图和时间序列；"
        "编号只用于核对画面，不能证明姓名或全程身份连续。"
        + rows +
        f"全部时间片中，建议教师确认的片段共{review_total}个。"
        "状态由固定区域画面变化、相邻区域活动、整段课堂声音和当窗画质共同判定；"
        "声音无法定位到单个学生，只作为课堂情境参考。"
        "这些状态是教学复盘线索：注意力下降可能是倾听、等待或遮挡；困惑·停滞需要结合当时指令判断；"
        "成人干扰下不确定应直接交教师确认；系统不据此推断专注、情绪、掌握程度、意愿、障碍类型或正式课堂成绩。"
        "跑步、走位、伸展等正常体育活动不能单凭运动强度判定分心。"
        "请按关键片段回看原片，并结合教学目标与教师现场观察解释；无法核对的时间段保留为待确认，不用其他人物的表现填补。"
    )
    score_note = ("页面展示 Demo1 风格状态：参与、注意力下降、困惑·停滞、成人干扰下不确定、无法判断；"
                  "每段附屏幕/语音建议和是否需要教师确认，本版本不含机器人动作。"
                  + MOTION_SCORE_NOTE)
    return dict(
        available=True, analysis_version=VERSION, persons=persons, window_sec=WINDOW_SEC,
        detected_samples=detection_count, observed_frames=len(samples), max_persons=MAX_PERSONS,
        score_kind="individual_motion_index",
        student_score_kind="demo1_state_cue_index",
        state_policy_version="demo1_student_state_cues_v2",
        report_version=REPORT_VERSION,
        classroom_rhythm=rhythm,
        support_conclusions=support,
        score_note=score_note,
        lesson_report={"title": "全片课堂状态线索概览", "text": report,
                       "character_count": len(report),
                       "basis": "逐秒画面样本、逐人物固定区域、相邻区域活动、课堂声音和30秒时间片",
                       "scope": f"{len(persons)}个匿名人物候选", "formal_score": False},
        network_used=False,
        tracking_config={"detection_interval_sec": DETECTION_INTERVAL_SEC,
                         "initial_search_samples": INITIAL_SEARCH_SAMPLES,
                         "small_face_threshold": "tracking_only",
                         "scene_motion_suppression": True,
                         "primary_signal": "fixed_seat_local_motion",
                         "adult_interference_signal": "ring_motion_outside_seat",
                         "audio_role": "classroom_context_only",
                         "face_motion_role": "localization_only",
                         "identity_guard": "left_to_right_lane_plus_current_face_box"})


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    raw = sys.stdin.buffer.read(2*1024*1024+1)
    if len(raw) > 2*1024*1024:
        raise SystemExit(2)
    print(json.dumps(analyze(json.loads(raw)), ensure_ascii=True, allow_nan=False))
