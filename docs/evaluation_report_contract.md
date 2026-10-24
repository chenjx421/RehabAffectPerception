# 评价与报告模块接口说明

本模块只负责 4-9 项：学生测量评分、双轨评价、学校指标与本课目标、普通课堂评分基线、分差解释和课堂报告。上传、身份、IEP 原件与公司后台数据模块保持原有实现。

## 数据关联

评价页面保存后，服务端生成稳定的 `evaluation_id`，不接受浏览器伪造。当前上传任务通过 `task_id` 和 `frame_revision` 绑定；视频版本变化或来源不可验证时，评价不会进入有效报告。课程报告统一返回：

`school_id`、`student_id`、`course_id`、`task_id`、`iep_summary_id`、`evaluation_id`、`report_id`。

## 接口

- `GET /api/v1/demo2/evaluations`：当前学校范围内的双轨评价工作区。
- `POST /api/v1/demo2/evaluations/preview`：只计算不保存。
- `POST /api/v1/demo2/evaluations`：保存学校评价、系统增强评价、目标、权重和证据。
- `POST /api/v1/demo2/evaluations/withdraw`：保留审计版本并撤销当前记录。
- `GET /api/v1/demo2/course-analysis?task_id=<任务ID>`：返回当前任务的学生状态、观察记录、评价和报告。
- `GET /api/v1/demo2/course-analysis/report?task_id=<任务ID>`：下载当前任务的结构化课堂报告 JSON。

## 评分口径

普通课堂采用学校基础评分作为起点，系统增强分单独展示。报告计算学校分、系统分、总差值，以及证据修正和权重调整；缺失证据不按 0 分处理。6 分是当前试行参考线，不是经过教育效果验证的官方及格线。

## 合并验收

使用合成任务执行：课程上传/分析完成 -> 任务评价 -> 双轨对照 -> `course-analysis` 读取 -> `course-analysis/report` 下载。真实学生视频、IEP 原件、账号密钥和生产数据库不进入测试提交。
