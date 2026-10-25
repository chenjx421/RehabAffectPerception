"""Refresh the page guide against current code in an isolated synthetic workspace."""
from pathlib import Path
import scripts.capture_current_pages_20260917 as previous

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/playwright/delivery_20261008'

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    source = (ROOT / 'scripts/capture_current_pages_20260917.js').read_text(encoding='utf8')
    source = source.replace("date:'2026-09-17'", "date:'2026-10-08'")
    start = source.index("    await go('/demo2/evaluation');")
    end = source.index("    await role('admin');", start)
    source = source[:start] + '''
    await go('/demo2/evaluation');
    await shot('24_evaluation','双轨评价入口','课堂评价','选择学校评价模板，建立课程记录，切换学校标准与系统增强结果。','默认普通课继承学校评分；具体调整需证据和复核，不自动给老师低分。','已调整');
    await go('/demo2/teaching-support?task_id='+config.task_id);
    await shot('25_support','教学支持与可及性','教学支持','管理支持条件、表达方式与教学建议，兼顾指认、手势及辅助沟通。','建议不能替代专业评估，不从视频推断疾病或诊断。','新增功能');
    await align('#growth');
    await shot('25b_growth','教师逐课改进记录','教学支持','记录本课有效做法、下一课调整和验证方法，保存为教学改进计划。','改进记录不等于已证明教学效果提升，需要后续课例验证。','新增功能');
    await align('#ai');
    await shot('25c_ai','模型解释入口与发送边界','教学支持','展示模型解释入口与数据边界，便于后续受控接入。','当前外部模型分析暂停；入口存在不表示已完成真实自动评分。','新增功能');
    await go('/demo2/safety');
    await shot('26_safety','安全事件独立复核','安全复核','将疑似风险与日常评分分开处理，保留事件记录与核查状态。','当前不是自动伤害检测；没有人工核查不能认定伤害事实。','新增功能');
    await go('/demo2/course-batch?task_id='+config.task_id);
    await shot('27_batch','课程批次整理','课程工作区','按课程整理视频与关联材料，为同一批次的分析与复核提供入口。','多个视频的录制时间和学生对应关系仍需正确填写。','新增功能');
    await go('/demo2/analysis?task_id='+config.task_id);
    await shot('28_analysis','新上传课程分析入口','课程工作区','从当前任务进入群像、个体和证据复核工作区。','材料准备就绪不代表已自动判断学生掌握程度。','已调整');
''' + source[end:]
    js = OUT / 'capture.js'
    js.write_text(source, encoding='utf8')
    previous.OUT = OUT
    previous.__file__ = str(js.with_suffix('.py'))
    return previous.main()

if __name__ == '__main__':
    raise SystemExit(main())
