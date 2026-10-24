# 具身智能模型接入策略

本项目的模型栈分三层，而不是只选一个模型解决全部问题：

```text
Perception Models
  YOLO / MediaPipe / Whisper
  -> objects, pose, voice text, affect cues

Human-State Module
  temporal smoothing + multimodal fusion
  -> human_state

Embodied Policy / VLA Models
  OpenPI / pi0 / pi0.5 style VLA or simulated VLA adapter
  -> high-level robot action or low-level action chunk
```

## 1. 为什么要加入 pi / OpenPI

π0、π0.5 这类模型属于 Vision-Language-Action，也就是 VLA。它们和 YOLO、Whisper 不一样：

| 模型 | 输入 | 输出 | 在本项目里的角色 |
| --- | --- | --- | --- |
| YOLO | 图像 | object boxes | 环境物体识别 |
| MediaPipe | 图像 | face/pose landmarks | 人脸、姿态、动作线索 |
| Whisper | 音频 | transcript | 用户语言线索 |
| RehabAffectPipeline | 多模态特征 | `human_state` | 辅读学校课堂/训练交互状态估计 |
| OpenPI / π0 / π0.5 | 图像、语言、机器人状态 | robot action | 具身动作策略候选 |

所以 pi 不是拿来做“用户疲劳识别”的主模型，而是更适合作为：

```text
human_state + robot_context + instruction
-> embodied action policy
```

例如：

```text
Instruction: assist the student through a classroom shape-sorting task
Human state: fatigued
Robot context: obstacle near robot, student seated
Policy output: reduce task load, stop approaching, ask whether to rest
```

## 2. 为什么第一阶段不直接跑 pi

当前项目机器是 Intel i5 + 16 GB RAM + Intel UHD，无 NVIDIA CUDA GPU。OpenPI 这类 VLA 模型对环境和算力要求明显高于普通感知模型。

因此两个月项目里采用“显式接入、轻量模拟、后续替换”的路线：

```text
Phase A: VLA-style policy adapter
  用统一接口模拟 pi 的输入输出

Phase B: OpenPI research integration
  阅读 openpi 接口，设计 action schema 和 robot adapter

Phase C: GPU/Ubuntu 条件满足后
  真实跑 π0 / π0.5 inference 或 fine-tuning experiment
```

这样项目仍然紧贴具身智能，但不会被本地硬件卡死。

## 3. 本项目建议的 VLA 接口

新增一个抽象接口：

```python
class EmbodiedPolicyModel:
    def predict_action(
        self,
        instruction: str,
        human_state: HumanState,
        robot_context: RobotContext,
        observation: dict,
    ) -> RobotAction:
        ...
```

第一版可以实现两个 backend：

| Backend | 作用 |
| --- | --- |
| `RuleEmbodiedPolicy` | 当前可运行的规则策略 |
| `MockPiPolicy` | 模拟 pi/VLA 的输入输出，便于项目展示 |

未来再加：

| Backend | 作用 |
| --- | --- |
| `OpenPIClientPolicy` | 调用独立 openpi 服务 |
| `ROS2ActionPolicy` | 输出 ROS2 action 或 Nav2 goal |

## 4. VLA-style prompt / input

给 pi/OpenPI 风格模型的高层输入可以设计为：

```json
{
  "instruction": "Assist the student with a classroom shape-sorting task.",
  "human_state": {
    "state": "fatigued",
    "confidence": 0.82,
    "evidence": ["voice", "pose", "task_behavior"]
  },
  "robot_context": {
    "nearby_objects": ["chair", "wheelchair"],
    "obstacle_distance_m": 0.8,
    "nav_status": "safe_to_stop"
  },
  "safety_policy": {
    "pain_risk": "stop_and_check",
    "needs_help": "alert_teacher_or_caregiver"
  }
}
```

输出：

```json
{
  "action": "offer_break",
  "motion_policy": "stop_or_slow",
  "speech": "你看起来有些累了，我们要不要休息一下？",
  "reason": "User state is fatigued with voice and pose evidence."
}
```

## 5. 两个月内的现实目标

本项目不承诺两个月内把 π0.5 真正部署到机器人上，而是完成：

1. 明确 VLA 模型在系统里的位置。
2. 做出 `EmbodiedPolicyModel` 抽象接口。
3. 实现 `RuleEmbodiedPolicy` 和 `MockPiPolicy`。
4. 让仿真场景输出类似 VLA 的动作决策。
5. 文档中说明未来可替换成 OpenPI/π0/π0.5。

这样面试时可以非常清楚地说：

```text
我了解 pi0/pi0.5 这类 VLA 模型主要用于机器人动作策略，不是直接替代人类状态感知。
所以我把项目设计成 perception -> human_state -> embodied policy 的分层架构。
当前用轻量规则和 mock VLA 跑通闭环，未来在有 GPU 和机器人动作数据时，可以把 policy backend 替换为 OpenPI/π0 类模型。
```
