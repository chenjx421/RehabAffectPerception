# RehabAffectPerception

面向辅读学校辅助机器人的多模态人类状态感知与动作决策模块。项目目标不是“读心”、普通情绪分类或医学诊断，而是从视觉、语音、姿态、课堂任务表现和历史状态中估计学生在学习/训练交互中的状态，并把结构化 `human_state` 和最终 `robot_action` 提供给机器人上层策略。

## Project Goal

在辅读学校和特殊教育支持场景中，机器人需要根据学生状态调整交互方式。例如学生困惑时分步骤重复说明，疲劳或压力升高时降低任务负荷，明确拒绝时暂停并询问意愿，疑似不适时停止动作并提醒教师或照护者。本项目构建一个轻量的人类状态感知与具身动作决策模块：

```text
RGB / RGB-D camera + microphone
    -> face, voice, pose, text and task-behavior signals
    -> temporal smoothing and multimodal fusion
    -> human_state with confidence
    -> robot_action for speech, motion, task adjustment, and safety handoff
```

## State Labels

第一版不直接做“七分类情绪”，而是面向辅读学校课堂/训练交互定义更实用的状态：

| Label | Meaning | Robot Response |
| --- | --- | --- |
| `engaged` | 积极配合 | 继续任务并正向反馈 |
| `neutral` | 正常 | 保持当前交互 |
| `confused` | 困惑 | 放慢语速，重复说明 |
| `fatigued` | 疲劳/任务负荷过高 | 降低任务负荷，询问是否休息 |
| `frustrated` | 挫败/烦躁 | 暂停催促，降低交互压力 |
| `refusing` | 抗拒/拒绝继续 | 暂停，询问意愿并提供选择 |
| `pain_risk` | 疑似疼痛/不适风险 | 立即暂停，询问并提醒教师或照护者 |
| `low_attention` | 注意力下降 | 重新吸引注意力或简化任务 |
| `needs_help` | 需要帮助 | 提供协助或呼叫教师/照护者 |

同时输出连续情绪维度：

```text
valence: 情绪正负，范围 [-1, 1]
arousal: 激活程度，范围 [0, 1]
confidence: 置信度，范围 [0, 1]
```

## MVP Architecture

```mermaid
flowchart LR
    A["RGB Camera"] --> B["Face Emotion"]
    C["Microphone"] --> D["Voice / ASR Emotion"]
    E["RGB-D / Pose"] --> F["Body Pose State"]
    G["Robot Task Logs"] --> H["Behavior Features"]
    B --> I["Temporal Smoothing"]
    D --> I
    F --> I
    H --> I
    I --> J["Multimodal Fusion"]
    J --> K["HumanState JSON"]
    K --> L["Robot Policy"]
    L --> M["RobotAction JSON / ROS2 / WebSocket"]
```

## Repository Layout

```text
docs/
  project_plan_zh.md        项目方案与面试讲法
  data_schema_zh.md         数据采集和标注格式
  special_education_solution_design_zh.md  辅读学校实地需求结合现有原型的设计方案
  mvp_integration_zh.md     MVP 模块与 ROS2/WebSocket 接入方案
  two_month_embodied_ai_roadmap_zh.md  两个月具身智能项目路线图
  two_month_embodied_ai_roadmap.xlsx   两个月路线图 Excel 打卡表
  embodied_model_strategy_zh.md        OpenPI/pi0/pi0.5 具身模型接入策略
  special_education_benchmark_zh.md    辅读学校 MuJoCo/Isaac Sim benchmark 设计
  evaluation_report_zh.md              benchmark 评估报告
  demo_script_zh.md                    3 分钟演示脚本
  seewo_student_demo_readme_zh.md      Seewo 单学生追踪 Demo 截图说明
src/rehab_affect/
  schema.py                 核心数据结构
  inputs.py                 摄像头、麦克风和模拟输入
  recognizers.py            多模态轻量识别器/模型接入占位
  smoothing.py              多帧平滑逻辑
  fusion.py                 多模态规则融合逻辑
  policy.py                 human_state 到机器人动作的规则策略
  learned_policy.py         本地可训练的具身动作策略 baseline
  pipeline.py               输入到 human_state 的 MVP pipeline
  train_policy.py           从 benchmark 场景训练动作策略
  sim_runner.py             辅读学校 benchmark 场景运行器
  closed_loop.py            机器人动作反馈到下一步学生状态的闭环仿真
  closed_loop_report.py     闭环具身 benchmark 报告导出器
  demo_launcher.py          本地演示总入口页生成器
  policy_compare.py         rule/raw learned/shielded learned 策略对比
  demo_export.py            静态 HTML 展示页生成器
  interactive_console.py    交互式 benchmark 控制台导出器
  robustness_eval.py        多 seed 随机扰动鲁棒性评估
  precloud_release.py       云电脑前本地最终版一键生成器
  scenario_lab_server.py    本地可编辑 Scenario Lab 服务
  mujoco_snapshot.py        MuJoCo 场景截图导出器
  websocket_server.py       WebSocket benchmark 事件推送
  ros2_mock_publisher.py    Windows 本地 ROS2-style JSONL mock
  demo.py                   不依赖模型权重的模拟 demo
  mvp.py                    JSONL 输出命令行入口
configs/
  labels.json               状态标签配置
  objects.json              辅读学校场景对象配置
  scenarios/                辅读学校 benchmark 场景
data/
  README.md                 数据目录说明
```

## Quick Demo

```bash
cd D:/GIT/RehabAffectPerception
python -m src.rehab_affect.demo
```

运行第一版 MVP 模拟流：

```bash
python -m src.rehab_affect.mvp --mode mock --steps 10
python -m src.rehab_affect.mvp --mode mock --steps 3 --pretty --include-signals
```

接入本机摄像头/麦克风前先安装可选输入依赖：

```bash
pip install -e ".[input]"
python -m src.rehab_affect.mvp --mode live --camera --microphone --steps 20
```

`--mode live` 不指定 `--camera` 或 `--microphone` 时默认两者都启用；只想测试单一路径时可单独传其中一个参数。

运行辅读学校 benchmark：

```bash
python -m src.rehab_affect.sim_runner --scenario-dir configs/scenarios --summary-only --pretty
python -m src.rehab_affect.sim_runner --scenario configs/scenarios/pain_risk_safety.json --pretty
```

第一版默认使用轻量 `kinematic` 后端，保证本地稳定运行；后续接 MuJoCo 时安装：

```bash
pip install -e ".[simulation]"
python -m src.rehab_affect.sim_runner --backend mujoco --scenario configs/scenarios/pain_risk_safety.json --pretty
```

训练本地具身动作策略 baseline：

```powershell
pip install -e ".[training,simulation]"
python -m src.rehab_affect.train_policy `
  --scenario-dir configs/scenarios `
  --output models/learned_school_policy.pkl `
  --metrics-output data/processed/learned_policy_metrics.json `
  --benchmark-backend mujoco `
  --augmentations-per-scenario 8 `
  --eval-ratio 0.25 `
  --seed 123 `
  --pretty
```

用学习策略运行 MuJoCo benchmark：

```powershell
python -m src.rehab_affect.sim_runner `
  --backend mujoco `
  --policy learned `
  --model-path models/learned_school_policy.pkl `
  --scenario-dir configs/scenarios `
  --summary-only `
  --pretty
```

生成展示页：

```powershell
python -m src.rehab_affect.demo_export `
  --backend mujoco `
  --policy learned `
  --model-path models/learned_school_policy.pkl `
  --output outputs/special_education_benchmark_demo.html
```

启动 30 日学校沟通用 AI 助教 Demo：

```powershell
python -m src.rehab_affect.scenario_lab_server --host 127.0.0.1 --port 8791 --policy rule
```

打开：

```text
http://127.0.0.1:8791/education_demo
```

该页面演示“视频识别头 1 / 视频识别头 2 / 语音识别头 -> 时间线融合 -> 人物状态库 -> 教师端、学生端和机器人动作 JSON 输出”的完整闭环。当前使用公开课堂视频风格的匿名模拟切片，不含真实学生隐私；取得校方授权后替换为真实抽帧、ASR 与教师校准标签。

生成交互式控制台：

```powershell
python -m src.rehab_affect.interactive_console `
  --backend mujoco `
  --policy learned `
  --model-path models/learned_school_policy.pkl `
  --scenario-dir configs/scenarios `
  --compare-backend kinematic `
  --output outputs/interactive_benchmark_console.html
```

生成闭环动作反馈 benchmark 报告：

```powershell
python -m src.rehab_affect.closed_loop_report `
  --scenario-dir configs/scenarios `
  --backend kinematic `
  --policy learned `
  --model-path models/learned_school_policy.pkl `
  --json-output data/processed/closed_loop_benchmark.json `
  --html-output outputs/closed_loop_benchmark_report.html `
  --pretty
```

对比规则策略、原始学习策略、带 shield 学习策略：

```powershell
python -m src.rehab_affect.policy_compare `
  --backend kinematic `
  --model-path models/learned_school_policy.pkl `
  --scenario-dir configs/scenarios `
  --augmentations-per-scenario 2 `
  --output data/processed/policy_comparison.json `
  --pretty
```

生成云电脑前本地最终版：

```powershell
python -m src.rehab_affect.precloud_release `
  --benchmark-backend mujoco `
  --compare-backend kinematic `
  --release-manifest outputs/precloud_release_manifest.json `
  --final-report docs/final_precloud_report_zh.md `
  --pretty
```

生成演示总入口页：

```powershell
python -m src.rehab_affect.demo_launcher `
  --manifest outputs/precloud_release_manifest.json `
  --output outputs/demo_index.html `
  --pretty
```

启动课堂展示页和可编辑 Scenario Lab：

```powershell
python -m src.rehab_affect.scenario_lab_server `
  --host 127.0.0.1 `
  --port 8787 `
  --scenario-dir configs/scenarios `
  --model-path models/learned_school_policy.pkl `
  --policy learned
```

打开：

```text
http://127.0.0.1:8787/showcase
http://127.0.0.1:8787
http://127.0.0.1:8787?preset=pain
http://127.0.0.1:8787?scenario=shape_sorting_confused&loop=1
```

其中 `/showcase` 是面向汇报展示的一屏闭环入口：学生端任务、仿真课堂、教师端状态、`human_state`、`robot_action` 和整节课闭环报告会同时显示。

然后打开：

```text
outputs/special_education_benchmark_demo.html
```

导出 MuJoCo 场景截图：

```bash
python -m src.rehab_affect.mujoco_snapshot --scenario configs/scenarios/pain_risk_safety.json --output-dir outputs/mujoco_frames
```

运行 WebSocket 接口 demo：

```powershell
pip install -e ".[websocket]"
python -m src.rehab_affect.websocket_server `
  --backend mujoco `
  --policy learned `
  --model-path models/learned_school_policy.pkl `
  --scenario-dir configs/scenarios `
  --host 127.0.0.1 `
  --port 8765
```

生成 ROS2-style mock topic 日志：

```powershell
python -m src.rehab_affect.ros2_mock_publisher `
  --backend mujoco `
  --policy learned `
  --model-path models/learned_school_policy.pkl `
  --scenario-dir configs/scenarios `
  --output data/processed/ros2_mock_messages.jsonl
```

本地阶段生成的主要展示产物：

```text
models/learned_school_policy.pkl
data/processed/learned_policy_metrics.json
outputs/demo_index.html
outputs/special_education_benchmark_demo.html
outputs/interactive_benchmark_console.html
outputs/closed_loop_benchmark_report.html
outputs/playwright/interactive_benchmark_console.png
outputs/playwright/scenario_lab.png
outputs/playwright/scenario_lab_pain_risk.png
outputs/playwright/scenario_lab_closed_loop.png
outputs/playwright/classroom_showcase.png
outputs/playwright/classroom_showcase_closed_loop.png
outputs/playwright/classroom_showcase_mujoco.png
outputs/playwright/classroom_showcase_mujoco_closed_loop.png
outputs/mujoco_frames/pain_risk_safety_contact_sheet.png
data/processed/policy_comparison.json
data/processed/robustness_eval.json
data/processed/closed_loop_benchmark.json
outputs/precloud_release_manifest.json
docs/final_precloud_report_zh.md
data/processed/websocket_stream_sample.jsonl
data/processed/ros2_mock_messages.jsonl
```

输出示例：

```json
{
  "human_state": {
    "person_id": "user_001",
    "state": "fatigued",
    "confidence": 0.78,
    "evidence": ["face", "voice", "task_behavior"],
    "risk_level": "medium",
    "recommended_robot_action": "reduce_task_load_and_offer_break",
    "handoff_required": false
  },
  "robot_action": {
    "action_id": "reduce_task_load_and_offer_break",
    "speech_action": "offer_break",
    "motion_policy": "slow_down",
    "task_adjustment": "reduce_task_load",
    "safety_action": "monitor_fatigue",
    "priority": "medium"
  }
}
```

## Roadmap

1. MVP：摄像头/麦克风/mock 输入 + 规则识别器 + 时间平滑 + `human_state` JSON。
2. 训练：数据 schema、采集回放、baseline 模型、评估指标和实验记录。
3. 优化：融合权重、阈值、置信度校准、平滑策略、延迟和鲁棒性评估。
4. 仿真：MuJoCo/Isaac Sim 优先的辅读学校场景 benchmark，模拟课堂任务、学生状态、机器人距离、障碍物和动作反馈。
5. 接口：优先 WebSocket，随后 ROS2-style publisher，把状态发布给机器人控制端。
6. 展示：可运行 demo、日志、架构图、实验报告和简历项目包装。
