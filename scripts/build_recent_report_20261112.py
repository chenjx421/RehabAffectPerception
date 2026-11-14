from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

OUT = "/Users/chenjia/Downloads/WeGlow_近期优化与验收报告_20261112.docx"
INK = RGBColor(0x17, 0x2B, 0x4D)
BLUE = RGBColor(0x1F, 0x63, 0xC6)
MUTED = RGBColor(0x5F, 0x71, 0x86)


def shade(cell, color):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), color)
    tcPr.append(shd)


def set_cell(cell, text, bold=False, size=9, color=INK, align=None):
    cell.text = ""
    p = cell.paragraphs[0]
    p.paragraph_format.space_after = Pt(1)
    if align is not None:
        p.alignment = align
    r = p.add_run(text)
    r.bold = bold
    r.font.size = Pt(size)
    r.font.color.rgb = color
    r.font.name = "Arial"
    r._element.rPr.rFonts.set(qn("w:eastAsia"), "Heiti SC")


def table(doc, headers, rows, widths=None):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(headers):
        set_cell(t.rows[0].cells[i], h, bold=True, size=8, color=INK)
        shade(t.rows[0].cells[i], "E8EEF7")
    for row in rows:
        cells = t.add_row().cells
        for i, value in enumerate(row):
            set_cell(cells[i], str(value), size=8.5)
    if widths:
        for row in t.rows:
            for i, width in enumerate(widths):
                row.cells[i].width = Cm(width)
    return t


def bullet(doc, text, bold_prefix=""):
    p = doc.add_paragraph(style="List Bullet")
    p.paragraph_format.space_after = Pt(2)
    if bold_prefix:
        r = p.add_run(bold_prefix)
        r.bold = True
    p.add_run(text)


doc = Document()
section = doc.sections[0]
section.top_margin = Cm(1.7)
section.bottom_margin = Cm(1.7)
section.left_margin = Cm(2.0)
section.right_margin = Cm(2.0)
normal = doc.styles["Normal"]
normal.font.name = "Arial"
normal.font.size = Pt(10)
normal._element.rPr.rFonts.set(qn("w:eastAsia"), "Heiti SC")
normal.paragraph_format.space_after = Pt(4)

# Header/footer
header = section.header.paragraphs[0]
header.text = "WeGlow 微光系统 · 近期优化与验收材料"
header.alignment = WD_ALIGN_PARAGRAPH.RIGHT
for r in header.runs:
    r.font.size = Pt(8)
    r.font.color.rgb = MUTED
footer = section.footer.paragraphs[0]
footer.text = "内部项目材料 · 2026-11-12"
footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
for r in footer.runs:
    r.font.size = Pt(8)
    r.font.color.rgb = MUTED

p = doc.add_paragraph()
r = p.add_run("WeGlow 微光系统")
r.bold = True
r.font.size = Pt(11)
r.font.color.rgb = BLUE
p.paragraph_format.space_after = Pt(2)

p = doc.add_paragraph()
r = p.add_run("近期优化与验收报告")
r.bold = True
r.font.size = Pt(24)
r.font.color.rgb = INK
p.paragraph_format.space_after = Pt(4)

p = doc.add_paragraph("2026-11-12 · 项目验收与后续排期使用")
p.runs[0].font.color.rgb = MUTED
p.paragraph_format.space_after = Pt(14)

doc.add_heading("一、结论摘要", level=1)
doc.add_paragraph(
    "长期目标、短期目标、本课目标、视频证据、测量与课程评价已经形成可走通的闭环。"
    "5 名学生的验收数据已完成目标确认、负责人验收、15 条测量复核和课程总览计算；"
    "标准课堂视频可以在不输入人数的情况下自动筛出 3 名学生。"
)
doc.add_paragraph(
    "当前版本适合继续做校内试用和内容验收，但仍有四项边界没有完成："
    "5 人以上不输入人数的全自动筛选、真实学校手写件 OCR、独立角色账号、生产级队列与灾备演练。"
    "这些边界在文末单独列出，不与已完成能力混写。"
)

doc.add_heading("二、关键验收数据", level=1)
table(doc, ["指标", "当前结果", "说明"], [
    ["标准视频自动筛选", "3/3", "不输入人数、不画框，自动保留 3 名学生"],
    ["5 人水果课堂", "5/5", "输入 5 人可自动 5/5；正式留档使用教师确认的 5 个座位"],
    ["目标草案确认", "5/5", "5 名学生均已确认短期目标"],
    ["负责人验收", "5/5", "均已写入验收时间"],
    ["测量复核", "15/15", "5 名学生 × 3 条本课目标"],
    ["课程总览", "71.7 / 良好", "课程评价 78 × 60% + 短期目标达成 62.2 × 40%"],
    ["IEP 摘要", "77 条", "真实 IEP 解析；上限从 40 提到 80"],
    ["扫描 PDF OCR", "parsed_with_ocr", "本地与云端均可"],
    ["跨页扫描", "2 页", "摘要按页保留来源"],
    ["手写模拟 OCR", "通过", "倾斜、噪点模拟样本；真实手写未验证"],
    ["并发冒烟", "50 并发 / 200 请求", "全部 200"],
    ["备份恢复", "52 表 / 5 账号", "本机异地副本恢复校验通过"],
], widths=[4.2, 4.3, 8.2])

doc.add_heading("三、已验证功能", level=1)

doc.add_heading("1. 长期/短期目标工作台", level=2)
for text in [
    "内置生活语文低年级、生活数学第一学段课标目标，可从课标生成长期目标。",
    "长期目标可拆成 3 条短期目标，并逐条修改通过标准、证据、支持方式。",
    "短期目标可关联本课 G-01/G-02/G-03，进入学生证据链。",
    "支持教师确认与产品负责人验收；长期观测页直接显示长期/短期目标和关联结果。",
    "生成结果定位为规则草案，页面和报告均写明不能替代正式 IEP。",
]:
    bullet(doc, text)

doc.add_heading("2. 统一证据链", level=2)
for text in [
    "学生证据链页展示：长期目标 → 短期目标 → 本课目标 → 测量 → 视频证据 → 课程结论。",
    "5 名学生均有已确认目标、本课映射和已复核测量；缺失目标或测量不会按 0 分补齐。",
    "课程总览已正式改用短期目标达成均值；覆盖不完整时保留原口径并提示缺口。",
    "支持导出单名学生一页 Word 报告，报告包含目标链、阶段日期、结论和边界说明。",
]:
    bullet(doc, text)

doc.add_heading("3. OCR 与文档", level=2)
for text in [
    "扫描 PDF 走 RapidOCR，本地和云端均已安装并验证。",
    "两页跨页扫描能保留页码，摘要条目能回到对应页。",
    "手写模拟 PDF 能识别长期目标、短期目标、支持方式、注意事项。",
    "IEP 摘要上限从 40 条提高到 80 条，真实 IEP 实测 77 条不再截断。",
]:
    bullet(doc, text)

doc.add_heading("4. 阶段复测与提醒", level=2)
for text in [
    "从目标确认日期起算 1/2/4/8 周；学生页显示到期状态、窗口内记录数和均分。",
    "首页和目标页均有到期提醒；有跨课堂趋势展示。",
    "云端已安装每日 08:00 检查任务，可配置 webhook 推送；未配置时安全退出。",
    "模拟 webhook 已收到 18 个到期阶段。",
]:
    bullet(doc, text)

doc.add_heading("5. 分享、备份与运行检查", level=2)
for text in [
    "报告链接区分家长/管理者角色标签，24 小时有效，无需登录，可撤销。",
    "云端每日备份，本机保留异地副本；恢复校验通过。",
    "队列健康检查可直接看到待处理、处理中、完成和失败数量，当前 failed 为 0。",
    "安全响应头、安全检查、50 并发冒烟均已通过。",
]:
    bullet(doc, text)

doc.add_heading("四、当前边界与风险", level=1)
table(doc, ["边界", "现状", "影响"], [
    ["5 人以上不输入人数全自动", "未完成；现有输入人数自动筛选与教师确认座位", "大班仍建议教师核对座位，不能宣传为全自动"],
    ["真实学校手写件", "未验证；只验证了模拟手写", "正式使用前需用真实样本复测"],
    ["独立角色账号", "未完成；当前是家长/管理者链接标签", "不能按账号控制查看范围与撤销权限"],
    ["生产级队列/灾备演练", "部分完成；有队列健康、备份、异地副本、恢复校验", "尚未做完整压力、故障切换和恢复演练"],
], widths=[4.5, 6.2, 6.0])

doc.add_heading("五、建议的下一步", level=1)
for text in [
    "用学校真实 IEP 扫描件和手写件做一轮 OCR 验收，记录识别率与人工修正量。",
    "先在一个班级完成 5 人以上课堂的座位确认流程，再决定是否继续做全自动。",
    "把家长/管理者链接升级为独立只读账号，明确查看范围和撤销流程。",
    "确定生产压测目标、备份保留周期和恢复演练时间。",
]:
    bullet(doc, text)

doc.add_paragraph()
p = doc.add_paragraph("本报告只陈述已在本地测试、代码提交和云端部署中验证过的结果；"
                      "未完成的边界没有以“已支持”表述。")
p.paragraph_format.space_before = Pt(8)
for r in p.runs:
    r.font.size = Pt(9)
    r.font.color.rgb = MUTED

doc.save(OUT)
print(OUT)
