from __future__ import annotations

import copy
import random
from typing import Any


STATE_UTTERANCES: dict[str, list[str]] = {
    "engaged": [
        "好的，我试试",
        "我在看",
        "可以，我继续",
        "这个我会一点",
    ],
    "confused": [
        "我不会，这个怎么做？",
        "老师说的是哪一个？",
        "我没听懂",
        "可以再说一遍吗？",
    ],
    "fatigued": [
        "有点累",
        "我想休息一下",
        "做不动了",
        "能不能慢一点",
    ],
    "frustrated": [
        "好烦",
        "我不想一直错",
        "这个太难了",
        "我有点着急",
    ],
    "refusing": [
        "不要，我不想做了",
        "我不做这个",
        "先停一下",
        "不要靠过来",
    ],
    "pain_risk": [
        "有点疼，不舒服",
        "疼，需要老师",
        "这里痛",
        "我不舒服，想停一下",
    ],
    "low_attention": [
        "",
        "嗯",
        "我在看别的",
        "等一下",
    ],
    "needs_help": [
        "帮帮我",
        "老师能来一下吗？",
        "我需要帮助",
        "这个我做不了",
    ],
}

STATE_CONFIDENCE_RANGES: dict[str, tuple[float, float]] = {
    "engaged": (0.68, 0.92),
    "confused": (0.64, 0.88),
    "fatigued": (0.64, 0.88),
    "frustrated": (0.62, 0.86),
    "refusing": (0.68, 0.92),
    "pain_risk": (0.78, 0.96),
    "low_attention": (0.58, 0.84),
    "needs_help": (0.76, 0.94),
}


def generate_augmented_scenarios(
    scenarios: list[dict[str, Any]],
    *,
    variants_per_scenario: int,
    seed: int = 42,
) -> list[dict[str, Any]]:
    if variants_per_scenario < 0:
        raise ValueError("variants_per_scenario must be non-negative")

    rng = random.Random(seed)
    augmented: list[dict[str, Any]] = []
    for scenario in scenarios:
        for index in range(variants_per_scenario):
            augmented.append(augment_scenario(scenario, variant_index=index, rng=rng))
    return augmented


def augment_scenario(
    scenario: dict[str, Any],
    *,
    variant_index: int,
    rng: random.Random,
) -> dict[str, Any]:
    augmented = copy.deepcopy(scenario)
    base_id = str(scenario.get("scenario_id", "scenario"))
    augmented["scenario_id"] = f"{base_id}_aug_{variant_index:03d}"
    augmented["description"] = (
        f"{scenario.get('description', '')} Domain-randomized local variant {variant_index}."
    ).strip()
    augmented["source_scenario_id"] = base_id
    augmented["domain_randomization"] = {
        "variant_index": variant_index,
        "fields": [
            "speech_text",
            "voice_amplitude",
            "face_confidence",
            "attention_score",
            "movement_speed",
            "response_delay_sec",
            "robot_distance_m",
            "obstacle_distance_m",
            "task_difficulty",
        ],
    }

    for step in augmented.get("steps", []):
        _augment_step(step, rng)
    return augmented


def _augment_step(step: dict[str, Any], rng: random.Random) -> None:
    state = str(step.get("ground_truth_state") or "neutral")
    cues = step.setdefault("observable_cues", {})
    context = step.setdefault("robot_context", {})
    expected_action = str(step.get("expected_action_id") or "")

    if state in STATE_UTTERANCES:
        cues["speech_text"] = rng.choice(STATE_UTTERANCES[state])
    if state in STATE_CONFIDENCE_RANGES:
        low, high = STATE_CONFIDENCE_RANGES[state]
        cues["face_confidence"] = round(rng.uniform(low, high), 3)

    cues["voice_amplitude"] = _jitter_float(
        cues.get("voice_amplitude"),
        rng,
        ratio=0.24,
        lower=0.005,
        upper=0.14,
    )
    cues["attention_score"] = _stateful_attention(
        state,
        _jitter_float(cues.get("attention_score"), rng, delta=0.08, lower=0.05, upper=0.95),
    )
    cues["movement_speed"] = _stateful_speed(
        state,
        _jitter_float(cues.get("movement_speed"), rng, delta=0.05, lower=0.0, upper=0.55),
    )
    cues["response_delay_sec"] = _stateful_delay(
        state,
        _jitter_float(cues.get("response_delay_sec"), rng, delta=0.65, lower=0.0, upper=7.0),
    )

    if state in {"needs_help", "pain_risk", "refusing"} and rng.random() < 0.65:
        cues["request_text"] = cues.get("speech_text")

    context["robot_distance_m"] = _jitter_float(
        context.get("robot_distance_m"),
        rng,
        delta=0.16,
        lower=0.65,
        upper=1.65,
    )
    context["obstacle_distance_m"] = _safe_obstacle_distance(
        expected_action,
        _jitter_float(context.get("obstacle_distance_m"), rng, delta=0.18, lower=0.35, upper=1.7),
    )
    if rng.random() < 0.25:
        context["task_difficulty"] = rng.choice(["easy", "normal", "hard", "adaptive"])


def _jitter_float(
    value: Any,
    rng: random.Random,
    *,
    ratio: float | None = None,
    delta: float | None = None,
    lower: float,
    upper: float,
) -> float:
    try:
        base = float(value)
    except (TypeError, ValueError):
        base = (lower + upper) / 2.0
    if ratio is not None:
        base *= rng.uniform(1.0 - ratio, 1.0 + ratio)
    if delta is not None:
        base += rng.uniform(-delta, delta)
    return round(max(lower, min(upper, base)), 3)


def _stateful_attention(state: str, value: float) -> float:
    if state == "engaged":
        return max(value, 0.72)
    if state == "low_attention":
        return min(value, 0.34)
    if state == "pain_risk":
        return min(value, 0.48)
    return value


def _stateful_speed(state: str, value: float) -> float:
    if state == "engaged":
        return max(value, 0.22)
    if state in {"fatigued", "pain_risk"}:
        return min(value, 0.14)
    if state == "low_attention":
        return min(value, 0.18)
    return value


def _stateful_delay(state: str, value: float) -> float:
    if state == "engaged":
        return min(value, 1.4)
    if state == "confused":
        return max(value, 4.0)
    if state in {"pain_risk", "needs_help"}:
        return max(value, 3.6)
    return value


def _safe_obstacle_distance(expected_action: str, value: float) -> float:
    if expected_action == "continue_and_encourage":
        return max(value, 0.82)
    if expected_action == "regain_attention":
        return min(value, 0.65)
    return value
