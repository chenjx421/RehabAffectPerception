from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

from .pipeline import RehabAffectPipeline
from .schema import RobotAction, RobotContext
from .sim_runner import (
    DEFAULT_LEARNED_POLICY_PATH,
    DEFAULT_SCENARIO_DIR,
    HANDOFF_STATES,
    KinematicClassroomBackend,
    _batch_from_step,
    _build_backend,
    _context_from_step,
    _optional_float,
    _policy_name,
    _safety_violation,
    build_policy,
    load_scenario,
)


RECOVERY_STATES = {"engaged", "neutral"}
CHALLENGE_STATES = {
    "confused",
    "fatigued",
    "frustrated",
    "refusing",
    "low_attention",
    "needs_help",
}


def run_closed_loop_scenario(
    scenario: dict[str, Any],
    *,
    backend: KinematicClassroomBackend | None = None,
    robot_policy: Any | None = None,
    person_id: str = "student_001",
    smooth_window: int = 1,
    include_base_steps: bool = False,
) -> dict[str, Any]:
    """Run a scenario where each robot action influences the next step.

    The ordinary benchmark evaluates each scripted step independently. This
    runner keeps the same perception and policy stack, then feeds embodied
    action effects back into the next step's cues and robot context.
    """

    backend = backend or KinematicClassroomBackend()
    pipeline = RehabAffectPipeline(
        person_id=person_id,
        smooth_window=smooth_window,
        robot_policy=robot_policy,
    )
    records: list[dict[str, Any]] = []
    pending_patch: dict[str, Any] = {}

    for index, base_step in enumerate(scenario.get("steps", [])):
        adapted_step = apply_feedback_patch(base_step, pending_patch)
        adapted_step["step"] = base_step.get("step", index)

        context = _context_from_step(adapted_step)
        result = pipeline.process_batch(
            _batch_from_step(adapted_step),
            robot_context=context,
        )
        post_context = backend.apply_action(context, result.robot_action)
        feedback = build_embodied_feedback(
            step=adapted_step,
            base_step=base_step,
            context=context,
            post_context=post_context,
            action=result.robot_action,
        )
        pending_patch = feedback["next_step_patch"]

        record: dict[str, Any] = {
            "step": adapted_step.get("step", index),
            "base_ground_truth_state": base_step.get("ground_truth_state"),
            "ground_truth_state": adapted_step.get("ground_truth_state"),
            "expected_action_id": adapted_step.get("expected_action_id"),
            "feedback_applied": bool(pending_patch) if index < len(scenario.get("steps", [])) - 1 else False,
            "human_state": result.human_state.to_dict(),
            "robot_context": context.to_dict(),
            "robot_action": result.robot_action.to_dict(),
            "post_action_context": post_context.to_dict(),
            "embodied_feedback": feedback,
            "action_match": result.robot_action.action_id == adapted_step.get("expected_action_id"),
            "safety_violation": _safety_violation(
                ground_truth_state=str(adapted_step.get("ground_truth_state") or ""),
                context=context,
                post_context=post_context,
                action=result.robot_action,
            ),
        }
        if include_base_steps:
            record["base_step"] = base_step
            record["adapted_step"] = adapted_step
        records.append(record)

    return {
        "scenario_id": scenario.get("scenario_id"),
        "task": scenario.get("task"),
        "description": scenario.get("description"),
        "backend": backend.name,
        "policy": _policy_name(robot_policy),
        "closed_loop": True,
        "metrics": closed_loop_metrics(records),
        "steps": records,
    }


def run_closed_loop_path(
    path: Path,
    *,
    backend_name: str = "kinematic",
    robot_policy: Any | None = None,
    person_id: str = "student_001",
    smooth_window: int = 1,
    include_base_steps: bool = False,
) -> dict[str, Any]:
    return run_closed_loop_scenario(
        load_scenario(path),
        backend=_build_backend(backend_name),
        robot_policy=robot_policy,
        person_id=person_id,
        smooth_window=smooth_window,
        include_base_steps=include_base_steps,
    )


def apply_feedback_patch(base_step: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    step = copy.deepcopy(base_step)
    if not patch:
        return step

    cue_patch = patch.get("observable_cues", {})
    context_patch = patch.get("robot_context", {})
    cues = step.setdefault("observable_cues", {})
    context = step.setdefault("robot_context", {})
    cues.update(cue_patch)
    context.update(context_patch)

    for key in ("ground_truth_state", "expected_action_id"):
        if key in patch:
            step[key] = patch[key]
    return step


def build_embodied_feedback(
    *,
    step: dict[str, Any],
    base_step: dict[str, Any],
    context: RobotContext,
    post_context: RobotContext,
    action: RobotAction,
) -> dict[str, Any]:
    action_id = action.action_id
    cues = dict(step.get("observable_cues") or {})
    patch = _base_next_patch(step, post_context)
    outcome = "monitor"
    effect_tags: list[str] = []

    if action_id == "repeat_instruction_slowly":
        outcome = "instruction_clarified"
        effect_tags.extend(["reduce_confusion", "task_recovery"])
        patch["ground_truth_state"] = "engaged"
        patch["expected_action_id"] = "continue_and_encourage"
        patch["observable_cues"].update(
            {
                "speech_text": "我懂一点了，慢慢来",
                "face_state_hint": "engaged",
                "attention_score": _raise(cues.get("attention_score"), 0.18, minimum=0.72),
                "movement_speed": _raise(cues.get("movement_speed"), 0.18, minimum=0.24),
                "instruction_repeated": max(0, int(cues.get("instruction_repeated", 0)) - 1),
                "response_delay_sec": max(0.6, float(cues.get("response_delay_sec", 0.0)) - 2.0),
                "recent_failure_count": max(0, int(cues.get("recent_failure_count", 0)) - 1),
                "task_success": True,
                "task_stage": "guided_retry",
            }
        )
        patch["robot_context"].update({"task_stage": "guided_retry"})

    elif action_id == "regain_attention":
        outcome = "attention_regained"
        effect_tags.extend(["attention_recovery", "motion_safety"])
        patch["ground_truth_state"] = "engaged"
        patch["expected_action_id"] = "continue_and_encourage"
        patch["observable_cues"].update(
            {
                "speech_text": "我看到了",
                "face_state_hint": "engaged",
                "attention_score": _raise(cues.get("attention_score"), 0.25, minimum=0.74),
                "movement_speed": _raise(cues.get("movement_speed"), 0.14, minimum=0.26),
                "response_delay_sec": max(0.8, float(cues.get("response_delay_sec", 0.0)) - 2.0),
                "task_success": True,
                "task_stage": "attention_confirmed",
            }
        )
        patch["robot_context"].update({"is_robot_moving": False, "task_stage": "attention_confirmed"})

    elif action_id == "reduce_task_load_and_offer_break":
        outcome = "load_reduced"
        effect_tags.extend(["difficulty_reduced", "fatigue_recovery"])
        patch["ground_truth_state"] = "engaged"
        patch["expected_action_id"] = "continue_and_encourage"
        patch["observable_cues"].update(
            {
                "speech_text": "可以继续了",
                "face_state_hint": "engaged",
                "attention_score": _raise(cues.get("attention_score"), 0.18, minimum=0.68),
                "movement_speed": _raise(cues.get("movement_speed"), 0.12, minimum=0.22),
                "response_delay_sec": max(1.0, float(cues.get("response_delay_sec", 0.0)) - 1.8),
                "recent_failure_count": max(0, int(cues.get("recent_failure_count", 0)) - 1),
                "task_success": True,
                "task_stage": "reduced_load_retry",
            }
        )
        patch["robot_context"].update({"task_difficulty": "easy", "task_stage": "reduced_load_retry"})

    elif action_id == "pause_and_reduce_pressure":
        outcome = "pressure_reduced"
        effect_tags.extend(["deescalation", "task_recovery"])
        patch["ground_truth_state"] = "neutral"
        patch["expected_action_id"] = "continue_current_plan"
        patch["observable_cues"].update(
            {
                "speech_text": "我先缓一下",
                "face_state_hint": "neutral",
                "attention_score": _raise(cues.get("attention_score"), 0.14, minimum=0.58),
                "movement_speed": _raise(cues.get("movement_speed"), 0.08, minimum=0.18),
                "response_delay_sec": max(1.2, float(cues.get("response_delay_sec", 0.0)) - 1.5),
                "recent_failure_count": max(0, int(cues.get("recent_failure_count", 0)) - 1),
                "task_stage": "pressure_reduced",
            }
        )
        patch["robot_context"].update({"task_stage": "pressure_reduced"})

    elif action_id == "pause_and_request_consent":
        outcome = "consent_respected"
        effect_tags.extend(["consent_respected", "personal_space"])
        patch["ground_truth_state"] = "refusing"
        patch["expected_action_id"] = "pause_and_request_consent"
        patch["observable_cues"].update(
            {
                "speech_text": "我想先停一下",
                "face_state_hint": "refusing",
                "attention_score": _raise(cues.get("attention_score"), 0.08, minimum=0.44),
                "movement_speed": min(0.08, float(cues.get("movement_speed", 0.05))),
                "task_success": False,
                "task_stage": "paused_for_consent",
            }
        )
        patch["robot_context"].update(
            {
                "is_robot_moving": False,
                "robot_distance_m": _raise(post_context.robot_distance_m, 0.15, minimum=0.95),
                "task_stage": "paused_for_consent",
            }
        )

    elif action_id == "stop_and_check_pain_risk":
        outcome = "risk_contained"
        effect_tags.extend(["risk_containment", "handoff"])
        patch["ground_truth_state"] = "pain_risk"
        patch["expected_action_id"] = "stop_and_check_pain_risk"
        patch["observable_cues"].update(
            {
                "speech_text": "我先停一下，需要老师确认",
                "face_state_hint": "pain_risk",
                "attention_score": _raise(cues.get("attention_score"), 0.06, minimum=0.38),
                "movement_speed": min(0.04, float(cues.get("movement_speed", 0.04))),
                "pain_guarding": True,
                "task_success": False,
                "task_stage": "safety_check",
            }
        )
        patch["robot_context"].update(
            {
                "is_robot_moving": False,
                "task_stage": "safety_check",
                "visible_objects": _with_teacher(step),
            }
        )

    elif action_id == "offer_help":
        outcome = "help_handoff_started"
        effect_tags.extend(["help_offered", "handoff"])
        patch["ground_truth_state"] = "needs_help"
        patch["expected_action_id"] = "offer_help"
        patch["observable_cues"].update(
            {
                "speech_text": "请老师帮我一下",
                "face_state_hint": "needs_help",
                "attention_score": _raise(cues.get("attention_score"), 0.10, minimum=0.52),
                "movement_speed": min(0.12, float(cues.get("movement_speed", 0.10))),
                "task_success": False,
                "task_stage": "help_handoff",
            }
        )
        patch["robot_context"].update({"is_robot_moving": False, "task_stage": "help_handoff"})

    elif action_id == "continue_and_encourage":
        outcome = "task_progressed"
        effect_tags.extend(["positive_feedback", "task_progress"])
        patch["observable_cues"].update(
            {
                "attention_score": _raise(cues.get("attention_score"), 0.04, minimum=0.66),
                "task_success": True,
            }
        )

    patch["metadata"] = {
        "from_action_id": action_id,
        "outcome": outcome,
        "effect_tags": effect_tags,
    }
    return {
        "outcome": outcome,
        "effect_tags": effect_tags,
        "next_step_patch": patch,
        "risk_contained": outcome == "risk_contained"
        and post_context.is_robot_moving is False
        and action.handoff_required,
        "distance_delta_m": _distance_delta(context, post_context),
        "base_state": base_step.get("ground_truth_state"),
        "adapted_state": step.get("ground_truth_state"),
    }


def _base_next_patch(step: dict[str, Any], post_context: RobotContext) -> dict[str, Any]:
    post = post_context.to_dict()
    return {
        "observable_cues": {},
        "robot_context": {
            "task_id": post.get("task_id"),
            "task_stage": post.get("task_stage"),
            "robot_distance_m": post.get("robot_distance_m"),
            "obstacle_distance_m": post.get("obstacle_distance_m"),
            "is_robot_moving": post.get("is_robot_moving", False),
            "task_difficulty": post.get("task_difficulty", "normal"),
            "visible_objects": post.get("visible_objects", []),
        },
    }


def _raise(value: Any, delta: float, *, minimum: float) -> float:
    base = _optional_float(value)
    if base is None:
        base = minimum
    return round(min(1.0, max(minimum, base + delta)), 3)


def _with_teacher(step: dict[str, Any]) -> list[str]:
    context = step.get("robot_context") or {}
    objects = list(context.get("visible_objects") or [])
    if "teacher" not in objects:
        objects.append("teacher")
    return objects


def _distance_delta(context: RobotContext, post_context: RobotContext) -> float | None:
    if context.robot_distance_m is None or post_context.robot_distance_m is None:
        return None
    return round(post_context.robot_distance_m - context.robot_distance_m, 3)


def closed_loop_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(records)
    if total == 0:
        return {
            "step_count": 0,
            "action_match_accuracy": 0.0,
            "safety_violation_count": 0,
            "recovery_count": 0,
            "risk_containment_count": 0,
            "consent_respected_count": 0,
            "forced_motion_stop_count": 0,
            "difficulty_reduction_count": 0,
            "closed_loop_score": 0.0,
        }

    action_matches = sum(1 for record in records if record["action_match"])
    safety_violations = sum(1 for record in records if record["safety_violation"])
    recovery_count = sum(1 for record in records if _is_recovery(record))
    risk_containment_count = sum(
        1 for record in records if record["embodied_feedback"].get("risk_contained")
    )
    consent_respected_count = sum(
        1
        for record in records
        if "consent_respected" in record["embodied_feedback"].get("effect_tags", [])
    )
    forced_motion_stop_count = sum(
        1
        for record in records
        if record["robot_context"].get("is_robot_moving")
        and record["post_action_context"].get("is_robot_moving") is False
    )
    difficulty_reduction_count = sum(
        1
        for record in records
        if "difficulty_reduced" in record["embodied_feedback"].get("effect_tags", [])
    )
    task_success_count = sum(
        1
        for record in records
        if record["human_state"]["state"] in RECOVERY_STATES
        or record["embodied_feedback"]["outcome"] in {"task_progressed", "instruction_clarified"}
    )
    handoff_latency = _closed_loop_handoff_latency(records)
    closed_loop_score = _closed_loop_score(
        action_matches=action_matches,
        safety_violations=safety_violations,
        recovery_count=recovery_count,
        task_success_count=task_success_count,
        total=total,
    )

    return {
        "step_count": total,
        "action_match_accuracy": action_matches / total,
        "safety_violation_count": safety_violations,
        "recovery_count": recovery_count,
        "recovery_rate": recovery_count / max(1, _challenge_count(records)),
        "risk_containment_count": risk_containment_count,
        "consent_respected_count": consent_respected_count,
        "forced_motion_stop_count": forced_motion_stop_count,
        "difficulty_reduction_count": difficulty_reduction_count,
        "classroom_task_success_rate": task_success_count / total,
        "handoff_latency_steps": handoff_latency,
        "closed_loop_score": closed_loop_score,
    }


def _is_recovery(record: dict[str, Any]) -> bool:
    base_state = record.get("base_ground_truth_state")
    human_state = record["human_state"]["state"]
    return base_state in CHALLENGE_STATES and human_state in RECOVERY_STATES


def _challenge_count(records: list[dict[str, Any]]) -> int:
    return sum(1 for record in records if record.get("base_ground_truth_state") in CHALLENGE_STATES)


def _closed_loop_handoff_latency(records: list[dict[str, Any]]) -> int | None:
    first_handoff_state_index: int | None = None
    for index, record in enumerate(records):
        if record.get("ground_truth_state") in HANDOFF_STATES:
            first_handoff_state_index = index
            break
    if first_handoff_state_index is None:
        return None
    for index in range(first_handoff_state_index, len(records)):
        action = records[index]["robot_action"]
        if action["handoff_required"] or "teacher_or_caregiver" in action["safety_action"]:
            return index - first_handoff_state_index
    return None


def _closed_loop_score(
    *,
    action_matches: int,
    safety_violations: int,
    recovery_count: int,
    task_success_count: int,
    total: int,
) -> float:
    action_score = action_matches / total
    safety_score = 1.0 if safety_violations == 0 else max(0.0, 1.0 - safety_violations / total)
    recovery_score = min(1.0, recovery_count / max(1, total // 2))
    task_score = task_success_count / total
    return round(100.0 * (0.35 * action_score + 0.35 * safety_score + 0.15 * recovery_score + 0.15 * task_score), 2)


def aggregate_closed_loop_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    if not results:
        return {}
    total_steps = sum(result["metrics"]["step_count"] for result in results)
    if total_steps == 0:
        return {}

    def weighted_average(metric: str) -> float:
        return sum(
            result["metrics"][metric] * result["metrics"]["step_count"]
            for result in results
        ) / total_steps

    return {
        "scenario_count": len(results),
        "step_count": total_steps,
        "action_match_accuracy": weighted_average("action_match_accuracy"),
        "classroom_task_success_rate": weighted_average("classroom_task_success_rate"),
        "recovery_rate": weighted_average("recovery_rate"),
        "mean_closed_loop_score": weighted_average("closed_loop_score"),
        "safety_violation_count": sum(result["metrics"]["safety_violation_count"] for result in results),
        "recovery_count": sum(result["metrics"]["recovery_count"] for result in results),
        "risk_containment_count": sum(result["metrics"]["risk_containment_count"] for result in results),
        "consent_respected_count": sum(result["metrics"]["consent_respected_count"] for result in results),
        "forced_motion_stop_count": sum(result["metrics"]["forced_motion_stop_count"] for result in results),
        "difficulty_reduction_count": sum(result["metrics"]["difficulty_reduction_count"] for result in results),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run closed-loop embodied classroom benchmark scenarios.")
    parser.add_argument("--scenario", type=Path, help="Run one scenario JSON file.")
    parser.add_argument("--scenario-dir", type=Path, default=DEFAULT_SCENARIO_DIR)
    parser.add_argument("--backend", choices=("kinematic", "mujoco"), default="kinematic")
    parser.add_argument("--policy", choices=("rule", "learned"), default="rule")
    parser.add_argument("--model-path", type=Path, default=DEFAULT_LEARNED_POLICY_PATH)
    parser.add_argument("--person-id", default="student_001")
    parser.add_argument("--smooth-window", type=int, default=1)
    parser.add_argument("--include-base-steps", action="store_true")
    parser.add_argument("--summary-only", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = [args.scenario] if args.scenario else sorted(args.scenario_dir.glob("*.json"))
    if not paths or any(path is None for path in paths):
        print("No scenario JSON files found", file=sys.stderr)
        return 2

    try:
        robot_policy = build_policy(args.policy, args.model_path)
        results = [
            run_closed_loop_path(
                path,
                backend_name=args.backend,
                robot_policy=robot_policy,
                person_id=args.person_id,
                smooth_window=args.smooth_window,
                include_base_steps=args.include_base_steps,
            )
            for path in paths
            if path is not None
        ]
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.summary_only:
        results = [{key: value for key, value in result.items() if key != "steps"} for result in results]

    payload = {
        "benchmark": "special_education_classroom_closed_loop",
        "backend": args.backend,
        "policy": args.policy,
        "scenario_count": len(results),
        "aggregate_metrics": aggregate_closed_loop_results(results),
        "results": results,
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(payload, ensure_ascii=False, indent=2 if args.pretty else None), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
