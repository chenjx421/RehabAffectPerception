# 两个月具身智能项目路线图

项目名称：RehabAffectPerception  
周期：2026-06-09 到 2026-08-04  
目标：把当前人类状态感知模块打磨成一个面向辅读学校场景、可演示、可解释、可接机器人系统、可包装成实习经历的具身智能项目。

## 1. 最终项目定位

本项目不包装成单纯的“情绪识别 demo”，而是包装成：

```text
面向辅读学校辅助机器人的具身学生状态感知与动作决策系统
Embodied student-state perception and action decision for assistive robots in special education schools
```

核心闭环：

```text
人类状态感知
  camera / microphone / pose / task behavior
  -> human_state

机器人环境感知
  YOLO objects / obstacle cues / simulated robot context
  -> robot_context

具身交互策略
  human_state + robot_context + classroom task
  -> robot_action

仿真与接口验证
  mock / WebSocket / ROS2-style messages / simulation scenarios
  -> demo, logs, metrics, resume story
```

## 2. 两个月总体交付物

到第 8 周结束时，项目目录里应有这些可展示成果：

| 类别 | 交付物 | 验收标准 |
| --- | --- | --- |
| 核心代码 | `RehabAffectPipeline` | mock 输入能稳定输出 `human_state` JSON |
| 输入层 | camera/mic/mock adapters | 无硬件可 mock，有硬件可 live |
| 状态识别 | face/voice/pose/task recognizers | 能输出 `engaged/fatigued/confused/refusing/pain_risk/needs_help` |
| 环境感知 | YOLO 或 YOLO mock context | 能输出学生、教师、桌椅、轮椅、白板、教具、障碍物等 object context |
| 具身策略 | policy adapter | 根据人状态和环境上下文给出机器人动作 |
| 接口层 | WebSocket 或 ROS2-style publisher | 能把 `human_state` 和 `robot_action` 发给外部进程 |
| 仿真层 | 辅读学校教室/训练角 MuJoCo 或 Isaac Sim 场景 | 至少 3 个状态切换场景可回放 |
| 实验 | metrics/logs | 有平滑效果、触发延迟、接口延迟、策略正确率等指标 |
| 文档 | README、架构图、接口文档、演示脚本 | 面试时能 3 分钟讲清楚 |
| 包装 | 简历 bullet、项目介绍、demo video 脚本 | 能作为实习经历项目讲述 |

## 3. 技术栈优先级

### 必须掌握

- Python 工程结构：模块、CLI、配置、日志、测试。
- OpenCV 基础：摄像头读取、帧处理、YOLO 推理输入。
- 音频基础：采样率、音频 chunk、能量、静音、关键词。
- 多模态融合：置信度、证据来源、时间平滑、安全优先级。
- WebSocket 或 ROS2 topic 思维：消息格式、发布频率、订阅者。
- 具身智能表达：机器人不只是识别，而是根据感知改变动作和交互。
- VLA/具身策略模型：理解 OpenPI、π0、π0.5 这类模型的输入输出边界。

### 需要能讲清楚

- YOLO：object detection、bounding box、confidence、mAP、IoU、实时性优化。
- SLAM/Nav2：map、odom、base_link、tf、costmap、global planner、local planner。
- 仿真：辅读学校教室/训练角、机器人、传感器、课堂任务事件、学生状态变化脚本。
- 安全边界：本项目不做医学诊断，只做交互状态提示和保守暂停策略。

### 暂时不深挖

- 从零训练大模型。
- 高精度医疗疼痛诊断。
- 真机底盘控制闭环。
- 大规模数据标注平台。

## 4. 每周路线图

### Week 1：项目基线与主线闭环

时间：2026-06-09 到 2026-06-15

目标：把当前 MVP 稳住，形成第一条完整主线。

任务：

| 编号 | 任务 | 输出文件/模块 | 验收标准 |
| --- | --- | --- | --- |
| W1-1 | 梳理现有 README、schema、fusion、smoothing | `docs/project_plan_zh.md` | 能说明当前系统输入、处理、输出 |
| W1-2 | 完成 `inputs.py` mock/live 输入层 | `src/rehab_affect/inputs.py` | mock 不依赖硬件可跑 |
| W1-3 | 完成 recognizers 规则版 | `src/rehab_affect/recognizers.py` | 每个 modality 能产出 `ModalitySignal` |
| W1-4 | 完成 pipeline CLI | `src/rehab_affect/mvp.py` | `python -m src.rehab_affect.mvp --mode mock --steps 10` 可跑 |
| W1-5 | 写第一版接口文档 | `docs/mvp_integration_zh.md` | JSON、ROS2、WebSocket 接入点清楚 |

验收命令：

```bash
python -m src.rehab_affect.demo
python -m src.rehab_affect.mvp --mode mock --steps 10
python -m compileall src
```

简历积累点：

```text
Implemented a modular human-state perception pipeline with camera/audio/pose/task adapters, temporal smoothing, multimodal fusion, and JSON output.
```

### Week 2：WebSocket 接口与可视化调试

时间：2026-06-16 到 2026-06-22

目标：让 `human_state` 能被外部系统实时订阅，形成机器人系统接口感。

任务：

| 编号 | 任务 | 输出文件/模块 | 验收标准 |
| --- | --- | --- | --- |
| W2-1 | 新增 WebSocket server | `src/rehab_affect/ws_server.py` | 客户端能收到 `human_state` |
| W2-2 | 新增 WebSocket client 示例 | `examples/ws_client.py` | 能打印实时状态 |
| W2-3 | 支持 task behavior 远程输入 | `TaskBehavior` update API | 客户端能发送重复指令、失败次数、请求帮助 |
| W2-4 | 新增 JSONL 日志记录 | `logs/*.jsonl` | 每次运行可保存状态序列 |
| W2-5 | 写接口测试脚本 | `tests/` 或 `scripts/` | 至少能测消息格式和状态字段 |

验收场景：

```text
启动 server
-> mock 用户从 engaged 变 fatigued
-> client 收到 human_state
-> client 发送 request_text="疼，需要帮忙"
-> server 输出 pain_risk/needs_help
```

简历积累点：

```text
Built real-time WebSocket interfaces for publishing human-state perception results and receiving robot task events.
```

### Week 3：YOLO 环境感知接入

时间：2026-06-23 到 2026-06-29

目标：加入具身环境信息，让项目从“识别人”升级为“理解人和机器人周围环境”。

任务：

| 编号 | 任务 | 输出文件/模块 | 验收标准 |
| --- | --- | --- | --- |
| W3-1 | 定义 `RobotContext` schema | `src/rehab_affect/context.py` | 包含 objects、obstacles、robot_pose、task |
| W3-2 | 加 YOLO adapter 或 mock YOLO | `src/rehab_affect/yolo_adapter.py` | 无 GPU 时可 mock，有模型时可推理 |
| W3-3 | 定义辅读学校场景类别 | `configs/objects.json` | student、teacher、desk、chair、wheelchair、whiteboard、teaching_aid、obstacle、quiet_corner |
| W3-4 | 融合 `human_state + robot_context` | `src/rehab_affect/policy.py` | 输出 `robot_action` |
| W3-5 | 加实时性统计 | `metrics` 字段或日志 | 输出 FPS/latency |

验收场景：

```text
person detected + obstacle near robot + low_attention
-> robot_action = stop_and_regain_attention
```

简历积累点：

```text
Integrated object-level scene context with human-state perception to support embodied robot interaction decisions.
```

### Week 4：具身策略层

时间：2026-06-30 到 2026-07-06

目标：把状态识别结果真正转成机器人动作策略，并显式预留 VLA/π 类具身模型接口。

任务：

| 编号 | 任务 | 输出文件/模块 | 验收标准 |
| --- | --- | --- | --- |
| W4-1 | 设计策略表 | `configs/policy_rules.json` | 状态、上下文、动作一一对应 |
| W4-2 | 实现 policy engine | `src/rehab_affect/policy.py` | 输入 state/context，输出 action |
| W4-3 | 增加安全优先级 | `pain_risk/needs_help` rules | 安全状态优先暂停 |
| W4-4 | 增加解释字段 | `decision_reason` | 能解释为什么这样动作 |
| W4-5 | 写策略单元测试 | `tests/test_policy.py` | 关键场景覆盖 |
| W4-6 | 新增 VLA policy 抽象 | `EmbodiedPolicyModel` | 可接 `RuleEmbodiedPolicy`、`MockPiPolicy`、未来 `OpenPIClientPolicy` |

建议动作集合：

| Action | 含义 |
| --- | --- |
| `continue_and_encourage` | 继续训练并鼓励 |
| `repeat_instruction_slowly` | 放慢并重复说明 |
| `offer_break` | 询问是否休息 |
| `reduce_task_intensity` | 降低任务强度 |
| `stop_and_check_pain_risk` | 停止并确认不适 |
| `alert_teacher_or_caregiver` | 提醒教师或照护者 |
| `stop_motion_for_safety` | 停止机器人移动 |
| `regain_attention` | 重新吸引注意 |

简历积累点：

```text
Designed an explainable embodied policy layer with a VLA-style interface for future OpenPI/pi0 integration.
```

### Week 5：仿真场景与回放系统

时间：2026-07-07 到 2026-07-13

目标：加入仿真条件，让项目具备具身智能项目的“场景验证”味道。

任务：

| 编号 | 任务 | 输出文件/模块 | 验收标准 |
| --- | --- | --- | --- |
| W5-1 | 设计辅读学校教室/训练角场景 | `docs/special_education_benchmark_zh.md` | 至少 3 个 benchmark 场景 |
| W5-2 | 新增 scenario JSON | `configs/scenarios/*.json` | 可描述用户状态、障碍物、任务事件 |
| W5-3 | 实现 scenario runner | `src/rehab_affect/sim_runner.py` | 从 JSON 回放输入流 |
| W5-4 | 支持虚拟机器人上下文 | `RobotContext` | 位姿、目标点、障碍距离 |
| W5-5 | 生成 demo logs | `data/processed/demo_*.jsonl` | 可复现演示 |

推荐场景：

| 场景 | 变化 | 期望策略 |
| --- | --- | --- |
| 场景 A | engaged -> fatigued | 降低任务负荷，询问休息 |
| 场景 B | confused + instruction repeated | 重复说明，简化任务 |
| 场景 C | pain_risk + needs_help | 暂停任务，提醒教师或照护者 |
| 场景 D | low_attention + obstacle near robot | 停止移动，重新吸引注意 |

简历积累点：

```text
Created simulation scenarios and replayable logs for evaluating affect-aware robot behavior adaptation.
```

### Week 6：ROS2 风格接口与 SLAM/Nav2 概念接入

时间：2026-07-14 到 2026-07-20

目标：即使暂时不在真机上跑，也要把 ROS2/SLAM/Nav2 的接口语言讲清楚。

任务：

| 编号 | 任务 | 输出文件/模块 | 验收标准 |
| --- | --- | --- | --- |
| W6-1 | 定义 ROS2 topic 方案 | `docs/ros2_interface_zh.md` | topic、message、frequency 清楚 |
| W6-2 | 新增 ROS2-style publisher stub | `src/rehab_affect/ros2_bridge.py` | 无 ROS2 时可 dry-run |
| W6-3 | 定义 SLAM/Nav2 输入字段 | `RobotContext` | map_frame、odom_frame、base_link、costmap risk |
| W6-4 | 写 costmap/obstacle mock | `sim_runner` | 可模拟障碍距离变化 |
| W6-5 | 建立系统架构图 | README 或 docs | 感知、策略、仿真、接口一图讲清 |

需要会讲：

```text
SLAM 负责定位和建图，Nav2 负责路径规划和避障。
本项目不替代 SLAM/Nav2，而是给上层策略提供人类状态和交互安全信号。
当用户 low_attention 或 pain_risk 时，即使 Nav2 认为路径可行，策略层也可以要求机器人减速、停止或暂停交互。
```

简历积累点：

```text
Designed ROS2-compatible message interfaces to connect human-state perception with navigation and robot behavior layers.
```

### Week 7：实验指标与质量打磨

时间：2026-07-21 到 2026-07-27

目标：让项目有实验结果，不只是功能堆叠。

任务：

| 编号 | 任务 | 输出文件/模块 | 验收标准 |
| --- | --- | --- | --- |
| W7-1 | 平滑前后抖动对比 | `scripts/evaluate_smoothing.py` | 输出 state switches 数量 |
| W7-2 | 安全状态触发延迟 | `scripts/evaluate_latency.py` | pain_risk latency 有统计 |
| W7-3 | WebSocket 延迟测试 | `scripts/evaluate_ws_latency.py` | 输出平均/最大延迟 |
| W7-4 | 策略正确率评估 | `scripts/evaluate_policy.py` | 对 scenario expected action 计算 accuracy |
| W7-5 | 生成实验报告 | `docs/evaluation_report_zh.md` | 有表格、有结论、有局限 |

建议指标：

| 指标 | 意义 |
| --- | --- |
| state switch count | 平滑是否减少状态抖动 |
| safety trigger latency | 不适/求助是否及时触发 |
| policy match accuracy | 策略是否符合预期 |
| pipeline latency | 单次感知到输出耗时 |
| WebSocket latency | 外部系统接收延迟 |
| FPS | 视觉处理实时性 |

简历积累点：

```text
Evaluated temporal smoothing, safety-trigger latency, policy correctness, and real-time communication latency across simulated rehabilitation scenarios.
```

### Week 8：演示、文档与实习经历包装

时间：2026-07-28 到 2026-08-04

目标：把项目整理成能投简历、能面试讲、能演示的视频/截图。

任务：

| 编号 | 任务 | 输出文件/模块 | 验收标准 |
| --- | --- | --- | --- |
| W8-1 | 重写 README 首页 | `README.md` | 30 秒能看懂项目价值 |
| W8-2 | 补系统架构图 | README 或 `docs/architecture_zh.md` | Mermaid 图清楚 |
| W8-3 | 写 demo 操作脚本 | `docs/demo_script_zh.md` | 3 分钟演示流程 |
| W8-4 | 整理简历 bullet | `docs/resume_packaging_zh.md` | 中文和英文各一版 |
| W8-5 | 录制演示素材清单 | `docs/demo_video_plan_zh.md` | 镜头、命令、讲解词清楚 |

最终面试讲法：

```text
这个项目是一个面向辅读学校辅助机器人的具身学生状态感知与动作决策系统。
我没有把它做成单纯情绪分类，而是把摄像头、麦克风、姿态、任务行为和机器人环境上下文结合起来，
输出可解释的 human_state，并通过 WebSocket/ROS2 风格接口提供给策略层。
在仿真辅读学校教室场景中，机器人会根据学生疲劳、困惑、注意力下降、抗拒或疑似不适状态，
调整课堂任务负荷、分步骤重复说明、停止移动、保持距离或提醒教师/照护者。
```

## 5. 每周推进规则

每周固定做四件事：

| 动作 | 内容 |
| --- | --- |
| 周初规划 | 从本路线图选 3-5 个任务进入本周 TODO |
| 周中实现 | 先保证可运行，再优化模型和展示 |
| 周末验收 | 跑命令、保存日志、写本周总结 |
| 项目包装 | 每周至少沉淀 1 条简历素材或面试讲法 |

每个任务完成必须满足：

```text
有代码或文档文件
有运行命令或示例输入
有可观察输出
有一句能写进简历/面试的价值说明
```

## 6. 风险与降级方案

| 风险 | 影响 | 降级方案 |
| --- | --- | --- |
| 本机没有 NVIDIA GPU | YOLO/语音模型实时性不足 | 用 YOLO nano、降低分辨率、mock 推理、离线视频 |
| ROS2 Windows 环境麻烦 | 真 ROS2 节点开发拖慢 | 先做 ROS2-style JSON 和 WebSocket，必要时 WSL/Ubuntu |
| 仿真太重 | Gazebo/Isaac 本地跑不动 | 先做 scenario runner 和 2D mock context |
| 数据不足 | 真实模型效果不好 | 用规则和公开模型 warm start，重点展示系统闭环 |
| 项目范围膨胀 | 两个月做不完 | 以 human_state + policy + simulation replay 为主线 |

## 7. 项目目录建议

后续逐步补成：

```text
configs/
  labels.json
  objects.json
  policy_rules.json
  scenarios/
    fatigued_session.json
    confused_session.json
    pain_risk_session.json
docs/
  two_month_embodied_ai_roadmap_zh.md
  mvp_integration_zh.md
  ros2_interface_zh.md
  simulation_scenarios_zh.md
  evaluation_report_zh.md
  resume_packaging_zh.md
examples/
  ws_client.py
scripts/
  evaluate_smoothing.py
  evaluate_latency.py
  evaluate_policy.py
src/rehab_affect/
  inputs.py
  recognizers.py
  pipeline.py
  context.py
  yolo_adapter.py
  policy.py
  ws_server.py
  ros2_bridge.py
  sim_runner.py
tests/
  test_pipeline.py
  test_policy.py
```

## 8. 当前下一步

从现在开始，下一步优先做 Week 2：

1. 新增 WebSocket server。
2. 新增 WebSocket client 示例。
3. 让 task behavior 可以从外部消息更新。
4. 保存 JSONL 日志。
5. 为 `human_state` 消息格式写最小测试。

完成 Week 2 后，这个项目就从“本地脚本”升级成“机器人系统里的实时感知服务”。

同时保留一条 Week 4 的具身模型主线：`human_state + robot_context + instruction -> RobotAction`。当前先用规则和 `MockPiPolicy` 跑通，未来在 GPU/Ubuntu/机器人动作数据条件满足后，再替换成 OpenPI/π0/π0.5 后端。
