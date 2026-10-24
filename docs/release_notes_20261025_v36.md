# v3.6 发布说明（2026-10-25）

## 本轮修复

- 课堂视频分析统一使用 `simple_student_seats_v3_6`，媒体缓存和学生跟踪器版本一致。
- 恢复 Demo1 风格的逐人物状态时间轴：最多输出 3 名人物，首次检测按画面从左到右编号；每个人物使用自己的固定区域、截图和时间片，不用其他人物补图或补状态。
- 学生状态线索单独输出：稳定参与、出现回应或操作、回应信号较低、未观察到有效作答机会、证据不足。
- 人脸位移只用于定位复核，不再直接提高或降低学生主状态分；主信号来自对应人物固定区域的局部画面变化。
- 结果页支持人物切换、人物截图、逐时间片状态、课堂阶段、教师活动线索、学生参与参考值和个人报告。
- 保留姓名绑定、本课总结归档和最小 IEP 支持摘要入口。
- 评价与报告契约补齐稳定 ID：学校、学生、课程、任务、IEP 摘要、评价和报告可以按 ID 关联；新增课堂报告下载路由。
- 评价存储允许前端提交课程、IEP 摘要和报告关联 ID，但评价 ID 仍由服务端生成。

## 验收结果

- 学生状态、人物截图、缓存和媒体分析回归：通过。
- 4-9 评价模块定向回归：`262 passed`。
- 4-9 范围覆盖评分标准、双轨评价、学校指标与课程目标、普通课堂基础、分差解释、报告生成、报告下载和稳定 ID 关联。
- 真实课堂短片回归：120 秒、960x544、18fps、有音频；输出 3 名人物、每人 4 个独立时间片，三人的状态序列不同，三份个人报告均不少于 300 字，处理进度到 100%。
- 彩色帧检查：输出仍为彩色 JPEG；结果页使用每个人物对应时刻的局部证据。

## 已知限制

- 当前最多稳定展示 3 名匿名人物；人物编号不是姓名识别，也不是生物特征身份确认。
- 0-10 参考值是视频证据线索，不是正式成绩、医学判断或学校最终评课分。
- 仓库仍有两条历史验收测试互相矛盾：一条把同版本改名视为允许编辑，另一条要求同场景返回版本冲突；另一条把 `fixture-1` 视为非法 ID，但同套测试使用它作为稳定记录 ID。本轮未通过改变业务规则来掩盖冲突，相关两条在定向回归中单独保留并标记。
- 本轮只完成本地代码与测试验证，没有宣称云端已经同步或真实学生数据已经完成科学有效性验证。

## 测试命令

```powershell
$env:PYTHONPATH='src'
python -m pytest -q tests/test_demo2_course_analysis.py tests/test_demo2_evaluation_api.py tests/test_classroom_rubric.py tests/test_assessment_rubric.py tests/test_evaluation_reference_context.py tests/test_evaluation_subject_policy.py tests/test_demo2_evaluation_provenance.py tests/test_demo2_evaluation_store.py tests/test_demo2_measurement_store.py tests/test_demo2_measurement_html.py tests/test_demo2_batch_review.py tests/test_student_seat_tracking.py tests/test_simple_analysis_cache.py tests/test_simple_person_portraits.py
```
