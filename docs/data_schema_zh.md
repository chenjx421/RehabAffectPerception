# 数据采集与标注格式

## 0. 状态标签集合

标注和模型输出统一使用面向辅读学校课堂/训练交互的状态，而不是泛化的开心/难过分类：

| Label | 含义 | 风险等级 | 机器人响应原则 |
| --- | --- | --- | --- |
| `engaged` | 专注/参与 | low | 继续任务并鼓励 |
| `neutral` | 正常/无明显异常 | low | 保持当前节奏 |
| `confused` | 困惑 | medium | 放慢语速，重复说明 |
| `fatigued` | 疲劳/任务负荷过高 | medium | 降低任务负荷，询问是否休息 |
| `frustrated` | 挫败/烦躁 | medium | 暂停催促，降低压力 |
| `refusing` | 抗拒/拒绝继续 | medium | 暂停，询问意愿并提供选择 |
| `pain_risk` | 疑似疼痛或不适风险 | high | 立即暂停，询问并提醒教师/照护者 |
| `low_attention` | 注意力下降 | medium | 重新吸引注意力或简化任务 |
| `needs_help` | 需要帮助 | high | 提供协助或呼叫教师/照护者 |

兼容旧标签：`discomfort` 视为 `pain_risk`，`need_help` 视为 `needs_help`。

## 1. Episode 级数据

一次课堂任务或生活技能训练交互可以定义为一个 episode：

```json
{
  "episode_id": "session_20260604_0001_ep0001",
  "user_id_hash": "u_7f3a",
  "task": "shape_sorting",
  "robot_instruction": "请把红色积木放到圆形盒子里",
  "start_time": 1780000000.0,
  "end_time": 1780000012.0,
  "success": true,
  "notes": "Student completed the task but showed fatigue near the end."
}
```

## 2. Clip 级标注

每段短视频/音频片段 5-15 秒：

```json
{
  "clip_id": "ep0001_clip0003",
  "episode_id": "session_20260604_0001_ep0001",
  "time_range": [6.0, 12.0],
  "state_label": "fatigued",
  "valence": -0.35,
  "arousal": 0.22,
  "label_confidence": 0.85,
  "task_stage": "task_attempt",
  "visible_cues": ["slow_response", "downward_gaze", "long_pause"],
  "annotator_role": "special_education_teacher"
}
```

## 3. Frame / Feature 级数据

实际训练时不一定保存原始视频到云端，可以保存脱敏后的特征：

```json
{
  "timestamp": 1780000007.2,
  "face": {
    "detected": true,
    "emotion_probs": {
      "neutral": 0.3,
      "sad": 0.2,
      "tired": 0.4,
      "happy": 0.1
    },
    "valence": -0.3,
    "arousal": 0.2
  },
  "voice": {
    "detected": true,
    "energy": 0.24,
    "speech_rate": 0.5,
    "sentiment": "negative"
  },
  "pose": {
    "attention_score": 0.42,
    "movement_speed": 0.18
  },
  "task_behavior": {
    "instruction_repeated": 1,
    "response_delay_sec": 3.4,
    "recent_failure_count": 1,
    "request_text": "有点累，想休息"
  }
}
```

## 4. HumanState 输出 JSON

机器人策略先消费 `human_state`，再输出真正给执行层使用的 `robot_action`：

```json
{
  "timestamp": 1780000007.2,
  "person_id": "user_001",
  "state": "fatigued",
  "confidence": 0.78,
  "valence": -0.35,
  "arousal": 0.22,
  "evidence": ["face", "voice", "task_behavior"],
  "risk_level": "medium",
  "recommended_robot_action": "reduce_task_load_and_offer_break",
  "handoff_required": false,
  "metadata": {
    "state_scores": {
      "fatigued": 1.82,
      "low_attention": 0.76
    }
  }
}
```

字段约定：

- `state`：使用上方状态标签集合。
- `confidence`：融合后置信度，范围 `[0, 1]`。
- `evidence`：触发当前状态的模态来源，例如 `face`、`voice`、`pose`、`task_behavior`。
- `risk_level`：`low`、`medium`、`high`，用于机器人动作安全分级。
- `recommended_robot_action`：给上层策略的保守动作建议。
- `handoff_required`：是否建议通知教师、班主任、特教老师或照护者。
- `metadata`：可选调试信息，不应包含未经脱敏的隐私数据。

## 5. RobotAction 输出 JSON

最终决策必须落到机器人动作上，至少拆成语音、运动、任务调整和安全处理四类：

```json
{
  "action_id": "reduce_task_load_and_offer_break",
  "speech_action": "offer_break",
  "motion_policy": "slow_down",
  "task_adjustment": "reduce_task_load",
  "safety_action": "monitor_fatigue",
  "priority": "medium",
  "reason": "Fatigue cues should reduce workload before frustration or risk escalates.",
  "target_state": "fatigued",
  "confidence": 0.78,
  "handoff_required": false,
  "timestamp": 1780000007.2
}
```

评估时不只看 `state` 是否正确，也要看 `robot_action` 是否符合辅读学校场景的安全、尊重、克制和教师可接管原则。

## 6. 数据质量规则

采集时重点检查：

- 图像里是否能看到用户脸部或身体关键部位。
- 音频是否有明显噪声或多人同时说话。
- 标签是否和任务阶段对应。
- 同一片段是否存在多个冲突标签。
- 是否涉及隐私信息，需要脱敏或删除。
- 是否有用户或监护人授权。

## 7. 为什么要个体化校准

辅读学校学生的表情、语音、动作和课堂反应可能与公开数据集分布不同。同一个 `neutral` 状态，不同学生的面部肌肉张力、语速、运动幅度、注意力表现可能差异很大。

因此建议每个用户建立 baseline：

```text
前 3-5 分钟自然交互
-> 记录 neutral / comfortable 状态
-> 后续判断相对变化，而不是只看绝对阈值
```
