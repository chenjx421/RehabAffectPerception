# Demo2 1-10 整合缺口报告（2026-10-26）

## 1. 核对结论

| 项目 | 结果 |
|---|---|
| 仓库 | `https://github.com/chenjx421/RehabAffectPerception`，本地目录 `RehabAffectPerception` |
| 当前分支 | `integration/demo2-1-10` |
| 本地 HEAD / 远端 HEAD | `d804a6b` / `d804a6b`（远端已不再停在 `7b6a3d6`） |
| 4 个整合提交 | 全部存在且位于 HEAD 历史中 |
| 4 个提交之后的新增提交 | `da8b5ba` 交接文档、`d94717f` 管理员分析路由断言、`d804a6b` 网关拒绝请求排空处理 |
| Demo1/Demo2 原有上传、时间轴、报告、下载入口 | 20 项入口文件与函数/路由全部存在，未丢失 |
| `PYTHONPATH=src` 导入主包 | 通过（Python 3.12.11，uv venv `.venv`） |
| `python -m compileall src` | 通过；原 `demo2_portal.py` 管理员页 JS 正则里的 `SyntaxWarning: invalid escape sequence '\/'` 已于 2026-10-26 修正为 `\\/`（渲染出的 HTML 前后 SHA256 一致），`compileall -f` 现为 0 警告；核对脚本改为 `compileall -f` 以免 .pyc 缓存掩盖警告 |
| 聚焦数据闭环冒烟 | `25 passed, 1 skipped`（4 个文件，见第 6 节；不是交接文档里的 47 项全组，全组在后续子任务重跑） |
| `.runtime` 与敏感文件 | 未被 git 跟踪；`.gitignore` 已补充私钥/证书/邀请配置规则 |

提交核对明细：

| SHA | 提交说明 | 改动文件 | 结论 |
|---|---|---|---|
| `3b355be` | Fix Demo2 upload processing and cloud deployment integration | `demo2_manager_gateway.py`、`demo2_media_analysis.py`、`demo2_portal.py`、`scenario_lab_server.py`、`student_record_store.py`、`scripts/cloud_ssh_operator.py` | 存在 |
| `a3208e0` | Require task scope for company analysis access | `scenario_lab_server.py` | 存在 |
| `df0710f` | Harden IEP joins and admin report privacy | `demo2_iep_context.py`、`demo2_report_store.py`、`tests/test_demo2_iep_report_integration.py` | 存在 |
| `051b0ab` | Keep upload flow focused and refresh legacy checks | `demo2_portal.py`、`scenario_lab_server.py`、两个 dual 验收测试 | 存在 |

因此**没有缺失提交**。下文的「部分存在」是按交接文档/Doc2 截图规格逐项比对源码后得出的功能缺口，作为后续子任务补齐依据。

## 2. 1-3：学生资料、IEP 与课堂关联

| # | 功能（对应 Doc2 截图） | 现状 | 源码位置 | 说明 / 后续补齐点 |
|---|---|---|---|---|
| 1 | 学生资料与授权：核对身份、授权保存/撤回、有效期、到期清理、资料版本 | 已存在 | `src/rehab_affect/demo2_dossier_store.py`（`Demo2DossierStore` L140、`save_authorization` L486、`withdraw_authorization` L509、`cleanup_expired` L424、`create_document` L524、`document_download` L590、`delete_document` L611）；`demo2_dossier.py`（`render_student` L87）；`demo2_dossier_vault.py`（`DossierVault` 加密封装）；API `/api/v1/demo2/dossier/authorization[/withdraw]`、`/dossier/document(s)` 在 `demo2_manager_gateway.py` | 授权状态 `active/withdrawn/expired`（L154）。生产密钥与真实授权流程需现场验收 |
| 2 | IEP 与专业资料导入、分开读取、多份有效 IEP 标 ambiguous | 已存在 | `demo2_iep_context.py`（`iep_link_is_current` L10 只认 `doc.document_type='iep'` L18；`attach_iep_context` L51 多份有效 IEP 标 `ambiguous` L74/L120；`snapshot_report` L126）；`demo2_dossier_store.py`（`create_document`） | 规格中的 `iep_document_id` 在代码里叫 `iep_summary_id`（= 被选中的 IEP 文档版本 ID），见第 5 节 |
| 3 | 课堂关联学生资料：已确认学生 + 资料版本引用、撤回后不再带入分析 | 已存在 | `demo2_dossier_store.py`（`create_reference` L707、`reference_export` L737、`task_workspace` L692）；`demo2_dossier.py`（`render_task` L132）；`demo2_identity_store.py`（`Demo2IdentityStore` L87、`save_binding` L537、`revoke_binding` L598、`workspace` L500）；`demo2_identity.py`；`demo2_evaluation_store.py` 内过期/撤回来源过滤 | 结果页「人物 → 学生」轻量绑定在 `demo2_simple_result.py`；云端主线默认匿名人物，绑定需人工确认 |

## 3. 4-9：评分、双轨评价与报告

| # | 功能 | 现状 | 源码位置 | 说明 / 后续补齐点 |
|---|---|---|---|---|
| 4 | 学生测量评分标准（10 分制、准确性 35%/独立性 30%/一致性 20%/泛化性 15%、observed ≥ 2） | 已存在 | `assessment_rubric.py`（`score_band` L77、`weighted_score` L93、`build_assessment_summary` L115、`build_longitudinal_series` L191）；`demo2_measurement.py`（`render_measurement`）；`demo2_measurement_store.py`（`save` L111、`withdraw` L228、`course_workspace` L278、`course_report` L305） | 权重为试行值，未经学校样本校准；不得表述为准确性已验证 |
| 5 | 双轨评价入口（新建评价记录、课堂基本信息、口径锁定、评分来源） | 已存在 | `demo2_evaluation.py`（`render_evaluation` L160）；`demo2_evaluation_store.py`（`Demo2EvaluationStore` L15、`workspace` L117、`preview` L236、`save` L244、`withdraw` L265）；API `/api/v1/demo2/evaluations[/preview|/withdraw]`；页面 `/demo2/evaluation` | 不是上传主线必经步骤 |
| 6 | 学校模板与本课目标（学科、评价模板、方案、本课目标与分层支持约定） | 已存在 | `classroom_rubric.py`（`catalog` L71、`evaluate` L96）；`evaluation_policy.py`（`catalog_policy` L34、`resolve_policy` L41） | 校方真实模板与合格线待提供 |
| 7 | 普通课堂：学校分数作为基线、系统增强沿用学校权重 | 已存在 | `classroom_rubric.py`（`evaluate`）；`evaluation_policy.py`（`resolve_policy`）；`demo2_evaluation.py` 学校标准/系统增强标签页 | 动态权重科学依据未完成验证 |
| 8 | 学校轨与系统轨分差对照（证据差值、权重差值、总分差值、逐项分差图） | 已存在 | `evaluation_policy.py`（`sensitivity` L87）；`demo2_evaluation_store.py`（`for_task` L191、`save`）；`demo2_evaluation.py` 双轨对照页 | 需要同课学校人工评分对照样本 |
| 9 | 千字图文报告、报告快照、过期判定、下载 | 已存在 | `demo2_course_analysis.py`（`build_workspace` L21、`build_report` L90）；`demo2_report_store.py`（`save_from_workspace` L156、`list_for_task` L271、`list_admin` L282、`get` L314、`download` L326、`report_stale` L119）；`seewo_long_report.py`（`build_long_course_report` L62）；`evaluation_report_contract.py`（稳定 ID 契约）；API `/api/v1/demo2/course-analysis[/report]`、`/api/v1/demo2/reports[/download]` | 模型未配置时用本地证据模板，模板文字不能当作真实观察 |

## 4. 10：公司后台与上传主线

| 子项 | 现状 | 源码位置 | 说明 |
|---|---|---|---|
| 公司后台总览（账号、通道、任务总数、存储） | 已存在 | `demo2_portal.py`（`render_demo2_admin_html` L1053）；`student_record_store.py`（`admin_platform_summary` L1094）；API `/api/v1/demo2/admin/summary` | — |
| 任务查询、报告查看/下载 | 已存在 | `demo2_report_store.py`（`list_admin`、`download`）；API `/api/v1/demo2/admin/reports`、`/api/v1/demo2/reports/download` | — |
| 管理员报告移除 `iep_links` | 已存在 | `demo2_report_store.py` L150 | — |
| 视频查询/下载 | 已存在 | `student_record_store.py`（`video_result_for_download` L3057、`account_video_result_for_download` L3073）；路由 `/api/seewo_demo2/video_result_download`（`scenario_lab_server.py` L729） | — |
| 通道管理、暂停通道不被静默替换 | 已存在 | `demo2_channel_admin.py`（`render_channel_admin`）；`demo2_channel_admin_store.py`（`list_channels` L113、`update_channel` L121）；`student_record_store.py` L1034、L1751 | — |
| 上传主线：登录 → 少量课程信息 → 上传并分析 → 学生状态 | 已存在 | `demo2_portal.py`（`render_demo2_upload_html` L328、进度条 `uploadProgress` L489、暂停/续传）；`demo2_manager_gateway.py` 分片/续传/任务 API；`demo2_media_worker.py`、`demo2_media_analysis.py` 后台处理；`demo2_simple_result.py` 结果页 | — |
| 管理员无 `task_id` 访问 `/demo2/analysis` 返回 200 安全引导页 | 已存在 | `scenario_lab_server.py` L975-L985 | 带 `task_id` 时走 `course_workspace` 授权检查 |
| 网关拒绝小型非上传 POST 前排空 ≤64 KiB 请求体 | 已存在 | `demo2_manager_gateway.py`（`d804a6b`） | 上传分片仍在鉴权前不读请求体 |

## 5. 稳定 ID 链路核对

规格链路：`school_id -> student_id -> iep_document_id -> course_id -> video_task_id -> evaluation_id -> report_id`

| 规格字段 | 代码字段 | 现状 | 位置 |
|---|---|---|---|
| `school_id` | `school_id` | 部分存在 | `evaluation_report_contract.py` L17/L44/L71（契约解析）、`student_record_store.py` L308（任务表，默认 `demo_school`）；`demo2_reports` 快照表无 `school_id` 列，按 `owner_account_id`/`scope_key` 隔离 |
| `student_id` | `student_id` | 已存在 | 26 个模块，含 `demo2_identity_store.py`、`demo2_dossier_store.py`、`demo2_course_analysis.py` |
| `iep_document_id` | `iep_summary_id`（IEP 文档版本 ID）+ `document_id` | 已存在（命名不同） | `demo2_iep_context.py`、`demo2_evaluation_store.py`、`demo2_course_analysis.py`、`evaluation_report_contract.py` L21 |
| `course_id` | `course_id` | 已存在 | 19 个模块，含 `demo2_report_store.py` L41 |
| `video_task_id` | `task_id` | 已存在（命名不同） | 36 个模块，`student_record_store.create_video_task` 生成 |
| `evaluation_id` | `evaluation_id` | 已存在 | `demo2_evaluation_store.py`、`demo2_report_store.py`、`demo2_course_analysis.py`、`evaluation_report_contract.py` |
| `report_id` | `report_id`（快照 ID）/ `content_report_id`（内容 ID） | 已存在 | `demo2_report_store.py`、`evaluation_report_contract.py`、`demo2_portal.py` |

后续补齐依据：接口贯通核对时需确认 `school_id` 在报告快照/管理员报告列表中可直接返回，并在接口文档中注明 `iep_document_id ≡ iep_summary_id`、`video_task_id ≡ task_id` 的别名关系。

## 6. 环境与安全核对

- Python：`uv venv --python 3.12 .venv`，安装 `numpy opencv-python-headless cryptography pillow pytest imageio-ffmpeg`。运行统一使用 `PYTHONPATH=src`。
- pytest 独立临时目录：`--basetemp=.runtime/pytest-tmp/<时间戳>`，并加 `-p no:cacheprovider`。
- 冒烟测试文件：`tests/test_demo2_iep_report_integration.py`、`tests/test_demo2_report_store.py`、`tests/test_demo2_course_analysis.py`、`tests/test_demo2_evaluation_provenance.py` → `25 passed, 1 skipped`。
- `git ls-files .runtime` 为空；`*.db/*.sqlite*/*.pem/*.key/*.mp4/*.mov` 无已跟踪文件。
- `.gitignore` 新增：`*.pem`、`*.key`、`*.p12`、`*.pfx`、`id_rsa*`、`id_ed25519*`、`id_ecdsa*`、`**/invitations*.json`、`**/invite_config*.json`、`**/*credentials*.json`。新增规则未让任何已跟踪文件被忽略（`git ls-files -ci --exclude-standard` 为空）。
- 本机 PATH 无系统 `ffmpeg/ffprobe`，使用 imageio-ffmpeg 二进制；云端 `/usr/bin/ffmpeg`、`/usr/bin/ffprobe` 未确认，不能用本地状态代替。

## 7. 未完成 / 不在本次范围

- GitHub 推送与腾讯云部署本次均未执行，不能描述为「已发布」。
- 交接文档中的三组完整测试（47 / 350+3 / 340+1）在后续子任务重跑，本次只跑数据闭环冒烟。
- 教育准确性未经学校样本验证；评分输出不等于准确性已证实。

## 8. 复核方法

```bash
cd RehabAffectPerception
PYTHONPATH=src .venv/bin/python scripts/verify_integration_20261026.py --fetch --pytest
```

每一步都会带时间戳、操作类型（fetch/checkout/head/remote-head/log-check/entry-file/id-field/gitignore/import/compileall/pytest）、关键参数和 PASS/FAIL 写入 `.runtime/logs/integration_check_<时间戳>.jsonl`，并生成 `docs/integration_check_log_20261026.md`。

## 9. 子任务 2 补齐记录：学生资料授权、期限与 IEP/专业资料分离（2026-10-26）

- 保存期限：`create_document` 对「资料保存至 > 授权截止日」返回 `retention_after_authorization`，中文提示含截止日；页面在提交前用同一文案做即时校验（`#retainUntilError`）。
- IEP 上下文：新增 `Demo2DossierStore.iep_context` 和 `GET /api/v1/demo2/dossier/iep-context?student_id=`。只读取 `document_type='iep'`，每个 IEP 系列只取最新可用版本；存在多个系列时返回 `status=ambiguous`，`iep=null`，不自动选择。
- 课堂分析（`attach_iep_context`）：同一引用含多份 IEP 系列时也标为 `ambiguous`；不可用时返回 `reason`/`message`（授权撤回、授权到期、资料删除或到期、身份失效）。
- 可用性检查：新增 `material_access_state` 和 `GET /api/v1/demo2/dossier/access?student_id=&purpose=analysis|scoring`。评分接口 `iep_link_unavailable` 的提示改为写明具体原因。
- 调试日志：`<数据目录>/logs/dossier_debug_YYYYMMDD.jsonl`，可用 `REHAB_DEMO2_DOSSIER_DEBUG_LOG_DIR` 指定目录。字段只允许时间戳、操作类型、结果、各类 ID、document_type、日期、计数和错误码，不写姓名、摘要、来源、文件名或授权原文。
- 测试：`tests/test_demo2_dossier_iep_access.py` 11 项全部通过。`test_demo2_dossier_store.py` 中有一处 POSIX 路径问题（`unused/..`），已修复。
- 既有问题（与本次改动无关）：`test_demo2_student_summary_api.py::test_teacher_summary_company_read_export_and_revoke` 在本机因缺少 `vault_key_required` 所需的加密密钥而失败，改动前后结果相同。

## 10. 子任务 3 补齐记录：课堂关联学生资料（课堂引用记录）（2026-10-26）

- 页面 `/demo2/course-dossier?task_id=`（`demo2_dossier.py` `render_task`）：顶部警示条、左侧「本次课堂引用」、右侧「已留存的引用」、底部 60 天合规说明，与 `03-课堂关联学生资料.png` 一致。未选学生时按钮置灰并提示「请选择一位当前已确认的学生。」；勾选 0 个或超过 10 个版本时按钮不可用并给出中文提示；后端同样拒绝（`invalid_document_ids`）。
- 可选资料：`task_workspace` 只返回当前可用（授权有效、未删除、未过期）的资料版本，且只列出当前身份版本中已确认绑定的学生。
- 稳定 ID：引用记录返回 `reference_id`、`video_task_id`（≡ `task_id`）、`student_id`、`iep_document_ids`、`document_versions`（文档版本 ID + 版本号）。资料出新版本后旧引用仍指向原版本 ID。
- 失效标记与导出：每条引用新增 `sources[]`（逐个来源的 `valid_as_evidence`/`reason`）。下载 `GET /api/v1/demo2/dossier/reference` 时重新核验，返回 `export.valid_sources`/`export.invalid_sources`/`export.valid_evidence`；已撤回、删除、过期或身份失效的来源只出现在 `invalid_sources`。
- 课堂撤回授权：新增 `POST /api/v1/demo2/dossier/references/withdraw`（`reference_id`、`confirmed`），页面卡片带「撤回本课引用授权」按钮。撤回只记录 `withdrawn_at`，历史记录保留；`attach_iep_context`、`iep_link_is_current`（评分）都会跳过已撤回的引用。
- 分析输入快照：新增 `GET /api/v1/demo2/dossier/analysis-context?task_id=`，列出哪些 IEP/专业资料版本会进入本课分析与评分（`reads_iep`、`reads_professional_materials`、逐引用 `included`/`excluded`）。
- 调试日志（`dossier_debug_YYYYMMDD.jsonl`）：`reference_create`、`reference_export`、`reference_withdraw`、`reference_validity_check`、`analysis_context_snapshot`，字段含 `ts`、操作类型、`task_id`、`student_id`、`reference_id`、结果、原因和有效/失效来源数，不写资料原文。
- 测试：`tests/test_demo2_classroom_reference.py` 10 项全部通过；资料/IEP/网关/身份回归 `535 passed, 7 skipped`（跳过项为需要本机 Node + Playwright Chromium 的浏览器测试）。另在 9181 端口用隔离合成数据库通过 Playwright 手工验证了选择 → 保存 → 下载 → 撤回，控制台无报错。

## 11. 子任务 4 补齐记录：上传主线收敛与后台分析跳转（2026-10-26）

- 上传页（`demo2_portal.py` `render_demo2_upload_html`）：主线只要求「课程名称」「上课日期」（默认今天，写入 `session_id=<course_id>-<日期>`）和课堂视频；课程批次号、关注学生仍只在 `?advanced=1` 下显示。进度区新增三段阶段条：上传视频 → 后台处理 → 学生状态结果。上传完成后进入「后台处理：排队中 / 后台处理中 · N%」，完成后跳转 `/demo2/simple-result?task_id=<id>&from=upload`；结果页加载后用 `history.replaceState` 去掉 `from`，并在视频信息里显示「任务 <task_id>」。
- 结果页范围：`/demo2/simple-result` 只接受 `task_id`（或 `task_id`+`from=upload`），其他参数仍 400；页面和 `/api/v1/demo2/simple-result` 都按任务授权读取，只返回该任务的数据。其他账号访问时页面由原来的 500 改为 403/404。
- 通道：`account_upload_workspace` 的选中通道始终是账号绑定通道，绑定通道不存在时返回 `channel=None`，不再回落到第一个启用通道；新增 `bound_channel_id`、`channel_status`、`upload_blocked{code,message}`。页面通道下拉只列绑定通道，暂停时显示「上传通道 N（已暂停）」与暂停提示条，禁用「开始上传并分析」。后端在绑定通道暂停时，新建任务一律返回 `409 channel_paused`（即使请求里显式选了别的通道）；通道不存在返回 `409 channel_missing`。已开始的分片上传/续传按原有约定继续可完成（`test_pause_preserves_existing_media_analysis_and_partial_upload`）。为兼容旧接口，`workspace.channels` 仍列出启用通道（`test_legacy_video_routes_keep_account_channel_quota_and_result_isolation`）。
- FFmpeg/ffprobe：`_resolve_tool_with_source` 依次使用 `REHAB_FFMPEG`/`REHAB_FFPROBE`（配置路径不存在时不回退）→ PATH → 同目录 ffprobe → 仓库 `.tools` → imageio-ffmpeg 二进制（仅 ffmpeg）。新增 `media_tool_status()`，worker 启动时写入 `media_tools_check`。工具缺失时任务进入 `failed`，`processing_error.code=missing_dependency`，提示里点名缺少的是 ffmpeg 还是 ffprobe，不暴露路径。页面显示「后台分析失败」并弹出原因，轮询停止，不会一直卡在处理中。
- 调试日志：`<数据目录>/logs/upload_debug_YYYYMMDD.jsonl`（可用 `REHAB_DEMO2_UPLOAD_DEBUG_LOG_DIR` 指定）。操作：`upload_start`、`upload_rejected`、`upload_chunk`、`upload_complete`、`upload_resume`、`processing_start`、`processing_complete`、`processing_failed`、`media_tools_check`、`result_redirect`、`result_page_open`。字段：`ts`、`operation`、`result`、`task_id`、`channel_id`、`account_id`、`course_id`、`byte_size`、`received_bytes`、`chunk_index`、`chunk_bytes`、`duration_ms`、`code`、`http_status`、状态字段。不写文件名、课程名、教师名或解码器原文。浏览器端同样输出 `[upload-flow]` 结构化 console 日志。
- 本机环境：之前 `test_default_engine_integrates_with_worker_and_sqlite` 失败的原因是缺少 YuNet 模型（`models/` 不进 git）。已用仓库自带的 `scripts/download_demo2_yunet.py` 下载并校验 SHA256；云端同样需要确认 `models/face_detection_yunet_2023mar.onnx` 存在，否则任务会以 `processing_failed` 失败。
- 测试：新增 `tests/test_demo2_upload_analysis_flow.py`，9 项全部通过。上传/媒体/门户/网关/通道相关 14 个文件 `647 passed, 40 skipped`。更大范围回归 `2616 passed, 77 skipped, 3 failed, 353 errors`：3 个失败在改动前就存在（缺少保险库加密密钥、旧导航断言、Node 未安装 `playwright`）；errors 都是环境原因（`.runtime/cloud_release_overrides`、`.runtime/cloud_student_release` 只在 Windows 机器上，未进 git；未安装 `psutil`/`reportlab`）；`test_cloud_upload_acceleration.py` 在未改动的代码上同样 71 errors。
- 浏览器验证（9181 端口，隔离的合成数据库，合成测试图像视频，没有真实学生）：登录 → 上传 → 「后台处理」阶段 → 自动跳转到带 task_id 的结果页；暂停的绑定通道显示提示且上传被禁用；FFmpeg 路径无效时任务明确失败并给出原因。控制台无报错。截图在 `../.runtime/ui_verify_upload/01~05-*.png`。这只说明流程能跑通，不代表学生状态识别准确。
