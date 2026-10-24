# Doc2.docx 查漏补缺清单

更新时间：2026-10-24

## 1. 材料性质

`Doc2.docx` 是截图型材料：没有可直接提取的正文段落或表格，主要由 10 张页面截图组成。因此它不作为一个新的 Demo 版本，也不直接证明截图中的每个按钮在云端已经可用。它的作用是检查历史版本目录和源码是否漏记了经理此前要求的功能。

## 2. 十张截图对应关系

| 序号 | 截图表达的功能 | 已找到的源码入口 | 主要版本 | 当前判断 |
| ---: | --- | --- | --- | --- |
| 1 | 学生资料授权、期限、撤回和失效提示 | `src/rehab_affect/demo2_dossier.py`、`demo2_dossier_store.py`、`demo2_dossier_vault.py` | V14、V20 | 源码存在；真实授权流程需现场验收 |
| 2 | 公司后台总览、学校、任务、状态和下载 | `src/rehab_affect/demo2_portal.py`、`demo2_channel_admin.py` | V13、V17、V20 | 已进入最终主线的后台链路 |
| 3 | IEP 与专业资料导入 | `demo2_dossier.py`、`demo2_dossier_store.py` | V14、V20 | 支持结构化摘要和受控资料；真实资料不应公开推送 |
| 4 | 课堂关联学生资料 | `demo2_identity.py`、`demo2_identity_store.py`、`demo2_course_page.py` | V14、V16 | 有关联模块；最终云端主线先输出匿名人物 |
| 5 | 学生测量评分标准 | `assessment_rubric.py`、`demo2_measurement.py`、`demo2_measurement_store.py` | V15、V16 | 有 0-10 分、证据和趋势基础；准确性尚未完成学校校准 |
| 6 | 双轨评价入口 | `demo2_evaluation.py`、`demo2_evaluation_store.py` | V15、V16 | 页面和存储入口存在；不是主线必经步骤 |
| 7 | 学校传统评价 | `classroom_rubric.py`、`demo2_evaluation.py` | V15、V16 | 支持人工录入和学校轨结果；需要学校指标样本 |
| 8 | 系统增强评价 | `classroom_rubric.py`、`evaluation_policy.py` | V15、V16 | 有规则与建议入口；动态权重和科学依据尚未完成验证 |
| 9 | 学校分数与系统分数对照 | `demo2_evaluation.py`、`demo2_evaluation_store.py` | V15、V16 | 有双轨差异数据结构；需要真实人工评分对照 |
| 10 | 千字图文报告及公司汇总 | `seewo_long_report.py`、`demo2_course_analysis.py`、`demo2_portal.py`、`student_record_store.py` | V08、V15、V17、V20 | 长报告和后台汇总有源码；V23 主线输出几百字版本 |

### 2.1 具体代码块定位

下面不是“模块名级别”的概括，而是可以在 GitHub 中直接搜索的类名、函数名和源码行号。行号以本次归档快照为准；后续代码移动后，以函数名为主定位。

| Doc2 截图 | 具体代码块（文件 -> 类/函数） | 代码负责的事情 | 证据边界 |
| ---: | --- | --- | --- |
| 1 | `src/rehab_affect/demo2_dossier.py:87` -> `render_student`；`demo2_dossier_store.py:140` -> `Demo2DossierStore`；`demo2_dossier_store.py:486` -> `save_authorization`；`demo2_dossier_store.py:509` -> `withdraw_authorization`；`demo2_dossier_store.py:524` -> `create_document`；`demo2_dossier_store.py:707` -> `create_reference`；`demo2_dossier_store.py:737` -> `reference_export`；`demo2_dossier_vault.py:273` -> `DossierVault` | 学生资料页、授权保存/撤回、资料文档、课堂引用和受控导出；`DossierVault.seal/open` 负责资料加密封装 | 源码入口明确；真实授权期限和生产密钥仍需现场验收 |
| 2 | `src/rehab_affect/demo2_portal.py:1043` -> `render_demo2_admin_html`；`demo2_portal.py:326` -> `render_demo2_upload_html`；`demo2_channel_admin.py:78` -> `render_channel_admin`；`student_record_store.py:1086` -> `Demo2StudentRecordStore.admin_platform_summary`；`student_record_store.py:1638` -> `create_video_task` | 公司后台总览、学校/任务状态、上传任务建档和管理员查询 | 后台源码和任务存储存在；线上权限、持续留存和下载需单独验收 |
| 3 | `src/rehab_affect/demo2_dossier.py:87` -> `render_student`；`demo2_dossier.py:132` -> `render_task`；`demo2_dossier_store.py:524` -> `create_document`；`demo2_dossier_store.py:707` -> `create_reference`；`demo2_dossier_store.py:675` -> `_references` | IEP/评估/专业资料的结构化资料入口、课程引用和学生工作区 | 支持摘要和受控资料；真实学生资料、原件和密钥不进入公开仓库 |
| 4 | `src/rehab_affect/demo2_identity.py:200` -> `render_students`；`demo2_identity.py:247` -> `render_identity`；`demo2_identity_store.py:87` -> `Demo2IdentityStore`；`demo2_identity_store.py:236` -> `create_student`；`demo2_identity_store.py:500` -> `workspace`；`demo2_identity_store.py:537` -> `save_binding`；`demo2_identity_store.py:598` -> `revoke_binding` | 学生名册、视频人物帧、人物与学生绑定、撤销绑定和导出 | 历史身份闭环源码存在；最终云端 V23 先以匿名人物结果为主，不能把人物自动猜成真实姓名 |
| 5 | `src/rehab_affect/assessment_rubric.py:93` -> `weighted_score`；`assessment_rubric.py:191` -> `build_longitudinal_series`；`demo2_measurement.py:723` -> `render_measurement`；`demo2_measurement_store.py:25` -> `Demo2MeasurementStore`；`demo2_measurement_store.py:111` -> `save`；`demo2_measurement_store.py:278` -> `course_workspace` | 0-10 分测量、证据字段、课程测量记录、纵向趋势和支持计划入口 | 评分结构和趋势代码存在；学校评分表、真实样本和准确性尚未完成校准 |
| 6 | `src/rehab_affect/demo2_evaluation.py:160` -> `render_evaluation`；`demo2_evaluation_store.py:15` -> `Demo2EvaluationStore`；`demo2_evaluation_store.py:106` -> `workspace`；`demo2_evaluation_store.py:194` -> `save`；`demo2_evaluation_store.py:215` -> `withdraw` | 双轨评价页面、评价草稿/保存/撤回和评价工作区 | 页面和存储入口存在；不是 V23 上传分析主线的必经步骤 |
| 7 | `src/rehab_affect/classroom_rubric.py:71` -> `catalog`；`classroom_rubric.py:96` -> `evaluate`；`demo2_evaluation.py:160` -> `render_evaluation`；`demo2_evaluation_store.py:194` -> `save` | 学校传统评价模板、逐项评分、证据/原因/建议和人工录入保存 | 能支持表格录入和计算；校方最终评分口径、合格线和人工对照样本待确认 |
| 8 | `src/rehab_affect/evaluation_policy.py:34` -> `catalog_policy`；`evaluation_policy.py:41` -> `resolve_policy`；`evaluation_policy.py:87` -> `sensitivity`；`classroom_rubric.py:96` -> `evaluate` | 系统增强权重候选、课程类型策略、差异解释和敏感性信息 | 这是可追溯的候选规则入口，不等于已经用近年文献完成科学验证 |
| 9 | `src/rehab_affect/demo2_evaluation.py:160` -> `render_evaluation`；`demo2_evaluation_store.py:106` -> `workspace`；`demo2_evaluation_store.py:194` -> `save` | 学校分数、系统增强分数、差值、证据和建议的双轨对照数据 | 差异结构可保存；真实差异大小需用同一课程的学校人工评分对照 |
| 10 | `src/rehab_affect/seewo_long_report.py:46` -> `save_teacher_reviews`；`seewo_long_report.py:62` -> `build_long_course_report`；`seewo_long_report.py:162` -> `_build_compact_sections`；`seewo_long_report.py:237` -> `_build_sections`；`demo2_course_analysis.py:20` -> `build_workspace`；`demo2_course_analysis.py:57` -> `build_report`；`demo2_course_page.py:4` -> `render_course_analysis`；`student_record_store.py:1351` -> `save_support_profile`；`student_record_store.py:1086` -> `admin_platform_summary` | 课程总结、学生表现段落、教师意见、图文/文本报告、学生支持档案和公司后台汇总 | 历史长报告和 V23 几百字报告均有源码入口；模型未配置时使用本地证据模板，不能把模板文字当成真实观察 |

**阅读方式：**先看表中函数，再打开同目录下的测试文件搜索同名函数或接口。例如身份闭环对应 `tests/test_demo2_identity_store.py`、测量对应 `tests/test_demo2_measurement_store.py`、评分对应 `tests/test_classroom_rubric.py`。测试通过只说明代码契约通过，不代表真实课堂视频中的识别准确率已经被学校样本验证。

## 3. 已补入版本目录的内容

上述功能已回填到：

- V14：身份、档案授权、IEP 和课堂引用；
- V15：评分、长期测量、报告和双轨评价；
- V16：课程工作台、课程报告、教师支持和使用流程；
- V17：四通道、公司后台、任务查询和下载；
- V20：学生档案、课程历史、授权和后台留存。

因此不能把 Doc2 截图单独写成“Doc2 版本”，也不能把截图展示写成“已经全部上线”。

## 4. 与最终云端版本的关系

最终云端 `cloud-final-v3.2-20261022` 只把测试主线收敛为：

`登录 -> 少量课程信息 -> 上传 -> 后台分析 -> 匿名人物学生状态结果`

Doc2 中的高级模块保留在源码和历史版本中，但不强制阻塞上述主线。当前最终云端已经能确认的主线能力包括：真实上传、后台处理、最多 3 个匿名人物、人物独立时间轴、彩色证据帧、几百字报告、原视频回看/下载和后台任务查询。

## 5. 仍需补齐的缺口

### A. 姓名、人物与 IEP 的闭环

目前最稳妥的下一步是结果页直接提供“人物 1/2/3 -> 选择已有学生或新建学生”的轻量绑定。绑定后再引用 IEP 摘要；不能在没有确认的情况下把人脸自动猜成真实学生。

验收标准：

- 绑定不要求老师先维护完整花名册；
- 搜不到时可以创建待确认学生；
- 绑定记录包含任务、人物、确认人、时间和撤销状态；
- 本课总结挂到 `student_id`，不是只按姓名拼接；
- 未绑定时匿名结果仍然可看、可下载。

### B. 评分可验证性

教师核准应该发生在分析完成后，对关键片段做复核和修正，而不是阻塞第一次上传。下一步需把教师结论、片段、备注、评分版本和修改时间记录起来，再与学校人工评分表做对照。

### C. 科学依据和双轨评价

页面和规则已经有基础，但特殊教育学科的动态权重、近年文献和学校人工评分之间还没有完成正式校准。下一步应先收集实际评分表和课程样本，再按语文、数学、体育、音乐、表达/互动等类型校准，不用一次测试宣称准确率。

### D. 数据留存和生产化

当前有测试级任务、学生记录和公司后台入口。长期云端仍需单独验收对象存储、关系数据库、备份恢复、到期清理、审计和多学校租户隔离。后台能看见数据，不等于已经获准长期留存或用于训练。

## 6. 结论

Doc2 已完成“查漏映射”，没有新增虚构版本。后续应按照 `docs/github_versioning_plan_zh.md` 的 V01-V24 顺序推进 GitHub 历史，云端只继续维护最后一版正式发布版本。
