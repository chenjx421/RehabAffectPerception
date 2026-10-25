# YuNet：本地单帧人脸位置候选

模型只检测画面中的人脸位置；不输出姓名、身份特征或跨视频身份匹配。
检测分数是人脸检测分数，不是身份置信度。候选姓名需教师从获准校内名册人工确认。
本模型不用于医学诊断，也不能据人脸候选推断注意力、情绪或掌握度。

## 固定来源与完整性

- 官方仓库：[OpenCV Zoo](https://github.com/opencv/opencv_zoo)
- 固定提交：`47534e27c9851bb1128ccc0102f1145e27f23f98`
- 文件：`face_detection_yunet_2023mar.onnx`（FP32，非量化版本）
- 大小：`232589` 字节
- SHA-256：`8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4`
- [该提交的 Git LFS 指针](https://github.com/opencv/opencv_zoo/blob/47534e27c9851bb1128ccc0102f1145e27f23f98/models/face_detection_yunet/face_detection_yunet_2023mar.onnx)
- [该提交的官方 MIT 许可证](https://github.com/opencv/opencv_zoo/blob/47534e27c9851bb1128ccc0102f1145e27f23f98/models/face_detection_yunet/LICENSE)，完整副本见仓库内 `models/LICENSE.yunet`。
- 上游许可证原始字节 SHA-256：`c83b8120c50ccbd4c4f96edf53141bdd566ebb8f8e9227e415326aa1b1aba958`；本地校验允许换行符和文件末尾换行差异。

## 显式安装与离线校验

在仓库根目录执行（使用已有 Python，无额外运行时安装）：

```powershell
& 'D:/anaconda3/python.exe' scripts/download_demo2_yunet.py
& 'D:/anaconda3/python.exe' scripts/download_demo2_yunet.py --verify-only
```

下载脚本仅请求上述固定提交的官方 GitHub API 和模型媒体地址，先检查 LFS 指针、文件长度与 SHA-256，再安装模型。
请求有单次 socket 超时、总传输时间预算和响应大小上限；不下载示例照片，不读取或上传本地图片、视频、名册。
已有模型和许可证验证通过即幂等结束；不一致则报错，不覆盖。`--verify-only` 不联网。
检测模块不调用此脚本；缺少模型时返回不可用，不自动联网。

现有仓库 `.gitignore` 忽略 `models/`，但本说明位于 `docs/`，可随源码交付。离线交付或发布包须包含以下文件，其中模型和许可证需显式纳入，不能仅依赖默认 Git 文件清单：

- `src/rehab_affect/demo2_face_detection.py`
- `scripts/download_demo2_yunet.py`
- `models/face_detection_yunet_2023mar.onnx`
- `models/LICENSE.yunet`
- `docs/demo2_face_detection_zh.md`

## 输入与版本边界

[该提交的官方模型说明](https://github.com/opencv/opencv_zoo/blob/47534e27c9851bb1128ccc0102f1145e27f23f98/models/face_detection_yunet/README.md)
指出 2023mar 模型为固定输入尺寸，而 OpenCV 5.x 的 ONNX Runtime 引擎在任意分辨率输入时需要动态尺寸。
本实现使用固定 `640 × 640` 等比缩放加黑边（letterbox）、OpenCV DNN CPU 配置。本轮保留一次全幅检测，并增加最多四个重叠局部块：每块宽高为原图对应尺寸的 60%（向上取整），按 2×2 布置，局部允许放大；同一 detector 最多运行五次。本次不替换成其他年份模型，也不降低 `0.8` 检测阈值。
局部候选先反算回同一原图归一化坐标，再按检测分数与几何坐标稳定排序，进行全局贪心 NMS（IoU 大于 `0.3` 时抑制），最后截断至 32 项并编号。跨越局部人工裁切边缘的候选在裁剪前丢弃；原图外边界仍允许裁剪。内部每视图最多读取 512 行候选，不在跨视图去重前截断为 32。
当前本地 `cv2=5.0.0` 已完成全黑合成图的 640 输入真实推理，成功返回无候选；这只验证模型加载及该输入路径兼容，不代表真人课堂检出率已经验证。
缩小后的远处小脸、侧脸、遮挡、背光均可能漏检；检测不到人脸不等于画面无人，检测到人脸也不能证明其姓名。
局部放大不能恢复灰度缩图已丢失的细节。有限的真实采样帧目视抽查不是标注评估；候选数增加不表示检出率、精确率或学生覆盖率已得到验证，不作为姓名或个人状态的依据。
单帧确认不自动延续到下一帧、切镜、重新入画或另一段视频。

## 集成契约

仅对已经过任务权限校验的本地单帧文件调用：

```python
from pathlib import Path
from rehab_affect.demo2_face_detection import detect_faces

result = detect_faces(Path("path/to/teacher_selected_frame.jpg"))
```

返回结构为 `{"available": bool, "model": str, "faces": list, "reason": str}`。
候选为 `{"candidate_id": "face_001", "bbox": {"x": float, "y": float, "width": float, "height": float}, "score": float}`。
框值是原图左上角原点的归一化坐标；分数只是检测分数。候选按分数与框坐标稳定排序，最多 32 项，数值有限且框不越界。
`candidate_id` 每帧重新生成，不是学生编号，也不是跨帧追踪 ID。输出不含姓名、身份嵌入或生物特征库；姓名确认及授权由调用方独立处理。

输入文件最大 8 MiB，解码图像单边最多 8192 像素、总像素最多 16,000,000；Unicode 路径采用文件字节读取加 `cv2.imdecode`。
调用通过独立子进程进行本地推理，全部视图共享一次 6 秒子进程硬超时（不是每个局部块各 6 秒），进程内锁等待上限为 0.25 秒；为现有 10 秒网关预留前置校验及响应处理时间，不延长网关或前端超时。超时返回 `detection_timeout`，繁忙返回 `detector_busy`，均为 `available=false`、空候选；调用方应允许教师继续人工框选，不无限排队或自动重试。
模型缺失、完整性不符或 OpenCV 不可用时返回 `available=false`，原因包含 `no_network_download`；有效空白图可返回 `available=true`、`faces=[]`，这不是故障或身份判断。
该模块不修改原媒体、不连接网络、不自动把整幅画面运动或混合音轨指标归属给候选学生。
