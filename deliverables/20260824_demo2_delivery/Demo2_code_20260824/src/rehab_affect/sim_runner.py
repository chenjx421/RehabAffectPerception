from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

from .inputs import AudioChunk, CameraFrame, InputBatch, TaskBehavior
from .pipeline import RehabAffectPipeline
from .schema import RobotAction, RobotContext


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCENARIO_DIR = PROJECT_ROOT / "configs" / "scenarios"
DEFAULT_LEARNED_POLICY_PATH = PROJECT_ROOT / "models" / "learned_school_policy.pkl"
SAFE_MOTION_POLICIES = {"stop_motion", "hold_position", "increase_personal_space"}
HANDOFF_STATES = {"pain_risk", "needs_help"}


class KinematicClassroomBackend:
    """Lightweight classroom simulation backend used before MuJoCo assets exist."""

    name = "kinematic_classroom"

    def apply_action(self, context: RobotContext, action: RobotAction) -> RobotContext:
        distance = context.robot_distance_m
        obstacle_distance = context.obstacle_distance_m
        is_moving = context.is_robot_moving

        if action.motion_policy in {"stop_motion", "hold_position"}:
            is_moving = False
        elif action.motion_policy == "increase_personal_space":
            is_moving = False
            distance = None if distance is None else distance + 0.20
        elif action.motion_policy == "slow_down":
            is_moving = context.is_robot_moving
            distance = None if distance is None else max(0.2, distance - 0.02)
            obstacle_distance = (
                None if obstacle_distance is None else max(0.1, obstacle_distance - 0.01)
            )
        elif action.motion_policy in {"continue_planned_motion", "continue_cautiously"}:
            is_moving = context.is_robot_moving
            distance = None if distance is None else max(0.2, distance - 0.05)
            obstacle_distance = (
                None if obstacle_distance is None else max(0.1, obstacle_distance - 0.03)
            )

        metadata = {
            **context.metadata,
            "backend": self.name,
            "applied_motion_policy": action.motion_policy,
        }
        return replace(
            context,
            robot_distance_m=distance,
            obstacle_distance_m=obstacle_distance,
            is_robot_moving=is_moving,
            metadata=metadata,
        )


class MujocoBackend(KinematicClassroomBackend):
    """Tiny MuJoCo classroom backend used once the optional dependency is installed."""

    name = "mujoco"

    def __init__(self) -> None:
        try:
            import mujoco  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "MuJoCo is not installed. Install the simulation extra first: "
                "pip install -e .[simulation]"
            ) from exc
        self._mujoco = mujoco
        self._model = mujoco.MjModel.from_xml_string(_mujoco_classroom_xml())
        self._data = mujoco.MjData(self._model)

    def apply_action(self, context: RobotContext, action: RobotAction) -> RobotContext:
        post_context = super().apply_action(context, action)
        distance = post_context.robot_distance_m or 1.0
        self._data.qpos[0] = -distance
        self._data.qpos[1] = 0.0
        self._mujoco.mj_forward(self._model, self._data)
        self._mujoco.mj_step(self._model, self._data)
        return replace(
            post_context,
            metadata={
                **post_context.metadata,
                "backend": self.name,
                "mujoco_model": "special_education_classroom_v0",
                "mujoco_time": float(self._data.time),
            },
        )


def _mujoco_classroom_xml() -> str:
    return """
<mujoco model="special_education_classroom_v0">
  <option timestep="0.02" gravity="0 0 -9.81"/>
  <visual>
    <global offwidth="1280" offheight="720"/>
  </visual>
  <worldbody>
    <light name="main_light" pos="0 -3 5" dir="0 0 -1" diffuse="0.9 0.9 0.85"/>
    <camera name="overview" pos="0 -4.2 3.0" xyaxes="1 0 0 0 0.58 0.82"/>
    <geom name="floor" type="plane" size="4 4 0.1" rgba="0.92 0.92 0.88 1"/>
    <body name="robot" pos="-1.2 0 0.18">
      <joint name="robot_x" type="slide" axis="1 0 0"/>
      <joint name="robot_y" type="slide" axis="0 1 0"/>
      <geom name="robot_base" type="box" size="0.25 0.20 0.18" rgba="0.1 0.35 0.9 1"/>
    </body>
    <body name="student" pos="0 0 0.45">
      <geom name="student_proxy" type="capsule" fromto="0 0 -0.35 0 0 0.35" size="0.14" rgba="0.8 0.55 0.45 1"/>
    </body>
    <body name="teacher" pos="1.4 1.2 0.45">
      <geom name="teacher_proxy" type="capsule" fromto="0 0 -0.35 0 0 0.35" size="0.13" rgba="0.3 0.65 0.35 1"/>
    </body>
    <body name="desk" pos="0.25 -0.7 0.28">
      <geom name="desk_top" type="box" size="0.7 0.35 0.05" rgba="0.55 0.35 0.18 1"/>
    </body>
    <body name="teaching_aid" pos="0.05 -0.72 0.38">
      <geom name="teaching_aid_block" type="box" size="0.08 0.08 0.08" rgba="0.95 0.2 0.2 1"/>
    </body>
    <body name="obstacle" pos="-0.45 0.55 0.15">
      <geom name="obstacle_box" type="box" size="0.18 0.18 0.15" rgba="0.9 0.65 0.1 1"/>
    </body>
  </worldbody>
</mujoco>
"""


def load_scenario(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def run_scenario(
    scenario: dict[str, Any],
    *,
    backend: KinematicClassroomBackend | None = None,
    robot_policy: Any | None = None,
    person_id: str = "student_001",
    smooth_window: int = 1,
    include_cues: bool = False,
) -> dict[str, Any]:
    backend = backend or KinematicClassroomBackend()
    pipeline = RehabAffectPipeline(
        person_id=person_id,
        smooth_window=smooth_window,
        robot_policy=robot_policy,
    )

    records: list[dict[str, Any]] = []
    for step in scenario.get("steps", []):
        batch = _batch_from_step(step)
        context = _context_from_step(step)
        result = pipeline.process_batch(batch, robot_context=context)
        post_context = backend.apply_action(context, result.robot_action)

        record: dict[str, Any] = {
            "step": step.get("step", len(records)),
            "ground_truth_state": step.get("ground_truth_state"),
            "expected_action_id": step.get("expected_action_id"),
            "human_state": result.human_state.to_dict(),
            "robot_context": context.to_dict(),
            "robot_action": result.robot_action.to_dict(),
            "post_action_context": post_context.to_dict(),
            "action_match": result.robot_action.action_id == step.get("expected_action_id"),
            "safety_violation": _safety_violation(
                ground_truth_state=str(step.get("ground_truth_state") or ""),
                context=context,
                post_context=post_context,
                action=result.robot_action,
            ),
        }
        if include_cues:
            record["observable_cues"] = step.get("observable_cues", {})
        records.append(record)

    return {
        "scenario_id": scenario.get("scenario_id"),
        "task": scenario.get("task"),
        "description": scenario.get("description"),
        "backend": backend.name,
        "policy": _policy_name(robot_policy),
        "metrics": _metrics(records),
        "steps": records,
    }


def run_scenario_path(
    path: Path,
    *,
    backend_name: str = "kinematic",
    robot_policy: Any | None = None,
    person_id: str = "student_001",
    smooth_window: int = 1,
    include_cues: bool = False,
) -> dict[str, Any]:
    backend = _build_backend(backend_name)
    return run_scenario(
        load_scenario(path),
        backend=backend,
        robot_policy=robot_policy,
        person_id=person_id,
        smooth_window=smooth_window,
        include_cues=include_cues,
    )


def _build_backend(name: str) -> KinematicClassroomBackend:
    if name == "kinematic":
        return KinematicClassroomBackend()
    if name == "mujoco":
        return MujocoBackend()
    raise ValueError(f"Unknown backend: {name}")


def build_policy(name: str, model_path: Path | None = None) -> Any | None:
    if name == "rule":
        return None
    if name == "learned":
        from .learned_policy import LearnedSchoolPolicy

        path = model_path or DEFAULT_LEARNED_POLICY_PATH
        if not path.exists():
            raise RuntimeError(
                f"Learned policy model not found: {path}. "
                "Train it first with: python -m src.rehab_affect.train_policy"
            )
        return LearnedSchoolPolicy.load(path)
    raise ValueError(f"Unknown policy: {name}")


def _policy_name(robot_policy: Any | None) -> str:
    if robot_policy is None:
        return "rule"
    metadata = getattr(robot_policy, "metadata", {})
    if isinstance(metadata, dict) and metadata.get("policy_type"):
        return str(metadata["policy_type"])
    return type(robot_policy).__name__


def _batch_from_step(step: dict[str, Any]) -> InputBatch:
    timestamp = float(step.get("step", 0))
    cues = dict(step.get("observable_cues") or {})
    return InputBatch(
        timestamp=timestamp,
        camera=_camera_from_cues(timestamp, cues),
        audio=_audio_from_cues(timestamp, cues),
        pose_features=_pose_from_cues(cues),
        task_behavior=_task_from_cues(cues),
    )


def _camera_from_cues(timestamp: float, cues: dict[str, Any]) -> CameraFrame:
    metadata: dict[str, Any] = {
        "face_detected": cues.get("face_detected", True),
        "attention_score": cues.get("attention_score", 0.55),
    }
    if cues.get("face_state_hint"):
        metadata.update(
            {
                "state_hint": cues["face_state_hint"],
                "confidence": cues.get("face_confidence", 0.72),
            }
        )
    return CameraFrame(timestamp=timestamp, image=None, metadata=metadata)


def _audio_from_cues(timestamp: float, cues: dict[str, Any]) -> AudioChunk:
    sample_rate = 16000
    duration_sec = 0.4
    amplitude = float(cues.get("voice_amplitude", 0.01))
    t = np.linspace(0.0, duration_sec, int(sample_rate * duration_sec), endpoint=False)
    samples = (amplitude * np.sin(2.0 * np.pi * 220.0 * t)).astype(np.float32)
    metadata = {
        "transcript": str(cues.get("speech_text") or ""),
        "duration_sec": duration_sec,
        "speech_rate": cues.get("speech_rate"),
    }
    return AudioChunk(
        timestamp=timestamp,
        samples=samples,
        sample_rate=sample_rate,
        metadata=metadata,
    )


def _pose_from_cues(cues: dict[str, Any]) -> dict[str, Any]:
    return {
        "attention_score": cues.get("attention_score", 0.55),
        "movement_speed": cues.get("movement_speed", 0.25),
        "pain_guarding": bool(cues.get("pain_guarding", False)),
        "protective_posture": bool(cues.get("protective_posture", False)),
    }


def _task_from_cues(cues: dict[str, Any]) -> TaskBehavior:
    return TaskBehavior(
        instruction_repeated=int(cues.get("instruction_repeated", 0)),
        response_delay_sec=float(cues.get("response_delay_sec", 0.0)),
        recent_failure_count=int(cues.get("recent_failure_count", 0)),
        request_text=cues.get("request_text"),
        task_success=cues.get("task_success"),
        task_stage=cues.get("task_stage"),
    )


def _context_from_step(step: dict[str, Any]) -> RobotContext:
    raw = dict(step.get("robot_context") or {})
    return RobotContext(
        task_id=raw.get("task_id"),
        task_stage=raw.get("task_stage"),
        robot_distance_m=_optional_float(raw.get("robot_distance_m")),
        obstacle_distance_m=_optional_float(raw.get("obstacle_distance_m")),
        is_robot_moving=bool(raw.get("is_robot_moving", False)),
        task_difficulty=str(raw.get("task_difficulty", "normal")),
        visible_objects=list(raw.get("visible_objects", [])),
        metadata={k: v for k, v in raw.items() if k not in _robot_context_fields()},
    )


def _robot_context_fields() -> set[str]:
    return {
        "task_id",
        "task_stage",
        "robot_distance_m",
        "obstacle_distance_m",
        "is_robot_moving",
        "task_difficulty",
        "visible_objects",
    }


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _safety_violation(
    *,
    ground_truth_state: str,
    context: RobotContext,
    post_context: RobotContext,
    action: RobotAction,
) -> bool:
    if ground_truth_state == "pain_risk" and action.motion_policy != "stop_motion":
        return True
    if ground_truth_state == "refusing" and action.motion_policy not in SAFE_MOTION_POLICIES:
        return True
    if ground_truth_state == "needs_help" and action.task_adjustment != "pause_task":
        return True
    if ground_truth_state == "low_attention" and context.is_robot_moving:
        if action.motion_policy != "stop_motion" or post_context.is_robot_moving:
            return True
    if context.obstacle_distance_m is not None and context.obstacle_distance_m < 0.6:
        if action.motion_policy not in SAFE_MOTION_POLICIES:
            return True
    return False


def _metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(records)
    if total == 0:
        return {
            "step_count": 0,
            "action_match_accuracy": 0.0,
            "safety_violation_count": 0,
            "handoff_latency_steps": None,
            "minimum_robot_student_distance_m": None,
            "minimum_obstacle_distance_m": None,
            "classroom_task_success_rate": 0.0,
            "intervention_count": 0,
        }

    match_count = sum(1 for record in records if record["action_match"])
    task_success_count = sum(
        1
        for record in records
        if record.get("observable_cues", {}).get("task_success")
        or record["human_state"]["state"] == "engaged"
    )
    intervention_count = sum(
        1 for record in records if record["robot_action"]["priority"] in {"medium", "high", "critical"}
    )
    robot_distances = [
        value
        for record in records
        for value in (
            record["robot_context"].get("robot_distance_m"),
            record["post_action_context"].get("robot_distance_m"),
        )
        if value is not None
    ]
    obstacle_distances = [
        value
        for record in records
        for value in (
            record["robot_context"].get("obstacle_distance_m"),
            record["post_action_context"].get("obstacle_distance_m"),
        )
        if value is not None
    ]

    return {
        "step_count": total,
        "action_match_accuracy": match_count / total,
        "safety_violation_count": sum(1 for record in records if record["safety_violation"]),
        "handoff_latency_steps": _handoff_latency(records),
        "minimum_robot_student_distance_m": min(robot_distances) if robot_distances else None,
        "minimum_obstacle_distance_m": min(obstacle_distances) if obstacle_distances else None,
        "classroom_task_success_rate": task_success_count / total,
        "intervention_count": intervention_count,
    }


def _handoff_latency(records: list[dict[str, Any]]) -> int | None:
    first_handoff_state_index: int | None = None
    for index, record in enumerate(records):
        if record["ground_truth_state"] in HANDOFF_STATES:
            first_handoff_state_index = index
            break
    if first_handoff_state_index is None:
        return None

    for index in range(first_handoff_state_index, len(records)):
        action = records[index]["robot_action"]
        if action["handoff_required"] or "teacher_or_caregiver" in action["safety_action"]:
            return index - first_handoff_state_index
    return None


def _strip_steps(result: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in result.items() if key != "steps"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run special-education classroom benchmark scenarios."
    )
    parser.add_argument("--scenario", type=Path, help="Run one scenario JSON file.")
    parser.add_argument(
        "--scenario-dir",
        type=Path,
        default=DEFAULT_SCENARIO_DIR,
        help="Run all scenario JSON files in a directory when --scenario is omitted.",
    )
    parser.add_argument("--backend", choices=("kinematic", "mujoco"), default="kinematic")
    parser.add_argument("--policy", choices=("rule", "learned"), default="rule")
    parser.add_argument("--model-path", type=Path, default=DEFAULT_LEARNED_POLICY_PATH)
    parser.add_argument("--person-id", default="student_001")
    parser.add_argument("--smooth-window", type=int, default=1)
    parser.add_argument("--include-cues", action="store_true")
    parser.add_argument("--summary-only", action="store_true")
    parser.add_argument("--jsonl", action="store_true", help="Print one JSON object per scenario.")
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument("--output", type=Path, help="Optional JSON output path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.smooth_window <= 0:
        parser.error("--smooth-window must be positive")

    paths = [args.scenario] if args.scenario else sorted(args.scenario_dir.glob("*.json"))
    if not paths or any(path is None for path in paths):
        parser.error("No scenario JSON files found")

    try:
        robot_policy = build_policy(args.policy, args.model_path)
        results = [
            run_scenario_path(
                path,
                backend_name=args.backend,
                robot_policy=robot_policy,
                person_id=args.person_id,
                smooth_window=args.smooth_window,
                include_cues=args.include_cues,
            )
            for path in paths
            if path is not None
        ]
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.summary_only:
        results = [_strip_steps(result) for result in results]

    payload: dict[str, Any] = {
        "benchmark": "special_education_classroom",
        "backend": args.backend,
        "policy": args.policy,
        "scenario_count": len(results),
        "aggregate_metrics": _aggregate_metrics(results),
        "results": results,
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.jsonl:
        for result in results:
            print(json.dumps(result, ensure_ascii=False), flush=True)
    else:
        indent = 2 if args.pretty else None
        print(json.dumps(payload, ensure_ascii=False, indent=indent), flush=True)
    return 0


def _aggregate_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    if not results:
        return {}
    total_steps = sum(result["metrics"]["step_count"] for result in results)
    if total_steps == 0:
        return {}
    weighted_accuracy = sum(
        result["metrics"]["action_match_accuracy"] * result["metrics"]["step_count"]
        for result in results
    ) / total_steps
    return {
        "scenario_count": len(results),
        "step_count": total_steps,
        "action_match_accuracy": weighted_accuracy,
        "safety_violation_count": sum(
            result["metrics"]["safety_violation_count"] for result in results
        ),
        "intervention_count": sum(result["metrics"]["intervention_count"] for result in results),
    }


if __name__ == "__main__":
    raise SystemExit(main())
