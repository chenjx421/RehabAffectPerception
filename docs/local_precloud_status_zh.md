# 云电脑前本地完成清单

## 已完成

本地阶段目标是先证明主链路可运行：

```text
scenario cues
  -> multimodal recognizers
  -> temporal smoothing
  -> human_state
  -> robot_context
  -> learned / rule robot policy
  -> robot_action
  -> MuJoCo benchmark metrics
  -> demo page and screenshots
```

当前已完成内容：

| 模块 | 状态 | 产物 |
| --- | --- | --- |
| 辅读学校场景定义 | 完成 | `configs/scenarios/*.json` |
| 多模态输入结构 | 完成 | `src/rehab_affect/inputs.py` |
| 轻量识别器 | 完成 | `src/rehab_affect/recognizers.py` |
| 时间平滑 | 完成 | `src/rehab_affect/smoothing.py` |
| 多模态融合 | 完成 | `src/rehab_affect/fusion.py` |
| human_state / robot_action schema | 完成 | `src/rehab_affect/schema.py` |
| 规则安全策略 | 完成 | `src/rehab_affect/policy.py` |
| 可训练动作策略 | 完成 | `src/rehab_affect/learned_policy.py` |
| 策略训练入口 | 完成 | `src/rehab_affect/train_policy.py` |
| 闭环动作反馈仿真 | 完成 | `src/rehab_affect/closed_loop.py` |
| 闭环 benchmark 报告 | 完成 | `src/rehab_affect/closed_loop_report.py` |
| 本地演示总入口页 | 完成 | `src/rehab_affect/demo_launcher.py` |
| 策略对比评估 | 完成 | `src/rehab_affect/policy_compare.py` |
| 鲁棒性评估 | 完成 | `src/rehab_affect/robustness_eval.py` |
| 最终版 release 生成器 | 完成 | `src/rehab_affect/precloud_release.py` |
| MuJoCo 粗略教室 benchmark | 完成 | `src/rehab_affect/sim_runner.py` |
| MuJoCo 场景截图 | 完成 | `src/rehab_affect/mujoco_snapshot.py` |
| HTML 展示页 | 完成 | `src/rehab_affect/demo_export.py` |
| 交互式控制台 | 完成 | `src/rehab_affect/interactive_console.py` |
| 可编辑 Scenario Lab 本地服务 | 完成 | `src/rehab_affect/scenario_lab_server.py` |
| WebSocket 推送接口 | 完成 | `src/rehab_affect/websocket_server.py` |
| ROS2 mock publisher | 完成 | `src/rehab_affect/ros2_mock_publisher.py` |
| 自动测试 | 完成 | `tests/` |

## 本地运行命令

```powershell
cd D:/GIT/RehabAffectPerception
python -m pytest -q
python -m src.rehab_affect.train_policy `
  --scenario-dir configs/scenarios `
  --output models/learned_school_policy.pkl `
  --metrics-output data/processed/learned_policy_metrics.json `
  --benchmark-backend mujoco `
  --augmentations-per-scenario 8 `
  --eval-ratio 0.25 `
  --seed 123 `
  --pretty
python -m src.rehab_affect.sim_runner `
  --backend mujoco `
  --policy learned `
  --model-path models/learned_school_policy.pkl `
  --scenario-dir configs/scenarios `
  --summary-only `
  --pretty
python -m src.rehab_affect.demo_export `
  --backend mujoco `
  --policy learned `
  --model-path models/learned_school_policy.pkl `
  --output outputs/special_education_benchmark_demo.html
python -m src.rehab_affect.mujoco_snapshot `
  --scenario configs/scenarios/pain_risk_safety.json `
  --output-dir outputs/mujoco_frames
python -m src.rehab_affect.interactive_console `
  --backend mujoco `
  --policy learned `
  --model-path models/learned_school_policy.pkl `
  --scenario-dir configs/scenarios `
  --compare-backend kinematic `
  --output outputs/interactive_benchmark_console.html
python -m src.rehab_affect.closed_loop_report `
  --scenario-dir configs/scenarios `
  --backend kinematic `
  --policy learned `
  --model-path models/learned_school_policy.pkl `
  --json-output data/processed/closed_loop_benchmark.json `
  --html-output outputs/closed_loop_benchmark_report.html `
  --pretty
python -m src.rehab_affect.policy_compare `
  --backend kinematic `
  --model-path models/learned_school_policy.pkl `
  --scenario-dir configs/scenarios `
  --augmentations-per-scenario 2 `
  --output data/processed/policy_comparison.json `
  --pretty
python -m src.rehab_affect.robustness_eval `
  --backend kinematic `
  --model-path models/learned_school_policy.pkl `
  --scenario-dir configs/scenarios `
  --augmentations-per-scenario 4 `
  --output data/processed/robustness_eval.json `
  --pretty
python -m src.rehab_affect.precloud_release `
  --benchmark-backend mujoco `
  --compare-backend kinematic `
  --release-manifest outputs/precloud_release_manifest.json `
  --final-report docs/final_precloud_report_zh.md `
  --pretty
python -m src.rehab_affect.demo_launcher `
  --manifest outputs/precloud_release_manifest.json `
  --output outputs/demo_index.html `
  --pretty
python -m src.rehab_affect.websocket_server `
  --backend mujoco `
  --policy learned `
  --model-path models/learned_school_policy.pkl `
  --scenario-dir configs/scenarios `
  --dump-jsonl
python -m src.rehab_affect.ros2_mock_publisher `
  --backend mujoco `
  --policy learned `
  --model-path models/learned_school_policy.pkl `
  --scenario-dir configs/scenarios `
  --output data/processed/ros2_mock_messages.jsonl
python -m src.rehab_affect.scenario_lab_server `
  --host 127.0.0.1 `
  --port 8787 `
  --scenario-dir configs/scenarios `
  --model-path models/learned_school_policy.pkl `
  --policy learned
```

最后一个 `scenario_lab_server` 是本地网页服务，会持续运行；打开 `http://127.0.0.1:8787` 即可现场编辑学生线索并重新生成机器人动作。打开 `http://127.0.0.1:8787?preset=pain` 会直接进入疼痛风险安全动作演示。打开 `http://127.0.0.1:8787?scenario=shape_sorting_confused&loop=1` 会直接进入整段闭环轨迹演示。

## 当前指标

| 指标 | 结果 |
| --- | --- |
| 场景数 | 6 |
| 原始仿真 step | 18 |
| domain-randomized 训练 step | 126 |
| holdout step | 36 |
| 动作标签 | 7 |
| 学习策略特征 | 48 |
| 训练集动作准确率 | 100.0% |
| holdout 动作准确率 | 97.2% |
| holdout 安全违规 | 0 |
| MuJoCo benchmark 动作命中率 | 100.0% |
| MuJoCo benchmark 安全违规 | 0 |
| 闭环 benchmark 动作命中率 | 94.4% |
| 闭环 benchmark 状态恢复 | 3 |
| 闭环 benchmark 风险遏制 | 2 |
| 闭环 benchmark 安全违规 | 0 |
| 策略对比 step | 54 |
| raw learned 动作命中率 | 98.1% |
| shielded learned 动作命中率 | 100.0% |
| shielded learned 鲁棒性安全门 | 通过 |
| 高风险交接延迟 | 0 step |

说明：这些结果来自小规模 scenario-derived baseline，用于证明工程闭环，不代表真实学生数据上的泛化性能。

## 本地展示成品

```text
outputs/special_education_benchmark_demo.html
outputs/demo_index.html
outputs/interactive_benchmark_console.html
outputs/closed_loop_benchmark_report.html
outputs/playwright/interactive_benchmark_console.png
outputs/playwright/scenario_lab.png
outputs/playwright/scenario_lab_pain_risk.png
outputs/playwright/scenario_lab_closed_loop.png
outputs/mujoco_frames/pain_risk_safety_contact_sheet.png
models/learned_school_policy.pkl
data/processed/learned_policy_metrics.json
data/processed/policy_comparison.json
data/processed/robustness_eval.json
data/processed/closed_loop_benchmark.json
outputs/precloud_release_manifest.json
docs/final_precloud_report_zh.md
data/processed/websocket_stream_sample.jsonl
data/processed/ros2_mock_messages.jsonl
```

## 需要云电脑后再做

| 工作 | 为什么需要云电脑 |
| --- | --- |
| Isaac Sim 高保真辅读学校教室 | 依赖 Linux + NVIDIA GPU，Windows 本地不稳定 |
| 机器人第一视角 RGB/depth 视频 | 需要 Isaac Sim camera sensor 和渲染 |
| 大规模仿真随机化数据集 | 本地可做小规模，批量渲染/训练更适合云 GPU |
| ROS2 bridge 真实联调 | Windows 本地 mock 已完成，真实 ROS2/Isaac 联调更适合 Linux |
| 更复杂具身策略模型 | 本地 baseline 已完成，扩展模型训练需要更多数据和算力 |

## 云端升级目标

云电脑阶段不是推翻本地版本，而是把同一套合同升级：

```text
same scenario schema
same human_state JSON
same robot_context JSON
same robot_action JSON
same benchmark metrics
```

只替换仿真后端和传感器来源：

```text
MuJoCo coarse classroom
  -> Isaac Sim high-fidelity classroom
structured cues
  -> camera/depth/audio-like rendered cues + logs
DecisionTree baseline
  -> larger learned policy / imitation baseline
```
