# Demo2 课堂分析市场研究与三周实施计划

研究及资料访问日期：2026-09-08。项目：RehabAffectPerception。

## 一、交付边界与定位

据主任务最新进展，登录、学校、注册及隐私界面已实现，已有静态登录预览和本地服务；尚未实际公网部署。**学校上下文目前只是元数据，不等于租户隔离。** 本研究未独立验收页面。Word、截图及私密试点凭据另行交付，本文不包含凭据，不实现视频或报告 worker。

建议定位为教师使用的“课堂证据复核与个体目标进展工作台”：找到任务、回应和提示片段，依据教师确认记录学习表现。看起来专注、安静或动作多，均不能证明学会。

## 二、已有离线分析与新上传缺口

以下为当前工作树静态核对，行号可能随并行开发变化，可按函数名定位；未运行真实视频评测。

| 源码证据 | 已有能力与限制 |
| --- | --- |
| [student_record_store.py:1461](/D:/GIT/RehabAffectPerception/src/rehab_affect/student_record_store.py:1461)、[_build_video_precheck:1683](/D:/GIT/RehabAffectPerception/src/rehab_affect/student_record_store.py:1683) | 上传后调用预检，最多抽四十帧测亮度、清晰度、粗运动及元数据；不是课堂行为模型。`uploaded_pending_worker` 不证明消费者已运行。 |
| [seewo_multi_student_demo.py:143](/D:/GIT/RehabAffectPerception/src/rehab_affect/seewo_multi_student_demo.py:143)、[273](/D:/GIT/RehabAffectPerception/src/rehab_affect/seewo_multi_student_demo.py:273) | 离线流程真实解码关键帧，按固定座位 ROI 测帧差；不是稳定身份追踪，也未接通账号上传任务。 |
| [seewo_multi_student_demo.py:571](/D:/GIT/RehabAffectPerception/src/rehab_affect/seewo_multi_student_demo.py:571)、[1366](/D:/GIT/RehabAffectPerception/src/rehab_affect/seewo_multi_student_demo.py:1366) | 掌握初评使用历史等级和参与分调整，机会数由规则给定，阶段按时长比例划分；必须留在演示域。 |
| [seewo_student_demo.py:1298](/D:/GIT/RehabAffectPerception/src/rehab_affect/seewo_student_demo.py:1298)、[打包脚本:258](/D:/GIT/RehabAffectPerception/scripts/build_seewo_offline_package.py:258) | 旧流程抽音轨计算 RMS，脚本提供授权素材离线重分析入口；并非 ASR 或新上传队列。 |
| [seewo_long_report.py:46](/D:/GIT/RehabAffectPerception/src/rehab_affect/seewo_long_report.py:46)、[上传测试:96](/D:/GIT/RehabAffectPerception/tests/test_student_record_store.py:96) | 已有复核 JSON 保存；上传测试使用非真实视频字节，不是模型准确性验证。 |

可复用上传、课程、文件管理、时间线和复核表单；需新增持久任务、隔离结果目录、CV/ASR、证据索引及真实机会统计。生产失败不得回退合成课堂数据。

## 三、竞争参照

以下是官方公开说明，不是我方试用验证；未核实不等于竞品没有。

| 参照与直接来源 | 官方内容与本项目取舍 |
| --- | --- |
| [希沃课堂智能反馈](https://help.seewo.com/edulyse/v5tJFMYMbm) | 提供组织账号、采集、报告、关联人工听评课及实录下载，官方称课后约十分钟出报告。借鉴人机协同并兼容授权导出；未取得开放接口、报价，不承诺相同时效。 |
| [Edthena AI Coach](https://www.edthena.com/ai-coach-for-teachers/) | 录像时间戳评论、反思、行动及影响回顾；单校最多五十教师年费 US$3,450。借鉴教师复核与分享控制，不等同逐学生掌握判定。 |
| [TeachFX](https://teachfx.com/) | 课堂音频形成话语模式和教师私有反馈。先做指令、等待与回应证据；中文儿童远场效果未验证，话语时长不等于成效。 |
| [IRIS Center 进展监测](https://iris.peabody.vanderbilt.edu/module/iep01/cresource/q3/p09/) | 为个体目标定义客观测量、频率及报告安排。是方法资源而非 SaaS；借鉴重复测量，不套用美国学校法律义务。 |

核心差异化是目标与原始证据可追溯，不是情绪总分。希沃、TeachFX 本次所查页面无可据以承诺的标准采购价。IRIS 依据官方搜索可读内容，直接打开失败；所有课堂效果仍需本校验证。

## 四、三周初始排期

**以下尚未实施。** 按十五个工作日、固定机位、三名重点学生安排，前提是有授权素材、后端/模型工程师、测试人员及教师参与，不是无条件交付承诺。

```text
上传预检 -> 持久队列 -> 独立 worker 解码/CV/ASR
         -> 候选事件与原片索引 -> 教师复核 -> 统计/报告草稿
```

### 第 1 周：真实媒体处理

第 1-2 天，后端确认任务与权限契约，复用 SQLite 实现事务领取、租约、心跳、有限重试和幂等。上传与分析状态分开，采用 `queued/running/needs_review/failed/cancelled`，不能将预检完成显示为分析完成。

第 3-4 天接 ffprobe、流式解码和轻量人员检测/轨迹。教师确认座位与匿名 ID；换座、遮挡、轨迹断裂标记 unknown。按任务生成受保护的代理、缩略图和时间戳，不覆盖全局演示缓存；处理进程限制时间、内存和磁盘。

第 5 天测试新课程、无音轨、损坏文件、重复任务、崩溃恢复和账号越权。周交付是能回看真实片段的结果，不是掌握分。

### 第 2 周：互动证据与教师在环

第 6-7 天接中文 VAD/ASR、时间戳和匿名说话人分段；RMS 仅作活动特征。多机位记录同步偏移；齐答、同伴代答和不明声源不强行归属学生。

第 8-9 天接指令、提问、等待、回应、提示及反馈候选。教师同屏回看视频、逐字稿和目标，修正对象、机会、正确性及提示。保存复核人、时间、版本和修改历史；证据至少含 `task_id/media_id/student_id/goal_id/start_ms/end_ms/model_version/review_status`，未知身份允许为空。

第 10 天除审核候选外，还抽查随机和模型阴性片段，检查漏检并记录复核耗时。周交付是可纠错证据，不将模型自报 confidence 当准确率。

### 第 3 周：目标统计与报告试点

第 11-12 天教师定义目标、任务、允许提示及达标规则。机会单列有/无/未知；表现记录独立正确 I、提示正确 P、错误或未完成 E、证据不足 U。有效机会 N=I+P+E，展示 I/N、P/N、E/N，另列 U 及无机会数；N=0 显示暂无可评分机会，不能给零分。

第 13 天接确定性统计和报告草稿；每条结论关联证据，未复核不得正式发布。旧演示评分不得进入真实数据。跨课比较同时展示量表版本、任务难度、提示和样本数；调整后变化只能表述观察关联，不宣称因果。

第 14-15 天用两门课程、至少两节完整留出课试点，两位教师交叉复核部分片段；报告漏检/误检、语音 CER、身份错绑、证据覆盖、教师时间和成本。小样本不支持泛化准确率宣传。全班自动评分、实时干预和成熟跨校 SaaS 不在三周承诺内。

## 五、工具与大模型职责

[FFmpeg/ffprobe](https://ffmpeg.org/ffprobe.html)负责媒体处理；[Ultralytics](https://docs.ultralytics.com/modes/track/)提供预训练检测/跟踪，[MediaPipe Pose](https://developers.google.com/edge/mediapipe/solutions/vision/pose_landmarker)提供姿态线索；[FunASR](https://github.com/modelscope/FunASR)用于本地 ASR/VAD；[PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR)按需读清晰任务卡。均须学校样本验证，不从外观推断情绪、障碍或学习能力。检查 Ultralytics 的 AGPL/企业许可及 FunASR 权重独立许可。

可选 VLM 仅审阅经批准的短片/帧序列，输出可见事件、时间段和不确定原因；[阿里云视觉文档](https://help.aliyun.com/zh/model-studio/vision)支持视频/帧理解，[Paraformer API](https://help.aliyun.com/zh/model-studio/paraformer-recorded-speech-recognition-restful-api)另行转写音轨，不默认视觉模型听到了 MP4 声音。文本模型只整理确认数据，服务端核验引用和数字；字幕不是系统指令，模型不能写学生主档或自行发布。失败回退本地模板，不补造证据。

## 六、35 分钟成本与算力

[百炼官方价目表](https://help.aliyun.com/zh/model-studio/model-pricing)：北京常规按量、无缓存，Qwen3-VL-Plus 输入不超过 32K 时为 1/10 元每百万输入/输出 token；Qwen-Plus 非思考、输入不超过 128K 为 0.8/2 元；Paraformer-v2 非实时为 0.00008 元/秒。长输入按单请求阶梯计价，不扣免费额度。

演算假设：一条 2,100 秒音轨，十二段各二十秒、1 fps，共二百四十帧；每帧假设 256 token，每段文本输入 800、输出 300；报告输入 8,000、输出 1,500。帧 token 是预算参数，非官方固定换算，须用实际 usage 替换。

```text
视觉输入 = 240x256 + 12x800 = 71,040 token
视觉输出 = 12x300 = 3,600 token
ASR = 2,100x0.00008 = 0.168 元
VLM = (71,040x1 + 3,600x10)/1,000,000 = 0.10704 元
报告 = (8,000x0.8 + 1,500x2)/1,000,000 = 0.0094 元
合计 = 0.28444 元，仅假设下 API 项，不是平台整课成本
总成本 = API + CPU/GPU小时费 + 存储/流量 + 重试
         + 教师复核分钟/60x小时成本 + 许可/运维/折旧
```

短片仅覆盖整课约 11.4%，不能代表未审阅部分。多人重复裁剪、多机位、多音轨、分辨率及思考输出都会改变成本。Edthena 年费若假设五十教师各用一百次，摊为 US$0.69/次，仅为年费摊算，不是三十五分钟单价。

[豆包官方产品页](https://www.volcengine.com/product/doubao/)索引展示 Seed 2.0 Lite 为 0.6/3.6 元起每百万输入/输出 token，录音识别 2.0 为 0.8 元/小时；索引约两个月前抓取，[完整价格正文](https://www.volcengine.com/docs/82379/1544106)读取失败。因此仅记官方起价线索，不冒充当日完整报价，不直接套入视觉账单。视频能力、快照及音频计费待核实，[LAS 视频理解说明](https://www.volcengine.com/docs/6492/2192001?lang=en)不能代替方舟 API 契约；不混用 Seedance 生成价格。

容量估算非实测：UI 从 4 核/8 GB 起测；单路轻量 CPU worker 预算 8 核/16-32 GB，GPU 方案预算 8-12 GB 显存、32 GB RAM，需验证模型并存开销，不保证实时。4 Mbps 的课时录像约 1.05 GB；每日八节保留六十天原片约 504 GB，另加代理和备份。流式解码、限并发，再实测峰值与耗时。

## 七、界面与部署条件

教师端白底、蓝色导航、浅灰分隔和紧凑表格，不做卡通或营销首页。首屏显示账号/学校/课程与任务；复核页为播放器、时间线、逐字稿和目标表单。预检、分析、复核分开，缺失不填假分数；主任务检查桌面/手机长文本、键盘焦点及截图。

当前仅本地服务。局域网需监听地址、校园路由、防火墙和受控 HTTPS；公网需域名、DNS、服务器、TLS、备案适用性及运维，并未部署。上线前须补真正的服务端学校/账号对象授权，覆盖新旧媒体、缩略图、报告和下载路由，不能靠前端隐藏。

原片、数据库和凭据不公开；演示与真实数据分库分存储。云调用默认关闭，单独确认授权、地域、供应商留存/训练条款及删除；打码不等于匿名，禁止为 API 拉取而公开上传目录。保存期覆盖代理、音轨和备份。[个人信息保护法官方文本](https://wb.flk.npc.gov.cn/flfg/PDF/f67af9f12e1b4c83a998cf5a876ce0e4.pdf)与[工信部备案办法](https://www.miit.gov.cn/gyhxxhb/jgsj/cyzcyfgs/bmgz/xxtxl/art/2024/art_84a0cfa0ebd049bbbe751dca9a008e56.html)是上线核验入口，不是本项目合规认证。

**顺序：先账号界面和本地验收，再接真实证据、教师复核及报告草稿。本文不声明 worker、租户隔离或公网部署已实现。**
