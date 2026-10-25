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

VERSION = "simple_student_seats_v3_2"
WINDOW_SEC = 30
MAX_SAMPLES = 10800
TIMEOUT_SEC = 900
MAX_PERSONS = 3
REPORT_VERSION = "motion_report_v2"
MOTION_LABELS = {"movement_high": "动作变化较多", "movement_moderate": "中等动作变化",
                 "movement_low": "动作变化较少"}
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
    request = {"root": str(Path(run).resolve() / "frames"), "samples": samples,
               "duration": meta.get("duration_sec", 0)}
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
    """No detector ordering, transitive drift, or long-gap position matching."""
    x, y = center(face["bbox"])
    ax, ay = center(anchor)
    return (roi["x"] <= x <= roi["x"]+roi["width"]
            and abs(x-ax) <= max(.018, anchor["width"]*1.5)
            and abs(y-ay) <= max(.035, anchor["height"]*1.6)
            and .45 <= face["bbox"]["width"]/anchor["width"] <= 2.2)


class Detector:
    def __init__(self):
        import cv2
        from rehab_affect import demo2_face_detection as face
        if face._validate_model(face.MODEL_PATH):
            raise RuntimeError("face_model_unavailable")
        self.face = face
        self.model = cv2.FaceDetectorYN.create(str(face.MODEL_PATH), "", (640, 640), .8, .3, 512)

    def __call__(self, image):
        import cv2
        import numpy as np
        h, w = image.shape[:2]
        candidates = set()
        for i, region in enumerate(self.face._view_regions(w, h)):
            x, y, rw, rh = region
            ratio = 640/max(rw, rh)
            if i == 0:
                ratio = min(1., ratio)
            sw, sh = max(1, round(rw*ratio)), max(1, round(rh*ratio))
            px, py = (640-sw)//2, (640-sh)//2
            canvas = np.zeros((640, 640, 3), np.uint8)
            canvas[py:py+sh, px:px+sw] = cv2.resize(image[y:y+rh, x:x+rw], (sw, sh))
            _, raw = self.model.detect(canvas)
            candidates.update(self.face._collect_candidates(raw, w, h, sw, sh, px, py, region=region))
        return self.face._merge_candidates(candidates)


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


def _person_report(display_name, anchor, windows, average_score, visibility):
    """Create a distinct, evidence-bound report without inferring attention."""
    x = center(anchor)[0]
    area = "左侧" if x < 1/3 else "中部" if x < 2/3 else "右侧"
    scored = [w for w in windows if isinstance(w.get("score"), (int, float))]
    high = sorted(scored, key=lambda w: (-w["score"], w["start_sec"]))[:3]
    quiet = sorted(scored, key=lambda w: (w["score"], w["start_sec"]))[:3]

    def periods(items):
        return "、".join(f"{_clock(w['start_sec'])}–{_clock(w['end_sec'])}（{w['score']:.1f}）" for w in items) or "暂无可评分片段"

    count_by_state = {state: sum(w.get("state") == state for w in windows)
                      for state in ("movement_high", "movement_moderate", "movement_low", "uncertain")}
    observed = sum(int(w.get("observed_samples", 0)) for w in windows)
    expected = sum(int(w.get("expected_samples", 0)) for w in windows)
    average = f"{average_score:.1f}/10" if average_score is not None else "暂缺"
    report = (
        f"{display_name}是首次检测时位于原画面{area}的匿名人物候选；编号按该时点从左到右分配。"
        f"系统随后独立读取对应固定区域，未把其他人物的截图或数值复制到本区域。全片按30秒整理为{len(windows)}个时间片；"
        f"该区域在{observed}/{expected}个逐秒样本中满足图像可用条件，可用率约{visibility * 100:.0f}%。"
        f"这只表示区域图像可读，不代表本人全程在场或身份连续已获验证；人物离位、交叉或换位时需要回看原片。"
        f"有效时间片的平均局部画面变化参考值为{average}；变化较多片段为{periods(high)}，"
        f"变化较少片段为{periods(quiet)}。所有时间片中，中等变化{count_by_state['movement_moderate']}段，"
        f"较多变化{count_by_state['movement_high']}段，较少变化{count_by_state['movement_low']}段；"
        f"另有{count_by_state['uncertain']}段证据不足而不评分。"
        "0–10是本区域在本视频内按相对像素变化归一化得到的参考指数，只用于回看本人物候选的不同时间段，"
        "不适合与其他人物比较，也不识别具体动作。跑步、走位、伸展等正常活动不能单凭运动强度判定分心、"
        "不配合或扣分。画面变化还会受到镜头、光照、遮挡、衣物摆动及人物离开固定区域影响。"
        "建议按上述时间点回看原片，并结合当时教学目标、现场指令和人工观察解释；当前没有教案目标或教师标注，"
        "因此不推断专注、情绪、掌握程度、意愿、障碍类型或正式课堂成绩。"
    )
    action = (f"该区域的局部画面变化：较多 {periods(high)}；较少 {periods(quiet)}。"
              "参考值描述像素变化，不识别具体动作，也不能据此判定注意力。")
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
               "engaged": "movement_moderate"}
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
        counts = {state: sum(w["state"] == state for w in windows)
                  for state in dict.fromkeys(w["state"] for w in windows)}
        dominant = max(counts, key=counts.get)
        person["dominant_state"] = dominant
        person["dominant_state_zh"] = next(w["state_zh"] for w in windows if w["state"] == dominant)
        person["action_summary"], person["lesson_report"] = _person_report(
            person["display_name"], person["anchor_bbox"], windows,
            person.get("average_score"), person.get("visibility", 0))
        person["tracking"] = "按首次检测位置固定区域逐秒独立取样；可用率指区域图像，不自动跨区域认人或确认身份连续。"
        summaries.append(f"{person['display_name']}：共{len(windows)}个时间片，{person['dominant_state_zh']}最多；"
                         f"固定区域图像可用率约{person.get('visibility', 0)*100:.0f}%。")
    report = (
        f"本段视频读取了{result.get('observed_frames', 0)}个采样画面，按30秒一个时间片整理{len(people)}个匿名人物候选的局部画面变化。"
        "候选按首次检测时从左到右编号，各自使用不同的固定区域、截图和时间序列；"
        "编号只用于核对画面，不能证明姓名或全程身份连续。" + "".join(summaries)
        + "参考值按每个区域在本段视频内的变化幅度独立归一化，只能帮助定位该区域变化较多或较少的时间段，"
        "不可把不同人物的数值相加、排名或解释为学习成绩、专注度、情绪和动作完成质量。"
        "跑步、步移和伸展等正常体育活动不能单凭活动量判为分心，较少变化也可能是正常等待或保持姿势。"
        "固定区域图像可用率不是学生出勤率，也不是身份追踪成功率；镜头、光照、遮挡和人物交叉换位都可能影响结果。"
        "请分别查看各人物的截图、时间轴和个人报告，并结合原片、教学目标及教师现场观察解释，"
        "无法核对的时间段应保留为待确认，不用其他人物的表现填补。"
    )
    result.update(state_policy_version="motion_reference_v2", report_version=REPORT_VERSION,
                  score_note=MOTION_SCORE_NOTE,
                  lesson_report={"title": "全片动作变化概览", "text": report, "character_count": len(report),
                                 "basis": "逐秒画面样本、独立固定区域和30秒时间片",
                                 "scope": f"{len(people)}个匿名人物候选", "formal_score": False})
    return result


def analyze(request, detector=None):
    import cv2
    import numpy as np
    cv2.setNumThreads(1)
    root = Path(request["root"])
    samples = request["samples"]
    duration = float(request["duration"])
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
    detection_count = 0
    for sample in samples[:60:5]:
        candidate_image = _read(root, sample["frame"])
        if candidate_image is None:
            continue
        candidates = sorted(detector(candidate_image), key=lambda f: center(f["bbox"])[0])[:MAX_PERSONS]
        detection_count += 1
        if len(candidates) > len(faces):
            faces, initial = candidates, candidate_image
            anchor_time = float(sample["time"])
        if len(faces) == MAX_PERSONS:
            break
    if not faces:
        # A title slide or empty classroom at the start is not the whole lesson.
        for sample in samples[60::30]:
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
    tracks = [[] for _ in anchors]
    next_detection = anchor_time
    # Fixed background comparison rejects camera cuts; a stationary classroom
    # can be reacquired without letting one student's anchor walk to another.
    scene_ref = cv2.resize(initial, (80, 45)).astype(float)/255
    for sample in samples:
        t = float(sample["time"])
        image = _read(root, sample["frame"])
        if image is None:
            previous = [None]*len(anchors)
            continue
        scene_delta = float(np.abs(cv2.resize(image, (80, 45)).astype(float)/255-scene_ref).mean())
        scene_ok = scene_delta < .16 and image.shape == initial.shape and t >= anchor_time
        detected = []
        if scene_ok and t >= next_detection:
            detected = detector(image)
            detection_count += 1
            next_detection = t+10
        for i, (anchor, roi) in enumerate(zip(anchors, regions)):
            patch = crop(image, roi)
            similarity = _similarity(reference[i], _appearance(patch))
            textured_head = _head_texture(image, anchor) >= max(.025, head_texture[i]*.4)
            usable = scene_ok and similarity >= .68 and textured_head
            gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
            small = cv2.resize(gray, (96, 96), interpolation=cv2.INTER_AREA)
            prior = previous[i]
            # Same per-person 96x96 frame-difference measurement as Demo1.
            motion = float(cv2.absdiff(small, prior[1]).mean()/255) if usable and prior and t-prior[0] <= 1.5 else None
            previous[i] = (t, small) if usable else None
            brightness = float(small.mean())
            blur = float(cv2.Laplacian(small, cv2.CV_64F).var())
            quality = min(1., (blur/120)*.62 + (1. if 35 <= brightness <= 225 else .35)*.38)
            matched = [f for f in detected if face_in_seat(f, anchor, roi)] if usable else []
            face = min(matched, key=lambda f: math.dist(center(f["bbox"]), center(anchor))) if matched else None
            # On missed face detection, retain the actual same-time seat crop,
            # never a photograph borrowed from another time/person.
            tracks[i].append(dict(time=t, frame=sample["frame"], bbox=face["bbox"] if face else anchor,
                                  visible=usable, motion=motion, quality=quality,
                                  appearance=similarity, face_detected=bool(face), scene_ok=scene_ok))
    persons = []
    for i, items in enumerate(tracks):
        values = [x["motion"] for x in items if x["motion"] is not None]
        low, high = np.percentile(values, [10, 90]) if values else (0., 0.)
        scale = max(.015, float(high-low))
        windows = []
        for start in range(0, math.ceil(duration), WINDOW_SEC):
            end = min(duration, start+WINDOW_SEC)
            group = [x for x in items if start <= x["time"] < end]
            visible = [x for x in group if x["visible"]]
            expected = len([s for s in samples if start <= s["time"] < end])
            motions = [x["motion"] for x in visible if x["motion"] is not None]
            activity = float(np.mean([np.clip((m-low)/scale, 0, 1) for m in motions])) if motions else None
            raw = float(np.mean(motions)) if motions else None
            visibility = len(visible)/max(1, expected)
            # Always retain the same-time fixed-seat crop. When a face is not
            # confirmed, the crop is evidence of the observed region only and
            # the window remains unscored; it is never replaced by a neighbour.
            representative = max(visible, key=lambda x: (x["face_detected"], x["appearance"], x["quality"])) if visible else (
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
            w = dict(start_sec=start, end_sec=round(end, 3), state=state, state_zh=label,
                     score=score, confidence=round(min(.85, visibility*.5+quality*.2), 3),
                     evidence=evidence, frame=representative["frame"] if representative else "",
                     frame_time_sec=representative["time"] if representative else None,
                     bbox=representative["bbox"] if representative else None,
                     visibility=round(visibility, 3), movement=round(raw, 6) if raw is not None else None,
                     motion_signal=round(activity, 4) if activity is not None else None,
                     observed_samples=len(visible), expected_samples=expected,
                     localization="face_in_fixed_seat" if representative and representative["face_detected"] else "fixed_seat_roi",
                     identity_continuity="seat_region_only_not_biometric_identity",
                     nearby_face_verified=nearby_face,
                     appearance_similarity=round(representative["appearance"], 3) if representative else None)
            windows.append(w)
        scores = [w["score"] for w in windows if w["score"] is not None]
        counts = {state:sum(w["state"] == state for w in windows)
                  for state in dict.fromkeys(w["state"] for w in windows)}
        dominant = max(counts, key=counts.get)
        average_score = round(sum(scores)/len(scores), 2) if scores else None
        visibility = round(sum(x["visible"] for x in items)/max(1,len(samples)), 3)
        display_name = f"人物 {i+1}"
        action_summary, person_report = _person_report(display_name, anchors[i], windows, average_score, visibility)
        persons.append(dict(person_id=f"person_{i+1:02d}", display_name=display_name, anonymous=True,
                            anchor_bbox=anchors[i], observation_roi=regions[i], windows=windows,
                            average_score=average_score, dominant_state=dominant,
                            dominant_state_zh=next(w["state_zh"] for w in windows if w["state"] == dominant),
                            detected_samples=sum(x["face_detected"] for x in items),
                            observed_samples=sum(x["visible"] for x in items), visibility=visibility,
                            action_summary=action_summary, lesson_report=person_report,
                            tracking="首次从左到右固定局部区域，逐秒独立观察；不自动跨区域认人"))
    return present_motion_analysis(dict(
        available=True, analysis_version=VERSION, persons=persons, window_sec=WINDOW_SEC,
        detected_samples=detection_count, observed_frames=len(samples), max_persons=MAX_PERSONS,
        score_kind="individual_motion_index", network_used=False))



if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    raw = sys.stdin.buffer.read(2*1024*1024+1)
    if len(raw) > 2*1024*1024:
        raise SystemExit(2)
    print(json.dumps(analyze(json.loads(raw)), ensure_ascii=True, allow_nan=False))
