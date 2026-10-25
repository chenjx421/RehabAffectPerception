from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .closed_loop_report import build_closed_loop_payload, export_closed_loop_report
from .demo_launcher import export_demo_index
from .demo_export import _aggregate_metrics as demo_aggregate_metrics
from .demo_export import _render_html as render_demo_html
from .interactive_console import build_console_payload, export_console
from .policy_compare import compare_policies
from .robustness_eval import run_robustness_eval
from .ros2_mock_publisher import build_ros2_mock_messages
from .sim_runner import (
    DEFAULT_LEARNED_POLICY_PATH,
    DEFAULT_SCENARIO_DIR,
    _aggregate_metrics,
    build_policy,
    run_scenario_path,
)
from .train_policy import train_and_evaluate
from .websocket_server import build_benchmark_messages


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RELEASE_MANIFEST = PROJECT_ROOT / "outputs" / "precloud_release_manifest.json"
DEFAULT_FINAL_REPORT = PROJECT_ROOT / "docs" / "final_precloud_report_zh.md"
DEFAULT_DEMO_HTML = PROJECT_ROOT / "outputs" / "special_education_benchmark_demo.html"
DEFAULT_CONSOLE_HTML = PROJECT_ROOT / "outputs" / "interactive_benchmark_console.html"
DEFAULT_CLOSED_LOOP_HTML = PROJECT_ROOT / "outputs" / "closed_loop_benchmark_report.html"
DEFAULT_DEMO_INDEX = PROJECT_ROOT / "outputs" / "demo_index.html"
DEFAULT_CONSOLE_SCREENSHOT = PROJECT_ROOT / "outputs" / "playwright" / "interactive_benchmark_console.png"
DEFAULT_DEMO_SCREENSHOT = PROJECT_ROOT / "outputs" / "playwright" / "special_education_benchmark_demo_learned.png"
DEFAULT_SHOWCASE_SCREENSHOT = PROJECT_ROOT / "outputs" / "playwright" / "classroom_showcase_mujoco.png"
DEFAULT_SHOWCASE_CLOSED_LOOP_SCREENSHOT = (
    PROJECT_ROOT / "outputs" / "playwright" / "classroom_showcase_mujoco_closed_loop.png"
)
DEFAULT_SCENARIO_LAB_SCREENSHOT = PROJECT_ROOT / "outputs" / "playwright" / "scenario_lab.png"
DEFAULT_SCENARIO_LAB_PAIN_RISK_SCREENSHOT = PROJECT_ROOT / "outputs" / "playwright" / "scenario_lab_pain_risk.png"
DEFAULT_SCENARIO_LAB_CLOSED_LOOP_SCREENSHOT = PROJECT_ROOT / "outputs" / "playwright" / "scenario_lab_closed_loop.png"
DEFAULT_MUJOCO_CONTACT_SHEET = PROJECT_ROOT / "outputs" / "mujoco_frames" / "pain_risk_safety_contact_sheet.png"
DEFAULT_SCENARIO_LAB_URL = "http://127.0.0.1:8787"


def run_precloud_release(
    *,
    scenario_dir: Path = DEFAULT_SCENARIO_DIR,
    model_path: Path = DEFAULT_LEARNED_POLICY_PATH,
    release_manifest_path: Path = DEFAULT_RELEASE_MANIFEST,
    final_report_path: Path = DEFAULT_FINAL_REPORT,
    benchmark_backend: str = "mujoco",
    compare_backend: str = "kinematic",
    train_augmentations_per_scenario: int = 8,
    compare_augmentations_per_scenario: int = 2,
    robustness_augmentations_per_scenario: int = 4,
    robustness_seeds: list[int] | None = None,
    processed_dir: Path | None = None,
    demo_html_path: Path | None = None,
    console_html_path: Path | None = None,
    closed_loop_html_path: Path | None = None,
    demo_index_path: Path | None = None,
) -> dict[str, Any]:
    processed_dir = processed_dir or PROJECT_ROOT / "data" / "processed"
    demo_html_path = demo_html_path or DEFAULT_DEMO_HTML
    console_html_path = console_html_path or DEFAULT_CONSOLE_HTML
    closed_loop_html_path = closed_loop_html_path or DEFAULT_CLOSED_LOOP_HTML
    demo_index_path = demo_index_path or DEFAULT_DEMO_INDEX

    train_metrics_path = processed_dir / "learned_policy_metrics.json"
    benchmark_summary_path = processed_dir / "benchmark_learned_mujoco_summary.json"
    closed_loop_path = processed_dir / "closed_loop_benchmark.json"
    policy_comparison_path = processed_dir / "policy_comparison.json"
    robustness_path = processed_dir / "robustness_eval.json"
    websocket_sample_path = processed_dir / "websocket_stream_sample.jsonl"
    ros2_sample_path = processed_dir / "ros2_mock_messages.jsonl"

    training_payload = train_and_evaluate(
        scenario_dir=scenario_dir,
        output=model_path,
        metrics_output=train_metrics_path,
        benchmark_backend=benchmark_backend,
        augmentations_per_scenario=train_augmentations_per_scenario,
        eval_ratio=0.25,
        seed=123,
    )

    robot_policy = build_policy("learned", model_path)
    scenario_paths = sorted(scenario_dir.glob("*.json"))
    benchmark_results = [
        run_scenario_path(
            path,
            backend_name=benchmark_backend,
            robot_policy=robot_policy,
            include_cues=True,
            smooth_window=1,
        )
        for path in scenario_paths
    ]
    benchmark_payload = {
        "benchmark": "special_education_classroom",
        "backend": benchmark_backend,
        "policy": "learned",
        "scenario_count": len(benchmark_results),
        "aggregate_metrics": _aggregate_metrics(benchmark_results),
        "results": [{key: value for key, value in result.items() if key != "steps"} for result in benchmark_results],
    }
    benchmark_summary_path.parent.mkdir(parents=True, exist_ok=True)
    benchmark_summary_path.write_text(
        json.dumps(benchmark_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    demo_payload = {
        "benchmark": "special_education_classroom",
        "backend": benchmark_backend,
        "policy": "learned",
        "scenario_count": len(benchmark_results),
        "aggregate_metrics": demo_aggregate_metrics(benchmark_results),
        "results": benchmark_results,
    }
    demo_html_path.parent.mkdir(parents=True, exist_ok=True)
    demo_html_path.write_text(render_demo_html(demo_payload), encoding="utf-8")

    console_payload = build_console_payload(
        scenario_dir=scenario_dir,
        backend=benchmark_backend,
        policy="learned",
        model_path=model_path,
        compare_backend=compare_backend,
    )
    export_console(console_payload, console_html_path)

    closed_loop_payload = build_closed_loop_payload(
        scenario_dir=scenario_dir,
        backend=compare_backend,
        policy="learned",
        model_path=model_path,
    )
    export_closed_loop_report(
        closed_loop_payload,
        json_output=closed_loop_path,
        html_output=closed_loop_html_path,
    )

    policy_comparison = compare_policies(
        scenario_dir=scenario_dir,
        model_path=model_path,
        backend_name=compare_backend,
        augmentations_per_scenario=compare_augmentations_per_scenario,
    )
    policy_comparison_path.write_text(
        json.dumps(policy_comparison, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    robustness = run_robustness_eval(
        scenario_dir=scenario_dir,
        model_path=model_path,
        backend_name=compare_backend,
        seeds=robustness_seeds or [101, 202, 303, 404, 505],
        augmentations_per_scenario=robustness_augmentations_per_scenario,
    )
    robustness_path.write_text(json.dumps(robustness, ensure_ascii=False, indent=2), encoding="utf-8")

    websocket_messages = build_benchmark_messages(
        scenario_dir=scenario_dir,
        backend=benchmark_backend,
        policy_name="learned",
        model_path=model_path,
    )
    websocket_sample_path.write_text(
        "\n".join(json.dumps(message, ensure_ascii=False) for message in websocket_messages) + "\n",
        encoding="utf-8",
    )

    ros2_messages = build_ros2_mock_messages(
        scenario_dir=scenario_dir,
        backend=benchmark_backend,
        policy_name="learned",
        model_path=model_path,
    )
    ros2_sample_path.write_text(
        "\n".join(json.dumps(message, ensure_ascii=False) for message in ros2_messages) + "\n",
        encoding="utf-8",
    )

    manifest = _build_manifest(
        training_payload=training_payload,
        benchmark_payload=benchmark_payload,
        closed_loop_payload=closed_loop_payload,
        policy_comparison=policy_comparison,
        robustness=robustness,
        paths={
            "model": model_path,
            "training_metrics": train_metrics_path,
            "benchmark_summary": benchmark_summary_path,
            "closed_loop_benchmark": closed_loop_path,
            "closed_loop_report": closed_loop_html_path,
            "policy_comparison": policy_comparison_path,
            "robustness_eval": robustness_path,
            "demo_html": demo_html_path,
            "interactive_console": console_html_path,
            "interactive_console_screenshot": DEFAULT_CONSOLE_SCREENSHOT,
            "scenario_lab_screenshot": DEFAULT_SCENARIO_LAB_SCREENSHOT,
            "scenario_lab_pain_risk_screenshot": DEFAULT_SCENARIO_LAB_PAIN_RISK_SCREENSHOT,
            "scenario_lab_closed_loop_screenshot": DEFAULT_SCENARIO_LAB_CLOSED_LOOP_SCREENSHOT,
            "demo_screenshot": DEFAULT_DEMO_SCREENSHOT,
            "classroom_showcase_screenshot": DEFAULT_SHOWCASE_SCREENSHOT,
            "classroom_showcase_closed_loop_screenshot": DEFAULT_SHOWCASE_CLOSED_LOOP_SCREENSHOT,
            "mujoco_contact_sheet": DEFAULT_MUJOCO_CONTACT_SHEET,
            "websocket_sample": websocket_sample_path,
            "ros2_mock_messages": ros2_sample_path,
            "demo_index": demo_index_path,
            "final_report": final_report_path,
        },
        local_services={
            "scenario_lab": DEFAULT_SCENARIO_LAB_URL,
        },
    )
    release_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    release_manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    final_report_path.parent.mkdir(parents=True, exist_ok=True)
    final_report_path.write_text(_render_final_report(manifest), encoding="utf-8")
    export_demo_index(output=demo_index_path, manifest=manifest)
    return manifest


def _build_manifest(
    *,
    training_payload: dict[str, Any],
    benchmark_payload: dict[str, Any],
    closed_loop_payload: dict[str, Any],
    policy_comparison: dict[str, Any],
    robustness: dict[str, Any],
    paths: dict[str, Path],
    local_services: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "release": "precloud_local_final",
        "project": "RehabAffectPerception",
        "positioning": "special_education_embodied_student_state_to_robot_action",
        "training": {
            "row_count": training_payload["dataset"]["row_count"],
            "base_row_count": training_payload["dataset"]["base_row_count"],
            "eval_row_count": training_payload["dataset"]["eval_row_count"],
            "feature_count": training_payload["dataset"]["feature_count"],
            "training_action_accuracy": training_payload["training_metrics"]["action_accuracy"],
            "holdout_action_accuracy": training_payload["holdout_metrics"]["action_accuracy"],
            "holdout_safety_violation_count": training_payload["holdout_metrics"][
                "benchmark_aggregate_metrics"
            ].get("safety_violation_count"),
        },
        "benchmark": benchmark_payload["aggregate_metrics"],
        "closed_loop": closed_loop_payload["aggregate_metrics"],
        "policy_comparison": {
            variant["variant"]: variant["aggregate_metrics"]
            for variant in policy_comparison["variants"]
        },
        "robustness": robustness["summary"],
        "artifacts": {name: str(path) for name, path in paths.items()},
        "local_services": local_services or {},
        "cloud_next": [
            "Isaac Sim high-fidelity special-education classroom",
            "ROS2 bridge with real robot or Isaac Sim robot model",
            "RGB/depth camera rendering and sim2real sensor pipeline",
            "larger domain randomization and video demo generation",
        ],
    }


def _render_final_report(manifest: dict[str, Any]) -> str:
    training = manifest["training"]
    benchmark = manifest["benchmark"]
    closed_loop = manifest["closed_loop"]
    comparison = manifest["policy_comparison"]
    robustness = manifest["robustness"]
    artifacts = manifest["artifacts"]
    shielded = comparison.get("learned_shielded", {})
    raw = comparison.get("learned_raw", {})
    robust_shielded = robustness.get("learned_shielded", {})
    return f"""# RehabAffectPerception 云电脑前最终版报告

## 1. 项目定位

本项目当前定位为：面向辅读学校辅助机器人的多模态学生状态感知与具身动作决策模块。

核心链路：

```text
学生语音 / 姿态 / 任务行为 / 机器人上下文
  -> multimodal recognizers
  -> temporal smoothing
  -> human_state
  -> learned robot policy + action shield
  -> robot_action
  -> MuJoCo benchmark / WebSocket / ROS2-style mock
```

## 2. 本地最终版完成内容

| 模块 | 状态 |
| --- | --- |
| 辅读学校 scenario benchmark | 完成 |
| MuJoCo 粗略教室仿真 | 完成 |
| domain randomization 训练数据 | 完成 |
| LearnedSchoolPolicy | 完成 |
| action shield 安全约束 | 完成 |
| rule/raw/shielded 策略对比 | 完成 |
| 多 seed 鲁棒性评估 | 完成 |
| WebSocket 接口样例 | 完成 |
| ROS2-style mock publisher | 完成 |
| 静态展示页 | 完成 |
| 交互式 benchmark 控制台 | 完成 |
| 可编辑 Scenario Lab 本地服务 | 完成 |
| 闭环动作反馈 benchmark | 完成 |

## 3. 训练与验证

| 指标 | 结果 |
| --- | --- |
| 原始 step | {training["base_row_count"]} |
| 训练 step | {training["row_count"]} |
| holdout step | {training["eval_row_count"]} |
| 特征数 | {training["feature_count"]} |
| 训练动作准确率 | {training["training_action_accuracy"]:.1%} |
| holdout 动作准确率 | {training["holdout_action_accuracy"]:.1%} |
| holdout 安全违规 | {training["holdout_safety_violation_count"]} |

## 4. MuJoCo Benchmark

| 指标 | 结果 |
| --- | --- |
| 场景数 | {benchmark["scenario_count"]} |
| step 数 | {benchmark["step_count"]} |
| 动作命中率 | {benchmark["action_match_accuracy"]:.1%} |
| 安全违规 | {benchmark["safety_violation_count"]} |
| 干预次数 | {benchmark["intervention_count"]} |

## 5. 策略对比

| 策略 | 动作命中率 | 安全违规 | 干预次数 |
| --- | --- | --- | --- |
| learned_raw | {raw.get("action_match_accuracy", 0):.1%} | {raw.get("safety_violation_count", "n/a")} | {raw.get("intervention_count", "n/a")} |
| learned_shielded | {shielded.get("action_match_accuracy", 0):.1%} | {shielded.get("safety_violation_count", "n/a")} | {shielded.get("intervention_count", "n/a")} |

结论：raw learned policy 已经可用，但 shielded learned policy 更适合作为机器人动作层，因为它在状态-动作冲突时能保守回退。

## 6. 闭环动作反馈 Benchmark

| 指标 | 结果 |
| --- | --- |
| 场景数 | {closed_loop["scenario_count"]} |
| step 数 | {closed_loop["step_count"]} |
| 动作命中率 | {closed_loop["action_match_accuracy"]:.1%} |
| 状态恢复次数 | {closed_loop["recovery_count"]} |
| 风险遏制次数 | {closed_loop["risk_containment_count"]} |
| 安全违规 | {closed_loop["safety_violation_count"]} |
| 闭环分 | {closed_loop["mean_closed_loop_score"]:.1f} |

这部分验证机器人动作会反馈到下一步学生线索和环境上下文，而不是只做单帧状态分类。

## 7. 鲁棒性评估

| 策略 | 平均动作命中率 | 最低动作命中率 | 安全门 |
| --- | --- | --- | --- |
| learned_shielded | {robust_shielded.get("mean_action_match_accuracy", 0):.1%} | {robust_shielded.get("min_action_match_accuracy", 0):.1%} | {robust_shielded.get("pass_safety_gate")} |

## 8. 最终展示入口

```text
{manifest.get("local_services", {}).get("scenario_lab", DEFAULT_SCENARIO_LAB_URL)}
{artifacts["demo_index"]}
{artifacts["closed_loop_report"]}
{artifacts["interactive_console"]}
{artifacts["demo_html"]}
```

## 9. 主要产物

```text
{artifacts["model"]}
{artifacts["training_metrics"]}
{artifacts["benchmark_summary"]}
{artifacts["closed_loop_benchmark"]}
{artifacts["policy_comparison"]}
{artifacts["robustness_eval"]}
{artifacts["classroom_showcase_screenshot"]}
{artifacts["classroom_showcase_closed_loop_screenshot"]}
{artifacts["scenario_lab_screenshot"]}
{artifacts["scenario_lab_pain_risk_screenshot"]}
{artifacts["scenario_lab_closed_loop_screenshot"]}
{artifacts["websocket_sample"]}
{artifacts["ros2_mock_messages"]}
```

## 10. 上云电脑后做什么

本地最终版已经完成“MuJoCo 粗仿真 + 训练 + 评估 + 接口 + 展示”。云电脑阶段不再重做基础链路，而是升级仿真和传感器：

1. Isaac Sim 高保真辅读学校教室。
2. ROS2 bridge 与真实或仿真机器人模型。
3. RGB/depth camera 渲染和第一视角视频。
4. 更大规模 domain randomization。
5. 生成最终演示视频和 sim2real 对照材料。
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the final local pre-cloud release artifacts."
    )
    parser.add_argument("--scenario-dir", type=Path, default=DEFAULT_SCENARIO_DIR)
    parser.add_argument("--model-path", type=Path, default=DEFAULT_LEARNED_POLICY_PATH)
    parser.add_argument("--release-manifest", type=Path, default=DEFAULT_RELEASE_MANIFEST)
    parser.add_argument("--final-report", type=Path, default=DEFAULT_FINAL_REPORT)
    parser.add_argument("--benchmark-backend", choices=("kinematic", "mujoco"), default="mujoco")
    parser.add_argument("--compare-backend", choices=("kinematic", "mujoco"), default="kinematic")
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manifest = run_precloud_release(
        scenario_dir=args.scenario_dir,
        model_path=args.model_path,
        release_manifest_path=args.release_manifest,
        final_report_path=args.final_report,
        benchmark_backend=args.benchmark_backend,
        compare_backend=args.compare_backend,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
