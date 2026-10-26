# 本机开发环境（macOS / Linux）

更新时间：2026-10-27，对应 v3.6 源码。

## 一条命令

```bash
python3 scripts/setup_local_dev.py
```

脚本会依次完成：

1. 用 `uv`（没有则退回 `python3 -m venv`）创建 `.venv`，优先 Python 3.12，最低 3.10；
2. 从 `requirements-local.txt` 安装运行与测试依赖（numpy、opencv-headless、cryptography、pillow、requests、psutil、reportlab、pytest）；
3. 下载静态 `ffmpeg` / `ffprobe` 到 `.tools/`（macOS arm64 使用固定版本 9.0.2，校验 SHA-256；其它平台先找 PATH 与 `.tools/`）；
4. 下载 YuNet 人脸模型到 `models/face_detection_yunet_2023mar.onnx`，校验 SHA-256 与字节数；
5. 跑一遍验证并打印 PASS/FAIL 清单。

重复执行是安全的：已有的 venv、工具和模型会复用并重新校验。

常用参数：

```bash
python3 scripts/setup_local_dev.py --check    # 只验证，不写任何文件
python3 scripts/setup_local_dev.py --force    # 重建 .venv
```

## 启动与测试

```bash
./scripts/run_local_demo.sh          # http://127.0.0.1:8791/demo2/login
PORT=8800 ./scripts/run_local_demo.sh

PATH="$PWD/.tools:$PATH" PYTHONPATH=src .venv/bin/python -m pytest -q tests
```

本地运行数据放在 `.runtime/local_dev/`（数据库、上传目录、资料密钥），已被 `.gitignore` 排除，不会和 `outputs/seewo_demo2/`、也不会和任何部署数据混在一起。

`run_local_demo.sh` 首次启动会生成 `.runtime/local_dev/dossier.key`（权限 0600）并导出 `REHAB_DEMO2_DOSSIER_KEY`。原因是资料加密的自动密钥路径只在 Windows DPAPI 下可用；macOS/Linux 缺少该变量时，资料摘要、学生总结等接口会按设计 fail-closed 返回 `vault_key_required`。手工跑测试时同样需要这个变量：

```bash
export REHAB_DEMO2_DOSSIER_KEY="$(cat .runtime/local_dev/dossier.key)"
```

开发账号沿用仓库既有约定：`school_uploader_01`…`school_uploader_04` 与 `company_admin`，初始密码为 `REHAB_DEMO2_ACCOUNT_PASSWORD_PREFIX` + 用户名（默认前缀见 `src/rehab_affect/student_record_store.py`）。首次登录后请按需修改环境变量，不要把这些值写进提交。

## 本机基线（2026-10-27，macOS 27 / arm64 / Python 3.12.15）

```bash
PATH="$PWD/.tools:$PATH" PYTHONPATH=src REHAB_DEMO2_DOSSIER_KEY="$(cat .runtime/local_dev/dossier.key)" \
  .venv/bin/python -m pytest -q tests \
  --ignore=tests/test_classroom_draft.py \
  --ignore=tests/test_cloud_processing_acceleration.py \
  --ignore=tests/test_student_insights.py
```

结果：`3381 passed, 68 failed, 48 skipped, 488 errors`（约 5 分钟）。归类：

| 类别 | 数量 | 说明 |
| --- | ---: | --- |
| 环境错误 | 488 | 全部因 `.runtime/cloud_*` 私有产物缺失（416 个 `FileNotFoundError` + 72 个夹具路径断言） |
| Windows Edge 浏览器用例 | 63 | 写死 `msedge.exe` 路径，macOS 无法通过 |
| 仅 Windows 可测 | 1 | `test_windows_process_probe_uses_tasklist_without_command_line` |
| 需要私有真实视频 | 1 | `test_four_first_use_schools_real_media_named_binding_reload_report` |
| 仓库内互相矛盾的契约 | 3 | v3.6 已知的 `version_conflict` / `fixture-1` 两条；另加 `company_admin` 能否进入 `/demo2/analysis`（一条要求 200，一条要求 403） |

与平台无关的 6 条漂移已在 2026-10-27 修复：`demo2_manager_gateway._connection(timeout=...)` 的测试桩接受关键字参数（4 条）；`account_upload_workspace` 不再把已暂停的绑定通道静默换成另一条（1 条，改动 `student_record_store.py`）；`test_storage_marker...` 的临时目录创建（1 条）。

`company_admin` 进分析页这条没有改代码：仓库里两条断言互斥，当前保留更严格的 403，等产品口径确认后再统一。

## 环境差异说明

- 前端验收用例把 Windows Edge 路径写死（`C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe`），macOS 上必然失败，这是环境差异而非代码回归。需要本地看页面时可以用 Playwright 截图自查：`PLAYWRIGHT_BROWSERS_PATH=.tools/ms-playwright npx playwright screenshot <url> <png>`；想彻底解决则要做一次跨平台改造。
- 依赖 `.runtime/` 私有云端产物的用例（`test_classroom_draft.py`、`test_cloud_processing_acceleration.py`、`test_student_insights.py`，以及观察模型、人物候选、上传加速等文件的 setup 夹具）在公开仓库无法运行；全量跑测试时先 `--ignore`，需要时再指向本机 `.runtime/` 的对应目录。
- 媒体分析依赖 `ffmpeg`/`ffprobe` 与 YuNet 模型；缺失时接口会如实返回 `missing_dependency`，不会伪造分析结果。

## 云端复用

服务器上同样执行本脚本（或只用 `requirements-local.txt` + 固定版本 ffmpeg/ffprobe），再用 `deploy/cloud/.env.example` 里的 `REHAB_*` 变量把数据库、上传目录、ffmpeg 路径指向 `/var/lib/rehabaffect` 等持久化位置。生产环境不要沿用本机的 `.runtime/local_dev/` 路径和默认密码前缀。
