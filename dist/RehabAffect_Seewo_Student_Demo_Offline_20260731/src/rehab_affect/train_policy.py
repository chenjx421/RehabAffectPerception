from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

from .learned_policy import LearnedSchoolPolicy, featurize, feature_names
from .pipeline import RehabAffectPipeline
from .scenario_randomizer import generate_augmented_scenarios
from .sim_runner import (
    DEFAULT_LEARNED_POLICY_PATH,
    DEFAULT_SCENARIO_DIR,
    _aggregate_metrics,
    _batch_from_step,
    _build_backend,
    _context_from_step,
    load_scenario,
    run_scenario,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_METRICS_OUTPUT = PROJECT_ROOT / "data" / "processed" / "learned_policy_metrics.json"


def collect_training_rows(
    scenario_paths: list[Path],
    *,
    person_id: str = "student_001",
    smooth_window: int = 1,
) -> tuple[list[np.ndarray], list[str], list[dict[str, Any]]]:
    return collect_training_rows_from_scenarios(
        [load_scenario(path) for path in scenario_paths],
        person_id=person_id,
        smooth_window=smooth_window,
    )


def collect_training_rows_from_scenarios(
    scenarios: list[dict[str, Any]],
    *,
    person_id: str = "student_001",
    smooth_window: int = 1,
) -> tuple[list[np.ndarray], list[str], list[dict[str, Any]]]:
    rows: list[np.ndarray] = []
    labels: list[str] = []
    metadata: list[dict[str, Any]] = []

    for scenario in scenarios:
        pipeline = RehabAffectPipeline(person_id=person_id, smooth_window=smooth_window)
        for step in scenario.get("steps", []):
            expected_action_id = step.get("expected_action_id")
            if not expected_action_id:
                continue
            context = _context_from_step(step)
            result = pipeline.process_batch(_batch_from_step(step), robot_context=context)
            rows.append(featurize(result.human_state, context))
            labels.append(str(expected_action_id))
            metadata.append(
                {
                    "scenario_id": scenario.get("scenario_id"),
                    "step": step.get("step"),
                    "ground_truth_state": step.get("ground_truth_state"),
                    "predicted_state": result.human_state.state,
                    "expected_action_id": expected_action_id,
                    "task_stage": context.task_stage,
                    "robot_distance_m": context.robot_distance_m,
                    "obstacle_distance_m": context.obstacle_distance_m,
                    "is_robot_moving": context.is_robot_moving,
                }
            )

    return rows, labels, metadata


def train_and_evaluate(
    *,
    scenario_dir: Path,
    output: Path,
    metrics_output: Path,
    benchmark_backend: str = "kinematic",
    person_id: str = "student_001",
    smooth_window: int = 1,
    max_depth: int = 5,
    augmentations_per_scenario: int = 0,
    eval_ratio: float = 0.25,
    seed: int = 42,
) -> dict[str, Any]:
    scenario_paths = sorted(scenario_dir.glob("*.json"))
    if not scenario_paths:
        raise RuntimeError(f"No scenario JSON files found in {scenario_dir}")
    if augmentations_per_scenario < 0:
        raise ValueError("augmentations_per_scenario must be non-negative")
    if not 0.0 <= eval_ratio < 1.0:
        raise ValueError("eval_ratio must be in [0.0, 1.0)")

    base_scenarios = [load_scenario(path) for path in scenario_paths]
    augmented_scenarios = generate_augmented_scenarios(
        base_scenarios,
        variants_per_scenario=augmentations_per_scenario,
        seed=seed,
    )
    train_scenarios, eval_scenarios = _split_scenarios(
        base_scenarios=base_scenarios,
        augmented_scenarios=augmented_scenarios,
        eval_ratio=eval_ratio,
    )

    rows, labels, row_metadata = collect_training_rows_from_scenarios(
        train_scenarios,
        person_id=person_id,
        smooth_window=smooth_window,
    )
    policy = LearnedSchoolPolicy.fit(rows, labels, max_depth=max_depth)
    policy.save(output)

    predictions = [policy.predict_action_id(row) for row in rows]
    training_accuracy = _accuracy(labels, predictions)

    benchmark_results = _run_policy_benchmark(
        scenarios=base_scenarios,
        policy=policy,
        backend_name=benchmark_backend,
        person_id=person_id,
        smooth_window=smooth_window,
    )
    holdout_rows: list[np.ndarray] = []
    holdout_labels: list[str] = []
    holdout_predictions: list[str] = []
    holdout_benchmark_results: list[dict[str, Any]] = []
    if eval_scenarios:
        holdout_rows, holdout_labels, _holdout_metadata = collect_training_rows_from_scenarios(
            eval_scenarios,
            person_id=person_id,
            smooth_window=smooth_window,
        )
        holdout_predictions = [policy.predict_action_id(row) for row in holdout_rows]
        holdout_benchmark_results = _run_policy_benchmark(
            scenarios=eval_scenarios,
            policy=policy,
            backend_name=benchmark_backend,
            person_id=person_id,
            smooth_window=smooth_window,
        )

    payload = {
        "model_path": str(output),
        "metrics_scope": (
            "scenario-derived and domain-randomized baseline; "
            "not a real-world generalization claim"
        ),
        "dataset": {
            "scenario_count": len(scenario_paths),
            "row_count": len(labels),
            "base_row_count": sum(len(scenario.get("steps", [])) for scenario in base_scenarios),
            "train_scenario_count": len(train_scenarios),
            "eval_scenario_count": len(eval_scenarios),
            "eval_row_count": len(holdout_labels),
            "augmentations_per_scenario": augmentations_per_scenario,
            "eval_ratio": eval_ratio,
            "seed": seed,
            "feature_count": len(feature_names()),
            "label_counts": dict(sorted(Counter(labels).items())),
            "scenario_files": [str(path) for path in scenario_paths],
        },
        "model": policy.metadata,
        "training_metrics": {
            "action_accuracy": training_accuracy,
            "prediction_counts": dict(sorted(Counter(predictions).items())),
        },
        "holdout_metrics": {
            "action_accuracy": _accuracy(holdout_labels, holdout_predictions),
            "row_count": len(holdout_labels),
            "prediction_counts": dict(sorted(Counter(holdout_predictions).items())),
            "benchmark_aggregate_metrics": _aggregate_metrics(holdout_benchmark_results)
            if holdout_benchmark_results
            else {},
        },
        "benchmark": {
            "backend": benchmark_backend,
            "aggregate_metrics": _aggregate_metrics(benchmark_results),
            "results": [
                {key: value for key, value in result.items() if key != "steps"}
                for result in benchmark_results
            ],
        },
        "rows": [
            {
                **meta,
                "predicted_action_id": pred,
                "match": pred == label,
            }
            for meta, label, pred in zip(row_metadata, labels, predictions)
        ],
    }

    metrics_output.parent.mkdir(parents=True, exist_ok=True)
    metrics_output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def _split_scenarios(
    *,
    base_scenarios: list[dict[str, Any]],
    augmented_scenarios: list[dict[str, Any]],
    eval_ratio: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not augmented_scenarios or eval_ratio <= 0.0:
        return base_scenarios + augmented_scenarios, []

    by_source: dict[str, list[dict[str, Any]]] = {}
    for scenario in augmented_scenarios:
        source_id = str(scenario.get("source_scenario_id") or scenario.get("scenario_id"))
        by_source.setdefault(source_id, []).append(scenario)

    train_scenarios = list(base_scenarios)
    eval_scenarios: list[dict[str, Any]] = []
    for source_id in sorted(by_source):
        variants = by_source[source_id]
        eval_count = max(1, round(len(variants) * eval_ratio))
        split_at = max(0, len(variants) - eval_count)
        train_scenarios.extend(variants[:split_at])
        eval_scenarios.extend(variants[split_at:])
    return train_scenarios, eval_scenarios


def _run_policy_benchmark(
    *,
    scenarios: list[dict[str, Any]],
    policy: LearnedSchoolPolicy,
    backend_name: str,
    person_id: str,
    smooth_window: int,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for scenario in scenarios:
        results.append(
            run_scenario(
                scenario,
                backend=_build_backend(backend_name),
                robot_policy=policy,
                person_id=person_id,
                smooth_window=smooth_window,
                include_cues=True,
            )
        )
    return results


def _accuracy(labels: list[str], predictions: list[str]) -> float:
    if not labels:
        return 0.0
    return sum(label == pred for label, pred in zip(labels, predictions)) / len(labels)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Train the local learned school robot-action policy baseline."
    )
    parser.add_argument("--scenario-dir", type=Path, default=DEFAULT_SCENARIO_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_LEARNED_POLICY_PATH)
    parser.add_argument("--metrics-output", type=Path, default=DEFAULT_METRICS_OUTPUT)
    parser.add_argument("--benchmark-backend", choices=("kinematic", "mujoco"), default="kinematic")
    parser.add_argument("--person-id", default="student_001")
    parser.add_argument("--smooth-window", type=int, default=1)
    parser.add_argument("--max-depth", type=int, default=5)
    parser.add_argument("--augmentations-per-scenario", type=int, default=0)
    parser.add_argument("--eval-ratio", type=float, default=0.25)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.smooth_window <= 0:
        raise SystemExit("--smooth-window must be positive")
    if args.max_depth <= 0:
        raise SystemExit("--max-depth must be positive")

    payload = train_and_evaluate(
        scenario_dir=args.scenario_dir,
        output=args.output,
        metrics_output=args.metrics_output,
        benchmark_backend=args.benchmark_backend,
        person_id=args.person_id,
        smooth_window=args.smooth_window,
        max_depth=args.max_depth,
        augmentations_per_scenario=args.augmentations_per_scenario,
        eval_ratio=args.eval_ratio,
        seed=args.seed,
    )
    indent = 2 if args.pretty else None
    print(json.dumps(payload, ensure_ascii=False, indent=indent))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
