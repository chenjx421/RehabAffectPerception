from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean
from typing import Any

from .policy_compare import compare_policies
from .sim_runner import DEFAULT_LEARNED_POLICY_PATH, DEFAULT_SCENARIO_DIR


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "processed" / "robustness_eval.json"


def run_robustness_eval(
    *,
    scenario_dir: Path = DEFAULT_SCENARIO_DIR,
    model_path: Path = DEFAULT_LEARNED_POLICY_PATH,
    backend_name: str = "kinematic",
    seeds: list[int] | None = None,
    augmentations_per_scenario: int = 4,
    smooth_window: int = 1,
) -> dict[str, Any]:
    if augmentations_per_scenario < 0:
        raise ValueError("augmentations_per_scenario must be non-negative")
    seeds = seeds or [101, 202, 303, 404, 505]

    runs = [
        compare_policies(
            scenario_dir=scenario_dir,
            model_path=model_path,
            backend_name=backend_name,
            augmentations_per_scenario=augmentations_per_scenario,
            seed=seed,
            smooth_window=smooth_window,
        )
        for seed in seeds
    ]

    variant_names = [variant["variant"] for variant in runs[0]["variants"]] if runs else []
    summary = {
        name: _summarize_variant_across_runs(name, runs)
        for name in variant_names
    }
    return {
        "benchmark": "special_education_policy_robustness",
        "backend": backend_name,
        "seeds": seeds,
        "augmentations_per_scenario": augmentations_per_scenario,
        "run_count": len(runs),
        "summary": summary,
        "runs": runs,
    }


def _summarize_variant_across_runs(
    variant_name: str,
    runs: list[dict[str, Any]],
) -> dict[str, Any]:
    accuracies: list[float] = []
    safety_violations: list[int] = []
    intervention_counts: list[int] = []
    handoff_max_values: list[int] = []

    for run in runs:
        variant = next(item for item in run["variants"] if item["variant"] == variant_name)
        metrics = variant["aggregate_metrics"]
        accuracies.append(float(metrics["action_match_accuracy"]))
        safety_violations.append(int(metrics["safety_violation_count"]))
        intervention_counts.append(int(metrics["intervention_count"]))
        handoff_max = variant.get("handoff_latency", {}).get("max")
        if handoff_max is not None:
            handoff_max_values.append(int(handoff_max))

    return {
        "mean_action_match_accuracy": mean(accuracies) if accuracies else 0.0,
        "min_action_match_accuracy": min(accuracies) if accuracies else 0.0,
        "max_safety_violation_count": max(safety_violations) if safety_violations else 0,
        "total_safety_violation_count": sum(safety_violations),
        "mean_intervention_count": mean(intervention_counts) if intervention_counts else 0.0,
        "max_handoff_latency_steps": max(handoff_max_values) if handoff_max_values else None,
        "pass_safety_gate": sum(safety_violations) == 0,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run seeded robustness evaluation for policy variants."
    )
    parser.add_argument("--scenario-dir", type=Path, default=DEFAULT_SCENARIO_DIR)
    parser.add_argument("--model-path", type=Path, default=DEFAULT_LEARNED_POLICY_PATH)
    parser.add_argument("--backend", choices=("kinematic", "mujoco"), default="kinematic")
    parser.add_argument("--augmentations-per-scenario", type=int, default=4)
    parser.add_argument("--seeds", default="101,202,303,404,505")
    parser.add_argument("--smooth-window", type=int, default=1)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.smooth_window <= 0:
        raise SystemExit("--smooth-window must be positive")
    seeds = [int(item.strip()) for item in args.seeds.split(",") if item.strip()]
    payload = run_robustness_eval(
        scenario_dir=args.scenario_dir,
        model_path=args.model_path,
        backend_name=args.backend,
        seeds=seeds,
        augmentations_per_scenario=args.augmentations_per_scenario,
        smooth_window=args.smooth_window,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
