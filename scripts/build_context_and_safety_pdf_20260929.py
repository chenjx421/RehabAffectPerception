"""Consolidate the features delivered after the contextual-grading request."""
from io import BytesIO
from pathlib import Path
from reportlab.pdfgen import canvas
from pypdf import PdfReader, PdfWriter
from build_context_evaluation_pdf_20260929 import text

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/pdf'
TARGET = OUT / 'Demo2_情境评价与安全核查新增功能汇总_20260929.pdf'


def main():
    cover = BytesIO()
    c = canvas.Canvas(cover, pagesize=(842, 595))
    text(c, 'RehabAffect | 新增功能汇总 | 2026.09.29', 35, 560, 770, 11, '#2463dc')
    text(c, '情境评价与安全事件人工核查', 35, 520, 770, 27, '#172e49')
    text(c, '范围：从“普通课评分稳定，特殊情境体现合理差异”这条需求开始，汇总随后完成的功能。', 35, 465, 765, 12)
    y = 407
    sections = [
        ('01  学校基础 + 情境复核评价  |  第2至5页',
         '普通课堂保留学校基础分及原权重，不凭算法变化制造分差。特殊情境记录证据、教师应对和学生后续表现，修正建议经教师复核后生效。保留双轨对照、差异解释与历史方案。'),
        ('02  安全事件人工核查  |  第6至9页',
         '新增视频时段提交、同校独立核查人授权、原视频回看、人工结论、补充材料及撤销授权。事件详情加密保存，核查权限与普通课堂评分分开。'),
        ('两部分怎样配合',
         '教学情境的证据修正进入评价流程；疑似安全事件进入独立核查流程。安全核查结论目前不会自动回写评分，也不自动扣分。高总分不能代替安全核查，学生出现困难也不等于教师教学失当。'),
        ('当前交付边界',
         '这是可操作的人工录入、计算与复核流程，不是AI自动伤害识别或自动视频评分。未实现自动报警、线下处置或科学有效性校准。文中截图均来自实际页面，使用合成视频与合成事件。'),
    ]
    for title, body in sections:
        y = text(c, title, 35, y, 770, 15, '#205bb5')
        y = text(c, body, 35, y-8, 770, 11)-19
    assert y > 45
    c.save()
    writer = PdfWriter()
    writer.append(PdfReader(cover))
    for name in ['Demo2_学校基础与情境复核评价说明_20260929.pdf',
                 'Demo2_安全事件人工核查功能说明_20260929.pdf']:
        writer.append(PdfReader(OUT / name))
    for n, page in enumerate(writer.pages, 1):
        overlay = BytesIO()
        c = canvas.Canvas(overlay, pagesize=(842, 595))
        c.setFillColorRGB(1, 1, 1)
        c.rect(765, 8, 77, 30, fill=1, stroke=0)
        text(c, f'{n} / {len(writer.pages)}', 774, 31, 50, 9, '#68788a')
        c.save()
        page.merge_page(PdfReader(overlay).pages[0])
    writer.add_outline_item('功能范围与配合方式', 0)
    writer.add_outline_item('学校基础与情境复核评价', 1)
    writer.add_outline_item('安全事件人工核查', 5)
    writer.add_metadata({'/Title': 'Demo2 情境评价与安全核查新增功能汇总', '/Author': 'RehabAffect'})
    with TARGET.open('wb') as f:
        writer.write(f)
    print(str(TARGET))


if __name__ == '__main__':
    main()
