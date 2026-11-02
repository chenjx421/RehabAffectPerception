"""Build a synthetic classroom clip for the student-only person filter.

Everything is drawn with OpenCV (no real people):
  * one large walking "adult/teacher" cartoon on the left, standing higher;
  * three (``--students``, 1..5) small seated "student" cartoon faces with
    light head movement — the default of three is the multi-student acceptance
    clip (每课至少 3 名学生，可切换);
  * one faceless figure on the right whose face only flickers faintly in a
    few opening seconds (a blank pick that must be excluded).

Usage:
  PYTHONPATH=src .venv/bin/python scripts/make_person_filter_synthetic_video.py OUT.mp4 [--seconds 60] [--students 3]
FFmpeg comes from REHAB_FFMPEG or the bundled imageio-ffmpeg binary.
"""

from __future__ import annotations

import argparse
import math
import os
from pathlib import Path
import subprocess
import sys

import numpy as np

WIDTH, HEIGHT, FPS = 1280, 720, 10
STUDENT_X = (520, 780, 1040)
# Seat columns for --students 1..5 (3 keeps the original layout used by the tests).
STUDENT_LAYOUTS = {1: (780,), 2: (600, 960), 3: STUDENT_X, 4: (470, 660, 850, 1040), 5: (440, 590, 740, 890, 1040)}
STUDENT_Y = 400
STUDENT_FACE = 140
TEACHER_FACE = 250
TEACHER_Y = 250
BLANK_X, BLANK_Y = 1215, 420
# Seconds in which the faceless figure briefly shows a faint face.
BLANK_FLICKER = (0, 3, 6)


def _ffmpeg() -> str:
    configured = os.getenv("REHAB_FFMPEG", "").strip()
    if configured:
        return configured
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def draw_face(img: np.ndarray, cx: int, cy: int, h: int, *, skin=(140, 170, 215), hair=(35, 35, 50),
              strength: float = 1.0) -> None:
    """Cartoon face drawn so the YuNet model can localise it (fictional, not a person)."""
    import cv2
    w = int(h * .78)
    layer = img.copy()
    shade = tuple(int(c * .85) for c in skin)
    cv2.rectangle(layer, (cx - int(w * .2), cy + int(h * .3)), (cx + int(w * .2), cy + int(h * .62)), shade, -1)
    for dx in (-1, 1):
        cv2.ellipse(layer, (cx + dx * int(w * .5), cy), (int(w * .09), int(h * .12)), 0, 0, 360,
                    tuple(int(c * .9) for c in skin), -1, cv2.LINE_AA)
    cv2.ellipse(layer, (cx, cy), (w // 2, h // 2), 0, 0, 360, skin, -1, cv2.LINE_AA)
    cv2.ellipse(layer, (cx, cy - int(h * .22)), (int(w * .55), int(h * .36)), 0, 180, 360, hair, -1, cv2.LINE_AA)
    cv2.ellipse(layer, (cx, cy - int(h * .22)), (int(w * .55), int(h * .12)), 0, 0, 180, hair, -1, cv2.LINE_AA)
    features = layer.copy()
    for dx in (-1, 1):
        ex, ey = cx + dx * int(w * .21), cy - int(h * .04)
        cv2.ellipse(features, (ex, ey + int(h * .01)), (int(w * .14), int(h * .06)), 0, 0, 360,
                    tuple(int(c * .75) for c in skin), -1, cv2.LINE_AA)
        cv2.ellipse(features, (ex, ey), (int(w * .11), int(h * .04)), 0, 0, 360, (235, 240, 245), -1, cv2.LINE_AA)
        cv2.circle(features, (ex, ey), int(h * .035), (40, 60, 90), -1, cv2.LINE_AA)
        cv2.circle(features, (ex, ey), int(h * .018), (10, 10, 10), -1, cv2.LINE_AA)
        cv2.ellipse(features, (ex, ey - int(h * .09)), (int(w * .14), int(h * .03)), 0, 180, 360, hair,
                    max(2, h // 30), cv2.LINE_AA)
    nose = np.array([[cx, cy - int(h * .02)], [cx - int(w * .07), cy + int(h * .14)],
                     [cx + int(w * .07), cy + int(h * .14)]], np.int32)
    cv2.fillPoly(features, [nose], tuple(int(c * .82) for c in skin), cv2.LINE_AA)
    for dx in (-1, 1):
        cv2.circle(features, (cx + dx * int(w * .04), cy + int(h * .15)), max(1, int(h * .012)), (50, 60, 90), -1,
                   cv2.LINE_AA)
    cv2.ellipse(features, (cx, cy + int(h * .27)), (int(w * .16), int(h * .04)), 0, 0, 360, (70, 80, 170), -1,
                cv2.LINE_AA)
    cv2.line(features, (cx - int(w * .15), cy + int(h * .27)), (cx + int(w * .15), cy + int(h * .27)),
             (40, 40, 100), max(1, h // 60), cv2.LINE_AA)
    layer = cv2.addWeighted(features, strength, layer, 1 - strength, 0)
    mask = np.zeros(img.shape[:2], np.uint8)
    cv2.ellipse(mask, (cx, cy), (w // 2 + 4, h // 2 + 4), 0, 0, 360, 1, -1)
    k = max(3, (h // 40) | 1)
    blurred = cv2.GaussianBlur(layer, (k, k), 0)
    img[:] = np.where(mask[..., None] > 0, blurred, layer)


def render_frame(t: float, students: int = 3) -> np.ndarray:
    import cv2
    img = np.full((HEIGHT, WIDTH, 3), (200, 210, 212), np.uint8)
    cv2.rectangle(img, (0, 640), (WIDTH, HEIGHT), (150, 170, 185), -1)
    cv2.putText(img, "SYNTHETIC QA ONLY - person filter", (430, 40), cv2.FONT_HERSHEY_SIMPLEX, .8,
                (90, 90, 90), 2, cv2.LINE_AA)
    # Seated students: small faces, desks, light head movement.
    layout = STUDENT_LAYOUTS.get(students, STUDENT_X)
    face = STUDENT_FACE if len(layout) <= 3 else 110
    desk = 85 if len(layout) <= 3 else 62
    for index, x in enumerate(layout):
        bob = int(4 * math.sin(t * 1.3 + index))
        sway = int(6 * math.sin(t * .7 + index * 2))
        cv2.rectangle(img, (x - desk, 480), (x + desk, 640), (180, 110, 60), -1)
        draw_face(img, x + sway, STUDENT_Y + bob, face, skin=(140 - index * 6, 170 - index * 4, 215 - index * 5))
        cv2.rectangle(img, (x - desk - 30, 560), (x + desk + 30, 600), (120, 90, 70), -1)
    # Standing adult: large face, higher in the frame, walking left-right.
    walk = 175 + int(95 * math.sin(t * 2 * math.pi / 12))
    cv2.rectangle(img, (walk - 120, TEACHER_Y + 170), (walk + 120, HEIGHT), (70, 70, 70), -1)
    draw_face(img, walk, TEACHER_Y, TEACHER_FACE, skin=(135, 165, 210))
    # Faceless figure: plain head and body, faint face only in a few seconds.
    cv2.rectangle(img, (BLANK_X - 52, 480), (BLANK_X + 52, 640), (90, 140, 90), -1)
    if int(t) in BLANK_FLICKER:
        draw_face(img, BLANK_X, BLANK_Y, 120, strength=.75)
    else:
        cv2.ellipse(img, (BLANK_X, BLANK_Y), (45, 60), 0, 0, 360, (140, 170, 215), -1, cv2.LINE_AA)
    return img


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("output", type=Path)
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--students", type=int, default=3, help="seated cartoon students, 1..5 (default 3)")
    args = parser.parse_args(argv)
    if not 10 <= args.seconds <= 600:
        parser.error("--seconds must be 10..600")
    if args.students not in STUDENT_LAYOUTS:
        parser.error("--students must be 1..5")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    command = [_ffmpeg(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{WIDTH}x{HEIGHT}",
               "-r", str(FPS), "-i", "-", "-f", "lavfi", "-i", f"sine=frequency=440:duration={args.seconds}",
               "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "64k",
               str(args.output)]
    process = subprocess.Popen(command, stdin=subprocess.PIPE)
    assert process.stdin is not None
    try:
        for index in range(args.seconds * FPS):
            process.stdin.write(render_frame(index / FPS, args.students).tobytes())
    finally:
        process.stdin.close()
    code = process.wait()
    if code:
        print(f"ffmpeg failed with exit code {code}", file=sys.stderr)
        return code
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
