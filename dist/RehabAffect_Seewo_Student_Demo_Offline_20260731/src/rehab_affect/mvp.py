from __future__ import annotations

import argparse
import json
import sys
from time import sleep

from .inputs import (
    CameraInput,
    LiveInputSource,
    MicrophoneInput,
    MockInputSource,
    OptionalDependencyError,
    TaskBehavior,
)
from .pipeline import RehabAffectPipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the RehabAffectPerception MVP pipeline and print human_state JSON."
    )
    parser.add_argument("--mode", choices=("mock", "live"), default="mock")
    parser.add_argument("--person-id", default="user_001")
    parser.add_argument("--steps", type=int, default=10, help="Number of batches to process.")
    parser.add_argument("--forever", action="store_true", help="Run until interrupted.")
    parser.add_argument("--interval-sec", type=float, default=0.2)
    parser.add_argument("--smooth-window", type=int, default=3)
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument("--include-signals", action="store_true")
    parser.add_argument("--seed", type=int, default=42)

    parser.add_argument("--camera", action="store_true", help="Use camera in live mode.")
    parser.add_argument("--microphone", action="store_true", help="Use microphone in live mode.")
    parser.add_argument("--camera-index", type=int, default=0)
    parser.add_argument("--width", type=int)
    parser.add_argument("--height", type=int)
    parser.add_argument("--audio-duration-sec", type=float, default=0.8)
    parser.add_argument("--sample-rate", type=int, default=16000)
    parser.add_argument("--audio-device")

    parser.add_argument("--instruction-repeated", type=int, default=0)
    parser.add_argument("--response-delay-sec", type=float, default=0.0)
    parser.add_argument("--recent-failure-count", type=int, default=0)
    parser.add_argument("--request-text")
    parser.add_argument("--task-stage")
    return parser


def build_source(args: argparse.Namespace):
    if args.mode == "mock":
        return MockInputSource(seed=args.seed)

    use_camera = args.camera or not args.microphone
    use_microphone = args.microphone or not args.camera
    camera = (
        CameraInput(camera_index=args.camera_index, width=args.width, height=args.height)
        if use_camera
        else None
    )
    microphone = (
        MicrophoneInput(
            duration_sec=args.audio_duration_sec,
            sample_rate=args.sample_rate,
            device=args.audio_device,
        )
        if use_microphone
        else None
    )
    task_behavior = TaskBehavior(
        instruction_repeated=args.instruction_repeated,
        response_delay_sec=args.response_delay_sec,
        recent_failure_count=args.recent_failure_count,
        request_text=args.request_text,
        task_stage=args.task_stage,
    )
    return LiveInputSource(camera=camera, microphone=microphone, task_behavior=task_behavior)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.steps <= 0 and not args.forever:
        parser.error("--steps must be positive unless --forever is set")
    if args.interval_sec < 0:
        parser.error("--interval-sec must be non-negative")

    pipeline = RehabAffectPipeline(person_id=args.person_id, smooth_window=args.smooth_window)
    source = build_source(args)

    try:
        source.open()
        step = 0
        while args.forever or step < args.steps:
            batch = source.read()
            result = pipeline.process_batch(batch)
            payload = result.to_dict(include_signals=args.include_signals)
            if args.pretty:
                print(json.dumps({"step": step, **payload}, ensure_ascii=False, indent=2), flush=True)
            else:
                print(json.dumps({"step": step, **payload}, ensure_ascii=False), flush=True)
            step += 1
            if args.interval_sec:
                sleep(args.interval_sec)
    except KeyboardInterrupt:
        return 130
    except OptionalDependencyError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    finally:
        source.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
