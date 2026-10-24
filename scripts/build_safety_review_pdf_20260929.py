"""Illustrated guide for the restricted human-review workflow."""
from pathlib import Path
from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor
from reportlab.lib.utils import ImageReader
from build_context_evaluation_pdf_20260929 import text, notes

ROOT = Path(__file__).resolve().parents[1]
SHOTS = ROOT / 'output/playwright/safety_20260929'
OUT = ROOT / 'output/pdf/Demo2_安全事件人工核查功能说明_20260929.pdf'


def frame(c, n, title, subtitle):
    text(c, 'RehabAffect | 安全事件人工核查 | 2026.09.29', 30, 571, 780, 10, '#2463dc')
    text(c, title, 30, 542, 782, 23, '#172e49')
    text(c, subtitle, 30, 502, 782, 10)
    c.setStrokeColor(HexColor('#d7e3f0')); c.line(30, 42, 812, 42)
    text(c, '实际页面截图 · 合成视频与合成事件，不涉及真实学生或伤害指控', 30, 31, 710, 9, '#68788a')
    text(c, f'{n} / 4', 774, 31, 40, 9)


def shot(c, name, y=60, height=410):
    im = Image.open(SHOTS / name)
    scale = min(526/im.width, height/im.height)
    w, h = im.width*scale, im.height*scale
    c.drawImage(ImageReader(im), 30+(526-w)/2, y+(height-h)/2, w, h)


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(OUT), pagesize=(842, 595))
    c.setTitle('Demo2 安全事件人工核查功能说明')
    c.setAuthor('RehabAffect')
    frame(c, 1, '提交核查：保留时间段与客观情况', '入口：课堂评价 → 安全核查；或单课工作台 → 提交安全核查。')
    shot(c, '01b_create_form.png')
    notes(c, [
        ('新增操作', '选择已处理的课堂视频，填写开始和结束秒数；也可直接用播放器当前位置设点。后端校验视频归属、可用性和实际时长。'),
        ('记录事实，不急于定性', '填写观察到的动作及前后情境，补充现场已经采取的措施。提交后为待核查；未指定核查人时显示待指定负责人。'),
        ('现场处置优先', '若现场存在即时危险，应按学校安全流程及时处理，不等待平台分析。本功能不自动认定伤害、不自动扣分。'),
    ]); c.showPage()
    frame(c, 2, '指定核查人：单独授权，不开放全部资料', '提交者选择另一名同校账号，确认学校授权和账号身份后，才能保存授权。')
    shot(c, '01c_assignment.png')
    notes(c, [
        ('谁可以核查', '提交者不能自行结案。指定核查人确认无利益冲突后，才能记录结论。学校仍需核实负责人身份，不能仅凭账号的学校名称判断其资格。'),
        ('授权范围明确', '核查人可查看本事件说明及关联的完整原视频，包括音频；不是只开放截取的几秒。不会因此获得其他档案权限。'),
        ('可以撤销或更换', '选择暂不指定可撤销授权，并恢复待核查状态。撤销阻断后续读取；已经接收的视频内容无法远程收回。'),
    ]); c.showPage()
    frame(c, 3, '独立核查：回看前后情境，再记录结论', '状态包括待核查、补充材料中、已核实、已排除、无法判断。')
    shot(c, '02b_review_form.png', y=234, height=225)
    shot(c, '02c_history.png', y=58, height=158)
    notes(c, [
        ('先回看再判断', '可回看事件前后各10秒，也可查看完整录像。视频不可用时明确提示；系统阻止在原视频缺失时提交“已核实”。'),
        ('结论由人工负责', '核查人填写依据、结论及后续处理，并确认无利益冲突。已核实只是人工核查记录，不是模型判定或司法认定。'),
        ('保留不同意见', '提交者和核查人均可补充材料。补充后转为补充材料中，旧结论继续留在历史里，供后续核对。'),
    ]); c.showPage()
    frame(c, 4, '留痕与保护：事件处理不直接变成课堂扣分', '保存操作历史、明确访问范围；评分与安全核查保持独立。')
    shot(c, '02c_history.png', y=264, height=192)
    y = text(c, '已经验证的流程', 30, 239, 526, 15, '#205bb5')
    text(c, '提交事件 → 指定核查人 → 视频回看 → 结论记录 → 补充或重新核查 → 必要时撤销授权。相关测试98项通过；两账号浏览器验证使用真实可播放的合成视频。测试通过不代表伤害识别准确率。', 30, y-10, 526, 12)
    notes(c, [
        ('权限和留痕', '事件说明与处理历史加密保存。未授权账号及公司管理员不能直接读取详情。保存版本校验防止覆盖，并记录授权变更和视频读取。'),
        ('到期与数据范围', '原视频不复制、不延长保存期。事件详情最长60天且不晚于原视频到期，到期后访问接口时清理；尚无独立定时清理及备份擦除流程。'),
        ('尚未实现的部分', '自动伤害识别、自动上报、学校现场处置、自动扣分均未实现。下一步先确认校方授权和独立复核机制，再评估通知与候选片段筛选。'),
    ]); c.showPage()
    c.save()
    print(OUT)


if __name__ == '__main__':
    main()
