# Demo2 1-10 整合核对日志（2026-10-26）

由 `scripts/verify_integration_20261026.py` 生成；原始 JSONL：`.runtime/logs/integration_check_20261026_201316.jsonl`（.runtime 不入库）。

失败项：0

| 时间 | 操作 | 结果 | 关键参数 |
|---|---|---|---|
| 2026-10-26T20:13:16+08:00 | start | INFO | root=/Volumes/数据/workdir/闲鱼/教育课堂视频分析平台_20261026172608/RehabAffectPerception; branch=integration/demo2-1-10 |
| 2026-10-26T20:13:16+08:00 | checkout | PASS | expected=integration/demo2-1-10; actual=integration/demo2-1-10 |
| 2026-10-26T20:13:16+08:00 | head | PASS | sha=d875333 |
| 2026-10-26T20:13:16+08:00 | remote-head | PASS | sha=d804a6b; legacy_head=7b6a3d6; note=remote advanced past legacy head |
| 2026-10-26T20:13:16+08:00 | log-check | PASS | sha=051b0ab; subject=Keep upload flow focused and refresh legacy checks; in_head_history=True; actual=051b0ab/2026-10-25 22:56:17 +0800/Keep upload flow focused and refresh legacy checks |
| 2026-10-26T20:13:16+08:00 | log-check | PASS | sha=df0710f; subject=Harden IEP joins and admin report privacy; in_head_history=True; actual=df0710f/2026-10-25 21:59:25 +0800/Harden IEP joins and admin report privacy |
| 2026-10-26T20:13:16+08:00 | log-check | PASS | sha=a3208e0; subject=Require task scope for company analysis access; in_head_history=True; actual=a3208e0/2026-10-25 21:33:01 +0800/Require task scope for company analysis access |
| 2026-10-26T20:13:16+08:00 | log-check | PASS | sha=3b355be; subject=Fix Demo2 upload processing and cloud deployment integration; in_head_history=True; actual=3b355be/2026-10-25 21:11:23 +0800/Fix Demo2 upload processing and cloud deployment integration |
| 2026-10-26T20:13:16+08:00 | worktree | PASS | tracked_changes=3 |
| 2026-10-26T20:13:16+08:00 | entry-file | PASS | capability=Demo2 上传页; file=src/rehab_affect/demo2_portal.py; missing=- |
| 2026-10-26T20:13:16+08:00 | entry-file | PASS | capability=Demo2 分片上传/续传 API; file=src/rehab_affect/demo2_manager_gateway.py; missing=- |
| 2026-10-26T20:13:16+08:00 | entry-file | PASS | capability=Demo2 上传任务建档; file=src/rehab_affect/student_record_store.py; missing=- |
| 2026-10-26T20:13:16+08:00 | entry-file | PASS | capability=Demo1/旧版视频分片上传; file=src/rehab_affect/scenario_lab_server.py; missing=- |
| 2026-10-26T20:13:16+08:00 | entry-file | PASS | capability=Demo1 单学生状态时间轴; file=src/rehab_affect/seewo_student_demo.py; missing=- |
| 2026-10-26T20:13:16+08:00 | entry-file | PASS | capability=Demo1 多学生状态时间轴; file=src/rehab_affect/seewo_multi_student_demo.py; missing=- |
| 2026-10-26T20:13:16+08:00 | entry-file | PASS | capability=Demo2 人物学生状态时间轴页; file=src/rehab_affect/demo2_simple_result.py; missing=- |
| 2026-10-26T20:13:16+08:00 | entry-file | PASS | capability=Demo2 学生跟踪; file=src/rehab_affect/demo2_student_tracking.py; missing=- |
| 2026-10-26T20:13:16+08:00 | entry-file | PASS | capability=Demo2 媒体分析; file=src/rehab_affect/demo2_media_analysis.py; missing=- |
| 2026-10-26T20:13:16+08:00 | entry-file | PASS | capability=Demo1 长报告; file=src/rehab_affect/seewo_long_report.py; missing=- |
| 2026-10-26T20:13:16+08:00 | entry-file | PASS | capability=Demo2 课程报告构建; file=src/rehab_affect/demo2_course_analysis.py; missing=- |
| 2026-10-26T20:13:16+08:00 | entry-file | PASS | capability=Demo2 报告快照与下载; file=src/rehab_affect/demo2_report_store.py; missing=- |
| 2026-10-26T20:13:16+08:00 | entry-file | PASS | capability=报告/分析 API; file=src/rehab_affect/demo2_manager_gateway.py; missing=- |
| 2026-10-26T20:13:16+08:00 | entry-file | PASS | capability=视频结果下载; file=src/rehab_affect/scenario_lab_server.py; missing=- |
| 2026-10-26T20:13:16+08:00 | entry-file | PASS | capability=视频结果下载存储; file=src/rehab_affect/student_record_store.py; missing=- |
| 2026-10-26T20:13:16+08:00 | entry-file | PASS | capability=资料原件下载; file=src/rehab_affect/demo2_dossier_store.py; missing=- |
| 2026-10-26T20:13:16+08:00 | entry-file | PASS | capability=页面路由; file=src/rehab_affect/scenario_lab_server.py; missing=- |
| 2026-10-26T20:13:16+08:00 | entry-file | PASS | capability=公司后台页; file=src/rehab_affect/demo2_portal.py; missing=- |
| 2026-10-26T20:13:16+08:00 | entry-file | PASS | capability=Windows 启动入口 Demo1; file=start_school_demo.cmd; missing=- |
| 2026-10-26T20:13:16+08:00 | entry-file | PASS | capability=Windows 启动入口 Demo2; file=start_school_demo2.cmd; missing=- |
| 2026-10-26T20:13:16+08:00 | id-field | PASS | field=school_id; file_count=5; files=demo2_dossier_store.py,demo2_evaluation_store.py,demo2_report_store.py,evaluation_report_contract.py,student_record_store.py |
| 2026-10-26T20:13:16+08:00 | id-field | PASS | field=student_id; file_count=28; files=demo2_batch_page.py,demo2_batch_review.py,demo2_course_analysis.py,demo2_course_page.py,demo2_dossier.py,demo2_dossier_store.py,demo2_evaluation_store.py,demo2_identity.py |
| 2026-10-26T20:13:16+08:00 | id-field | PASS | field=iep_document_id; file_count=3; files=demo2_dossier_store.py,demo2_evaluation_store.py,demo2_report_store.py |
| 2026-10-26T20:13:16+08:00 | id-field | PASS | field=iep_summary_id; file_count=4; files=demo2_course_analysis.py,demo2_evaluation_store.py,demo2_iep_context.py,evaluation_report_contract.py |
| 2026-10-26T20:13:16+08:00 | id-field | PASS | field=course_id; file_count=23; files=demo2_admin_debug.py,demo2_batch_page.py,demo2_capture.py,demo2_channel_admin_store.py,demo2_course_analysis.py,demo2_dossier.py,demo2_dossier_store.py,demo2_evaluation.py |
| 2026-10-26T20:13:16+08:00 | id-field | PASS | field=video_task_id; file_count=5; files=demo2_dossier_store.py,demo2_evaluation_debug.py,demo2_evaluation_store.py,demo2_report_store.py,student_record_store.py |
| 2026-10-26T20:13:16+08:00 | id-field | PASS | field=task_id; file_count=41; files=closed_loop.py,demo2_admin_debug.py,demo2_batch_page.py,demo2_batch_review.py,demo2_capture.py,demo2_course_analysis.py,demo2_course_page.py,demo2_dossier.py |
| 2026-10-26T20:13:16+08:00 | id-field | PASS | field=evaluation_id; file_count=7; files=demo2_course_analysis.py,demo2_course_page.py,demo2_evaluation_debug.py,demo2_evaluation_store.py,demo2_report_debug.py,demo2_report_store.py,evaluation_report_contract.py |
| 2026-10-26T20:13:16+08:00 | id-field | PASS | field=report_id; file_count=10; files=demo2_admin_debug.py,demo2_course_analysis.py,demo2_course_page.py,demo2_evaluation_store.py,demo2_portal.py,demo2_report_debug.py,demo2_report_store.py,evaluation_report_contract.py |
| 2026-10-26T20:13:16+08:00 | tracked-runtime | PASS | tracked_count=0 |
| 2026-10-26T20:13:16+08:00 | tracked-sensitive | PASS | files=- |
| 2026-10-26T20:13:16+08:00 | gitignore | PASS | path=.runtime/demo2.sqlite3; rule=.gitignore:8:.runtime/	.runtime/demo2.sqlite3 |
| 2026-10-26T20:13:16+08:00 | gitignore | PASS | path=.runtime/demo2.sqlite3-wal; rule=.gitignore:8:.runtime/	.runtime/demo2.sqlite3-wal |
| 2026-10-26T20:13:16+08:00 | gitignore | PASS | path=.runtime/demo2.sqlite3-shm; rule=.gitignore:8:.runtime/	.runtime/demo2.sqlite3-shm |
| 2026-10-26T20:13:16+08:00 | gitignore | PASS | path=.runtime/keys/dossier.key; rule=.gitignore:8:.runtime/	.runtime/keys/dossier.key |
| 2026-10-26T20:13:16+08:00 | gitignore | PASS | path=.runtime/secrets/fernet.key; rule=.gitignore:8:.runtime/	.runtime/secrets/fernet.key |
| 2026-10-26T20:13:16+08:00 | gitignore | PASS | path=.runtime/invitations.json; rule=.gitignore:8:.runtime/	.runtime/invitations.json |
| 2026-10-26T20:13:16+08:00 | gitignore | PASS | path=.runtime/uploads/lesson.mp4; rule=.gitignore:8:.runtime/	.runtime/uploads/lesson.mp4 |
| 2026-10-26T20:13:16+08:00 | gitignore | PASS | path=.runtime/cloud_candidate_20261026/source.tar.gz; rule=.gitignore:8:.runtime/	.runtime/cloud_candidate_20261026/source.tar.gz |
| 2026-10-26T20:13:16+08:00 | gitignore | PASS | path=data/raw/real_lesson.mov; rule=.gitignore:9:data/raw/	data/raw/real_lesson.mov |
| 2026-10-26T20:13:16+08:00 | gitignore | PASS | path=classroom.db; rule=.gitignore:21:*.db	classroom.db |
| 2026-10-26T20:13:16+08:00 | gitignore | PASS | path=deploy/cloud/.env; rule=.gitignore:7:.env	deploy/cloud/.env |
| 2026-10-26T20:13:16+08:00 | gitignore | PASS | path=deploy/cloud/id_ed25519; rule=.gitignore:50:id_ed25519*	deploy/cloud/id_ed25519 |
| 2026-10-26T20:13:16+08:00 | gitignore | PASS | path=deploy/cloud/server.pem; rule=.gitignore:45:*.pem	deploy/cloud/server.pem |
| 2026-10-26T20:13:16+08:00 | import | PASS | python=3.12.11 |
| 2026-10-26T20:13:17+08:00 | compileall | PASS | target=src; warnings=0 |
| 2026-10-26T20:13:17+08:00 | finish | PASS | failures=0 |
