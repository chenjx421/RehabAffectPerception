# 数据采集与标注格式

## 1. Episode 级数据

一次康复交互可以定义为一个 episode：

```json
{
  "episode_id": "session_20260604_0001_ep0001",
  "user_id_hash": "u_7f3a",
  "task": "raise_left_arm",
  "robot_instruction": "请慢慢抬起左手",
  "start_time": 1780000000.0,
  "end_time": 1780000012.0,
  "success": true,
  "notes": "User completed movement but showed fatigue near the end."
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
  "task_stage": "movement_execution",
  "visible_cues": ["slow_motion", "downward_gaze", "long_pause"],
  "annotator_role": "rehab_assistant"
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
    "recent_failure_count": 1
  }
}
```

## 4. 数据质量规则

采集时重点检查：

- 图像里是否能看到用户脸部或身体关键部位。
- 音频是否有明显噪声或多人同时说话。
- 标签是否和任务阶段对应。
- 同一片段是否存在多个冲突标签。
- 是否涉及隐私信息，需要脱敏或删除。
- 是否有用户或监护人授权。

## 5. 为什么要个体化校准

康复/残障用户的表情、语音和动作可能与公开数据集分布不同。同一个 `neutral` 状态，不同用户的面部肌肉张力、语速、运动幅度可能差异很大。

因此建议每个用户建立 baseline：

```text
前 3-5 分钟自然交互
-> 记录 neutral / comfortable 状态
-> 后续判断相对变化，而不是只看绝对阈值
```

