from src.rehab_affect.fusion import fuse_signals
from src.rehab_affect.schema import ModalitySignal


def test_pain_risk_contract_includes_risk_and_handoff() -> None:
    state = fuse_signals(
        person_id="user_test",
        signals=[
            ModalitySignal(
                source="voice",
                state="pain_risk",
                confidence=0.90,
                valence=-0.70,
                arousal=0.78,
            )
        ],
        timestamp=123.0,
    )

    payload = state.to_dict()
    assert payload["state"] == "pain_risk"
    assert payload["risk_level"] == "high"
    assert payload["handoff_required"] is True
    assert payload["recommended_robot_action"] == "stop_check_pain_risk_and_alert_teacher_or_caregiver"
    assert payload["suggested_robot_action"] == payload["recommended_robot_action"]
    assert payload["timestamp"] == 123.0


def test_legacy_discomfort_alias_maps_to_pain_risk() -> None:
    state = fuse_signals(
        person_id="user_test",
        signals=[
            ModalitySignal(
                source="face",
                state="discomfort",
                confidence=0.92,
                valence=-0.70,
                arousal=0.78,
            )
        ],
    )

    assert state.state == "pain_risk"
    assert state.handoff_required is True
