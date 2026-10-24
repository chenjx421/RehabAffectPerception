from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .sim_runner import DEFAULT_SCENARIO_DIR, _mujoco_classroom_xml, run_scenario_path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "outputs" / "mujoco_frames"


STATE_COLORS = {
    "engaged": (0.10, 0.50, 0.24, 1.0),
    "neutral": (0.42, 0.44, 0.45, 1.0),
    "confused": (0.72, 0.46, 0.10, 1.0),
    "fatigued": (0.72, 0.46, 0.10, 1.0),
    "frustrated": (0.75, 0.25, 0.20, 1.0),
    "refusing": (0.75, 0.25, 0.20, 1.0),
    "pain_risk": (0.75, 0.25, 0.20, 1.0),
    "low_attention": (0.75, 0.25, 0.20, 1.0),
    "needs_help": (0.16, 0.34, 0.86, 1.0),
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render MuJoCo classroom scenario screenshots.")
    parser.add_argument("--scenario", type=Path, default=DEFAULT_SCENARIO_DIR / "pain_risk_safety.json")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--width", type=int, default=960)
    parser.add_argument("--height", type=int, default=540)
    parser.add_argument("--contact-sheet", action="store_true", default=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    result = run_scenario_path(
        args.scenario,
        backend_name="mujoco",
        include_cues=True,
        smooth_window=1,
    )
    frame_paths = render_result(result, args.output_dir, width=args.width, height=args.height)
    if args.contact_sheet:
        sheet_path = args.output_dir / f"{result['scenario_id']}_contact_sheet.png"
        write_contact_sheet(frame_paths, result, sheet_path)
    manifest = {
        "scenario_id": result["scenario_id"],
        "frame_paths": [str(path) for path in frame_paths],
        "contact_sheet": str(args.output_dir / f"{result['scenario_id']}_contact_sheet.png"),
    }
    (args.output_dir / f"{result['scenario_id']}_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


def render_result(
    result: dict[str, Any],
    output_dir: Path,
    *,
    width: int,
    height: int,
) -> list[Path]:
    import mujoco

    model = mujoco.MjModel.from_xml_string(_mujoco_classroom_xml())
    data = mujoco.MjData(model)
    renderer = mujoco.Renderer(model, height=height, width=width)
    student_geom = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, "student_proxy")
    frame_paths: list[Path] = []

    try:
        for record in result["steps"]:
            state = record["human_state"]["state"]
            distance = record["post_action_context"].get("robot_distance_m") or 1.0
            model.geom_rgba[student_geom] = np.asarray(
                STATE_COLORS.get(state, STATE_COLORS["neutral"]),
                dtype=np.float32,
            )
            data.qpos[0] = -float(distance)
            data.qpos[1] = 0.0
            mujoco.mj_forward(model, data)
            renderer.update_scene(data, camera="overview")
            image = renderer.render()
            path = output_dir / f"{result['scenario_id']}_step_{record['step']}.png"
            Image.fromarray(image).save(path)
            frame_paths.append(path)
    finally:
        renderer.close()

    return frame_paths


def write_contact_sheet(
    frame_paths: list[Path],
    result: dict[str, Any],
    output_path: Path,
) -> None:
    frames = [Image.open(path).convert("RGB") for path in frame_paths]
    if not frames:
        raise ValueError("No frames to render")
    font = ImageFont.load_default()
    caption_height = 78
    gutter = 14
    card_width = frames[0].width
    card_height = frames[0].height + caption_height
    sheet_width = card_width * len(frames) + gutter * (len(frames) - 1)
    sheet_height = card_height
    sheet = Image.new("RGB", (sheet_width, sheet_height), (246, 247, 243))
    draw = ImageDraw.Draw(sheet)

    for index, frame in enumerate(frames):
        x = index * (card_width + gutter)
        sheet.paste(frame, (x, 0))
        record = result["steps"][index]
        state = record["human_state"]["state"]
        action = record["robot_action"]["action_id"]
        speech = record.get("observable_cues", {}).get("speech_text") or "(silent)"
        lines = [
            f"step {record['step']} | state={state}",
            f"speech={speech}",
            f"robot_action={action}",
        ]
        y = frame.height + 8
        for line in lines:
            draw.text((x + 10, y), line, fill=(23, 32, 28), font=font)
            y += 20
    sheet.save(output_path)


if __name__ == "__main__":
    raise SystemExit(main())
