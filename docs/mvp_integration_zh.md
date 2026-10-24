# 第一版 MVP 与接口接入方案

## 1. 当前 MVP 模块边界

第一版保持可解释、可替换、可降级：

```text
inputs.py
  CameraInput / MicrophoneInput / MockInputSource
      -> InputBatch
recognizers.py
  FaceStateRecognizer / VoiceStateRecognizer / PoseStateRecognizer / TaskBehaviorRecognizer
      -> ModalitySignal
smoothing.py
  TemporalSmoother per modality
      -> smoothed ModalitySignal
fusion.py
  fuse_signals
      -> HumanState
policy.py
  RuleRobotPolicy
      -> RobotAction
mvp.py
  command line runner
      -> JSONL human_state + robot_action output
websocket_server.py
  WebSocket benchmark stream
      -> perception_decision messages
ros2_mock_publisher.py
  Windows local ROS2-style mock
      -> /rehab_affect/human_state and /rehab_affect/robot_action JSONL
```

没有摄像头、麦克风或模型权重时，用模拟流跑完整链路：

```bash
python -m src.rehab_affect.mvp --mode mock --steps 10
```

有硬件时安装可选依赖：

```bash
pip install -e ".[input]"
python -m src.rehab_affect.mvp --mode live --camera --microphone --steps 20
```

## 2. 多模态识别器的替换点

当前识别器是轻量规则版，目标是先打通系统，而不是宣称已经有高精度情绪模型。

### 2.1 摄像头/人脸

`CameraFrame.metadata` 支持这些字段：

```json
{
  "face_detected": true,
  "attention_score": 0.82,
  "emotion_probs": {
    "neutral": 0.5,
    "tired": 0.3,
    "pain": 0.2
  },
  "valence": -0.2,
  "arousal": 0.35
}
```

后续可把 OpenCV/MediaPipe/ONNX/DeepFace 类模型输出写入 `emotion_probs` 和 `attention_score`，不需要重写 pipeline。

### 2.2 麦克风/语音

`AudioChunk.metadata` 支持：

```json
{
  "transcript": "有点累，想休息",
  "sentiment": "negative",
  "speech_rate": 0.42
}
```

后续可以接 Whisper/paraformer 做 ASR，接 wav2vec2/Hubert 类模型做语音情绪，再把文本和语音特征交给 `VoiceStateRecognizer` 或替换成模型版 recognizer。

### 2.3 姿态/RGB-D

`InputBatch.pose_features` 支持：

```json
{
  "attention_score": 0.45,
  "movement_speed": 0.12,
  "pain_guarding": false
}
```

后续可接 MediaPipe Pose、MoveNet、RealSense/OpenPose 风格的骨架特征，用于判断注意力下降、运动速度下降、保护性姿势等线索。

### 2.4 任务行为

`TaskBehavior` 表示机器人侧事件：

```json
{
  "instruction_repeated": 1,
  "response_delay_sec": 3.4,
  "recent_failure_count": 1,
  "request_text": "需要帮忙"
}
```

这是辅读学校课堂任务里很重要的信号，因为疲劳、困惑、需要帮助或抗拒往往出现在任务进展、提示次数和交互节奏里。

## 3. human_state 与 robot_action JSON 契约

MVP 每一行输出一个 JSON，`human_state` 是状态估计，`robot_action` 才是最终给机器人执行层或策略层消费的动作决策：

```json
{
  "human_state": {
    "person_id": "user_001",
    "state": "fatigued",
    "confidence": 0.78,
    "valence": -0.35,
    "arousal": 0.22,
    "evidence": ["face", "voice", "task_behavior"],
    "recommended_robot_action": "reduce_task_load_and_offer_break",
    "risk_level": "medium",
    "handoff_required": false,
    "timestamp": 1780000000.0
  },
  "robot_action": {
    "action_id": "reduce_task_load_and_offer_break",
    "speech_action": "offer_break",
    "motion_policy": "slow_down",
    "task_adjustment": "reduce_task_load",
    "safety_action": "monitor_fatigue",
    "priority": "medium",
    "handoff_required": false
  }
}
```

建议机器人上层策略按三层处理：

- `confidence < 0.4`：只作为弱提示，不改变关键动作。
- `confused/fatigued/low_attention/frustrated`：调整交互节奏、解释方式和任务强度。
- `pain_risk/needs_help/refusing`：保守触发暂停、询问、保持距离，并提醒教师或照护者。

## 4. ROS2 接入方案

第一步可用 `std_msgs/msg/String` 发布 JSON，减少自定义消息带来的集成成本：

```text
Node: rehab_affect_node
Publish:
  /rehab_affect/human_state    std_msgs/msg/String
  /rehab_affect/robot_action   std_msgs/msg/String
Subscribe:
  /rehab_affect/task_behavior  std_msgs/msg/String
Parameters:
  person_id
  camera_index
  sample_rate
  smooth_window
  publish_hz
```

后续稳定后建议定义自定义消息：

```text
builtin_interfaces/Time stamp
string person_id
string state
float32 confidence
float32 valence
float32 arousal
string[] evidence
string recommended_robot_action
string risk_level
bool handoff_required
```

节点逻辑：

```text
camera/microphone/task events
  -> RehabAffectPipeline.process_batch()
  -> HumanState + RobotAction
  -> publish /rehab_affect/human_state
  -> publish /rehab_affect/robot_action
```

发布频率建议 1-2 Hz；内部识别可以更高频，输出前通过 `TemporalSmoother` 平滑。`pain_risk` 和 `needs_help` 这类安全状态允许绕过部分平滑，以免被窗口延迟压住。

## 5. WebSocket 接入方案

适合非 ROS 的网页控制台、上层策略服务或远程评估工具：

```text
ws://<host>:8765/rehab_affect
```

服务端主动推送：

```json
{
  "type": "perception_decision",
  "payload": {
    "human_state": {
      "person_id": "user_001",
      "state": "fatigued",
      "confidence": 0.78,
      "evidence": ["face", "voice"],
      "risk_level": "medium"
    },
    "robot_action": {
      "action_id": "reduce_task_load_and_offer_break",
      "speech_action": "offer_break",
      "motion_policy": "slow_down",
      "task_adjustment": "reduce_task_load",
      "safety_action": "monitor_fatigue"
    }
  }
}
```

客户端回传机器人事件：

```json
{
  "type": "task_behavior",
  "payload": {
    "instruction_repeated": 1,
    "response_delay_sec": 3.4,
    "recent_failure_count": 1,
    "request_text": null
  }
}
```

当前已经提供本地 WebSocket server：

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

也可以不启动服务，直接导出 WebSocket 消息样例：

```powershell
python -m src.rehab_affect.websocket_server `
  --backend mujoco `
  --policy learned `
  --model-path models/learned_school_policy.pkl `
  --scenario-dir configs/scenarios `
  --dump-jsonl
```

ROS2 在 Windows 本地先用 mock publisher 输出 `std_msgs/msg/String` 等价 JSONL：

```powershell
python -m src.rehab_affect.ros2_mock_publisher `
  --backend mujoco `
  --policy learned `
  --model-path models/learned_school_policy.pkl `
  --scenario-dir configs/scenarios `
  --output data/processed/ros2_mock_messages.jsonl
```

真实 ROS2 node 和 Isaac Sim bridge 放到 Linux/NVIDIA 云电脑阶段联调。

## 6. 下一步开发顺序

1. 接真实 ASR，把 `transcript` 写入 `AudioChunk.metadata`。
2. 接人脸/姿态模型，把 `emotion_probs`、`attention_score`、`movement_speed` 写入输入 metadata。
3. 建立 5-15 秒 clip 标注和回放工具，用真实或仿真的辅读学校课堂交互片段校准规则和阈值。
4. 在云电脑上实现真实 ROS2 node 和 Isaac Sim bridge。
5. 为 `pain_risk/needs_help` 建立更大规模安全回归测试，避免后续模型替换时削弱保守行为。
