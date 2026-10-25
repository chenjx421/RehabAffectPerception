# Demo2 1-10 整合交接说明（2026-10-25）

## 交接结论

本次本地整合已完成到 `integration/demo2-1-10` 分支。当前本地分支比远端同名分支多 4 个提交，远端仍停在 `7b6a3d6`。本地已生成不含数据库、视频、凭据和 API Key 的候选包：

```text
.runtime/cloud_candidate_20261025_final/source.tar.gz
SHA256 2B1FFB46A8983363746BF8FBDD2775E1F452EC2BA96354A96D4B2D4E40E47626
```

本次没有完成 GitHub 远程推送，也没有覆盖腾讯云正式环境。原因是当前 GitHub token 已失效，Windows Credential Manager 无法在当前会话写入凭据；云端部署私钥位于本机受保护目录，当前自动执行环境不能读取。不要把这两项描述成“已发布”。

## 已整合内容

### 1-3：学生资料、IEP 和课堂任务关联

- 学生、IEP、课程、视频任务、评价、报告使用稳定 ID 关联。
- IEP 上下文只读取 `document_type='iep'`，不会把专业评估资料混入 IEP。
- 同一学生存在多个有效 IEP 时标记为 `ambiguous`，不会静默取最后一条。
- 授权、撤回、有效期和任务范围仍由原有资料库控制。
- 课堂任务撤回授权后，不再继续把 IEP 或专业资料带入分析和评分。

### 4-9：评分、双轨评价和报告

- 保留学生课堂状态、测量记录、学校评分、系统评分、分差说明和课堂报告。
- 报告通过 `task_id`、`evaluation_id`、`report_id` 等字段关联，不依赖姓名拼接。
- 报告下载会检查当前评分/版本是否仍然一致；评分变化后旧报告会被标记为过期。
- 教师侧可以保留必要的 IEP 关联；公司管理员查看或下载报告时会移除 `iep_links` 元数据，避免把专业资料关联细节暴露到管理员导出内容中。

### 10：公司后台和上传主线

- 公司后台保留总览、任务查询、处理状态、报告查看和下载入口。
- 上传页主线收敛为：登录 -> 选择少量课程信息 -> 上传并分析 -> 学生状态结果。
- 上传完成后进度条进入后台处理阶段，处理完成后跳转任务范围内的分析结果。
- 账号的绑定通道会被保留显示；暂停的绑定通道不会被静默替换成其他通道。
- 管理员访问不带 `task_id` 的旧分析地址时，只显示“请从任务记录进入”的安全引导，不读取课堂数据；带任务 ID 时继续按任务授权检查。

## 本地验收结果

以下均使用 `PYTHONPATH=src` 和独立可写 pytest 临时目录运行：

| 范围 | 结果 |
|---|---|
| IEP、学生关联、评分、报告闭环 | `47 passed` |
| 媒体分析、上传处理、媒体 API、FFmpeg 调用路径 | `350 passed, 3 skipped` |
| 门户页面、管理员 API、通道管理、后台刷新 | `339 passed, 1 skipped, 1 failed` |

门户唯一失败：

```text
tests/test_demo2_portal_api.py::test_portal_pages_redirect_and_enforce_roles
```

旧测试期待公司管理员访问 `/demo2/analysis`（没有 `task_id`）返回 `403`；当前代码按新的安全契约返回 `200` 安全引导页，并明确要求从公司任务记录进入。这是测试断言需要更新为 `200` 并检查引导文字，不是上传、分析或报告逻辑失败。请整合时先更新该测试，再重新跑门户组。

补充检查：

- `compileall` 通过。
- `git diff --check` 通过。
- 候选包已重新生成并记录 SHA256。
- 当前 Windows PATH 没有 `ffmpeg`/`ffprobe`；Python 环境中有 imageio-ffmpeg 7.1 二进制。Linux 云端必须单独确认 `/usr/bin/ffmpeg` 和 `/usr/bin/ffprobe`，不能拿 Windows 状态代替云端确认。

## 给程序员的整合顺序

1. 从远端拉取 `integration/demo2-1-10`，确认包含以下 4 个本地提交：

   ```text
   051b0ab Keep upload flow focused and refresh legacy checks
   df0710f Harden IEP joins and admin report privacy
   a3208e0 Require task scope for company analysis access
   3b355be Fix Demo2 upload processing and cloud deployment integration
   ```

2. 更新 `tests/test_demo2_portal_api.py` 中管理员无任务分析地址的旧断言，按当前安全引导行为验收。
3. 重新跑本说明的三组相关测试；不要把历史全量媒体/浏览器/恢复套件的耗时结果混写成 1-10 整合结果。
4. 重点人工验收以下字段是否贯通：

   ```text
   school_id -> student_id -> iep_document_id -> course_id
   -> video_task_id -> evaluation_id -> report_id
   ```

5. 用合成视频完成一次完整流程：登录、上传、后台处理、学生状态、学校评分、系统评分、分差说明、报告生成、报告下载、公司后台查询、视频/报告下载。
6. 不要用真实学生资料替代合成验收；不要把“输出了状态/评分”描述为教育准确性已验证。

## GitHub 推送

在已经完成 GitHub 登录、且本机代理仍运行在 `127.0.0.1:7897` 的 Windows PowerShell 中执行：

```powershell
cd D:\GIT\RehabAffectPerception
git status --short --branch
git push -u origin integration/demo2-1-10
```

如果终端未继承代理，先确认网络连通后再执行：

```powershell
git -c http.proxy=http://127.0.0.1:7897 push -u origin integration/demo2-1-10
```

推送完成后核对远端提交：

```powershell
git -c http.proxy=http://127.0.0.1:7897 ls-remote --heads origin integration/demo2-1-10
```

不要把 `.runtime` 中的数据库、密钥、邀请配置、真实视频或真实学生截图提交到公开仓库。候选包只作为云端私有部署输入，不提交密钥。

## 腾讯云部署和 FFmpeg 验收

以下命令由拥有已授权云端 SSH 私钥的 Windows 操作员执行。私钥路径不写入报告，不发送给其他人：

```powershell
cd D:\GIT\RehabAffectPerception

# 1. 上传候选包到云端私有暂存目录
python scripts\cloud_ssh_operator.py `
  --upload .runtime\cloud_candidate_20261025_final\source.tar.gz `
  /var/lib/rehabaffect-migration/source-20261025.tar.gz

# 2. 云端确认 FFmpeg 和 ffprobe
python scripts\cloud_ssh_operator.py --command `
  "command -v ffmpeg && command -v ffprobe && ffmpeg -version | head -n 1 && ffprobe -version | head -n 1"

# 3. 云端安装候选代码（先完成备份和写入窗口审批）
python scripts\cloud_ssh_operator.py --command `
  "sudo -n /opt/rehabaffect/deploy/cloud/install_private_release.sh /var/lib/rehabaffect-migration/source-20261025.tar.gz 2b1ffb46a8983363746bf8fbdd2775e1f452ec2ba96354a96d4b2d4e40e47626"

# 4. 云端预检和合成媒体解码
python scripts\cloud_ssh_operator.py --command `
  "cd /opt/rehabaffect && .venv/bin/python scripts/cloud_runtime_preflight.py app"
python scripts\cloud_ssh_operator.py --command `
  "cd /opt/rehabaffect && .venv/bin/python scripts/cloud_runtime_preflight.py gateway"
python scripts\cloud_ssh_operator.py --command `
  "cd /opt/rehabaffect && .venv/bin/python scripts/cloud_media_smoke.py --ffmpeg /usr/bin/ffmpeg --ffprobe /usr/bin/ffprobe"
```

上面第 3 步的路径和 SHA 必须与实际上传文件一致；本次候选包 SHA 的小写形式是：

```text
2b1ffb46a8983363746bf8fbdd2775e1f452ec2ba96354a96d4b2d4e40e47626
```

正式重启服务前，先备份数据库、WAL/SHM、上传目录和当前代码，并确认没有学校正在上传或分析。随后再执行云端整条验收：

```text
登录 -> 上传合成视频 -> 后台处理 -> 学生状态结果
-> 学校评分/系统评分 -> 报告生成 -> 报告下载
-> 公司后台查询 -> 视频和报告下载
```

`cloud_e2e_acceptance.py` 默认是合成媒体验收，不代表真实学生识别准确度；使用保留账号时必须通过私有凭据文件传入，不把账号密码放进仓库：

```bash
.venv/bin/python scripts/cloud_e2e_acceptance.py \
  --base-url http://127.0.0.1:8765 \
  --account-scope retained \
  --school-credentials-file /private/schools.md \
  --admin-credentials-file /private/admin.json \
  --allow-synthetic-uploads \
  --require-automatic-report \
  --ffmpeg /usr/bin/ffmpeg
```

只有上述预检、解码、服务状态和完整 E2E 全部通过后，才可以说云端已更新。当前这一步尚未执行，因为本地自动环境没有权限读取部署私钥。

## 当前需要程序员完成的事项

- 拉取并检查本分支 4 个提交。
- 修正门户旧测试断言并重新跑三组整合测试。
- 在有 GitHub 写权限的环境推送 `integration/demo2-1-10`。
- 在有云端 SSH 私钥的环境上传候选包，确认 FFmpeg/ffprobe，执行预检和完整合成 E2E。
- 将云端验收日志、提交 SHA、候选包 SHA 和失败项回传；不要回传任何密码、API Key、邀请密钥、真实学生资料或人脸截图。
