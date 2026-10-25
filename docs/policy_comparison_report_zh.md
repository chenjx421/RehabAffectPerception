# 策略对比报告

## 1. 对比目标

本项目的最终输出必须落到机器人动作，因此评估不只看 `human_state` 是否正确，还要看 `robot_action` 是否安全、克制、适合辅读学校课堂交互。

当前比较三类策略：

| 策略 | 含义 |
| --- | --- |
| `rule` | 人工规则 oracle / fallback，用于安全对照 |
| `learned_raw` | 只使用训练得到的动作分类器，不启用 action shield |
| `learned_shielded` | 学习策略 + 状态先验与安全 shield |

## 2. 运行命令

```powershell
python -m src.rehab_affect.policy_compare `
  --backend kinematic `
  --model-path models/learned_school_policy.pkl `
  --scenario-dir configs/scenarios `
  --augmentations-per-scenario 2 `
  --output data/processed/policy_comparison.json `
  --pretty
```

## 3. 当前结果

评估集：

```text
6 base scenarios
2 randomized variants per scenario
18 total scenarios
54 total steps
```

| 策略 | 动作命中率 | 安全违规 | 干预次数 | 说明 |
| --- | --- | --- | --- | --- |
| `rule` | 100.0% | 0 | 36 | 安全 oracle |
| `learned_raw` | 98.1% | 0 | 36 | 1 个困惑场景 step 被预测成求助 |
| `learned_shielded` | 100.0% | 0 | 36 | shield 修正了不一致动作 |

`learned_shielded` 的 action shield 统计：

```text
consistent: 53
state_prior_high_state_confidence: 1
```

这说明大多数情况下模型动作和状态先验一致；少数情况下 shield 介入，把机器人动作拉回更符合学生状态的动作。

## 4. 为什么需要 action shield

辅读学校辅助机器人不适合完全依赖模型分类结果。即使模型总体准确，也可能在个别场景把“困惑”误判成“需要帮助”或把“疲劳”误判成“继续任务”。action shield 的作用是：

- 对 `pain_risk`、`needs_help`、`refusing` 等安全/尊重意愿状态保守处理。
- 当模型置信度较低但 `human_state` 置信度较高时，优先执行状态对应动作。
- 使输出动作更适合机器人执行层，而不是单纯追求分类准确率。

## 5. 展示口径

```text
I compared a rule-based safety oracle, a raw learned policy, and a shielded learned policy.
The raw learned policy already performs well, but the shielded policy is safer for embodied interaction:
it preserves learned behavior while enforcing state-action safety priors for special-education classroom robots.
```
