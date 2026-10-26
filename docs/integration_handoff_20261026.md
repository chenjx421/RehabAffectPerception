# Demo2 1-10 候选发布包、GitHub 推送与腾讯云部署验收手册（2026-10-26）

## 0. 实际执行状态（先读）

| 项目 | 状态 | 说明 |
|---|---|---|
| 本地提交 | 已完成 | 分支 `integration/demo2-1-10`，候选包构建自 `3c4c4075313aa9c64c25568e6bb7ae6497381e39`（`3c4c407`） |
| 候选包生成与校验 | 已完成 | `.runtime/cloud_candidate_20261026/source.tar.gz`，审计结果 `PASSED` |
| 四个云端脚本 `--help` | 已完成 | 均存在，均返回退出码 0 |
| GitHub 推送 | **未推送** | 本环境执行 `git push --dry-run` 返回 `403 Permission denied`（当前登录账号对 `chenjx421/RehabAffectPerception` 没有写权限）。远端分支仍停在 `d804a6b`，本地比远端多 2 个代码提交，另加本文档的 1 个提交 |
| 腾讯云部署 | **未发布** | 本环境没有云端 SSH 部署私钥（私钥只在操作员的 Windows 受保护目录中），没有执行上传、安装、预检、媒体冒烟或 E2E。云端仍是之前的版本 |

在第 3、4 节的命令由有权限的操作员实际执行，并且第 4 节所有检查都通过之前，不得把本版本描述为“已推送”“已发布”或“云端已更新”。

## 1. 提交与候选包

### 1.1 本分支相对 `7b6a3d6` 的提交

```text
3c4c407 Add reproducible audited cloud candidate builder            （本地，未推送）
e1239eb Integrate Demo2 1-10 acceptance fixes, debug logging and ID chain checks  （本地，未推送）
d804a6b Harden rejected gateway request handling                    （远端已有）
d94717f Align admin analysis route acceptance                       （远端已有）
da8b5ba Document Demo2 1-10 integration handoff                     （远端已有）
051b0ab Keep upload flow focused and refresh legacy checks          （远端已有）
df0710f Harden IEP joins and admin report privacy                   （远端已有）
a3208e0 Require task scope for company analysis access              （远端已有）
3b355be Fix Demo2 upload processing and cloud deployment integration（远端已有）
```

本文档自身在 `3c4c407` 之后单独提交，只增加 `docs/integration_handoff_20261026.md`，不改变候选包内容。

### 1.2 候选包

```text
路径     .runtime/cloud_candidate_20261026/source.tar.gz
构建提交 3c4c4075313aa9c64c25568e6bb7ae6497381e39
文件数   299
大小     1460172 字节（解压后 5447680 字节）
SHA256（大写） 66A0F7442D1BAB0C7EF9131E357A7AA5354BC0A90D9D969FFFD6520C5D58D540
SHA256（小写） 66a0f7442d1bab0c7ef9131e357a7aa5354bc0a90d9d969fffd6520c5d58d540
```

同目录下的附带文件：

| 文件 | 内容 |
|---|---|
| `source.tar.gz.sha256` | `sha256sum -c` 可直接使用的小写校验行 |
| `source.tar.gz.sha256.upper.txt` | 大写 SHA256 |
| `source.tar.gz.manifest.json` | 包内每个文件的 SHA256、构建分支和提交 |
| `build_log.jsonl` | 带时间戳的打包和审计日志 |
| `build_summary.json` | 文件数、大小、SHA256、各排除规则命中数、审计结果 |
| `script_help_check.log` | 四个云端脚本的存在性和 `--help` 检查日志 |

整个 `.runtime/` 都在 `.gitignore` 中，候选包和日志不进入仓库。

### 1.3 重新生成方式（可复现）

```bash
cd RehabAffectPerception
git checkout 3c4c4075313aa9c64c25568e6bb7ae6497381e39
.venv/bin/python scripts/build_cloud_candidate_20261026.py
# Windows：.venv\Scripts\python scripts\build_cloud_candidate_20261026.py
```

脚本做了以下处理：

- tar 条目使用提交时间作为 mtime，属主统一为 root，权限固定为 `0644`（`.sh` 为 `0755`）；gzip 头不写时间戳。
- 同一个提交重新打包，得到的 SHA256 相同。本次已重新打包一次做验证，两次的 SHA 都是 `66a0f744…d540`。
- 如果已跟踪文件和 HEAD 不一致，脚本拒绝打包，除非显式传入 `--allow-dirty`，并会把这种情况写入日志。

包内容的选取规则与 `scripts/cloud_build_release.py` 一致：

- `src/**/*.py`、`configs/**/*.json`、`tests/**/*.py`
- `deploy/cloud/*.{service,txt,sh}`
- `scripts/cloud_*.py`，但不含 `cloud_ssh_operator.py` 和 `cloud_prepare_snapshot.py`
- `scripts/prepare_upload_video.py`、`pyproject.toml`
- `models/face_detection_yunet_2023mar.onnx`、`models/LICENSE.yunet`

### 1.4 排除规则与命中情况

| 规则 | 匹配模式 | 命中 |
|---|---|---|
| database | `*.db *.sqlite *.sqlite3 *.db3` | 0 |
| wal_shm | `*-wal *-shm *-journal *.wal *.shm` | 0 |
| video | `*.mp4 *.mov *.avi *.mkv *.webm *.m4v *.flv *.wmv *.mpg *.mpeg *.3gp` | 0 |
| audio | `*.wav *.mp3 *.m4a *.aac *.flac` | 0 |
| key_material | `*.pem *.key *.p12 *.pfx *.crt *.der id_rsa* id_ed25519* id_ecdsa* *_ed25519 *_rsa *.ppk` | 0 |
| invitation_config | `invitations*.json invite_config*.json gateway.json` | 0 |
| credentials | `*credential* *secret* *password* *token*.json schools.md admin.json .env *.env cloud.env .netrc` | **1**：`scripts/cloud_install_observation_credentials.py`（仅操作员侧使用的凭据下发脚本，依赖 SSH 操作脚本，服务器上不需要） |
| runtime | `.runtime/* */.runtime/* data/* outputs/*` | 0 |
| bytecode | `*.pyc */__pycache__/*` | 0 |
| key_content_scan | 文件内容含 `BEGIN … PRIVATE KEY`、`sk-…`、`ghp_…`、`AKIA…` | 0 |
| symlink | 符号链接 | 0 |

打包后脚本还做了一次解压审计：把包解压到临时目录，重新套用上面所有规则，并检查 SQLite 文件头和密钥内容；同时逐个文件核对 manifest 中的 SHA256。审计结果：`forbidden_hits={}`，`missing=0`，`problems=0`，`status=PASSED`。

此外用系统 `tar -xzf` 独立解压做了一次复核：共 299 个文件，没有发现 `.db/.sqlite/-wal/-shm`、视频、密钥、`.env`、邀请配置或凭据文件，内容扫描也没有私钥或 API Key。

### 1.5 打包日志摘录（`build_log.jsonl`）

```text
2026-10-26T20:09:09+08:00 start    branch=integration/demo2-1-10 head=3c4c407 dirty_tracked_files=0
2026-10-26T20:09:09+08:00 excluded scripts/cloud_install_observation_credentials.py rule=credentials
2026-10-26T20:09:09+08:00 package  files=299 excluded=1 bytes=1460172 sha256=66a0f744…d540
2026-10-26T20:09:09+08:00 audit    forbidden_hits={} missing=0 problems=0
2026-10-26T20:09:09+08:00 result   status=PASSED
```

### 1.6 云端脚本检查（`script_help_check.log`）

```text
2026-10-26T20:10:02+0800 scripts/cloud_ssh_operator.py      present help_exit=0 PASSED
2026-10-26T20:10:02+0800 scripts/cloud_runtime_preflight.py present help_exit=0 PASSED
2026-10-26T20:10:02+0800 scripts/cloud_media_smoke.py       present help_exit=0 PASSED
2026-10-26T20:10:02+0800 scripts/cloud_e2e_acceptance.py    present help_exit=0 PASSED
```

`cloud_ssh_operator.py` 依赖 `paramiko`。操作员机器上如果缺这个包，先执行 `pip install paramiko`。它只是操作员本机的工具依赖，不是服务器依赖。

## 2. 本地验收基线（打包前）

- `compileall` 通过，`git diff --check` 通过。
- 本轮新增的 ID 链路、网关拒绝请求排空、IEP 授权、课堂报告测试：`51 passed`。
- 整合基线以 `docs/local_acceptance_20261026.md` 和 `docs/integration_check_log_20261026.md` 为准。历史全量媒体、浏览器、恢复套件的耗时结果不要和 1-10 整合结果混在一起写。

## 3. GitHub 推送（未执行：需要有写权限的操作员）

在已登录有写权限 GitHub 账号、且本机代理运行在 `127.0.0.1:7897` 的 Windows PowerShell 中执行：

```powershell
cd D:\GIT\RehabAffectPerception
git status --short --branch
git log --oneline -4
git -c http.proxy=http://127.0.0.1:7897 push -u origin integration/demo2-1-10
git -c http.proxy=http://127.0.0.1:7897 ls-remote --heads origin integration/demo2-1-10
```

核对要求：

- `ls-remote` 返回的 SHA 必须等于本地 `git rev-parse HEAD`，也就是本文档所在的提交。
- 本地 `git log` 中必须能看到 `3c4c407` 和 `e1239eb`。

如果 Windows 工作副本不是本次的仓库，可以在本仓库目录执行 `git bundle create demo2-1-10.bundle d804a6b..integration/demo2-1-10` 生成 bundle，复制到 Windows 后在 `D:\GIT\RehabAffectPerception` 中执行 `git fetch <bundle路径> integration/demo2-1-10:integration/demo2-1-10`，然后再推送。

不要提交 `.runtime/`，也不要提交任何数据库、视频、邀请配置、密钥或凭据。

## 4. 腾讯云部署（未执行：需要持有部署私钥的操作员）

以下命令都在 Windows PowerShell 中执行，工作目录为 `D:\GIT\RehabAffectPerception`，并且需要先把候选包复制到该仓库的 `.runtime\cloud_candidate_20261026\` 下。

多行远程命令用 PowerShell 单引号 here-string（`@' … '@`）传入，避免转义；`-replace "`r",""` 用来去掉 Windows 回车符。

```powershell
function Invoke-Cloud([string]$Cmd) {
  $Cmd = $Cmd -replace "`r", ""
  python scripts\cloud_ssh_operator.py --command $Cmd
  if ($LASTEXITCODE -ne 0) { throw "cloud command failed: $LASTEXITCODE" }
}
$Pkg = ".runtime\cloud_candidate_20261026\source.tar.gz"
$Sha = "66a0f7442d1bab0c7ef9131e357a7aa5354bc0a90d9d969fffd6520c5d58d540"
$Remote = "/var/lib/rehabaffect-migration/source-20261026.tar.gz"
(Get-FileHash $Pkg -Algorithm SHA256).Hash.ToLower()   # 必须等于 $Sha，否则停止
```

### 4.1 发布窗口前检查：确认没有学校正在上传或分析（只读）

```powershell
Invoke-Cloud @'
sudo -n /opt/rehabaffect/.venv/bin/python - <<'PY'
import sqlite3, json
from pathlib import Path
env = dict(l.split("=", 1) for l in Path("/etc/rehabaffect/cloud.env").read_text().splitlines() if "=" in l and not l.startswith("#"))
db = Path(env["REHAB_DEMO2_DB_PATH"])
c = sqlite3.connect(db.as_uri() + "?mode=ro", uri=True)
busy = c.execute("SELECT count(*) FROM video_analysis_tasks WHERE analysis_status IN ('queued','processing')").fetchone()[0]
uploading = c.execute("SELECT count(*) FROM video_analysis_tasks WHERE upload_status='uploading' AND julianday(updated_at)>julianday('now','-10 minutes')").fetchone()[0]
print(json.dumps({"db": str(db), "analysis_busy": busy, "recent_uploading": uploading, "quick_check": c.execute("PRAGMA quick_check").fetchone()[0]}))
PY
'@
```

只有同时满足 `analysis_busy=0`、`recent_uploading=0`、`quick_check="ok"` 才能继续，否则等待后重查。确认后在 5 分钟内进入下一步。

确认空闲之后再停服备份，原因是 WAL/SHM 的原样拷贝只有在没有写入时才一致。

### 4.2 停服并备份数据库、WAL/SHM、上传目录和当前代码

```powershell
Invoke-Cloud @'
set -euo pipefail
sudo -n systemctl stop rehabaffect-gateway.service rehabaffect-app.service
sudo -n systemctl stop rehabaffect-observations.service 2>/dev/null || true
sudo -n systemctl is-active rehabaffect-app.service rehabaffect-gateway.service || true
DB="$(sudo -n sed -n 's/^REHAB_DEMO2_DB_PATH=//p' /etc/rehabaffect/cloud.env)"
UP="$(sudo -n sed -n 's/^REHAB_DEMO2_UPLOAD_DIR=//p' /etc/rehabaffect/cloud.env)"
BK="/var/lib/rehabaffect/cloud_backups/before-20261026-$(date -u +%Y%m%dT%H%M%SZ)"
df -h /var/lib/rehabaffect
sudo -n install -d -m 0700 "$BK"
# 1) SQLite 一致性备份（包含已提交的 WAL 内容）
sudo -n /opt/rehabaffect/.venv/bin/python -c "import sqlite3,sys; s=sqlite3.connect('file:'+sys.argv[1]+'?mode=ro',uri=True); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); print('sqlite_backup_ok')" "$DB" "$BK/database.backup.sqlite3"
# 2) 原样拷贝 DB + WAL + SHM（服务已停止）
for f in "$DB" "$DB-wal" "$DB-shm"; do if sudo -n test -e "$f"; then sudo -n cp -a "$f" "$BK/"; fi; done
# 3) 上传目录与视频任务目录（含分片/结果）
sudo -n tar -C "$(dirname "$DB")" -czf "$BK/video_tasks.tar.gz" video_tasks 2>/dev/null || echo "no video_tasks dir"
sudo -n tar -C "$(dirname "$UP")" -czf "$BK/upload_dir.tar.gz" "$(basename "$UP")" 2>/dev/null || echo "no upload dir"
# 4) 当前代码
sudo -n tar -C /opt/rehabaffect -czf "$BK/code.tar.gz" src scripts tests configs deploy models pyproject.toml
sudo -n sh -c "cd '$BK' && sha256sum * > SHA256SUMS && chmod 0600 *"
sudo -n ls -la "$BK"
echo "BACKUP_DIR=$BK"
'@
```

把输出里的 `BACKUP_DIR=` 记下来，回滚时要用。备份目录只保留在云端私有目录，不下载到聊天或仓库中。

### 4.3 上传候选包并在云端校验 SHA

```powershell
python scripts\cloud_ssh_operator.py --upload $Pkg $Remote
Invoke-Cloud "sha256sum $Remote"
```

云端输出的 SHA 必须等于 `66a0f7442d1bab0c7ef9131e357a7aa5354bc0a90d9d969fffd6520c5d58d540`。

### 4.4 确认 FFmpeg / ffprobe

```powershell
Invoke-Cloud "command -v ffmpeg && command -v ffprobe && test -x /usr/bin/ffmpeg && test -x /usr/bin/ffprobe && /usr/bin/ffmpeg -version | head -n 1 && /usr/bin/ffprobe -version | head -n 1"
Invoke-Cloud "sudo -n grep -E '^REHAB_FF(MPEG|PROBE)=' /etc/rehabaffect/cloud.env"
```

`/usr/bin/ffmpeg` 和 `/usr/bin/ffprobe` 都必须存在且可执行。

`cloud.env` 中的 `REHAB_FFMPEG` 和 `REHAB_FFPROBE` 必须指向已确认可用的二进制。模板 `.env.example` 写的是 `/usr/local/bin/…`，如果服务器上只有 `/usr/bin/…`，需要由有权限的操作员修正 `cloud.env`。不能用 Windows 或本地的状态代替云端确认。

### 4.5 安装（SHA 必须与实际包一致）

```powershell
Invoke-Cloud "sudo -n /opt/rehabaffect/deploy/cloud/install_private_release.sh $Remote 66a0f7442d1bab0c7ef9131e357a7aa5354bc0a90d9d969fffd6520c5d58d540"
```

安装脚本会先用 `sha256sum` 比对 SHA，不一致直接失败。之后它会把包解压到 `/opt/rehabaffect`，并执行 `pip install -r deploy/cloud/requirements.txt pytest`，这一步需要云端能访问 PyPI 或已配置的镜像。

### 4.6 运行时预检（app / gateway）

预检脚本读取服务环境，必须带上 `cloud.env`，并以服务用户身份运行：

```powershell
Invoke-Cloud "sudo -n systemd-run --quiet --wait --pipe --collect -p User=rehabaffect -p EnvironmentFile=/etc/rehabaffect/cloud.env -p WorkingDirectory=/opt/rehabaffect /opt/rehabaffect/.venv/bin/python scripts/cloud_runtime_preflight.py app"
Invoke-Cloud "sudo -n systemd-run --quiet --wait --pipe --collect -p User=rehabaffect-gateway -p EnvironmentFile=/etc/rehabaffect/cloud.env -p WorkingDirectory=/opt/rehabaffect /opt/rehabaffect/.venv/bin/python scripts/cloud_runtime_preflight.py gateway"
```

两条预检都通过后再启动服务。服务单元的 `ExecStartPre` 会再执行一次同样的预检。

```powershell
Invoke-Cloud "sudo -n systemctl start rehabaffect-app.service rehabaffect-gateway.service && sleep 5 && systemctl is-active rehabaffect-app.service rehabaffect-gateway.service"
Invoke-Cloud "sudo -n systemctl start rehabaffect-observations.service 2>/dev/null || true; systemctl is-active rehabaffect-observations.service || true"
```

`rehabaffect-observations.service` 只有在 4.2 之前就处于运行状态时才需要重新启动。

### 4.7 合成媒体解码冒烟

```powershell
Invoke-Cloud "cd /opt/rehabaffect && .venv/bin/python scripts/cloud_media_smoke.py --ffmpeg /usr/bin/ffmpeg --ffprobe /usr/bin/ffprobe"
```

输出必须含 `"ok": true`。它的 scope 是 `synthetic_media_decode_only_not_scoring_accuracy`，只说明合成媒体能解码，不代表评分准确。

### 4.8 合成视频完整 E2E

账号通过云端私有凭据文件传入。文件属主必须是执行用户，权限为 `0600` 或 `0400`；账号和密码不写进仓库，也不写进本文档。

```powershell
Invoke-Cloud @'
cd /opt/rehabaffect && .venv/bin/python scripts/cloud_e2e_acceptance.py \
  --base-url http://127.0.0.1:8765 \
  --account-scope retained \
  --school-credentials-file /private/schools.md \
  --admin-credentials-file /private/admin.json \
  --allow-synthetic-uploads \
  --require-automatic-report \
  --ffmpeg /usr/bin/ffmpeg
'@
```

退出码为 0 才算通过。覆盖的流程：登录 → 上传合成视频 → 后台处理 → 学生状态结果 → 学校评分/系统评分 → 报告生成 → 报告下载 → 公司后台查询 → 视频和报告下载。

人工抽查 ID 链路：`school_id → student_id → iep_document_id → course_id → video_task_id → evaluation_id → report_id`。

只有 4.3 到 4.8 全部通过，才可以对外说“云端已更新”。回传内容包括：

- 云端 SHA 校验行、FFmpeg 版本行
- 两条预检的 JSON
- 媒体冒烟 JSON
- E2E 汇总、提交 SHA 和候选包 SHA

不要回传密码、API Key、邀请密钥、私钥、真实学生资料或人脸截图。

## 5. 回滚

只要满足任一条件就回滚：4.5 安装失败、4.6 预检失败、服务起不来、4.7 或 4.8 失败。

`<BACKUP_DIR>` 替换为 4.2 输出的目录。

```powershell
$Bk = "<BACKUP_DIR>"
Invoke-Cloud @"
set -euo pipefail
BK='$Bk'
sudo -n systemctl stop rehabaffect-gateway.service rehabaffect-app.service
sudo -n systemctl stop rehabaffect-observations.service 2>/dev/null || true
sudo -n sh -c "cd '`$BK' && sha256sum -c SHA256SUMS"
# 1) 代码回滚：把失败版本整体挪开，再还原备份代码
FAILED=/opt/rehabaffect.failed-`$(date -u +%Y%m%dT%H%M%SZ)
sudo -n install -d -m 0700 "`$FAILED"
for d in src scripts tests configs deploy models pyproject.toml; do sudo -n mv "/opt/rehabaffect/`$d" "`$FAILED/" ; done
sudo -n tar -xzf "`$BK/code.tar.gz" --no-same-owner -C /opt/rehabaffect
sudo -n chmod -R go-w /opt/rehabaffect/src /opt/rehabaffect/scripts /opt/rehabaffect/tests
echo code_restored
"@
```

只有确认新版本写坏了数据库（预检报告结构或数据异常）时，才执行下面的数据库回滚。它会丢弃备份之后产生的写入，执行前必须再次确认没有学校在用。

```powershell
Invoke-Cloud @"
set -euo pipefail
BK='$Bk'
DB="`$(sudo -n sed -n 's/^REHAB_DEMO2_DB_PATH=//p' /etc/rehabaffect/cloud.env)"
OWNER="`$(sudo -n stat -c '%U:%G' "`$DB")"
sudo -n mv "`$DB" "`$DB.failed-`$(date -u +%Y%m%dT%H%M%SZ)"
sudo -n rm -f "`$DB-wal" "`$DB-shm"
for f in "`$(basename "`$DB")" "`$(basename "`$DB")-wal" "`$(basename "`$DB")-shm"; do if sudo -n test -e "`$BK/`$f"; then sudo -n cp -a "`$BK/`$f" "`$(dirname "`$DB")/"; fi; done
sudo -n chown "`$OWNER" "`$DB"*
echo db_restored
"@
```

上传目录或视频任务目录损坏时，按同样的方式从 `$BK/video_tasks.tar.gz` 和 `$BK/upload_dir.tar.gz` 还原。还原前先把现有目录改名保留，不要直接删除。

回滚后重新启动服务并验证：

```powershell
Invoke-Cloud "sudo -n systemctl start rehabaffect-app.service rehabaffect-gateway.service && sleep 5 && systemctl is-active rehabaffect-app.service rehabaffect-gateway.service"
Invoke-Cloud "cd /opt/rehabaffect && .venv/bin/python scripts/cloud_media_smoke.py --ffmpeg /usr/bin/ffmpeg --ffprobe /usr/bin/ffprobe"
```

注意：`install_private_release.sh` 执行过的 `pip install` 不会随代码回滚而撤销。如果依赖版本导致问题，需要按回滚前的 `pip freeze` 重新固定依赖。

## 6. 当前仍存在的限制

1. **未推送**：本环境的 GitHub 账号对仓库没有写权限（403），`e1239eb`、`3c4c407` 和本文档的提交只存在于本地。
2. **未发布**：本环境没有云端部署私钥，第 4 节全部没有执行。云端代码、FFmpeg 路径、预检、媒体冒烟和 E2E 都没有在本版本上验证。
3. 云端 FFmpeg 的实际位置（`/usr/bin` 还是 `/usr/local/bin`）以及 `cloud.env` 的配置都没有确认。本地 macOS 的 FFmpeg 状态不能代表云端。
4. `install_private_release.sh` 安装时要联网执行 `pip install`，并且不会自动备份或回滚。备份和回滚必须按第 4.2 节和第 5 节手工完成。
5. 候选包不含 `scripts/cloud_ssh_operator.py` 和凭据下发脚本，这两个只在操作员机器上运行。
6. 所有验收都只用合成视频和虚构学生。输出了状态或评分，不等于教育准确性已经验证；真实学生识别准确度没有做过评估。
7. `uv.lock` 是本地 macOS 生成的，没有提交。服务器依赖仍以 `deploy/cloud/requirements.txt` 为准。
