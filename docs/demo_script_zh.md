# Demo 演示脚本

## 1. 演示目标

本 demo 展示一个面向辅读学校辅助机器人的具身智能 benchmark：

```text
学生语音/姿态/课堂任务线索
  -> human_state
机器人距离/障碍物/任务上下文
  -> robot_context
具身动作策略
  -> robot_action
MuJoCo/kinematic benchmark
  -> safety and action metrics
```

重点不是普通情绪识别，而是机器人最终动作：

```text
speech_action + motion_policy + task_adjustment + safety_action
```

## 2. 一键运行

```bash
cd D:/GIT/RehabAffectPerception
python -m src.rehab_affect.train_policy --scenario-dir configs/scenarios --output models/learned_school_policy.pkl --metrics-output data/processed/learned_policy_metrics.json --benchmark-backend mujoco --augmentations-per-scenario 8 --eval-ratio 0.25 --seed 123 --pretty
python -m src.rehab_affect.sim_runner --backend mujoco --policy learned --model-path models/learned_school_policy.pkl --scenario-dir configs/scenarios --summary-only --pretty
python -m src.rehab_affect.demo_export --backend mujoco --policy learned --model-path models/learned_school_policy.pkl --output outputs/special_education_benchmark_demo.html
python -m src.rehab_affect.interactive_console --backend mujoco --policy learned --model-path models/learned_school_policy.pkl --scenario-dir configs/scenarios --compare-backend kinematic --output outputs/interactive_benchmark_console.html
python -m src.rehab_affect.policy_compare --backend kinematic --model-path models/learned_school_policy.pkl --scenario-dir configs/scenarios --augmentations-per-scenario 2 --output data/processed/policy_comparison.json --pretty
python -m src.rehab_affect.robustness_eval --backend kinematic --model-path models/learned_school_policy.pkl --scenario-dir configs/scenarios --augmentations-per-scenario 4 --output data/processed/robustness_eval.json --pretty
python -m src.rehab_affect.precloud_release --benchmark-backend mujoco --compare-backend kinematic --release-manifest outputs/precloud_release_manifest.json --final-report docs/final_precloud_report_zh.md --pretty
python -m src.rehab_affect.demo_launcher --manifest outputs/precloud_release_manifest.json --output outputs/demo_index.html --pretty
python -m src.rehab_affect.mujoco_snapshot --scenario configs/scenarios/pain_risk_safety.json --output-dir outputs/mujoco_frames
python -m src.rehab_affect.websocket_server --backend mujoco --policy learned --model-path models/learned_school_policy.pkl --scenario-dir configs/scenarios --dump-jsonl
python -m src.rehab_affect.ros2_mock_publisher --backend mujoco --policy learned --model-path models/learned_school_policy.pkl --scenario-dir configs/scenarios --output data/processed/ros2_mock_messages.jsonl
python -m src.rehab_affect.scenario_lab_server --host 127.0.0.1 --port 8787 --scenario-dir configs/scenarios --model-path models/learned_school_policy.pkl --policy learned
```

最后一条命令是持续运行的本地网页服务，演示时最后启动即可。

打开：

```text
http://127.0.0.1:8787
http://127.0.0.1:8787?preset=pain
http://127.0.0.1:8787?scenario=shape_sorting_confused&loop=1
D:/GIT/RehabAffectPerception/outputs/demo_index.html
D:/GIT/RehabAffectPerception/outputs/special_education_benchmark_demo.html
```

## 3. 演示讲法

第一句话：

```text
这个项目是一个面向辅读学校辅助机器人的具身学生状态感知与动作决策 benchmark。
它不做医学诊断，也不是普通情绪分类，而是让机器人根据学生状态、课堂任务和环境上下文输出可执行动作。
```

第二步展示指标：

```text
当前 benchmark 包含 6 个场景、18 个仿真 step。
每个 step 都有学生线索、机器人上下文、human_state、robot_action 和安全评估。
动作策略包含规则 oracle 和一个本地训练的 LearnedSchoolPolicy baseline。
训练集通过 domain randomization 从原始 18 step 扩展到 126 个训练 step，并保留 36 个 holdout step 做验证。
```

第三步展示关键场景：

| 场景 | 讲解重点 |
| --- | --- |
| `shape_sorting_confused` | 学生说“我不会”，机器人保持位置、慢速重复说明、简化下一步 |
| `task_load_fatigue` | 学生说“有点累”，机器人降低任务负荷、询问休息 |
| `refusal_respect` | 学生拒绝继续，机器人暂停任务、确认意愿、保持距离 |
| `pain_risk_safety` | 学生说疼或不舒服，机器人停止运动、暂停任务、通知教师/照护者 |
| `low_attention_obstacle` | 学生注意力低且附近有障碍，机器人停止移动并重新吸引注意 |
| `needs_help_handoff` | 学生请求帮助，机器人提供帮助并必要时交接教师 |

第四步强调具身智能：

```text
系统不只输出学生状态，还把状态和机器人上下文结合起来。
例如 low_attention 本身不一定要求停止，但当 robot_context 里 is_robot_moving=true 且 obstacle_distance_m 很近时，
robot_action.motion_policy 会变成 stop_motion。
```

第五步现场改 Scenario Lab：

```text
打开 http://127.0.0.1:8787。
把 speech 改成“我疼，不想动”，勾选 pain guarding，并保持 robot moving=true。
系统会重新调用 Python pipeline，把 human_state 切到 pain_risk，
并输出 stop_and_check_pain_risk / stop_motion / notify_teacher。
```

第六步讲 MuJoCo/Isaac Sim 路线：

```text
第一版用 MuJoCo/kinematic classroom backend 验证 benchmark、动作策略和指标体系。
下一步可以把同一套 Scenario、StudentAgent、RobotContext 和 RobotAction 接到 Isaac Sim，
升级成更真实的辅读学校教室、摄像头视角、ROS2 接口和演示视频。
```

## 4. 预期结果

当前 MuJoCo benchmark summary：

```text
scenario_count: 6
step_count: 18
action_match_accuracy: 100.0%
safety_violation_count: 0
intervention_count: 12
holdout_action_accuracy: 97.2%
holdout_safety_violation_count: 0
```

本地展示文件：

```text
D:/GIT/RehabAffectPerception/outputs/special_education_benchmark_demo.html
D:/GIT/RehabAffectPerception/outputs/demo_index.html
D:/GIT/RehabAffectPerception/outputs/interactive_benchmark_console.html
D:/GIT/RehabAffectPerception/outputs/playwright/interactive_benchmark_console.png
D:/GIT/RehabAffectPerception/outputs/playwright/scenario_lab.png
D:/GIT/RehabAffectPerception/outputs/playwright/scenario_lab_pain_risk.png
D:/GIT/RehabAffectPerception/outputs/playwright/scenario_lab_closed_loop.png
D:/GIT/RehabAffectPerception/outputs/mujoco_frames/pain_risk_safety_contact_sheet.png
D:/GIT/RehabAffectPerception/data/processed/learned_policy_metrics.json
D:/GIT/RehabAffectPerception/data/processed/policy_comparison.json
D:/GIT/RehabAffectPerception/data/processed/robustness_eval.json
D:/GIT/RehabAffectPerception/outputs/precloud_release_manifest.json
D:/GIT/RehabAffectPerception/docs/final_precloud_report_zh.md
D:/GIT/RehabAffectPerception/data/processed/websocket_stream_sample.jsonl
D:/GIT/RehabAffectPerception/data/processed/ros2_mock_messages.jsonl
```

## 5. 面试版总结

```text
I built a simulation-first embodied AI benchmark for assistive robots in special education schools.
The system estimates student states from multimodal cues, combines them with robot context,
and outputs structured robot actions for speech, motion, task adjustment, and safety handoff.
I evaluated the policy across MuJoCo-style classroom scenarios using action accuracy,
safety violations, handoff latency, and distance-based safety metrics.
```
