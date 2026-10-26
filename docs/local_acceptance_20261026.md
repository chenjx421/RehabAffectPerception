# Demo2 1-10 本地验收记录（2026-10-26）

> **数据声明**：本次验收只使用 FFmpeg 生成的合成测试图案视频（`testsrc2` 彩条 + 440 Hz 正弦音）、虚构学生（“虚构学生甲”，编号 `SYN-001`）和合成 IEP 摘要文本；未使用任何真实学生视频、真实学生资料、人脸截图或 IEP 原件。
>
> **准确性声明**：本文记录的是软件流程与数据链路的验收结果。流程中“输出了学生状态 / 评分 / 报告”只说明接口、存储、权限和关联关系可用，**教育准确性未验证**，不能作为学生识别、状态判断或评分准确的证据。
>
> **凭据声明**：测试账号由临时库按随机前缀生成，密码、会话 Cookie、Fernet 密钥只存在于测试进程内存，本文和日志不含任何密码、API Key、邀请密钥或部署私钥。本次未执行 GitHub 推送或云端部署，不代表“已发布”。

## 1. 执行环境

| 项目 | 值 |
|---|---|
| 执行时间 | 2026-10-26T21:16:33+08:00 ~ 2026-10-26T21:19:17+08:00 |
| 分支 / HEAD | `integration/demo2-1-10` / `d875333`（工作区含 19 个未提交改动或新增文件，来自本轮 1-10 整合子任务） |
| 平台 | Darwin 24.6.0 arm64（macOS 开发机，非云端） |
| Python | 3.12.11（仓库 `.venv`，uv 管理） |
| FFmpeg | `/opt/homebrew/bin/ffmpeg`（ffmpeg version 8.1.2） |
| 运行方式 | `PYTHONPATH=src`；每组独立可写 `--basetemp`（`../.runtime/pytest-tmp/local_acceptance_20261026_211633/<组名>`） |
| 原始日志 | `../.runtime/logs/local_acceptance_20261026_211633.jsonl`（.runtime 不入库） |

本机 FFmpeg 状态不能代替云端 `/usr/bin/ffmpeg`、`/usr/bin/ffprobe` 的确认。

## 2. 三组回归测试

| 测试组 | 文件数 | passed | failed | errors | skipped | 基线 | 结论 | 耗时 |
|---|---|---|---|---|---|---|---|---|
| 数据闭环（IEP、学生关联、评分、报告） | 13 | 102 | 0 | 0 | 1 | ≥47 passed | 通过 | 20.7s |
| 上传 / 媒体 / FFmpeg 调用路径 | 13 | 391 | 0 | 0 | 1 | ≥350 passed，skipped ≤3 | 通过 | 84.1s |
| 门户与后台（含网关、通道管理、后台刷新） | 9 | 372 | 0 | 0 | 1 | ≥340 passed，skipped ≤1 | 通过 | 48.2s |
| 网关专项（门户组子集，单独复核） | 1 | 137 | 0 | 0 | 0 | ≥137 passed，skipped ≤0 | 通过 | 6.9s |
| 管理员无 task_id 访问 /demo2/analysis 断言（门户组子集） | 2 | 2 | 0 | 0 | 0 | ≥2 passed，skipped ≤0 | 通过 | 1.8s |

基线来源：2026-10-25 交接说明（数据闭环 47 passed；媒体 350 passed, 3 skipped；门户 340 passed, 1 skipped；网关专项 137 passed）。本次按同一范围选取文件，并补入后续子任务新增的相关测试，因此数量高于基线。历史全量媒体 / 浏览器 / 恢复套件未在本次运行，也不与本表混写。

### 数据闭环（IEP、学生关联、评分、报告）

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q -rfEs -p no:cacheprovider --basetemp=../.runtime/pytest-tmp/local_acceptance_20261026_211633/data tests/test_demo2_iep_report_integration.py tests/test_demo2_report_store.py tests/test_demo2_course_analysis.py tests/test_demo2_evaluation_provenance.py tests/test_demo2_evaluation_store.py tests/test_demo2_dossier_iep_access.py tests/test_demo2_measurement_store.py tests/test_demo2_dual_track_evaluation.py tests/test_demo2_evaluation_api.py tests/test_demo2_classroom_report.py tests/test_demo2_classroom_report_http.py tests/test_verify_id_chain.py tests/test_measurement_scoring_standard.py
```

- pytest 汇总：`102 passed, 1 skipped in 20.45s`
- 退出码：0
- 失败用例：无
- 跳过原因：
  - `SKIPPED [1] tests/test_demo2_evaluation_provenance.py:134: Installed Node/Playwright required; no downloads`

### 上传 / 媒体 / FFmpeg 调用路径

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q -rfEs -p no:cacheprovider --basetemp=../.runtime/pytest-tmp/local_acceptance_20261026_211633/media tests/test_demo2_media_analysis.py tests/test_demo2_media_api.py tests/test_demo2_media_cache.py tests/test_demo2_media_store.py tests/test_demo2_media_worker.py tests/test_demo2_upload_analysis_flow.py tests/test_demo2_upload_repair.py tests/test_demo2_upload_recovery_frontend.py tests/test_prepare_upload_video.py tests/test_cloud_media_smoke.py tests/test_demo2_frame_preview.py tests/test_video_applicability.py tests/test_student_record_store.py
```

- pytest 汇总：`391 passed, 1 skipped in 83.83s (0:01:23)`
- 退出码：0
- 失败用例：无
- 跳过原因：
  - `SKIPPED [1] tests/test_demo2_frame_preview.py:258: Windows mapped network drive policy`

### 门户与后台（含网关、通道管理、后台刷新）

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q -rfEs -p no:cacheprovider --basetemp=../.runtime/pytest-tmp/local_acceptance_20261026_211633/portal tests/test_demo2_manager_gateway.py tests/test_demo2_gateway_reject_drain.py tests/test_demo2_portal_html.py tests/test_demo2_portal_api.py tests/test_demo2_admin_refresh.py tests/test_demo2_admin_overview_tasks.py tests/test_demo2_channel_admin_html.py tests/test_demo2_channel_admin_store.py tests/test_scenario_lab_server.py
```

- pytest 汇总：`372 passed, 1 skipped in 47.97s`
- 退出码：0
- 失败用例：无
- 跳过原因：
  - `SKIPPED [1] tests/test_demo2_channel_admin_html.py:293: Installed Chromium 1243 and Playwright required; no downloads`

### 网关专项（门户组子集，单独复核）

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q -rfEs -p no:cacheprovider --basetemp=../.runtime/pytest-tmp/local_acceptance_20261026_211633/gateway tests/test_demo2_manager_gateway.py
```

- pytest 汇总：`137 passed in 6.65s`
- 退出码：0
- 失败用例：无

### 管理员无 task_id 访问 /demo2/analysis 断言（门户组子集）

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q -rfEs -p no:cacheprovider --basetemp=../.runtime/pytest-tmp/local_acceptance_20261026_211633/admin_analysis_guide tests/test_demo2_admin_overview_tasks.py tests/test_demo2_portal_api.py -k "test_analysis_guide_reads_no_classroom_data or test_portal_pages_redirect_and_enforce_roles"
```

- pytest 汇总：`2 passed, 47 deselected in 1.51s`
- 退出码：0
- 失败用例：无

门户组中管理员访问无 `task_id` 的 `/demo2/analysis` 的断言为 **HTTP 200 安全引导页且不读取课堂数据**（`tests/test_demo2_admin_overview_tasks.py::test_analysis_guide_reads_no_classroom_data`、`tests/test_demo2_portal_api.py::test_portal_pages_redirect_and_enforce_roles`），上表“管理员无 task_id”行单独复核该断言；端到端第 9 步也在真实 HTTP 下再次确认。

## 3. compileall 与 git diff --check

| 检查 | 命令 | 结果 | 输出 |
|---|---|---|---|
| compileall | `PYTHONPATH=src .venv/bin/python -m compileall -q src tests scripts` | 通过 | 无输出 |
| git diff --check | `git diff --check` | 通过 | 无输出 |
| 新增未跟踪文件空白检查 | `git ls-files --others --exclude-standard（逐行检查行尾空白 / 冲突标记）` | 通过 | 检查 0 个新增文本文件，无问题 |

## 4. 合成视频端到端流程

```bash
PYTHONPATH=src .venv/bin/python scripts/local_synthetic_e2e_20261026.py --port 9185
```

脚本在 `127.0.0.1:9185`（项目端口范围 9180-9199）启动隔离服务：临时 SQLite、临时上传目录、临时 Fernet 资料密钥、真实 FFmpeg 和真实后台分析 worker；不触碰 `outputs/` 或任何正式数据库。合成视频：ffmpeg lavfi testsrc2 320x240 10fps 4s + sine 440Hz，123642 字节，SHA256 `cb83c5d01a2326f47761e4684de26ca3dd24cbff6e1c59e7cd53b9f99a48e4d0`。

| # | 步骤 | 结果 | 关键记录 |
|---|---|---|---|
| 1 | 登录（学校上传账号 + 公司管理员） | 通过 | {"admin_account_id": "ecca51ff1a6e45b78e58b4692b856f19", "bound_channel_id": "channel_1", "school_account_id": "0f13141fca8a420bb27a81069d06da3f"} |
| 2 | 上传合成视频（分片上传 + SHA256 校验） | 通过 | {"bytes": 123642, "channel_id": "channel_1", "course_id": "synthetic-course-20261026", "video_task_id": "b7c7106ded8848dca011febf43df89c7"} |
| 3 | 后台处理（真实 FFmpeg + 分析 worker） | 通过 | {"analysis_status": "evidence_ready", "seconds": 1.1} |
| 4 | 学生状态结果（任务范围内） | 通过 | {"binding_id": "436a2003-f192-4e31-a772-f6ed2dc00058", "frame_revision": "a0e0d2fc93ad2d0b2bae2127f24677e609e92b8f27fb30dea2c09e42cfb10312", "frames": 4, "measurement_overall_score": 6.85, "measurement_record_id": "synthetic-measurement-1", "simple_analysis_available": false, "simple_analysis_reason": "no_face_candidates", "student_id": "879bc846-6dd3-4c56-9c20-59b58a2fd61b"} |
| 5 | 学校评分 / 系统评分 | 通过 | {"evaluation_id": "evaluation-synthetic-evaluation-1", "school_raw_score": 80.0, "school_teaching_score_70": 56.0, "system_score_10": 7.54, "version": 1} |
| 6 | 分差说明 | 通过 | {"evidence_delta": -0.5, "total_delta": -0.46, "weight_delta": 0.04} |
| 7 | 报告生成（课程报告快照） | 通过 | {"content_report_id": "report-74699a6c9239023ba610fe65", "evaluation_count": 1, "report_id": "9b340ae65d824b849a3fbef07676d6ae"} |
| 8 | 教师报告下载（md/json） | 通过 | {"json_bytes": 12406, "md_bytes": 5231, "teacher_iep_links": 1} |
| 9 | 公司后台查询（任务 + 报告） | 通过 | {"admin_report_rows": 1, "admin_task_status": "evidence_ready", "analysis_without_task_id_status": 200, "recent_uploads": 1} |
| 10 | 公司后台视频 / 报告下载 | 通过 | {"report_json_bytes": 12031, "report_md_bytes": 5231, "result_bytes": 3576, "video_bytes": 123642, "video_sha256_match": true} |

说明：

- 第 4 步“学生状态”：`/api/v1/demo2/simple-result` 与 `/demo2/simple-result` 页面均在任务范围内返回。合成彩条画面中没有人脸，自动人物状态返回 `available=False`、`reason=no_face_candidates`，这是预期的诚实结果；随后教师在分析画面中把区域确认为虚构学生，并录入一条已复核的课堂测量记录，学生状态由该记录进入课程工作区。
- 第 5、6 步：学校评分为教师录入的 10 项分数，系统评分为增强轨（证据修正 + 权重）结果；分差说明来自同一记录的 `comparison`，评分页同时展示“分差不表示系统比教师更准确”。
- 第 7~10 步：教师侧报告保留 `iep_links`；公司管理员查看和下载（md/json）报告时 `iep_links` 已移除，合成 IEP 摘要文本未出现在任何下载内容或报告快照中（快照检查：True）。管理员下载的源视频与上传字节完全一致。

### 4.1 贯通的 ID 链路（实际值）

由 `scripts/verify_id_chain.py --report-id <report_id> --json --require-iep` 以只读方式从报告反向追溯，退出码 `0`，并与端到端流程中接口返回的 ID 逐一比对（一致：True）。

| 层级 | 实际值 | 流程中接口返回值 |
|---|---|---|
| `school_id` | `school-49ecc873ba0703af03ba5581` | `（由学校快照派生，接口不直接返回）` |
| `student_id` | `879bc846-6dd3-4c56-9c20-59b58a2fd61b` | `879bc846-6dd3-4c56-9c20-59b58a2fd61b` |
| `iep_document_id` | `44f948766bfa49f593af12476089bcbc` | `44f948766bfa49f593af12476089bcbc` |
| `course_id` | `synthetic-course-20261026` | `synthetic-course-20261026` |
| `video_task_id` | `b7c7106ded8848dca011febf43df89c7` | `b7c7106ded8848dca011febf43df89c7` |
| `evaluation_id` | `evaluation-synthetic-evaluation-1` | `evaluation-synthetic-evaluation-1` |
| `report_id` | `9b340ae65d824b849a3fbef07676d6ae` | `9b340ae65d824b849a3fbef07676d6ae` |

报告内容编号 `content_report_id` = `report-74699a6c9239023ba610fe65`（与快照 `report_id` 按设计不同）。以上 ID 均来自本次临时库，测试结束后临时库随目录删除。

## 5. 执行日志

| 时间 | 测试组 | 步骤 | 结果 | 命令 | passed | failed | skipped | 失败用例 |
|---|---|---|---|---|---|---|---|---|
| 2026-10-26T21:16:53+08:00 | data | finish | PASS | `PYTHONPATH=src .venv/bin/python -m pytest -q -rfEs -p no:cacheprovider --basetemp=../.runtime/pytest-tmp/local_acceptance_20261026_211633/data tests/test_demo2_iep_report_integration.py tests/test_demo2_report_store.py tests/test_demo2_course_analysis.py tests/test_demo2_evaluation_provenance.py tests/test_demo2_evaluation_store.py tests/test_demo2_dossier_iep_access.py tests/test_demo2_measurement_store.py tests/test_demo2_dual_track_evaluation.py tests/test_demo2_evaluation_api.py tests/test_demo2_classroom_report.py tests/test_demo2_classroom_report_http.py tests/test_verify_id_chain.py tests/test_measurement_scoring_standard.py` |102 | 0 | 1 | 无 |
| 2026-10-26T21:18:17+08:00 | media | finish | PASS | `PYTHONPATH=src .venv/bin/python -m pytest -q -rfEs -p no:cacheprovider --basetemp=../.runtime/pytest-tmp/local_acceptance_20261026_211633/media tests/test_demo2_media_analysis.py tests/test_demo2_media_api.py tests/test_demo2_media_cache.py tests/test_demo2_media_store.py tests/test_demo2_media_worker.py tests/test_demo2_upload_analysis_flow.py tests/test_demo2_upload_repair.py tests/test_demo2_upload_recovery_frontend.py tests/test_prepare_upload_video.py tests/test_cloud_media_smoke.py tests/test_demo2_frame_preview.py tests/test_video_applicability.py tests/test_student_record_store.py` |391 | 0 | 1 | 无 |
| 2026-10-26T21:19:06+08:00 | portal | finish | PASS | `PYTHONPATH=src .venv/bin/python -m pytest -q -rfEs -p no:cacheprovider --basetemp=../.runtime/pytest-tmp/local_acceptance_20261026_211633/portal tests/test_demo2_manager_gateway.py tests/test_demo2_gateway_reject_drain.py tests/test_demo2_portal_html.py tests/test_demo2_portal_api.py tests/test_demo2_admin_refresh.py tests/test_demo2_admin_overview_tasks.py tests/test_demo2_channel_admin_html.py tests/test_demo2_channel_admin_store.py tests/test_scenario_lab_server.py` |372 | 0 | 1 | 无 |
| 2026-10-26T21:19:13+08:00 | gateway | finish | PASS | `PYTHONPATH=src .venv/bin/python -m pytest -q -rfEs -p no:cacheprovider --basetemp=../.runtime/pytest-tmp/local_acceptance_20261026_211633/gateway tests/test_demo2_manager_gateway.py` |137 | 0 | 0 | 无 |
| 2026-10-26T21:19:14+08:00 | admin_analysis_guide | finish | PASS | `PYTHONPATH=src .venv/bin/python -m pytest -q -rfEs -p no:cacheprovider --basetemp=../.runtime/pytest-tmp/local_acceptance_20261026_211633/admin_analysis_guide tests/test_demo2_admin_overview_tasks.py tests/test_demo2_portal_api.py -k "test_analysis_guide_reads_no_classroom_data or test_portal_pages_redirect_and_enforce_roles"` |2 | 0 | 0 | 无 |
| 2026-10-26T21:19:15+08:00 | compileall | finish | PASS | `PYTHONPATH=src .venv/bin/python -m compileall -q src tests scripts` |- | - | - | 无 |
| 2026-10-26T21:19:15+08:00 | git_diff_check | finish | PASS | `git diff --check` |- | - | - | 无 |
| 2026-10-26T21:19:15+08:00 | untracked_whitespace | finish | PASS | `git ls-files --others --exclude-standard（逐行检查行尾空白 / 冲突标记）` |- | - | - | 无 |
| 2026-10-26T21:19:17+08:00 | synthetic_e2e | finish | PASS | `PYTHONPATH=src .venv/bin/python scripts/local_synthetic_e2e_20261026.py --port 9185` |10 | 0 | 0 | 无 |
| 2026-10-26T21:19:17+08:00 | finish | summary | PASS | `-` |- | - | - | 无 |

端到端逐步日志：

| 时间 | 步骤 | 结果 |
|---|---|---|
| 2026-10-26T21:19:15.361+08:00 | generate_video | PASS |
| 2026-10-26T21:19:15.680+08:00 | login | PASS |
| 2026-10-26T21:19:15.705+08:00 | upload | PASS |
| 2026-10-26T21:19:16.759+08:00 | processing | PASS |
| 2026-10-26T21:19:16.808+08:00 | student_state | PASS |
| 2026-10-26T21:19:16.845+08:00 | iep_link | PASS |
| 2026-10-26T21:19:16.860+08:00 | school_system_scoring | PASS |
| 2026-10-26T21:19:16.863+08:00 | score_gap | PASS |
| 2026-10-26T21:19:16.888+08:00 | report_generation | PASS |
| 2026-10-26T21:19:16.938+08:00 | report_download | PASS |
| 2026-10-26T21:19:16.960+08:00 | admin_query | PASS |
| 2026-10-26T21:19:16.985+08:00 | admin_downloads | PASS |
| 2026-10-26T21:19:17.050+08:00 | id_chain | PASS |

## 6. 结论与仍存在的限制

- 三组回归：全部通过且不低于基线。
- compileall / git diff --check：通过。
- 合成端到端：10 个步骤全部通过，ID 链路完整贯通。
- 总体：本地验收通过。
- 限制：本地 macOS 结果不代表腾讯云环境；云端仍需按 `docs/integration_handoff_20261025.md` 完成备份、FFmpeg/ffprobe 确认、预检、`cloud_media_smoke.py` 和完整 `cloud_e2e_acceptance.py`。
- 限制：合成彩条视频不含人物，不验证人脸检测、学生识别或状态判断的准确性；评分仅验证计算与存储链路。
- 限制：GitHub 推送与云端部署未执行，不得描述为“已发布”。
