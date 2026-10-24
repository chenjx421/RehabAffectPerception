from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .sim_runner import (
    DEFAULT_LEARNED_POLICY_PATH,
    DEFAULT_SCENARIO_DIR,
    build_policy,
    run_scenario_path,
)


HUMAN_STATE_TOPIC = "/rehab_affect/human_state"
ROBOT_ACTION_TOPIC = "/rehab_affect/robot_action"


def build_ros2_mock_messages(
    *,
    scenario_dir: Path = DEFAULT_SCENARIO_DIR,
    backend: str = "kinematic",
    policy_name: str = "rule",
    model_path: Path = DEFAULT_LEARNED_POLICY_PATH,
    smooth_window: int = 1,
) -> list[dict[str, Any]]:
    scenario_paths = sorted(scenario_dir.glob("*.json"))
    if not scenario_paths:
        raise RuntimeError(f"No scenario JSON files found in {scenario_dir}")

    robot_policy = build_policy(policy_name, model_path)
    messages: list[dict[str, Any]] = []
    for path in scenario_paths:
        result = run_scenario_path(
            path,
            backend_name=backend,
            robot_policy=robot_policy,
            smooth_window=smooth_window,
            include_cues=True,
        )
        for step in result["steps"]:
            base = {
                "scenario_id": result["scenario_id"],
                "step": step["step"],
                "backend": backend,
                "policy": result["policy"],
            }
            messages.append(
                {
                    **base,
                    "topic": HUMAN_STATE_TOPIC,
                    "msg_type": "std_msgs/msg/String",
                    "data": json.dumps(step["human_state"], ensure_ascii=False),
                }
            )
            messages.append(
                {
                    **base,
                    "topic": ROBOT_ACTION_TOPIC,
                    "msg_type": "std_msgs/msg/String",
                    "data": json.dumps(step["robot_action"], ensure_ascii=False),
                }
            )
    return messages


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Print ROS2-style std_msgs/String JSONL messages for local integration demos."
    )
    parser.add_argument("--scenario-dir", type=Path, default=DEFAULT_SCENARIO_DIR)
    parser.add_argument("--backend", choices=("kinematic", "mujoco"), default="kinematic")
    parser.add_argument("--policy", choices=("rule", "learned"), default="rule")
    parser.add_argument("--model-path", type=Path, default=DEFAULT_LEARNED_POLICY_PATH)
    parser.add_argument("--smooth-window", type=int, default=1)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.smooth_window <= 0:
        raise SystemExit("--smooth-window must be positive")

    messages = build_ros2_mock_messages(
        scenario_dir=args.scenario_dir,
        backend=args.backend,
        policy_name=args.policy,
        model_path=args.model_path,
        smooth_window=args.smooth_window,
    )
    lines = [
        json.dumps(message, ensure_ascii=False, indent=2 if args.pretty else None)
        for message in messages
    ]
    text = "\n".join(lines) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
