from pathlib import Path

from src.rehab_affect.ros2_mock_publisher import (
    HUMAN_STATE_TOPIC,
    ROBOT_ACTION_TOPIC,
    build_ros2_mock_messages,
)
from src.rehab_affect.websocket_server import build_benchmark_messages


SCENARIO_DIR = Path(__file__).resolve().parents[1] / "configs" / "scenarios"


def test_websocket_message_builder_streams_decisions_and_summary() -> None:
    messages = build_benchmark_messages(scenario_dir=SCENARIO_DIR)

    assert len(messages) == 19
    assert messages[0]["type"] == "perception_decision"
    assert "human_state" in messages[0]["payload"]
    assert "robot_action" in messages[0]["payload"]
    assert messages[-1]["type"] == "benchmark_summary"
    assert messages[-1]["payload"]["aggregate_metrics"]["safety_violation_count"] == 0


def test_ros2_mock_publisher_builds_two_topics_per_step() -> None:
    messages = build_ros2_mock_messages(scenario_dir=SCENARIO_DIR)
    topics = {message["topic"] for message in messages}

    assert len(messages) == 36
    assert topics == {HUMAN_STATE_TOPIC, ROBOT_ACTION_TOPIC}
    assert all(message["msg_type"] == "std_msgs/msg/String" for message in messages)
