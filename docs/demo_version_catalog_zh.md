# RehabAffect Demo 全版本源代码与功能目录

更新时间：2026-10-24

## 目录目的

本目录把 Demo1、Demo2、学校交付包、本地平台、云端候选和最终云端版本按时间整理。重点不是只写“做过什么”，而是逐个说明：

各版本对应的可公开 PDF 统一放在 [`docs/version_pdfs/`](version_pdfs/README.md)，PDF 是否存在、是否因含入口或凭据而不上传，见 [`docs/public_archive_manifest_zh.md`](public_archive_manifest_zh.md)。

- 这个阶段有哪些功能；
- 对应的源代码、源码包或测试入口在哪里；
- 能不能作为独立代码基线恢复；
- 是否曾经真正发布到云端；
- 后来为什么可能看起来“消失”或不能直接复现。

当前 Git 仓库只有 2026-06-04 的初始化提交 `d945436`，没有保存从 Demo1 到现在的逐次 Git 历史。因此本目录是根据本地源码包、交付包、文档、测试记录、云端清单和文件时间重建的版本索引。能找到完整源码包的版本，标为可恢复源代码；只有页面、截图或说明文档的节点，不会被写成完整代码版本。

## 证据标记

| 标记 | 含义 |
| --- | --- |
| S1 | 有独立源码目录或源码压缩包，可作为该阶段代码基线恢复 |
| S2 | 当前工作区仍有对应源码，但没有该阶段完整独立快照 |
| S3 | 只有页面、截图、PDF、Word 或测试记录，不能单独恢复实现 |
| C | 有明确云端发布或云端验收证据 |
| P | 规划、候选、局部修复或试验过程，不是正式发布版本 |
| F | 正式最终云端交付版本 |

## 按时间整理的版本

### V01 2026-06-04 项目初始化与基础状态感知框架

- 类型：基础工程基线，S1/S2。
- 功能：`human_state` 数据结构，多模态输入占位，状态融合，时间平滑，机器人动作策略，基础演示命令。
- 源代码：
  - `src/rehab_affect/schema.py`
  - `src/rehab_affect/inputs.py`
  - `src/rehab_affect/recognizers.py`
  - `src/rehab_affect/fusion.py`
  - `src/rehab_affect/smoothing.py`
  - `src/rehab_affect/pipeline.py`
  - `src/rehab_affect/policy.py`
  - `src/rehab_affect/mvp.py`
- 测试和说明：`README.md`、`tests/test_human_state_contract.py`。
- 可恢复性：初始化提交可以恢复基础工程，但不包含后续课堂视频平台。
- 云端：未发布。

### V02 2026-06-26 至 06-29 初始课堂 AI 演示

- 类型：教育课堂演示原型，S1。
- 功能：课堂状态演示入口，视频识别头、语音识别头、时间线融合的页面表达，结构化状态和机器人动作展示。
- 源代码：
  - `src/rehab_affect/education_demo.py`
  - `src/rehab_affect/demo_launcher.py`
  - `scripts/build_education_demo_ppt.mjs`
- 可恢复源码包中的对应文件：
  - `dist/RehabAffect_Seewo_Student_Demo_Offline_20260727/src/rehab_affect/education_demo.py`
  - `dist/RehabAffect_Seewo_Student_Demo_Offline_20260731/src/rehab_affect/education_demo.py`
- 边界：主要是结构化演示和预置素材，不是通用真实课堂视频识别。
- 云端：未发布。

### V03 2026-07-01 至 07-02 Demo1 单学生课堂视频分析

- 类型：Demo1 核心功能基线，S1。
- 功能：指定单个学生，固定目标区域，课堂视频回放，30 秒时间窗口，学生状态时间轴，状态证据，结构化 JSON，支持建议。
- 源代码：
  - `src/rehab_affect/seewo_student_demo.py`
  - `src/rehab_affect/seewo_long_report.py`
- 关键实现：`seewo_student_demo.py` 中的目标学生 ROI、时间窗口状态、音频特征、支持建议和结果展示。
- 可恢复源码包：
  - `dist/RehabAffect_Seewo_Student_Demo_Offline_20260727/`
  - `dist/RehabAffect_Seewo_Student_Demo_Offline_20260731/`
  - `docs/seewo_student_demo_readme_zh.md`
- 重要边界：依赖固定视频、固定学生区域和预置资料，不等于对任意新视频自动识别姓名。
- 云端：未直接作为当前通用上传链路发布。

### V04 2026-07-03 至 07-06 学生画像、IEP 背景和学校演示输入输出

- 类型：Demo1 资料化交付，S1/S3。
- 功能：学生画像、基础资料来源、IEP 支持背景、课堂结论、支持重点、学校输入输出说明、课堂支持效果复盘。
- 源代码基线：`src/rehab_affect/seewo_student_demo.py`。
- 代表文档：
  - `docs/seewo_student_ai_support_solution_zh.docx`
  - `docs/seewo_school_demo_plan_zh.docx`
  - `docs/seewo_demo_io_flow_for_school_zh.docx`
- 可恢复性：核心 Demo1 代码可恢复；当时的真实资料和演示输入不应公开推送。
- 边界：没有希沃后台自动同步，不能把相邻时段变化证明为教师干预的因果效果。

### V05 2026-07-22 校方演示路线

- 类型：演示交付节点，S3。
- 功能：整理现场展示顺序，把学生、时间窗、证据和支持建议按讲解路线组织。
- 依据：`docs/seewo_school_demo_rehearsal_zh.md`。
- 源代码：没有新的独立源码快照，沿用 V03/V04。
- 云端：未发布。

### V06 2026-07-27 Demo1 离线代码包

- 类型：可运行离线源码包，S1。
- 源码目录：`dist/RehabAffect_Seewo_Student_Demo_Offline_20260727/`。
- 功能：基础状态感知框架，课堂演示页，Demo1 单学生分析，机器人动作策略，模拟场景，测试和启动脚本。
- 主要入口：
  - `start_demo.cmd`
  - `start_demo.ps1`
  - `src/rehab_affect/seewo_student_demo.py`
  - `src/rehab_affect/education_demo.py`
- 可恢复性：可以作为独立 GitHub 历史标签。
- 公开推送注意：包内 `data/raw`、`outputs` 及学生资料说明需要脱敏或移出。

### V07 2026-07-31 Demo1/Demo2 离线源码汇编包

- 类型：源码交付包，S1。
- 源码目录：`dist/RehabAffect_Seewo_Student_Demo_Offline_20260731/`。
- 代表文档：`docs/辅读学校Demo_源码汇编与通俗说明_20260731.docx`。
- 功能：学生多模态支持背景，课堂演示结构，源码说明，运行说明，验证脚本，数据目录约定。
- 代表代码：
  - `src/rehab_affect/seewo_student_demo.py`
  - `src/rehab_affect/education_demo.py`
  - `src/rehab_affect/scenario_lab_server.py`
  - `src/rehab_affect/seewo_long_report.py`
- 可恢复性：可建立 `demo1-20260731` 标签；不是当前云端版本。

### V08 2026-08-11 Demo2 三学生课堂学习成效

- 类型：Demo2 重要功能版本，S1。
- 功能：三名学生，课程目标，群像/个体视图，个体能力背景，学习掌握初评，支持建议和长报告。
- 源代码：
  - `src/rehab_affect/seewo_multi_student_demo.py`
  - `src/rehab_affect/seewo_long_report.py`
  - `src/rehab_affect/seewo_student_demo.py`
- 交付文档：`docs/辅读学校课堂学习成效分析_Demo2介绍文档.docx`。
- 可恢复源码：`deliverables/20260824_demo2_delivery/Demo2_code_20260824/` 中的同名源码。
- 边界：早期学习掌握初评含规则和演示假设，不能直接当作新上传视频的真实成绩。

### V09 2026-08-12 至 08-20 Demo2 页面与校方展示版本

- 类型：前端和交付节点，S1/S3。
- 功能：教师复核说明，App 化方向，群像/个体/时间片/报告页面，蓝白 UI，学校试点准备度和前端验收。
- 源代码基线：
  - `src/rehab_affect/seewo_multi_student_demo.py`
  - `src/rehab_affect/scenario_lab_server.py`
  - `design-system/rehabaffect-classroom-studio/`
- 代表材料：
  - `docs/Demo2_教师关键片段复核与标注操作说明.docx`
  - `docs/Demo2_App化产品方向与实施条件说明.docx`
  - `docs/Demo2_全部细分页面截图展示_20260814.docx`
  - `docs/Demo2_核心竞争力与课堂表现分析维度_20260817.docx`
  - `docs/Demo2_产品复盘与学校实体测试准备度报告_20260820.docx`
  - `docs/demo2_frontend_acceptance_zh.md`
- 可恢复性：核心多学生源码可从 V08/V09 交付目录恢复；某些页面按钮不能仅凭截图恢复。
- 云端：未作为当前最终云端版本。

### V10 2026-08-24 Demo2 阶段源码交付包

- 类型：可运行源码交付包，S1。
- 源码目录：`deliverables/20260824_demo2_delivery/`。
- 压缩包：`deliverables/20260824_demo2_delivery/RehabAffect_Demo2_源代码_20260824.zip`。
- 代表源码：
  - `src/rehab_affect/seewo_multi_student_demo.py`
  - `src/rehab_affect/seewo_long_report.py`
  - `src/rehab_affect/scenario_lab_server.py`
  - `src/rehab_affect/student_record_store.py`
  - `tests/test_seewo_multi_student_demo.py`
- 交付材料：阶段整改与后续方向 DOCX/PDF，代码说明，测试脚本，设计系统。
- 可恢复性：可建立 `demo2-20260824` 标签。
- 注意：SQLite、示例输出和学生图像不能公开推送。

### V11 2026-08-26 至 08-27 资料、数据库、四通道和安全版本

- 类型：Demo2 综合交付包，S1。
- 源码目录：`deliverables/20260827_demo2_delivery/RehabAffect_Demo2_交付包_20260827/02_源程序/`。
- 压缩包：`deliverables/20260827_demo2_delivery/RehabAffect_Demo2_交付包_20260827.zip`。
- 功能：
  - 学生档案和资料存储基础；
  - SQLite 与受控文件目录；
  - IEP/专业资料结构化支持方向；
  - 三学生 Demo2；
  - 四通道上传规划；
  - 60 天保存及到期前 15 天提醒说明；
  - 页面截图、运行脚本和验证清单。
- 代表源码：
  - `src/rehab_affect/student_record_store.py`
  - `src/rehab_affect/seewo_multi_student_demo.py`
  - `src/rehab_affect/seewo_long_report.py`
  - `src/rehab_affect/demo2_*`
- 代表证据：`03_测试与清单/TEST_RESULTS.txt`、`SOURCE_INVENTORY.csv`、`MANIFEST_SHA256.txt`。
- 可恢复性：可以建立 `demo2-20260827` 标签。
- 注意：交付包中的 SQLite、学生肖像、分析结果和教师记录属于测试数据，不能公开推送。

### V12 2026-08-31 系统汇总与源码说明

- 类型：源码说明交付，S3/S2。
- 依据：`docs/辅读学校Demo2_系统汇总与源码说明_20260831.docx`。
- 功能：将 V11 的系统结构、代码模块、页面和后续路线重新汇总。
- 源代码：没有新完整快照，代码基线沿用 V11。
- GitHub 处理：作为 V11 的说明文件，不单独建立可部署代码版本。

### V13 2026-09-07 至 09-08 平台入口、四账号和真实媒体处理

- 类型：平台后端和媒体链路版本，S2。
- 功能：
  - 登录和学校信息；
  - 四个学校上传账号和公司管理员后台；
  - 课程名额、上传进度、保存和下载；
  - FFmpeg/ffprobe 真实解码；
  - 采样画面、音轨、质量测量和受保护回放；
  - 上传任务和分析任务分离。
- 代表源码：
  - `src/rehab_affect/demo2_portal.py`
  - `src/rehab_affect/demo2_entry.py`
  - `src/rehab_affect/demo2_media_analysis.py`
  - `src/rehab_affect/demo2_media_worker.py`
  - `src/rehab_affect/demo2_manager_gateway.py`
  - `src/rehab_affect/student_record_store.py`
  - `src/rehab_affect/demo2_membership_store.py`
- 代表文档：
  - `docs/demo2_school_pilot_platform_plan_zh.md`
  - `docs/demo2_analysis_execution_plan_20260908_zh.md`
  - `docs/demo2_media_pipeline_zh.md`
  - `docs/media_pipeline_iteration_20260908_zh.md`
- 累计源码参考：`RehabAffect_Demo2_Source_20261011.zip` 包含该阶段之后的完整累计源码，但不是 9 月 8 日精确快照。
- 可恢复性：功能源码存在；精确日期差异不能由当前 Git 完整还原。

### V14 2026-09-09 至 09-11 身份、回看、手动画框和档案授权

- 类型：学生身份和敏感资料版本，S2。
- 功能：
  - 人脸位置与姓名身份拆分；
  - 学生 ID、学校范围和身份确认；
  - 手动画框、撤回、更正和短时位置建议；
  - 彩色原片参考和帧预览；
  - IEP、专业评估、支持资料的授权、版本、期限和课堂引用；
  - 资料原件和摘要的权限边界。
- 代表源码：
  - `src/rehab_affect/demo2_face_detection.py`
  - `src/rehab_affect/demo2_identity.py`
  - `src/rehab_affect/demo2_identity_store.py`
  - `src/rehab_affect/demo2_roi_tracking.py`
  - `src/rehab_affect/demo2_frame_preview.py`
  - `src/rehab_affect/demo2_dossier.py`
  - `src/rehab_affect/demo2_dossier_store.py`
  - `src/rehab_affect/demo2_dossier_vault.py`
  - `src/rehab_affect/student_record_store.py`
- 代表文档：
  - `docs/demo2_student_identity_flow_20260910_zh.md`
  - `docs/demo2_face_detection_zh.md`
  - `docs/demo2_teacher_identity_flow_20260911_zh.md`
  - `docs/contracts_demo2_dossier_v1_20260911.md`
  - `docs/demo2_dossier_delivery_20260911_zh.md`
- 主要边界：检测到人脸不等于确认姓名；未授权或证据失效时不能自动建立真实学生归属。

### V15 2026-09-15 至 09-17 评分、长期测量、图文报告和双轨评价

- 类型：评价和报告版本，S2。
- 功能：
  - 0 至 10 分制和 6 分参考线；
  - 证据不足不强行填 0；
  - 每课、每周、每月、滚动 60 天趋势；
  - 图文报告、关键时间段和证据引用；
  - 学校评价轨与系统增强评价轨；
  - 分差解释、权重和参考文献入口。
- 代表源码：
  - `src/rehab_affect/assessment_rubric.py`
  - `src/rehab_affect/classroom_rubric.py`
  - `src/rehab_affect/demo2_measurement.py`
  - `src/rehab_affect/demo2_measurement_store.py`
  - `src/rehab_affect/demo2_evaluation.py`
  - `src/rehab_affect/demo2_evaluation_store.py`
  - `src/rehab_affect/evaluation_policy.py`
  - `src/rehab_affect/seewo_long_report.py`
  - `src/rehab_affect/media_capture.py`
- 代表文档：
  - `docs/assessment_and_longitudinal_spec_zh.md`
  - `docs/dual_track_api_20260916.md`
  - `docs/dual_track_delivery_review_20260916.md`
- 边界：特殊教育课程动态权重、近年文献形成的正式权重和模型解释 Agent 尚未完成真实学校校准。

### V16 2026-09-21 至 09-29 课程工作台、同课去重、教学支持和体验优化

- 类型：课程分析和教师工作流版本，S2。
- 功能：
  - 新上传课程绑定自己的媒体版本；
  - 群像/个体观察、时间片、报告和导出；
  - 教师复核、修改、撤销和版本冲突保护；
  - 同课多视频去重复核；
  - 教学支持、逐课改进和发声记录；
  - 边看边记、目标复用、待办筛选和手机端布局。
- 代表源码：
  - `src/rehab_affect/demo2_course_analysis.py`
  - `src/rehab_affect/demo2_course_page.py`
  - `src/rehab_affect/demo2_batch_review.py`
  - `src/rehab_affect/demo2_batch_page.py`
  - `src/rehab_affect/teaching_support.py`
  - `src/rehab_affect/demo2_video_review.py`
  - `src/rehab_affect/video_applicability.py`
  - `src/rehab_affect/demo2_capture.py`
  - `src/rehab_affect/demo2_student_course_history.py`
  - `src/rehab_affect/demo2_student_summary_store.py`
  - `src/rehab_affect/demo2_student_summary_page.py`
- 代表文档：`docs/course_workspace_delivery_20260921.md`、`docs/batch_review_delivery_20260921.md`、`docs/teaching_support_delivery_20260928.md`、`docs/teacher_workflow_review_20260928.md`、`docs/context_evaluation_20260929.md`、`docs/safety_review_delivery_20260929.md`、`docs/video_applicability_20260929.md`。
- 验收：`output/playwright/course_workspace_20260921/acceptance.json`。

### V17 2026-10-08 四通道内测和平台交付基线

- 类型：内测平台交付基线，S2。
- 功能：四账号，公司后台，上传/处理/下载，保存期限，学校归属，后台查询和云端迁移准备。
- 代表源码：
  - `src/rehab_affect/demo2_portal.py`
  - `src/rehab_affect/demo2_manager_gateway.py`
  - `src/rehab_affect/demo2_channel_admin.py`
  - `src/rehab_affect/demo2_channel_admin_store.py`
  - `src/rehab_affect/student_record_store.py`
  - `src/rehab_affect/demo2_media_worker.py`
- 证据：`output/playwright/demo2_portal_*`、`.runtime/four_channel_acceptance*`、`output/pdf/Demo2_完整页面与四通道内测交付说明_20261008.pdf`。
- 可恢复性：当前工作区保留累计源码，但没有 10 月 8 日独立源码压缩包。

### V18 2026-10-11 Demo2 完整累计源码交付包

- 类型：完整累计源码包，S1。
- 源码包：本机归档中的 `RehabAffect_Demo2_Source_20261011.zip`（路径不写入公开仓库）。
- 包内功能：截至 10 月 11 日的 Demo2 入口、四账号平台、真实媒体处理、身份、档案、测量、双轨评价、课程工作台、教师支持、测试和部署辅助。
- 源码范围：压缩包内 `source/src/rehab_affect/`，覆盖 `demo2_*`、`student_record_store.py`、`assessment_rubric.py`、`classroom_rubric.py`、`teaching_support.py` 等。
- 版本用途：这是后续逐版本推送最重要的完整 Demo2 源码基线，可建立 `demo2-source-20261011` 标签。
- 不能公开：压缩包中的 `outputs`、运行数据库、示例媒体、密钥和测试数据必须排除。

### V19 2026-10-12 源码汇编与系统说明

- 类型：源码说明交付，S3/S1。
- 文档：本机归档中的“辅读学校 Demo2 源码汇编与系统说明”文档（路径不写入公开仓库）。
- 代码基线：V18 `RehabAffect_Demo2_Source_20261011.zip`。
- 用途：解释源码模块、运行方式、数据和云端方向，不是新的独立代码版本。

### V20 2026-10-16 学生档案、后台留存和维护版本

- 类型：数据维护和安全补充版本，S2。
- 功能：学生总结、课程历史、档案保存、授权、自动归档、后台查询和维护检查。
- 代表源码：
  - `src/rehab_affect/student_record_store.py`
  - `src/rehab_affect/demo2_dossier_store.py`
  - `src/rehab_affect/demo2_dossier_vault.py`
  - `src/rehab_affect/demo2_student_summary_store.py`
  - `src/rehab_affect/demo2_student_summary_page.py`
  - `src/rehab_affect/demo2_student_course_history.py`
  - `src/rehab_affect/demo2_evaluation_store.py`
  - `src/rehab_affect/demo2_identity_store.py`
- 测试证据：`.runtime/real_material_test_20261016/`、`.runtime/admin_history_acceptance_20261016/`、`.runtime/pilot_acceptance_20261016/`。
- 可恢复性：源码仍在当前工作区；没有独立完整压缩包，恢复时以 V18 加当前差异为准。

### V21 2026-10-20 云端迁移和上传修复候选过程

- 类型：云端部署过程，不拆成多个正式版本，P。
- 证据目录：`.runtime/cloud_deploy_20261020/`。
- 候选包：`app_initial.tar.gz`、`app_cloud_v1.tar.gz` 至 `app_cloud_v9.tar.gz`、多个 `app_cloud_v10_*`。
- 功能过程：腾讯云轻量服务器，HTTPS，网关和系统服务，分片上传，失败处理，下载，公司后台，四账号隔离，真实媒体处理，处理耗时、源文件哈希和报告下载验证。
- 正式处理：所有 `app_cloud_v1-v10` 只在本目录作为研发留痕，统一归入最终云端版本，不单独作为 GitHub 正式云端版本。
- 不能推送：`.runtime/` 内的邀请信息、私钥、截图、真实数据和内部配置。

### V22 2026-10-21 云端课堂草稿、学生结果和身份阶段

- 类型：云端候选过程，P/C。
- 阶段目录：
  - `.runtime/cloud_draft_release/`
  - `.runtime/cloud_student_release/`
  - `.runtime/cloud_identity_stage_20261021/`
  - `.runtime/cloud_release_overrides/`
- 功能：课堂草稿、真实视频课程分析、学生洞察卡、匿名人物候选、身份阶段入口、课堂报告和后台保留。
- 代表源码：`demo2_course_analysis.py`、`demo2_course_page.py`、`demo2_person_candidates.py`、`demo2_identity.py`、`demo2_dossier.py`、`demo2_media_analysis.py`、`student_record_store.py`。
- 证据：`deploy/cloud/classroom_draft_release_20261021.md`、各阶段 `accepted.json` 和云端验收目录。
- 正式处理：不拆成多个云端版本，合并说明到 V23。

### V23 2026-10-22 最终云端交付版 v3.2

- 类型：正式最终云端版本，F/C。
- 正式版本名：`cloud-final-v3.2-20261022`。
- 版本规则：云端正式目录只保留这一版；之前的云端候选、课堂草稿、学生阶段、身份阶段、帧修复、人物跟踪和人像修复都作为研发来源，不再单独作为云端交付版本。
- 最终功能：
  - 登录和学校上传入口；
  - 少量课程信息填写；
  - 视频分片上传和任务保存；
  - 后台真实解码、音轨提取和分析；
  - 最多 3 个匿名人物候选；
  - 按人物切换的独立截图、人物框、时间轴、状态线索和参考分；
  - 彩色证据帧和原视频播放/下载；
  - 每个人物的几百字课堂分析报告；
  - 帮助页面；
  - 公司后台任务查询、状态和下载；
  - 历史高级页面保留，但不强制阻塞“登录-上传-分析-结果”主线。
- 最终分析源码证据：
  - `.runtime/cloud_candidate_tracking_20261022_v2/src/rehab_affect/demo2_media_analysis.py`
  - `.runtime/cloud_candidate_tracking_20261022_v2/src/rehab_affect/demo2_media_worker.py`
  - `.runtime/cloud_candidate_tracking_20261022_v2/src/rehab_affect/demo2_student_tracking.py`
  - `.runtime/cloud_candidate_tracking_20261022_v2/src/rehab_affect/demo2_simple_result.py`
  - `.runtime/cloud_candidate_tracking_20261022_v2/src/rehab_affect/student_record_store.py`
- 帮助和人像修复证据：
  - `.runtime/cloud_help_release_20261022/`
  - `.runtime/cloud_candidate_20261022_portraits_v5/`
  - `deploy/cloud/portrait_release_20261022.md`
- 最终验收：
  - `output/playwright/full-real-v32-20261022/acceptance.json`
  - `output/playwright/full-real-v32-20261022/`
  - 三段任务均确认上传完成、后台完成、3 个人物、独立时间轴、参考分、报告、下载源文件哈希一致、人物结果不同和浏览器无错误。
- 当前分析版本：`simple_student_seats_v3_2`，报告版本 `motion_report_v2`。
- 边界：结果是匿名人物的课堂画面变化/活动线索，不是自动姓名识别、IEP 自动关联、医学诊断、正式学习成绩或已验证的教育评分准确率。
- GitHub 处理：只推送脱敏源码、测试和部署模板，不推送 `.runtime/`、数据库、真实视频、人物截图、私钥、邀请密钥和 API Key。

### V24 2026-10-23 户外视频和高清课堂视频复核

- 类型：最终云端版本的测试补充，不新增云端版本，P/C。
- 证据目录：`work/20261023_video_review/`。
- 功能：高清/户外视频解码，音轨提取，抽帧，人物状态结果页面，视频接触表和分析 JSON。
- 代表源码：`src/rehab_affect/demo2_media_analysis.py`、`src/rehab_affect/demo2_student_tracking.py`。
- 正式处理：归入 V23 的最终云端测试证据，不建立 `cloud-v24`。

## Doc2.docx 查漏补缺映射

`Doc2.docx` 是截图型材料，包含 10 张页面截图，没有可直接恢复的源代码。它用于核对以下功能是否在版本目录中有对应源码：

| Doc2 页面 | 功能 | 源代码入口 | 版本 | 最终云端状态 |
| --- | --- | --- | --- | --- |
| 学生资料授权与期限 | 授权依据、保存范围、截止日期、撤回和不可用提示 | `demo2_dossier.py`、`demo2_dossier_store.py`、`demo2_dossier_vault.py` | V14/V20 | 保留高级模块，不阻塞 V23 主线 |
| IEP 与专业资料导入 | IEP、专业评估、五领域评估、安全支持资料 | `demo2_dossier.py`、`demo2_dossier_store.py` | V14/V20 | 源码存在，真实资料需授权 |
| 课堂关联学生资料 | 学生身份、课程任务、资料版本、课堂引用 | `demo2_identity.py`、`demo2_identity_store.py`、`demo2_course_page.py` | V14/V16 | 源码存在，V23 先输出匿名人物 |
| 学生测量评分标准 | 0-10 分、参考线、证据和长期趋势 | `assessment_rubric.py`、`demo2_measurement.py`、`demo2_measurement_store.py` | V15/V16 | 源码存在，教育评分准确率未完成验证 |
| 双轨评价入口 | 学校评价和系统增强评价切换 | `demo2_evaluation.py`、`demo2_evaluation_store.py` | V15/V16 | 源码存在，保留高级页面 |
| 学校评价 | 学校原始指标、人工录入、学校轨结果 | `classroom_rubric.py`、`demo2_evaluation.py` | V15/V16 | 权重需校方实际数据校准 |
| 系统增强评价 | 系统规则、增强权重、证据和建议 | `classroom_rubric.py`、`evaluation_policy.py` | V15/V16 | 页面存在，不等于科学权重已验证 |
| 学校与系统分差对照 | 两套分数、差值、原因和证据 | `demo2_evaluation.py`、`demo2_evaluation_store.py` | V15/V16 | 源码存在，需学校评分数据对照 |
| 千字图文报告 | 课堂总结、时间段、趋势和文字说明 | `seewo_long_report.py`、`demo2_course_analysis.py`、`demo2_course_page.py` | V08/V15/V16 | V23 主线输出缩短版几百字报告 |
| 公司后台总览 | 学校、任务、状态、存储和下载 | `demo2_portal.py`、`demo2_channel_admin.py`、`student_record_store.py` | V13/V17/V20 | V23 已纳入云端链路 |

## 以前有、后来看起来没有的原因

1. Demo1 的单学生时间轴依赖固定学生区域和固定样例视频；后来 Demo2 改成通用上传和匿名人物结果，不能直接沿用姓名和 ROI。
2. 学生名册、IEP、教师复核和双轨评价后来被保留为高级页面，但为了先跑通“登录-上传-分析-结果”，它们被移出主线必经步骤。
3. 云端发布使用筛选后的发布包，不是把整个本地工作区原样搬过去；部分本地源码仍存在，但没有进入当时的云端候选包。
4. 多模态候选模型曾出现人物对应和动作错误，没有直接作为正式结果发布，后续回退到本地解码、匿名人物候选和彩色证据帧。
5. 当前 `simple_student_seats_v3_2` 的状态定义更保守，主要是活动变化和证据可见性线索，不再直接把 Demo1 的标签当成通用新视频结论。
6. Git 没有逐次历史，导致后续只能从源码包、运行目录和文档重建，不能用一次 `git checkout` 恢复所有旧版本。

## 正式逐版本推送顺序

1. V01-V07：推基础工程和 Demo1 源码，保留单学生状态时间轴基线。
2. V08-V12：推三学生 Demo2 和 2026-08-27 完整交付源码。
3. V13-V16：推平台、媒体、身份、档案、评分和课程工作台源码。
4. V17-V20：推四通道、后台、保存和维护相关源码。
5. V23：最后只推一个 `cloud-final-v3.2-20261022` 云端版本。
6. V24：作为 V23 的测试证据，不新增云端版本号。

每个正式版本都应包含源码、配置模板、测试、运行说明、版本说明和 SHA-256 清单；不应包含真实数据库、真实视频、学生档案、人物截图、邀请密钥、部署私钥或第三方 API Key。
