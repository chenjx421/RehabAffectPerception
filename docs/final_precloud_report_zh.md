# RehabAffectPerception 云电脑前最终版报告

## 1. 项目定位

本项目当前定位为：面向辅读学校辅助机器人的多模态学生状态感知与具身动作决策模块。

核心链路：

```text
学生语音 / 姿态 / 任务行为 / 机器人上下文
  -> multimodal recognizers
  -> temporal smoothing
  -> human_state
  -> learned robot policy + action shield
  -> robot_action
  -> MuJoCo benchmark / WebSocket / ROS2-style mock
```

## 2. 本地最终版完成内容

| 模块 | 状态 |
| --- | --- |
| 辅读学校 scenario benchmark | 完成 |
| MuJoCo 粗略教室仿真 | 完成 |
| domain randomization 训练数据 | 完成 |
| LearnedSchoolPolicy | 完成 |
| action shield 安全约束 | 完成 |
| rule/raw/shielded 策略对比 | 完成 |
| 多 seed 鲁棒性评估 | 完成 |
| WebSocket 接口样例 | 完成 |
| ROS2-style mock publisher | 完成 |
| 静态展示页 | 完成 |
| 交互式 benchmark 控制台 | 完成 |
| 可编辑 Scenario Lab 本地服务 | 完成 |
| 闭环动作反馈 benchmark | 完成 |

## 3. 训练与验证

| 指标 | 结果 |
| --- | --- |
| 原始 step | 18 |
| 训练 step | 126 |
| holdout step | 36 |
| 特征数 | 48 |
| 训练动作准确率 | 100.0% |
| holdout 动作准确率 | 97.2% |
| holdout 安全违规 | 0 |

## 4. MuJoCo Benchmark

| 指标 | 结果 |
| --- | --- |
| 场景数 | 6 |
| step 数 | 18 |
| 动作命中率 | 100.0% |
| 安全违规 | 0 |
| 干预次数 | 12 |

## 5. 策略对比

| 策略 | 动作命中率 | 安全违规 | 干预次数 |
| --- | --- | --- | --- |
| learned_raw | 98.1% | 0 | 36 |
| learned_shielded | 100.0% | 0 | 36 |

结论：raw learned policy 已经可用，但 shielded learned policy 更适合作为机器人动作层，因为它在状态-动作冲突时能保守回退。

## 6. 闭环动作反馈 Benchmark

| 指标 | 结果 |
| --- | --- |
| 场景数 | 6 |
| step 数 | 18 |
| 动作命中率 | 94.4% |
| 状态恢复次数 | 3 |
| 风险遏制次数 | 2 |
| 安全违规 | 0 |
| 闭环分 | 83.9 |

这部分验证机器人动作会反馈到下一步学生线索和环境上下文，而不是只做单帧状态分类。

## 7. 鲁棒性评估

| 策略 | 平均动作命中率 | 最低动作命中率 | 安全门 |
| --- | --- | --- | --- |
| learned_shielded | 99.6% | 97.8% | True |

## 8. 最终展示入口

```text
http://127.0.0.1:8787
D:\GIT\RehabAffectPerception\outputs\demo_index.html
D:\GIT\RehabAffectPerception\outputs\closed_loop_benchmark_report.html
D:\GIT\RehabAffectPerception\outputs\interactive_benchmark_console.html
D:\GIT\RehabAffectPerception\outputs\special_education_benchmark_demo.html
```

## 9. 主要产物

```text
D:\GIT\RehabAffectPerception\models\learned_school_policy.pkl
D:\GIT\RehabAffectPerception\data\processed\learned_policy_metrics.json
D:\GIT\RehabAffectPerception\data\processed\benchmark_learned_mujoco_summary.json
D:\GIT\RehabAffectPerception\data\processed\closed_loop_benchmark.json
D:\GIT\RehabAffectPerception\data\processed\policy_comparison.json
D:\GIT\RehabAffectPerception\data\processed\robustness_eval.json
D:\GIT\RehabAffectPerception\outputs\playwright\scenario_lab.png
D:\GIT\RehabAffectPerception\outputs\playwright\scenario_lab_pain_risk.png
D:\GIT\RehabAffectPerception\outputs\playwright\scenario_lab_closed_loop.png
D:\GIT\RehabAffectPerception\data\processed\websocket_stream_sample.jsonl
D:\GIT\RehabAffectPerception\data\processed\ros2_mock_messages.jsonl
```

## 10. 上云电脑后做什么

本地最终版已经完成“MuJoCo 粗仿真 + 训练 + 评估 + 接口 + 展示”。云电脑阶段不再重做基础链路，而是升级仿真和传感器：

1. Isaac Sim 高保真辅读学校教室。
2. ROS2 bridge 与真实或仿真机器人模型。
3. RGB/depth camera 渲染和第一视角视频。
4. 更大规模 domain randomization。
5. 生成最终演示视频和 sim2real 对照材料。
