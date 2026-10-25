# Demo2 本地媒体处理与证据契约

更新：2026-09-08。实现版本：`demo2_media_evidence_v1.1`。

主控验收补记：完整原课现已通过真实HTTP分片上传与后台处理。下文所列AI岗位临时原课目录的帧图和音轨已清理，只保留技术JSON；正式任务产物保存在受60天规则管理的业务目录。当前集成结果见 `docs/media_pipeline_iteration_20260908_zh.md`。

入口为 `src/rehab_affect/demo2_media_analysis.py` 的 `process_video_task(task, output_dir, progress=None, stop_event=None) -> dict`。本模块处理本地视频和音轨，生成技术测量及回看索引。它没有加载语义模型，没有进行 ASR、身份识别、姿态识别、情绪或掌握度判断。

## 调用和产物

`task` 必须提供由字母、数字、下划线或连字符组成、最长 128 字符的 `task_id`，以及普通本地文件的 `file_path`。可选 `sha256` 用于核对登记文件。调用方负责授权输入，并提供自己管理的私有输出目录；引擎不根据课程名或学生编号判断身份。

`progress(percent, stage)` 在调用线程执行，百分比单调不减。阶段包括 `validating`、`hashing`、`probing`、`sampling_video`、`extracting_audio`、`measuring_audio`、`audio_measured` / `audio_absent`、`writing_result`、`evidence_ready`。回调应快速返回。`stop_event` 支持取消；取消抛出 `MediaAnalysisCancelled`，其他预期失败抛出带 `.code` 的 `MediaAnalysisError`。

每次调用在 `output_dir` 下新建 `media_<随机值>/`，包含 `frames/frame_*.jpg`、有音轨时的 `audio.wav`、技术结果 `analysis.json`。同一任务重跑也不会覆盖上一次产物。所有 `artifacts` 和 `image_path` 都相对 `output_dir`。

后端应从可信结果的 `artifacts.audio` 安全解析音轨，不能假定音轨位于任务根目录的 `audio.wav`。引擎的 `analysis.json` 是本次运行的技术产物；由存储层完成发布的 `results/{task_id}.json` 才是后端对外结果。失败、取消或回调异常会终止解码子进程并清理本次运行目录，不删除调用方其他文件。

## 时间轴与测量口径

先校验文件、流元数据和 SHA-256，再完整解码视频。实际解码帧的 PTS、时间基和末帧持续时间确定视频起点与结束；容器总时长只用于预检，避免较长音轨把视频时长拉长。若明确的视频流时长与解码结果明显冲突，则失败。缺少必要解码时间信息、倒退时间戳或超限媒体不会生成合成结果。

显示旋转由 FFmpeg 应用，支持 0/90/180/270 度；采样图最长边不超过 640 像素。按 1 fps 重采样，并按 20 秒形成时间窗，末窗以实际视频结束时间收尾。这些“片段”是索引记录，当前不单独编码二十秒视频，也不生成代理视频。1 fps 时间是重采样网格，不是被选中原始帧的精确 PTS；短事件可能漏采，低帧率或时间戳缺口可能产生重复画面。

亮度是缩小灰度图的均值（0–255）；清晰度是 Laplacian 方差；运动量是相邻采样灰度图绝对差的均值除以 255。运动量属于全画面技术变化，第一张图为 `null`，不能直接解释为某位学生的动作或参与程度。本版尚未应用教师确认的座位 ROI。

音轨按实际视频起点对齐，导出 16 kHz、单声道、16-bit PCM WAV，长度与视频相差至多一个输出采样点。解码音频时间戳在补齐静音前记录，保留首尾与内部缺口；重采样强制处理超过一个输出采样点的时间偏差，避免默认 100 毫秒容忍导致小缺口后音画错位。区间合并允许一个采样点的量化误差。

音频 RMS 和能量活动比例仅在有解码覆盖的样本上统计，补齐样本不作为观察到的静音。能量活动由 20 毫秒块及固定 RMS 阈值 0.01 计算，不是语音 VAD。真实静音可为 `available=true, rms=0`；没有音轨或窗口完全由补齐构成时为 `available=false, rms=null`。存在音轨并不保证每个窗口都有有效覆盖。

## 输出 schema

原必需字段保持兼容，新增时间与覆盖字段：

| 路径 | 含义 |
| --- | --- |
| `analysis_status` / `analysis_version` | `evidence_ready` / 当前实现版本；不表示教师已复核 |
| `source_sha256` | 本次读取源文件的摘要，不输出原始文件绝对路径 |
| `media.duration_sec,width,height,fps` | 解码视频时长、旋转后尺寸、源流声明帧率 |
| `media.source_start_sec` | 第一帧实际解码 PTS，用于对应源媒体时间轴 |
| `media.duration_basis` | 成功结果为 `decoded_video_frame_end` |
| `media.has_audio,audio_status` | 是否存在被选中的音轨；`extracted` 或 `absent` |
| `media.audio_start_offset_sec` | 探测的音轨起点相对实际视频起点的偏移；实际覆盖见各窗口 |
| `segments[].start_sec,end_sec` | 从实际视频第一帧归零的半开时间区间 |
| `segments[].visual.sampled_frames` | 窗口采样图数量 |
| `segments[].visual.mean_brightness,mean_sharpness,mean_motion` | 全画面技术均值；无可用值为 `null` |
| `segments[].visual.samples[]` | 网格时间、图像相对路径及每图指标 |
| `segments[].audio.available,rms` | 本窗是否有解码覆盖；仅覆盖样本的 RMS |
| `segments[].audio.sample_count` | 对齐 WAV 在本窗的总样本数，含补齐 |
| `segments[].audio.observed_sample_count,padded_sample_count` | 解码覆盖样本数及补齐样本数，二者相加等于总数 |
| `segments[].audio.coverage_ratio,coverage_intervals` | 本窗覆盖比例及以视频起点归零的覆盖区间 |
| `segments[].audio.reason` | 完整覆盖为 `null`；部分覆盖为 `partial_audio_coverage`；无覆盖为 `no_audio_coverage`；无音轨为 `no_audio_stream` |
| `segments[].review_status` | 固定为 `unreviewed`，等待教师复核 |
| `summary.decoded_frames,sampled_frames` | 全速解码帧数及实际保存的采样图数 |
| `summary.unknown_fields` | 学生身份、说话人、情绪、掌握度均未判定 |
| `artifacts.audio,frames,result` | 相对当前调用 `output_dir` 的路径；无音轨时 `audio=null` |

无音轨时，音频对象保留 `available=false`、`rms=null`、`energy_activity_ratio=null` 与原因，不能假定覆盖统计字段一定存在。其他 `task` 业务字段不会被当作观测证据复制进结果。

## 依赖、边界和资源

运行时仅使用本地 FFmpeg、ffprobe、NumPy、OpenCV。FFmpeg 优先查找显式 `REHAB_FFMPEG`、PATH、项目 `.tools` 和已安装 `imageio_ffmpeg` 包的二进制目录；ffprobe 支持 `REHAB_FFPROBE`、PATH、FFmpeg 同目录及项目 `.tools/ffprobe.exe`。显式覆盖不存在时直接失败，不悄悄改用其他工具。已验证 imageio_ffmpeg 随附的 FFmpeg 7.1；替换工具需支持解码帧持续时间诊断。运行时不联网、不下载模型、不调用付费服务。

预检限制：源文件最多 8 GiB、视频最多 3 小时、边长最多 4096、像素数最多 4096×2160、声明帧率最多 120、最多 16 条流、音频最多 8 声道及 192 kHz。实际解码最多 1,296,000 帧；输出总额最多 1.5 GiB；JSON 索引最多 10 MiB；音频覆盖区间最多 100,000 条。时间戳碎片过多时可能先到区间或索引上限，不能把“三小时”解释成所有编码文件都可成功处理。

探测最长 30 秒，视频/音频子进程分别最长 2 小时；线程数限制为 1，FFmpeg 单次分配限制 64 MiB，管道仅缓存少量图像/音频块。这里没有操作系统级进程总内存硬限制。全片图像不会一次性进入内存，但结果索引和音频覆盖区间会保留在内存。

拒绝网络 URL、UNC、Windows 备用数据流、符号链接和重解析路径，禁用网络协议与播放列表类输入格式。检查源文件大小、修改时间和文件标识，发布前再次核对是否变化。调用方仍需控制源文件与输出目录的写权限；本模块不实现租户隔离或跨进程目录权限管理。

## 验证记录与下一阶段

测试位于 `tests/test_demo2_media_analysis.py`。使用 `PYTHONDONTWRITEBYTECODE=1`、`PYTHONPATH=src`、`-p no:cacheprovider`，以及每次独立的 `--basetemp=output/pytest_ai_<唯一值>`。既有 29 项测试通过；扩展测试覆盖旋转像素方向、VFR、边界尾段、不同音视频结束时间、负向音轨偏移、内部大/小音频缺口、损坏与截断文件、取消、超时、资源超限和重复运行隔离。Windows 当前账户不能创建符号链接，对应真实符号链接用例跳过；真实素材配置中的重解析路径已被引擎实际拒绝，验证时使用经确认的普通本地规范路径。

新增联调用例将真实 FFmpeg 结果交给临时测试数据库，再经临时本机受保护 HTTP 接口读取相对子目录中的 WAV，检查 HTTP 200、Range 206、字节一致性、采样格式和播放时长。没有修改 UI、server、store 或部署实现。

本次定向验证为 **54 passed, 1 skipped**，耗时 41.28 秒：本模块 50 项通过，另含真实 worker/store 联调 3 项与相对子目录音轨 API 回归 1 项。验证环境为 Python 3.12.7、NumPy 2.5.0、OpenCV 5.0.0、FFmpeg 7.1、ffprobe 9.0.1。使用的命令为：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONPATH='D:\GIT\RehabAffectPerception\src'
$runTag=[guid]::NewGuid().ToString('N')
python -m pytest tests/test_demo2_media_analysis.py tests/test_demo2_media_worker.py::test_default_engine_integrates_with_worker_and_sqlite tests/test_demo2_media_api.py::test_completed_audio_uses_processor_relative_artifact_and_stays_protected -q -p no:cacheprovider --basetemp="output/pytest_ai_$runTag"
```

整节真实课堂录像也已完成本地处理：1920×1080、30 fps、时长 2257.533333333 秒（约 37 分 37.53 秒），完整解码 67,726 帧、保存 2,258 张采样图、形成 113 个连续窗口。音轨导出 2257.5333125 秒，与视频相差约 0.000021 秒；记录到 13,838 个窗口内音轨覆盖区间，反映原片时间戳抖动及缺口，不将缺口当作观察到的静音。

本机耗时 243.14 秒；通过每 0.2 秒采样 Python 与 FFmpeg 进程树 RSS，观测内存峰值 116.76 MiB；总产物 158,330,463 字节（约 151.00 MiB）。RSS 为采样观测值，不是内存硬限额或其他机器性能承诺。真实结果位置为项目本地 `output/pytest_ai_real_eyechs9q/media_jfs03_5e/analysis.json`，同目录保存派生媒体。该结果仅用于本地技术验证，未写入业务学生记录。

独立复核已通过：ffprobe 声明的 67,726 帧与完整解码计数一致；全部 2,258 张索引图存在，网格时间连续并处于所属窗口内；WAV 样本总数与所有窗口之和一致。真实解码覆盖 35,971,358 个音频样本，补齐 149,175 个；另从 WAV 与覆盖区间重新计算一个窗口的 RMS，与结果误差小于 0.000001。结果 JSON 大小为 1,988,649 字节，低于 10 MiB 限额。

原始课堂媒体及派生产物始终保留本地，不在本说明记录学生姓名或原始绝对路径。首轮真实测试因音轨区间上限过低而失败，已清理其未完成运行目录；调整有界容量后重跑成功。数值统计和路径索引仍不构成课堂行为或学习成效模型验证。

下一阶段仍需：教师确认的 ROI 和身份关联暂停规则、代理视频/实际短片导出、VAD/中文 ASR 及转写时间戳、教师标注契约和评价数据划分。当前结果只有技术观测；语义模型推断未执行，教学与医学结论证据不足。
