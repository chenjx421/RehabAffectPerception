from src.rehab_affect.mujoco_snapshot import STATE_COLORS
from src.rehab_affect.sim_runner import _mujoco_classroom_xml


def test_mujoco_snapshot_state_colors_cover_safety_states() -> None:
    assert "pain_risk" in STATE_COLORS
    assert "low_attention" in STATE_COLORS
    assert "needs_help" in STATE_COLORS


def test_mujoco_classroom_xml_has_camera_and_core_objects() -> None:
    xml = _mujoco_classroom_xml()

    assert 'camera name="overview"' in xml
    assert 'body name="robot"' in xml
    assert 'body name="student"' in xml
    assert 'body name="teacher"' in xml
    assert 'body name="obstacle"' in xml
