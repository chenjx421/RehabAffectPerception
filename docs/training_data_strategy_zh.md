# 训练数据策略

## 1. 第一版数据从哪里来

第一版不要求真实学生录像，也不使用敏感个人数据。数据来自三层：

| 层级 | 来源 | 作用 |
| --- | --- | --- |
| Base scenario | 人工设计的 6 个辅读学校场景 | 定义任务、状态变化、机器人上下文和期望动作 |
| Domain randomization | 本地脚本随机化语音、距离、注意力、速度、延迟等字段 | 扩大训练集，测试策略对轻微变化是否稳健 |
| Holdout variants | 每个场景族留出的随机化变体 | 做非训练样本评估 |

当前生成方式：

```text
6 base scenarios x 3 steps = 18 raw steps
8 randomized variants per scenario
train split = 126 steps
holdout split = 36 steps
```

## 2. 随机化哪些字段

`scenario_randomizer.py` 保留这些字段不变：

- `ground_truth_state`
- `expected_action_id`
- 场景任务目标
- 安全语义，例如 pain_risk 必须停止，refusing 必须尊重意愿

随机化这些可观测字段：

- `speech_text`
- `voice_amplitude`
- `face_confidence`
- `attention_score`
- `movement_speed`
- `response_delay_sec`
- `robot_distance_m`
- `obstacle_distance_m`
- `task_difficulty`

这样做的目的不是制造“真实世界数据”，而是让本地 baseline 不只记住 18 个固定样本。

## 3. 当前模型

本地第一版模型：

```text
LearnedSchoolPolicy
  feature: human_state + robot_context + task_stage + visible_objects
  model: DecisionTreeClassifier
  output: robot_action.action_id
  shield: state/action safety prior
```

动作不是自由文本，而是固定机器人动作集合：

- `continue_and_encourage`
- `repeat_instruction_slowly`
- `reduce_task_load_and_offer_break`
- `pause_and_request_consent`
- `stop_and_check_pain_risk`
- `regain_attention`
- `offer_help`

## 4. 当前评估结果

| 指标 | 结果 |
| --- | --- |
| 训练 step | 126 |
| holdout step | 36 |
| feature count | 48 |
| 训练集动作准确率 | 100.0% |
| holdout 动作准确率 | 97.2% |
| holdout 安全违规 | 0 |
| MuJoCo base benchmark 动作命中率 | 100.0% |
| MuJoCo base benchmark 安全违规 | 0 |

说明：这是 scenario-derived + domain-randomized baseline，只说明训练、验证、仿真和动作输出闭环已经可运行。

## 5. 后续真实数据怎么接

真实数据不需要一开始就采集儿童隐私视频。建议分三步：

1. 使用成人/同学模拟课堂交互，只保存结构化特征和转写文本，不保存原始人脸视频。
2. 每段 5-15 秒 clip 标注 `human_state` 和期望 `robot_action`。
3. 将真实样本转换成同一套 scenario step schema，用于校准 recognizer、fusion threshold 和 action policy。

真实数据 schema 与仿真数据保持一致：

```text
observable_cues + robot_context + ground_truth_state + expected_action_id
```

这样可以直接复用当前训练、评估、WebSocket 和 ROS2 mock 工程链路。
