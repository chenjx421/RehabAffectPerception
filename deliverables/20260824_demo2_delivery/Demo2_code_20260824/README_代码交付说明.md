# RehabAffect Demo2 代码交付说明

交付日期：2026-08-24

## 本包内容

- `src/rehab_affect/`：Demo2 前端、本地服务、报告生成及项目其他运行模块。
- `tests/`：项目自动化测试。
- `scripts/`：启动、界面 QA、文档构建和辅助脚本。
- `configs/`：标签、场景和通用知识配置，不含学生个体数据。
- `design-system/`：Demo2 前端设计规范与页面约束。
- `pyproject.toml`：Python 项目与依赖配置。
- `start_school_demo2.cmd`：Demo2 启动入口。

## 本轮重点代码

- `src/rehab_affect/seewo_multi_student_demo.py`：七步课程入口、课堂证据工作台、三学生切换、14个分析页面、教师复核、支持工具、动作方案和报告页面。
- `src/rehab_affect/scenario_lab_server.py`：Demo2 路由、教师复核与报告接口、Gzip 响应。
- `src/rehab_affect/seewo_long_report.py`：课程深度报告生成与教师复核存储。
- `scripts/qa_demo2_ui.js`：桌面、学校电脑、平板和手机浏览器回归检查。
- `tests/test_seewo_multi_student_demo.py`：Demo2 页面结构和交互契约测试。
- `tests/test_scenario_lab_server.py`：本地服务与Gzip测试。

## 数据说明

根据交付要求，本压缩包只包含代码，不包含学生姓名、IEP、课堂视频、截图、分析结果或教师复核记录。因此单独解压后不能还原当前真实学生演示数据；需在授权环境中配置 `data/processed/seewo_demo2/session_config.json` 和对应视频/分析文件。

## 基本验证

在项目根目录设置 `PYTHONPATH=src` 后运行：

```text
python -m pytest -q tests
```

本轮最后一次全项目回归结果为 `38 passed, 5 skipped`，没有失败。5个跳过项来自当前环境中 `scikit-learn` 与 `NumPy` 的二进制兼容问题。
