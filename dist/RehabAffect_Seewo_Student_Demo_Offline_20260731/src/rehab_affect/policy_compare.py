from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .learned_policy import LearnedSchoolPolicy
from .scenario_randomizer import generate_augmented_scenarios
from .sim_runner import (
    DEFAULT_LEARNED_POLICY_PATH,
    DEFAULT_SCENARIO_DIR,
    _aggregate_metrics,
    _build_backend,
    load_scenario,
    run_scenario,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "processed" / "policy_comparison.json"


def compare_policies(
    *,
    scenario_dir: Path = DEFAULT_SCENARIO_DIR,
    model_path: Path = DEFAULT_LEARNED_POLICY_PATH,
    backend_name: str = "kinematic",
    augmentations_per_scenario: int = 0,
    seed: int = 123,
    smooth_window: int = 1,
) -> dict[str, Any]:
    base_scenarios = [load_scenario(path) for path in sorted(scenario_dir.glob("*.json"))]
    if not base_scenarios:
        raise RuntimeError(f"No scenario JSON files found in {scenario_dir}")

    scenarios = list(base_scenarios)
    if augmentations_per_scenario:
        scenarios.extend(
            generate_augmented_scenarios(
                base_scenarios,
                variants_per_scenario=augmentations_per_scenario,
                seed=seed,
            )
        )

    variant_results = []
    for variant_name, policy in _policy_variants(model_path):
        results = [
            run_scenario(
                scenario,
                backend=_build_backend(backend_name),
                robot_policy=policy,
                smooth_window=smooth_window,
                include_cues=True,
            )
            for scenario in scenarios
        ]
        variant_results.append(_summarize_variant(variant_name, results))

    return {
        "benchmark": "special_education_classroom_policy_comparison",
        "backend": backend_name,
        "scenario_count": len(scenarios),
        "base_scenario_count": len(base_scenarios),
        "augmentations_per_scenario": augmentations_per_scenario,
        "seed": seed,
        "variants": variant_results,
    }


def _policy_variants(model_path: Path) -> list[tuple[str, Any | None]]:
    variants: list[tuple[str, Any | None]] = [("rule", None)]
    if model_path.exists():
        raw = LearnedSchoolPolicy.load(model_path)
        raw.shield_enabled = False
        raw.metadata = {**raw.metadata, "policy_type": "learned_raw"}

        shielded = LearnedSchoolPolicy.load(model_path)
        shielded.shield_enabled = True
        shielded.metadata = {**shielded.metadata, "policy_type": "learned_shielded"}

        variants.extend(
            [
                ("learned_raw", raw),
                ("learned_shielded", shielded),
            ]
        )
    return variants


def _summarize_variant(variant_name: str, results: list[dict[str, Any]]) -> dict[str, Any]:
    aggregate = _aggregate_metrics(results)
    records = [step for result in results for step in result["steps"]]
    confusion = _confusion_matrix(records)
    action_counts = Counter(step["robot_action"]["action_id"] for step in records)
    shield_counts = Counter(
        step["robot_action"].get("metadata", {}).get("action_shield", "none") for step in records
    )

    return {
        "variant": variant_name,
        "aggregate_metrics": aggregate,
        "handoff_latency": _handoff_latency_summary(results),
        "action_counts": dict(sorted(action_counts.items())),
        "shield_counts": dict(sorted(shield_counts.items())),
        "confusion_matrix": confusion,
        "scenario_results": [
            {
                "scenario_id": result["scenario_id"],
                "metrics": result["metrics"],
            }
            for result in results
        ],
    }


def _confusion_matrix(records: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    matrix: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for record in records:
        expected = str(record.get("expected_action_id"))
        predicted = str(record["robot_action"]["action_id"])
        matrix[expected][predicted] += 1
    return {
        expected: dict(sorted(predictions.items()))
        for expected, predictions in sorted(matrix.items())
    }


def _handoff_latency_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    values = [
        result["metrics"]["handoff_latency_steps"]
        for result in results
        if result["metrics"]["handoff_latency_steps"] is not None
    ]
    if not values:
        return {"count": 0, "max": None, "mean": None}
    return {
        "count": len(values),
        "max": max(values),
        "mean": sum(values) / len(values),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare rule, raw learned, and shielded learned robot policies."
    )
    parser.add_argument("--scenario-dir", type=Path, default=DEFAULT_SCENARIO_DIR)
    parser.add_argument("--model-path", type=Path, default=DEFAULT_LEARNED_POLICY_PATH)
    parser.add_argument("--backend", choices=("kinematic", "mujoco"), default="kinematic")
    parser.add_argument("--augmentations-per-scenario", type=int, default=0)
    parser.add_argument("--seed", type=int, default=123)
    parser.add_argument("--smooth-window", type=int, default=1)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.augmentations_per_scenario < 0:
        raise SystemExit("--augmentations-per-scenario must be non-negative")
    if args.smooth_window <= 0:
        raise SystemExit("--smooth-window must be positive")

    payload = compare_policies(
        scenario_dir=args.scenario_dir,
        model_path=args.model_path,
        backend_name=args.backend,
        augmentations_per_scenario=args.augmentations_per_scenario,
        seed=args.seed,
        smooth_window=args.smooth_window,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
