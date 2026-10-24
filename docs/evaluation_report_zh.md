# Benchmark 评估报告

## 1. 实验设置

项目场景：辅读学校/特殊教育支持环境。  
仿真后端：MuJoCo classroom backend，可退回 kinematic backend。  
场景数量：6。  
总 step 数：18。  
策略模型：

- `RuleRobotPolicy`：安全优先的 oracle / fallback baseline。
- `LearnedSchoolPolicy`：从 benchmark 场景训练得到的轻量动作策略 baseline，输入 `human_state + robot_context`，输出最终 `robot_action`。

运行命令：

```bash
python -m src.rehab_affect.sim_runner --backend mujoco --scenario-dir configs/scenarios --summary-only --pretty
python -m src.rehab_affect.train_policy --scenario-dir configs/scenarios --output models/learned_school_policy.pkl --metrics-output data/processed/learned_policy_metrics.json --benchmark-backend mujoco --augmentations-per-scenario 8 --eval-ratio 0.25 --seed 123 --pretty
python -m src.rehab_affect.sim_runner --backend mujoco --policy learned --model-path models/learned_school_policy.pkl --scenario-dir configs/scenarios --summary-only --pretty
```

## 2. 场景覆盖

| 场景 | 学生状态 | 期望机器人动作 |
| --- | --- | --- |
| `shape_sorting_confused` | 困惑 | 慢速重复说明、简化下一步、保持位置 |
| `task_load_fatigue` | 疲劳/任务负荷高 | 降低任务负荷、询问休息、放慢节奏 |
| `refusal_respect` | 拒绝继续 | 暂停任务、确认意愿、保持距离 |
| `pain_risk_safety` | 疑似不适风险 | 停止运动、暂停任务、通知教师/照护者 |
| `low_attention_obstacle` | 注意力低 + 障碍近 | 停止运动、重新吸引注意 |
| `needs_help_handoff` | 请求帮助 | 提供帮助，必要时交接教师/照护者 |

## 3. 指标结果

| 指标 | 当前结果 |
| --- | --- |
| `scenario_count` | 6 |
| `step_count` | 18 |
| `action_match_accuracy` | 100.0% |
| `safety_violation_count` | 0 |
| `intervention_count` | 12 |

`LearnedSchoolPolicy` 训练数据：

| 项目 | 当前结果 |
| --- | --- |
| 训练来源 | 6 个辅读学校 scenario + domain randomization |
| 原始 step | 18 |
| 训练 step | 126 |
| holdout step | 36 |
| 特征数量 | 48 |
| 动作标签数量 | 7 |
| 训练集动作准确率 | 100.0% |
| holdout 动作准确率 | 97.2% |
| holdout 安全违规 | 0 |
| MuJoCo benchmark 动作命中率 | 100.0% |
| MuJoCo benchmark 安全违规 | 0 |

说明：该指标是 scenario-derived + domain-randomized baseline，用来证明训练、评估和仿真闭环可运行；不能宣称真实世界泛化能力。

高风险交接场景：

| 场景 | handoff latency |
| --- | --- |
| `pain_risk_safety` | 0 step |
| `needs_help_handoff` | 0 step |

## 4. 结论

第一版 benchmark 证明了主链路可行：

```text
Scenario cues
  -> HumanState
  -> RobotContext
  -> RobotAction
  -> Safety and action metrics
```

系统能够在 `pain_risk` 和 `needs_help` 场景中立即输出交接动作，在 `low_attention_obstacle` 场景中停止机器人运动，在 `refusal_respect` 场景中暂停并尊重学生意愿。

## 5. 局限

- 当前学生是 proxy agent，不是真实学生 avatar。
- MuJoCo 场景是轻量几何体，不是高保真教室。
- `LearnedSchoolPolicy` 当前训练于小规模合成 scenario 和本地 domain randomization，适合作为实习项目第一版 baseline；真实泛化需要更多仿真随机化和真实采集样本。
- 语音线索当前主要来自 scenario transcript，后续可接 TTS/ASR。
- 视觉线索当前主要来自结构化姿态/注意力字段，后续可接 Isaac Sim camera 或真实摄像头。

## 6. 下一步

1. 扩展 MuJoCo scenario 随机化，生成更大规模训练集。
2. 将相同 scenario schema 映射到 Isaac Sim，生成高保真可视化 demo。
3. 接 WebSocket/ROS2 mock，让 `robot_action` 可以被机器人控制端订阅。
4. 加入真实摄像头/麦克风 demo，对比 sim2real 行为一致性。
