# 康复陪伴机器人情绪与状态感知项目方案

## 1. 项目定位

本项目面向残障陪伴与康复训练机器人，构建一个人类状态感知模块。它不做医学诊断，而是估计用户在交互过程中的状态线索，例如疲劳、困惑、疼痛疑似、烦躁、注意力下降和积极配合。

更专业的英文定位是：

```text
Human affect and rehabilitation state perception for assistive companion robots.
```

## 2. 为什么不能只用 pi0/pi0.5

pi0/pi0.5 是 VLA policy，主要负责：

```text
视觉观测 + 语言指令 + 机器人状态 -> 机器人动作
```

情绪与康复状态识别应该作为独立的 perception 模块：

```text
人脸 / 语音 / 姿态 / 交互行为 -> human_state
```

然后把 `human_state` 提供给上层策略或 VLA prompt：

```text
用户状态 = fatigued
机器人策略 = 降低训练强度，询问是否休息
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

可以用公开情绪数据做人脸/语音模型的预训练或参考，但不能直接当康复场景真值。

### 5.2 场景数据采集

康复场景每段样本建议 5-15 秒，标注内容包括：

- 用户状态：`engaged`、`confused`、`fatigued`、`frustrated`、`discomfort` 等。
- valence/arousal：连续情绪维度。
- 任务阶段：听指令、执行动作、等待反馈、休息。
- 机器人事件：指令内容、是否重复提醒、任务是否完成。
- 标注置信度：标注者对该标签的确定程度。

### 5.3 主动学习

上线测试后优先保存并标注这些片段：

- 模型低置信度。
- 多模态信号冲突。
- 用户明确反馈模型判断错误。
- 康复师认为值得修正的失败案例。

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
  "suggested_robot_action": "slow_down_and_offer_break",
  "timestamp": 1780000000.0
}
```

上层策略可以根据状态做规则或 LLM 决策：

| State | Robot Behavior |
| --- | --- |
| `confused` | 重复解释，换更简单的话 |
| `fatigued` | 放慢节奏，询问是否休息 |
| `discomfort` | 暂停任务，通知护理人员 |
| `frustrated` | 降低催促，提供鼓励 |
| `engaged` | 继续任务，给正反馈 |

## 7. 面试/沟通说法

可以这样讲：

```text
我会把这个需求拆成 Human State Perception 模块，而不是直接让机器人“判断真实情绪”。第一版先用 RGB 和麦克风做人脸表情、语音情绪、姿态与交互行为特征，再做多帧平滑和多模态融合，输出 state、valence、arousal、confidence 和 suggested action。模型低置信度时不触发强决策，涉及 discomfort 时只做暂停和提醒护理人员，避免误判带来的风险。
```

