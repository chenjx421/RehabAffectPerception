# 多学生检测与统一学生切换（2026-11-01，子任务 75）

## 老师反馈
「学生检测只能检测一位学生，不知道切换学生的入口在哪里，能不能选择被检测的学生」，并要求每节课至少检测 3 名学生且可切换。

## 根因（已查实）
1. **人物筛查阈值把真实课堂的学生全部判为「无效人选」**（主因）。
   用 v3_7 追踪器 + person_filter_v1 重跑本机两节真实课堂（只统计数字，不输出图像）：
   追踪到 8 个和 7 个持续出现的人物（每人数百帧，出现时长约占全片 95%），
   但**学生 0 名**，全部被标成 blank，原因是 `small_face`（v1 要求人脸宽度至少 24 px）和
   `low_confidence`（v1 要求平均分至少 0.70）。广角教室在 768 px 分析尺寸下学生人脸只有 10–12 px，
   YuNet 平均分是 0.685–0.776。合成卡通视频里的人脸约 60 px，所以子任务 60 没有发现这个问题。
2. **切换入口不明显或缺失**：结果页的人物按钮只是一排小卡片；`/demo2/analysis` 人物页签只有一个
   `<select>`，而且只列出身份确认过的学生；身份确认页和测量页没有按学生切换的入口。
3. 追踪器本身不是瓶颈：1–5 名合成学生 + 走动老师都能逐个跟踪（`scripts/make_person_filter_synthetic_video.py --students N`）。

## 改动
- 筛查规则 `person_filter_v2`：绝对下限改为 `min_face_px=8`、`min_mean_score=0.64`；新增相对规则
  `relative_small_ratio=0.45`（比同班其他学生小一半以上的人脸才判为背景人物）。身份确认页的候选标注也采用同一规则。
  追踪版本升级到 `simple_student_seats_v3_8`，旧结果会进入后台刷新队列按新规则重新计算。
- 公共组件 `RxUI.studentSwitcher`（demo2_ui_kit）：横排头像卡片（192 px 头像），显示学生编号或已绑定姓名，
  徽标为已绑定 / 未绑定 / 已排除。URL 写入 `?person_id=` 或 `?student_id=`，支持前进、后退和深链；
  接入结果页、身份确认页、`/demo2/analysis` 个体观察页签和 `/demo2/measurement`。
- 结果页新增「本课检测学生」面板：勾选或取消「纳入本课检测」、标为老师、恢复为学生。
  覆盖表新增 `decision='excluded_by_teacher'`（旧表会自动重建以更新 CHECK 约束）。
  取消纳入或标为老师时，级联撤销视频测量（保留版本）、IEP 课堂引用、身份绑定和本课归档，
  并记录在 `demo2_person_filter_suspended`；重新纳入或恢复时原样恢复，报告自动重新生成。
- 学生少于 3 名时，`person_filter_summary.low_student_notice` 给出「本视频仅识别到 N 名学生」及原因，
  页面提供「手动画框添加学生」入口。
- API：`GET /api/v1/demo2/simple-result/persons?task_id=`；`POST /simple-result/person-filter`
  的 decision 新增 `exclude` / `include`；`POST /simple-result/person-switch` 用于记录切换日志。
  错误码：他校 403 `task_forbidden`，任务不存在 404 `task_unavailable`，人物不属于该任务 400 `person_not_in_task`，管理员 403。
- 日志 `person_filter_debug_YYYYMMDD.jsonl` 新增 `person_switch` / `person_list` / `person_include` / `person_exclude` /
  `low_student_count` / `person_filter_error`，每行都带 `task_short`，不写姓名和坐标。

## 测试
`tests/test_demo2_multi_student_switch.py`（新增），以及 person_filter、identity_html（45）、measurement_link、ui_kit、page_nav 回归。
