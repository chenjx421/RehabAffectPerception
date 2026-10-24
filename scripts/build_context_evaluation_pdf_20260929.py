"""Screenshot guide to school-baseline contextual evaluation."""
from pathlib import Path
from xml.sax.saxutils import escape
from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.colors import HexColor
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph
from reportlab.lib.utils import ImageReader

ROOT = Path(__file__).resolve().parents[1]
SHOTS = ROOT / 'output/playwright/context_evaluation_20260929'
OUT = ROOT / 'output/pdf/Demo2_学校基础与情境复核评价说明_20260929.pdf'
pdfmetrics.registerFont(TTFont('CN', 'C:/Windows/Fonts/simhei.ttf'))


def text(c, value, x, y, width, size=11, color='#304256'):
    p = Paragraph(escape(value), ParagraphStyle('body', fontName='CN', fontSize=size,
                  leading=size*1.6, textColor=HexColor(color), wordWrap='CJK'))
    _, height = p.wrap(width, 1000)
    p.drawOn(c, x, y-height)
    return y-height


def shot(c, name, x, y, width, height):
    im = Image.open(SHOTS / name)
    scale = min(width/im.width, height/im.height)
    w, h = im.width*scale, im.height*scale
    c.drawImage(ImageReader(im), x+(width-w)/2, y+(height-h)/2, w, h)


def frame(c, n, title, subtitle):
    c.setFillColor(HexColor('#ffffff')); c.rect(0, 0, 842, 595, fill=1, stroke=0)
    text(c, 'RehabAffect | 课堂评价 | 2026.09.29', 30, 571, 780, 10, '#2463dc')
    text(c, title, 30, 542, 782, 23, '#172e49')
    text(c, subtitle, 30, 502, 782, 10)
    c.setStrokeColor(HexColor('#d7e3f0')); c.line(30, 42, 812, 42)
    text(c, '真实页面截图 · 合成验收案例，不代表真实课堂成绩', 30, 31, 690, 9, '#68788a')
    text(c, f'{n} / 4', 774, 31, 40, 9)


def notes(c, blocks):
    y = 465
    for title, body in blocks:
        y = text(c, title, 581, y, 231, 14, '#205bb5')
        y = text(c, body, 581, y-8, 231, 11)-22
    assert y > 42, 'Notes overflow'


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(OUT), pagesize=(842, 595))
    c.setTitle('Demo2 学校基础与情境复核评价说明')
    c.setAuthor('RehabAffect')
    frame(c, 1, '新增评价方案：学校基础 + 情境复核', '登录后进入“课堂评价”，点击“新建”，使用10项基本评价表。')
    shot(c, '00_setup.png', 30, 62, 526, 408)
    notes(c, [
        ('新增入口', '新记录默认选择“学校基础 + 情境复核”。学校标准、系统增强、双轨对照和文献依据仍在同一工作台。'),
        ('减少重复录入', '先录入学校分；没有新的修正依据时，增强分留空即可沿用学校分。留空不代表零分。'),
        ('历史记录保留', '既有记录继续保留原方案，不会自动套用新规则。15项学校原表仍不强行映射为这套增强评价。'),
    ]); c.showPage()
    frame(c, 2, '普通课堂：没有新证据，不自动压低分数', '学校基础分与系统结果使用同一组权重，不因为更换计算方法产生额外分差。')
    shot(c, '01_ordinary.png', 30, 62, 526, 408)
    notes(c, [
        ('这张图说明什么', '合成案例的学校单项分在6至10分之间，总分为8.00。没有情境修正时，系统结果同样为8.00。'),
        ('共同计算基础', '学校10个项目各占10%；四类权重保持20%、30%、30%、20%。不另设保底分，也不人为拉高成绩。'),
        ('不把困难当作过错', '学生非口语回应、课堂中断、障碍特点或收音不清，都不能单独作为扣分理由。基础分缺项时不生成完整总分。'),
    ]); c.showPage()
    frame(c, 3, '特殊情境：先提建议，再复核生效', '同一项学校分6分，建议修正至8分；按10%权重，对总分的影响为 +0.20。')
    text(c, '复核前：总分仍为8.00，建议保留但不计入', 30, 470, 526, 12, '#205bb5')
    shot(c, '02_pending.png', 30, 272, 526, 166)
    text(c, '复核后：修正生效，总分变为8.20', 30, 246, 526, 12, '#205bb5')
    shot(c, '03_reviewed.png', 30, 60, 526, 160)
    notes(c, [
        ('修正必须有依据', '填写证据时间点、教师应对、学生后续表现及下一课建议。示例中，原评价遗漏了学生通过指认完成任务的有效回应。'),
        ('教师保留确认权', '复核前只显示建议；教师勾选确认并保存后才计入结果。保存重开仍保留待复核建议。'),
        ('修改后重新核对', '修改评分或证据，会自动取消原复核勾选。系统校验必填内容，但不能自动证明描述真实、充分。'),
    ]); c.showPage()
    frame(c, 4, '双轨对照：解释分差，而不是只报一个分数', '最终分 = 学校基础分 + 各项学校权重 × 已复核的单项分差。')
    shot(c, '03b_comparison.png', 30, 62, 526, 408)
    notes(c, [
        ('差异可以追溯', '对照学校分、复核结果、证据修正和权重影响。本方案权重影响为零；分差只来自已复核的单项修正。'),
        ('安全事件单独核查', '疑似伤害等安全事件不能被总分掩盖，也不由模型直接定性。本次尚未新增独立的自动识别、上报或处置流程。'),
        ('当前完成范围', '已实现计算、复核、保存重开与移动端操作；110项相关测试通过。仍由教师录入和复核，尚非自动视频评分，未完成科学有效性校准。'),
    ]); c.showPage()
    c.save()
    print(OUT)


if __name__ == '__main__':
    main()
