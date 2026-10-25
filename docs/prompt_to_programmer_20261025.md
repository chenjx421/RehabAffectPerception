# 请协助完成 Demo2 1-10 最后整合与验收

请基于仓库 `https://github.com/chenjx421/RehabAffectPerception` 的
`integration/demo2-1-10` 分支继续工作，不要删除 Demo1/Demo2 原有视频上传、学生状态时间轴、报告和下载能力。

## 当前本地结果

本地已经完成 1-10 的主要整合，包含：

- 学生资料授权、有效期、撤回和到期检查；
- IEP 与专业资料分开读取；
- 学生、IEP、课程、视频任务、评价、报告使用稳定 ID 关联；
- 学校评分、系统评分、分差说明、课堂报告和报告下载；
- 公司后台任务查询、报告查看/下载和视频查询/下载；
- 上传完成后进入后台分析，分析完成后进入任务范围内的学生状态结果；
- 管理员访问无 `task_id` 的旧分析入口时只显示安全引导，不读取课堂数据。

候选包已生成，路径和 SHA256：

```text
.runtime/cloud_candidate_20261025_final/source.tar.gz
7E559309477A62E9114AA0FBACEF37F66C6ABDC6A88FEFF470B9959730D17B5A
```

## 已验证结果

在 Windows 本地使用 `PYTHONPATH=src` 和独立 pytest 临时目录：

- 数据闭环：`47 passed`；
- 上传/媒体/FFmpeg 调用路径：`350 passed, 3 skipped`；
- 门户和后台：`340 passed, 1 skipped`。

之前的门户失败已修复：旧测试期待管理员访问无任务 ID 的 `/demo2/analysis` 返回 403，现已更新为检查 200 安全引导页。网关专项 `137 passed`，完整门户/后台组 `340 passed, 1 skipped`。

另外已修复 Windows 下小型非上传 POST 被拒绝时的连接中止问题。非上传且不超过 64 KiB 的拒绝请求会先排空请求体；上传分片和续传仍保持鉴权前不读请求体。

## 请完成的工作

1. 拉取 `integration/demo2-1-10`，检查上述提交和文件没有丢失。
2. 保留已更新的门户测试和网关拒绝请求修复，重新运行数据、媒体、门户三组测试。
3. 检查接口字段是否贯通：

   ```text
   school_id -> student_id -> iep_document_id -> course_id
   -> video_task_id -> evaluation_id -> report_id
   ```

4. 在云端先做备份和发布前预检，再上传候选包。
5. 确认云端存在 `/usr/bin/ffmpeg` 和 `/usr/bin/ffprobe`，运行 `cloud_media_smoke.py`。
6. 用合成视频完成：登录 -> 上传 -> 后台处理 -> 学生状态 -> 双轨评分 -> 报告 -> 下载 -> 公司后台查询/下载。
7. 将测试结果、云端提交 SHA、候选包 SHA 和仍存在的限制回传。不要提交密码、API Key、邀请密钥、部署私钥、真实学生视频、人脸截图或 IEP 原件。

## GitHub 与云端命令

GitHub 推送由有写权限的 Windows 操作员执行：

```powershell
cd D:\GIT\RehabAffectPerception
git -c http.proxy=http://127.0.0.1:7897 push -u origin integration/demo2-1-10
git -c http.proxy=http://127.0.0.1:7897 ls-remote --heads origin integration/demo2-1-10
```

候选包上传和云端检查使用仓库现有的 `scripts/cloud_ssh_operator.py`、
`scripts/cloud_runtime_preflight.py`、`scripts/cloud_media_smoke.py` 和
`scripts/cloud_e2e_acceptance.py`。云端部署私钥只由有权限的操作员使用，不要复制到 GitHub 或聊天中。

完整命令和回滚/备份要求见：

```text
docs/integration_handoff_20261025.md
```
