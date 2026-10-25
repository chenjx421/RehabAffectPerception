# 辅读学校辅助机器人状态感知与动作决策项目方案

## 1. 项目定位

本项目面向辅读学校/特殊教育支持场景，构建一个辅助机器人具身感知与动作决策模块。它不做医学诊断，也不替代教师，而是估计学生在课堂任务、生活技能训练或互动练习中的状态线索，例如专注、困惑、疲劳、挫败、抗拒、注意力下降、需要帮助或疑似不适风险。

更专业的英文定位是：

```text
Embodied student-state perception and action decision for assistive robots in special education schools.
```

## 2. 为什么不能只用 pi0/pi0.5

pi0/pi0.5 是 VLA policy，主要负责：

```text
视觉观测 + 语言指令 + 机器人状态 -> 机器人动作
```

学生状态识别应该作为独立的 perception 模块：

```text
人脸 / 语音 / 姿态 / 交互行为 -> human_state
```

然后把 `human_state` 提供给上层策略或 VLA prompt：

```text
用户状态 = fatigued
机器人策略 = 降低任务负荷，询问是否休息
```

## 3. 推荐硬件

最低可行版本：

- RGB 摄像头：做人脸、表情、注意力。
- 麦克风：做语音情绪、语速、停顿、求助词。
- GPU 主机或边缘计算设备：运行视觉/语音模型。

更完整版本：

- RGB-D 相机：增加人体姿态和距离估计。
- 麦克风阵列：声源定位和更稳的语音采集。
- 机器人本体相机：补充交互场景视角。
- ROS2/WebSocket 接口：向机器人上层策略发布 human_state。

## 4. 第一版 MVP

第一版不要追求大模型端到端，先做可解释的模块化系统：

```text
camera frame
  -> face detection / face emotion
microphone
  -> voice emotion / ASR text sentiment
pose
  -> attention / fatigue cues
task logs
  -> delay, repeated failure, request for help
all signals
  -> temporal smoothing
  -> multimodal fusion
  -> human_state JSON
```

## 5. 数据策略

### 5.1 公开数据 warm start

可以用公开情绪、语音、姿态或课堂行为数据做人脸/语音/姿态模型的预训练或参考，但不能直接当辅读学校场景真值。

### 5.2 场景数据采集

辅读学校场景每段样本建议 5-15 秒，标注内容包括：

- 用户状态：`engaged`、`confused`、`fatigued`、`frustrated`、`refusing`、`pain_risk`、`needs_help` 等。
- valence/arousal：连续情绪维度。
- 任务阶段：听指令、尝试任务、等待反馈、休息/安静角。
- 机器人事件：指令内容、是否分步骤提示、是否重复提醒、任务是否完成。
- 标注置信度：标注者对该标签的确定程度。

### 5.3 主动学习

上线测试后优先保存并标注这些片段：

- 模型低置信度。
- 多模态信号冲突。
- 用户明确反馈模型判断错误。
- 教师、特教老师或照护者认为值得修正的失败案例。

## 6. 与机器人策略的接口

建议输出 JSON：

```json
{
  "person_id": "user_001",
  "state": "fatigued",
  "valence": -0.35,
  "arousal": 0.22,
  "confidence": 0.78,
  "evidence": ["face", "voice", "task_behavior"],
  "recommended_robot_action": "reduce_task_load_and_offer_break",
  "risk_level": "medium",
  "handoff_required": false,
  "timestamp": 1780000000.0
}
```

上层策略可以根据状态做规则或 LLM 决策：

| State | Robot Behavior |
| --- | --- |
| `confused` | 重复解释，换更简单的话 |
| `fatigued` | 降低任务负荷，询问是否休息 |
| `pain_risk` | 暂停任务，询问不适并通知教师或照护者 |
| `frustrated` | 降低催促，提供鼓励 |
| `refusing` | 暂停，询问是否继续并提供选择 |
| `needs_help` | 提供协助或呼叫教师/照护者 |
| `engaged` | 继续任务，给正反馈 |

## 7. 面试/沟通说法

可以这样讲：

```text
我会把这个需求拆成 Student-State Perception 和 Embodied Action Policy 两层，而不是直接让机器人“判断真实情绪”。第一版先用 RGB、麦克风、姿态与课堂任务行为特征做多帧平滑和多模态融合，输出 human_state，再结合机器人距离、障碍物、任务阶段等 robot_context 生成 robot_action。模型低置信度时不触发强决策，涉及 pain_risk、needs_help 或 refusing 时只做暂停、询问、保持距离和提醒教师/照护者，避免误判带来的风险。
```
