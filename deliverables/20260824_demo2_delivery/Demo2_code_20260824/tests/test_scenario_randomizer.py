from pathlib import Path

from src.rehab_affect.scenario_randomizer import generate_augmented_scenarios
from src.rehab_affect.sim_runner import load_scenario


SCENARIO_DIR = Path(__file__).resolve().parents[1] / "configs" / "scenarios"


def test_scenario_randomizer_preserves_labels_and_actions() -> None:
    scenario = load_scenario(SCENARIO_DIR / "pain_risk_safety.json")
    augmented = generate_augmented_scenarios([scenario], variants_per_scenario=2, seed=7)

    assert len(augmented) == 2
    assert augmented[0]["source_scenario_id"] == "pain_risk_safety"
    assert augmented[0]["scenario_id"] == "pain_risk_safety_aug_000"

    original_pairs = [
        (step["ground_truth_state"], step["expected_action_id"]) for step in scenario["steps"]
    ]
    augmented_pairs = [
        (step["ground_truth_state"], step["expected_action_id"])
        for step in augmented[0]["steps"]
    ]
    assert augmented_pairs == original_pairs
    assert augmented[0]["steps"][1]["observable_cues"]["face_confidence"] >= 0.78
