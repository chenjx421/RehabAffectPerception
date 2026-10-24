from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from .sim_runner import (
    DEFAULT_LEARNED_POLICY_PATH,
    DEFAULT_SCENARIO_DIR,
    _aggregate_metrics,
    build_policy,
    run_scenario_path,
)


def build_benchmark_messages(
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
    results = [
        run_scenario_path(
            path,
            backend_name=backend,
            robot_policy=robot_policy,
            smooth_window=smooth_window,
            include_cues=True,
        )
        for path in scenario_paths
    ]

    messages: list[dict[str, Any]] = []
    for result in results:
        for step in result["steps"]:
            messages.append(
                {
                    "type": "perception_decision",
                    "scenario_id": result["scenario_id"],
                    "step": step["step"],
                    "payload": {
                        "human_state": step["human_state"],
                        "robot_context": step["robot_context"],
                        "robot_action": step["robot_action"],
                        "post_action_context": step["post_action_context"],
                        "action_match": step["action_match"],
                        "safety_violation": step["safety_violation"],
                    },
                }
            )

    messages.append(
        {
            "type": "benchmark_summary",
            "payload": {
                "benchmark": "special_education_classroom",
                "backend": backend,
                "policy": policy_name,
                "scenario_count": len(results),
                "aggregate_metrics": _aggregate_metrics(results),
            },
        }
    )
    return messages


async def serve_messages(
    *,
    host: str,
    port: int,
    messages: list[dict[str, Any]],
    interval_sec: float,
    once: bool = False,
) -> None:
    try:
        import websockets
    except ImportError as exc:
        raise RuntimeError(
            "websockets is required. Install it with: pip install -e .[websocket]"
        ) from exc

    stop_event = asyncio.Event()

    async def handler(websocket: Any, *_args: Any) -> None:
        await websocket.send(
            json.dumps(
                {
                    "type": "server_ready",
                    "payload": {
                        "message_count": len(messages),
                        "stream": "rehab_affect_perception_decision",
                    },
                },
                ensure_ascii=False,
            )
        )
        for message in messages:
            await websocket.send(json.dumps(message, ensure_ascii=False))
            if interval_sec > 0:
                await asyncio.sleep(interval_sec)
        if once:
            stop_event.set()

    async with websockets.serve(handler, host, port):
        print(f"WebSocket server running at ws://{host}:{port}/rehab_affect", flush=True)
        if once:
            await stop_event.wait()
        else:
            await asyncio.Future()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Stream human_state and robot_action benchmark events over WebSocket."
    )
    parser.add_argument("--scenario-dir", type=Path, default=DEFAULT_SCENARIO_DIR)
    parser.add_argument("--backend", choices=("kinematic", "mujoco"), default="kinematic")
    parser.add_argument("--policy", choices=("rule", "learned"), default="rule")
    parser.add_argument("--model-path", type=Path, default=DEFAULT_LEARNED_POLICY_PATH)
    parser.add_argument("--smooth-window", type=int, default=1)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--interval-sec", type=float, default=0.2)
    parser.add_argument("--once", action="store_true", help="Exit after streaming to one client.")
    parser.add_argument("--dump-jsonl", action="store_true", help="Print messages without serving.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.smooth_window <= 0:
        raise SystemExit("--smooth-window must be positive")
    if args.interval_sec < 0:
        raise SystemExit("--interval-sec must be non-negative")

    try:
        messages = build_benchmark_messages(
            scenario_dir=args.scenario_dir,
            backend=args.backend,
            policy_name=args.policy,
            model_path=args.model_path,
            smooth_window=args.smooth_window,
        )
        if args.dump_jsonl:
            for message in messages:
                print(json.dumps(message, ensure_ascii=False), flush=True)
            return 0
        asyncio.run(
            serve_messages(
                host=args.host,
                port=args.port,
                messages=messages,
                interval_sec=args.interval_sec,
                once=args.once,
            )
        )
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
