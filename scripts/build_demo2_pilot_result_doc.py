from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_ALIGN_VERTICAL, WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Inches, Pt, RGBColor
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "辅读学校课堂分析平台_四账号上传与落地实施结果方案_20260907.docx"
SCREENSHOTS = ROOT / "output" / "playwright"

BLUE = "1E5AA8"
BLUE_DARK = "143A66"
BLUE_LIGHT = "EAF3FF"
BLUE_PALE = "F5F9FF"
INK = "172033"
MUTED = "5D6B7E"
LINE = "C9D9EC"
WHITE = "FFFFFF"
GREEN = "1F7A5A"
AMBER = "9A6200"


def set_cell_shading(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shading = tc_pr.find(qn("w:shd"))
    if shading is None:
        shading = OxmlElement("w:shd")
        tc_pr.append(shading)
    shading.set(qn("w:fill"), fill)


def set_cell_border(cell, color: str = LINE, size: str = "6") -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    borders = tc_pr.first_child_found_in("w:tcBorders")
    if borders is None:
        borders = OxmlElement("w:tcBorders")
        tc_pr.append(borders)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        tag = f"w:{edge}"
        node = borders.find(qn(tag))
        if node is None:
            node = OxmlElement(tag)
            borders.append(node)
        node.set(qn("w:val"), "single")
        node.set(qn("w:sz"), size)
        node.set(qn("w:color"), color)


def set_cell_margin(cell, top: int = 90, start: int = 110, bottom: int = 90, end: int = 110) -> None:
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    tc_mar = tc_pr.first_child_found_in("w:tcMar")
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.append(tc_mar)
    for name, value in (("top", top), ("start", start), ("bottom", bottom), ("end", end)):
        node = tc_mar.find(qn(f"w:{name}"))
        if node is None:
            node = OxmlElement(f"w:{name}")
            tc_mar.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def set_repeat_table_header(row) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    tbl_header = OxmlElement("w:tblHeader")
    tbl_header.set(qn("w:val"), "true")
    tr_pr.append(tbl_header)


def set_keep_with_next(paragraph, value: bool = True) -> None:
    paragraph.paragraph_format.keep_with_next = value


def style_run(run, *, size: float | None = None, bold: bool | None = None, color: str | None = None) -> None:
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold
    if color:
        run.font.color.rgb = RGBColor.from_string(color)
    run.font.name = "Aptos"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")


def add_text(doc: Document, text: str, *, bold_prefix: str = "", color: str = INK, space_after: int = 5):
    paragraph = doc.add_paragraph()
    paragraph.paragraph_format.space_after = Pt(space_after)
    paragraph.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
    if bold_prefix and text.startswith(bold_prefix):
        first = paragraph.add_run(bold_prefix)
        style_run(first, size=10, bold=True, color=BLUE_DARK)
        rest = paragraph.add_run(text[len(bold_prefix) :])
        style_run(rest, size=10, color=color)
    else:
        run = paragraph.add_run(text)
        style_run(run, size=10, color=color)
    return paragraph


def add_bullet(doc: Document, text: str) -> None:
    paragraph = doc.add_paragraph(style="List Bullet")
    paragraph.paragraph_format.left_indent = Cm(0.55)
    paragraph.paragraph_format.first_line_indent = Cm(-0.25)
    paragraph.paragraph_format.space_after = Pt(3)
    style_run(paragraph.add_run(text), size=9.5, color=INK)


def add_number(doc: Document, text: str) -> None:
    paragraph = doc.add_paragraph(style="List Number")
    paragraph.paragraph_format.left_indent = Cm(0.65)
    paragraph.paragraph_format.first_line_indent = Cm(-0.3)
    paragraph.paragraph_format.space_after = Pt(3)
    style_run(paragraph.add_run(text), size=9.5, color=INK)


def add_heading(doc: Document, text: str, level: int = 1) -> None:
    paragraph = doc.add_paragraph()
    paragraph.style = doc.styles[f"Heading {level}"]
    paragraph.paragraph_format.space_before = Pt(10 if level == 1 else 7)
    paragraph.paragraph_format.space_after = Pt(5)
    set_keep_with_next(paragraph)
    run = paragraph.add_run(text)
    style_run(run, size=15 if level == 1 else 11.5, bold=True, color=INK if level == 1 else BLUE_DARK)


def add_badge_table(doc: Document, entries: list[tuple[str, str, str]]) -> None:
    table = doc.add_table(rows=1, cols=len(entries))
    table.autofit = False
    usable = 17.1 / len(entries)
    for index, (label, value, color) in enumerate(entries):
        cell = table.cell(0, index)
        cell.width = Cm(usable)
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        set_cell_shading(cell, BLUE_PALE)
        set_cell_border(cell, LINE)
        set_cell_margin(cell, 120, 120, 120, 120)
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_after = Pt(0)
        style_run(p.add_run(value + "\n"), size=16, bold=True, color=color)
        style_run(p.add_run(label), size=8.5, color=MUTED)
    doc.add_paragraph().paragraph_format.space_after = Pt(1)


def add_table(doc: Document, headers: list[str], rows: list[list[str]], widths: list[float] | None = None) -> None:
    table = doc.add_table(rows=1, cols=len(headers))
    table.autofit = False
    set_repeat_table_header(table.rows[0])
    for index, header in enumerate(headers):
        cell = table.rows[0].cells[index]
        if widths:
            cell.width = Cm(widths[index])
        set_cell_shading(cell, BLUE)
        set_cell_border(cell, BLUE)
        set_cell_margin(cell)
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        p = cell.paragraphs[0]
        p.paragraph_format.space_after = Pt(0)
        style_run(p.add_run(header), size=8.8, bold=True, color=WHITE)
    for row_index, values in enumerate(rows):
        cells = table.add_row().cells
        for index, value in enumerate(values):
            cell = cells[index]
            if widths:
                cell.width = Cm(widths[index])
            set_cell_shading(cell, WHITE if row_index % 2 == 0 else BLUE_PALE)
            set_cell_border(cell)
            set_cell_margin(cell)
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            p = cell.paragraphs[0]
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.keep_together = True
            style_run(p.add_run(str(value)), size=8.6, color=INK)
    doc.add_paragraph().paragraph_format.space_after = Pt(1)


def add_callout(doc: Document, title: str, body: str, *, accent: str = BLUE) -> None:
    table = doc.add_table(rows=1, cols=1)
    cell = table.cell(0, 0)
    set_cell_shading(cell, BLUE_PALE)
    set_cell_border(cell, accent, "9")
    set_cell_margin(cell, 130, 150, 130, 150)
    p = cell.paragraphs[0]
    p.paragraph_format.space_after = Pt(1)
    style_run(p.add_run(title + "\n"), size=10, bold=True, color=accent)
    style_run(p.add_run(body), size=9.2, color=INK)
    doc.add_paragraph().paragraph_format.space_after = Pt(1)


def add_figure(
    doc: Document,
    filename: str,
    caption: str,
    description: str,
    *,
    max_height: float = 6.1,
) -> None:
    path = SCREENSHOTS / filename
    if not path.is_file():
        raise FileNotFoundError(path)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.keep_together = True
    with Image.open(path) as source:
        width_px, height_px = source.size
    width_inches = 6.45
    height_inches = width_inches * height_px / width_px
    if height_inches > max_height:
        picture = p.add_run().add_picture(str(path), height=Inches(max_height))
    else:
        picture = p.add_run().add_picture(str(path), width=Inches(width_inches))
    picture._inline.docPr.set("title", caption)
    picture._inline.docPr.set("descr", description)
    caption_p = doc.add_paragraph()
    caption_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    caption_p.paragraph_format.space_after = Pt(3)
    style_run(caption_p.add_run(caption), size=8.5, bold=True, color=BLUE_DARK)
    add_callout(doc, "页面说明", description)


def new_page(doc: Document) -> None:
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)


def configure_document(doc: Document) -> None:
    section = doc.sections[0]
    section.page_width = Cm(21.0)
    section.page_height = Cm(29.7)
    section.top_margin = Cm(1.7)
    section.bottom_margin = Cm(1.55)
    section.left_margin = Cm(1.8)
    section.right_margin = Cm(1.8)

    normal = doc.styles["Normal"]
    normal.font.name = "Aptos"
    normal.font.size = Pt(10)
    normal.font.color.rgb = RGBColor.from_string(INK)
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
    normal.paragraph_format.line_spacing = 1.15
    normal.paragraph_format.space_after = Pt(5)

    for level in (1, 2, 3):
        style = doc.styles[f"Heading {level}"]
        style.font.name = "Aptos Display"
        style._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
        style.font.bold = True
        style.font.color.rgb = RGBColor.from_string(INK if level == 1 else BLUE_DARK)

    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    style_run(
        footer.add_run("RehabAffectPerception  |  辅读学校课堂分析平台内测方案  |  2026-09-07"),
        size=8,
        color=MUTED,
    )


def build() -> None:
    doc = Document()
    configure_document(doc)
    props = doc.core_properties
    props.title = "辅读学校课堂分析平台四账号上传与落地实施结果方案"
    props.subject = "学校内测软件平台、四路视频上传、数据存储与正式部署"
    props.author = "RehabAffectPerception 项目组"

    cover = doc.add_table(rows=1, cols=1)
    cell = cover.cell(0, 0)
    set_cell_shading(cell, BLUE)
    set_cell_border(cell, BLUE)
    set_cell_margin(cell, 520, 380, 520, 380)
    p = cell.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    p.paragraph_format.space_after = Pt(7)
    style_run(p.add_run("辅读学校课堂分析平台\n"), size=25, bold=True, color=WHITE)
    style_run(p.add_run("四账号视频上传与落地实施结果方案"), size=18, bold=True, color=WHITE)
    p2 = cell.add_paragraph()
    p2.paragraph_format.space_before = Pt(16)
    style_run(p2.add_run("学校内测软件平台  ·  Demo2  ·  2026-09-07"), size=10.5, color="D8E9FF")

    doc.add_paragraph().paragraph_format.space_after = Pt(10)
    add_callout(
        doc,
        "本阶段结论",
        "当前已经形成一套可登录、可按账号隔离上传、可显示任务进度、可保存结果、可由公司后台集中查看，并可进入课堂学习分析页面的本地内测软件平台。它可用于公司演示、学校需求确认和受控试点；当前地址不是公网网站。",
        accent=GREEN,
    )
    add_badge_table(
        doc,
        [
            ("学校上传账号", "4 个", BLUE),
            ("每账号每课程", "5 段", BLUE),
            ("课程合计容量", "20 段", GREEN),
            ("学校产品测试", "52 项", GREEN),
        ],
    )
    add_heading(doc, "核心回答", 1)
    add_bullet(doc, "127.0.0.1:8791 是本机程序监听的测试地址和网络端口，只能在运行程序的电脑访问，不是已上线网址。")
    add_bullet(doc, "“四个上传端口”在本方案中实现为四个业务上传通道，由四个内测账号分别使用，不需要四个域名或四台服务器。")
    add_bullet(doc, "账号、上传、后台功能不需要先购买域名即可开发和现场测试；异地联网使用时才进入云服务器、域名、HTTPS 和备案阶段。")
    add_bullet(doc, "上传中断后可取消未完成任务，临时分片会被清理并立即归还名额；原始视频到期后由后台任务自动删除，结构化结果和审计记录继续保留。")
    add_bullet(doc, "当前上传后自动生成完整性和视频质量预检；任意新视频的课堂状态、掌握度和教师效果自动分析仍需接入模型工作节点并用教师标注验证。")

    new_page(doc)
    add_heading(doc, "一、产品定位与使用对象", 1)
    add_text(doc, "平台面向辅读学校课堂中的学生学习支持与长期追踪。系统将课程目标、学生档案、IEP、课堂视频、声音、教师复核和分析报告关联到同一课程批次，帮助学校从一节课的录像中整理可复核的学习证据，而不是只给出“专注或不专注”的单一标签。")
    add_table(
        doc,
        ["使用对象", "主要任务", "系统提供"],
        [
            ["学校上传人员", "按课程与学生提交课堂视频", "独立账号、固定通道、5 段名额、上传进度和结果下载"],
            ["任课教师/特教教师", "核对关键片段与学习表现", "课程目标、状态时间线、正确性、提示等级、师生互动链和复核记录"],
            ["公司管理员", "查看平台运行和数据保存情况", "四通道汇总、任务状态、存储占用、授权记录和到期规则"],
            ["后续模型与硬件", "消费结构化分析结果", "标准 JSON、屏幕提示、语音提示或机器人低刺激动作建议"],
        ],
        [3.0, 5.1, 9.0],
    )
    add_heading(doc, "二、页面与数据流程", 1)
    add_table(
        doc,
        ["步骤", "页面", "关键动作", "产生的数据"],
        [
            ["01", "登录页", "使用项目方发放的内测账号登录", "账号、角色、绑定通道、8 小时会话"],
            ["02", "上传工作台", "填写课程、选择学生和视频、确认安全协议", "课程批次、授权范围、视频任务"],
            ["03", "上传处理", "浏览器按 4MB 分片上传；中断可取消", "进度、文件哈希、预检结果、到期时间、名额释放"],
            ["04", "课堂分析页", "查看群像、个体、时间切片并由教师复核", "状态证据、掌握度、师生互动和报告"],
            ["05", "公司后台", "查看四个通道、名额、任务和保存期", "运营汇总、近期上传、审计和提醒"],
        ],
        [1.2, 3.1, 6.1, 6.7],
    )
    add_callout(
        doc,
        "账号策略",
        "当前不开放公众自主注册。由项目方创建 4 个学校内测账号并分别交付账号密码，减少未知人员进入平台的风险；正式版再增加管理员开通、密码重置和学校组织管理。",
    )

    new_page(doc)
    add_heading(doc, "三、登录入口", 1)
    add_figure(
        doc,
        "demo2_portal_login_release.png",
        "图 1  学校内测平台登录页",
        "学校人员通过公司预置账号进入。页面说明当前为受控内测、不开公众注册，并提示原始课堂视频和学生资料的处理边界。学校上传账号登录后进入上传工作台，公司管理员登录后进入后台。",
    )
    add_table(
        doc,
        ["账号类型", "数量", "绑定范围", "允许操作"],
        [
            ["学校上传账号", "4", "各绑定 channel_1 至 channel_4 中的一个", "只查看和使用自己的视频通道；进入课堂分析"],
            ["公司管理员", "1", "查看四个通道汇总", "查看账号、任务、课程名额、存储和到期信息；不能上传视频分片"],
        ],
        [3.2, 1.5, 5.2, 7.1],
    )

    new_page(doc)
    add_heading(doc, "四、学校上传工作台", 1)
    add_figure(
        doc,
        "demo2_portal_upload_release_desktop.png",
        "图 2  单账号视频上传工作台",
        "当前账号只看到自己的绑定通道。课程批次号用于计算本课程的独立名额，课程名称写入任务记录；可选择具体学生或群像。课程批次改变后要重新读取工作区。上传前必须确认 60 天处理授权，长期资源授权为单独可选项。",
        max_height=4.45,
    )
    add_table(
        doc,
        ["输入项", "是否必填", "用途"],
        [
            ["课程批次号", "是", "唯一标识一节课或一次课程批次，并据此统计 5 段名额"],
            ["课程名称", "是", "写入任务、后台和结果文件，便于学校查找"],
            ["学生选择", "建议", "关联个体学生；无法确认时可选群像/暂不绑定"],
            ["课堂视频", "是", "支持 MP4、MOV、AVI、MKV、WebM；当前单文件上限 5GB"],
            ["安全协议确认", "是", "确认处理目的、保存 60 天和到期处置"],
            ["长期归档授权", "否", "仅授权脱敏结构化结果进入公司长期资源库，不含原视频"],
        ],
        [3.4, 2.2, 11.5],
    )

    new_page(doc)
    add_heading(doc, "五、公司数据后台", 1)
    add_figure(
        doc,
        "demo2_portal_admin_release_view.png",
        "图 3  公司管理员四通道数据后台",
        "后台汇总真实数据库记录，显示 4 个学校账号、4 个上传通道、课程配额、任务状态、文件占用、近期上传、60 天保存期限和自动清理状态。普通学校账号不能进入该页面；接口响应不返回服务器物理文件路径。",
        max_height=5.8,
    )
    add_badge_table(
        doc,
        [
            ("原始视频保留", "60 天", BLUE),
            ("到期预警", "提前 15 天", AMBER),
            ("通道状态", "集中查看", GREEN),
            ("结果文件", "授权下载", BLUE),
        ],
    )

    new_page(doc)
    add_heading(doc, "六、课堂学习分析", 1)
    add_figure(
        doc,
        "demo2_analysis_overview_final.png",
        "图 4  原 Demo2 课堂分析能力保留页",
        "上传平台没有替代原分析功能。学校可继续查看课程标准、三名学生群像与个体状态、时间切片、学习掌握度、师生互动、教师复核、学生档案、IEP/支持资料和千字课程报告。关键判断仍需教师确认，不做医学诊断或自动教师绩效结论。",
    )
    add_table(
        doc,
        ["分析维度", "系统整理内容", "教师需要确认"],
        [
            ["课程目标", "教学目标、校方考核标准、任务机会", "本节课标准和目标是否正确"],
            ["视觉状态", "头部朝向、姿态变化、动作活跃度和可见性", "画面是否足以支持判断，是否有画外原因"],
            ["声音与互动", "教师指令、学生回应、时间对齐和说话归属", "语音归属、回答含义和提示方式"],
            ["学习掌握", "正确性、独立程度、一致性、迁移表现", "是否正确、用了几级提示、未观察是否应排除"],
            ["教师支持效果", "学生表现 -> 教师调整 -> 学生后续变化", "关联是否真实，不用于简单排名或惩罚"],
        ],
        [3.0, 7.2, 6.9],
    )

    new_page(doc)
    add_heading(doc, "七、输入、处理与输出边界", 1)
    add_table(
        doc,
        ["层级", "当前输入", "当前输出", "状态"],
        [
            ["账号与课程", "账号密码、课程批次号、课程名称、学生", "角色、绑定通道、课程剩余名额", "已实现"],
            ["文件上传", "课堂视频与安全确认", "分片进度、任务 ID、哈希、到期时间", "已实现"],
            ["任务取消", "上传中断的未完成任务", "删除临时分片、记录审计、归还名额", "已实现"],
            ["自动预检", "已完整上传的视频", "可读性、分辨率、时长、亮度/清晰度等基础质量结果", "已实现"],
            ["到期处置", "超过 60 天的原始视频", "删除原视频，保留结构化结果和审计记录", "已实现后台定时执行"],
            ["课堂分析展示", "预先整理的课程、学生、切片和复核样例", "状态、掌握度、互动链、动作建议和报告", "已实现演示"],
            ["新视频全自动分析", "任意新上传视频和声音", "人物追踪、状态时序、掌握度和教师支持效果", "待接模型 worker 与真实验证"],
            ["学校规模化", "多个学校、班级、教师和学生", "租户隔离、组织权限、批量报表和运维监控", "待正式产品化"],
        ],
        [2.6, 4.5, 6.8, 3.2],
    )
    add_callout(
        doc,
        "展示时必须如实说明",
        "当前视频上传后的自动结果是上传完整性和画面质量预检，不应把样例课堂分析结果说成系统已经对任意新视频完成准确识别。下一阶段需要将上传任务接入异步模型工作节点，并用教师复核数据计算准确率、召回率和一致性。",
        accent=AMBER,
    )
    add_heading(doc, "八、本地数据保存设计", 1)
    add_bullet(doc, "结构化数据：当前由 SQLite 保存账号、会话、课程、任务、授权、保存期和审计记录。")
    add_bullet(doc, "文件数据：当前保存在本机受控目录，数据库仅记录元数据；前端和 API 不返回真实磁盘路径。")
    add_bullet(doc, "原始视频：默认 60 天，到期前 15 天进入提醒；服务启动时立即检查，之后默认每小时扫描，到期删除原视频并写入审计。")
    add_bullet(doc, "资源访问：课程展示图片通过白名单读取；数据库、JSON、原视频和报告不能经静态资源路径直接访问。")
    add_bullet(doc, "长期资源：只有另行授权的脱敏结构化结果可以进入公司长期资源队列，原始课堂视频不自动长期保留。")

    new_page(doc)
    add_heading(doc, "九、三种落地方式", 1)
    add_table(
        doc,
        ["方式", "访问范围", "是否需要域名", "适用阶段", "主要条件"],
        [
            ["本机测试", "仅运行程序的电脑", "不需要", "当前演示", "Windows、Python 环境、浏览器；地址为 127.0.0.1:8791"],
            ["校内局域网", "同一校园网络内设备", "不需要", "现场受控试点", "固定主机、局域网 IP、防火墙放行、校内账号管理"],
            ["云端内测", "学校可异地访问", "建议使用", "多地点试用", "云服务器、HTTPS、数据库、对象存储、备份和监控"],
            ["正式公网", "经授权的学校用户", "需要稳定域名", "产品上线", "租户隔离、备案/合规确认、密码重置、审计、容灾和运维"],
        ],
        [2.5, 3.4, 2.7, 3.1, 5.4],
    )
    add_text(doc, "域名与账号功能的关系：登录和账号系统可以先在本地完成，域名不是开发登录页的前置条件。域名解决的是跨地点访问、HTTPS 证书和稳定入口问题。使用中国境内服务器向公众提供互联网信息服务时，应由公司结合部署方式向云接入商及主管部门确认备案要求。")
    add_heading(doc, "十、当前运行与正式部署条件", 1)
    add_table(
        doc,
        ["项目", "当前演示", "校内试点建议", "正式云端建议"],
        [
            ["上传端", "普通办公电脑 + Chrome/Edge", "i5/R5、16GB 内存、稳定有线网络", "浏览器访问，无需安装客户端"],
            ["服务端", "开发电脑运行 Python 服务", "独立主机 8 核、32GB、1TB", "容器化 API 服务，按并发扩容"],
            ["数据库", "SQLite", "SQLite 或受控 PostgreSQL", "PostgreSQL 主备与自动备份"],
            ["视频存储", "本机目录", "受控磁盘/NAS", "对象存储、生命周期策略和访问签名"],
            ["模型算力", "上传预检以 CPU 为主", "批处理可使用 12GB 以上 GPU", "异步 GPU worker，按视频量弹性启停"],
            ["采集硬件", "可使用学校导出视频", "固定机位 1080P 摄像头和可辨认课堂声音", "可选边缘盒、摄像头或硬件插件"],
        ],
        [2.6, 4.5, 4.7, 5.3],
    )

    new_page(doc)
    add_heading(doc, "十一、正式产品化的数据对象", 1)
    add_table(
        doc,
        ["对象", "必须关联的内容", "权限原则"],
        [
            ["学校/租户", "学校、校区、数据策略", "不同学校数据严格隔离"],
            ["账号/角色", "教师、上传员、校方管理员、公司运维", "最小权限与操作审计"],
            ["课程批次", "课程标准、教案、考核要求、时间", "作为视频与报告的主索引"],
            ["学生档案", "基本资料、IEP、五大领域评估、支持策略", "按班级与授权范围访问"],
            ["视频任务", "上传账号、通道、课程、学生、文件和保存期", "上传者只看所属任务"],
            ["教师复核", "关键片段、真实性、正确性、提示等级和备注", "保留修改人、时间和版本"],
            ["分析报告", "课堂状态、掌握度、互动链、趋势与建议", "结果可下载、可追溯、可撤回"],
        ],
        [3.0, 7.4, 6.7],
    )
    add_heading(doc, "十二、建议实施顺序", 1)
    for text in (
        "用当前本地版本完成公司演示和学校操作确认，确定四个上传账号分别由谁使用。",
        "选择一个班级和少量课程做局域网或单机试点，验证真实视频大小、清晰度、声音和上传时长。",
        "接入异步分析 worker，将人物追踪、姿态、语音、课堂活动和时间序列结果写回任务。",
        "让特教教师只复核系统筛出的关键片段，形成准确率评估和可继续训练的数据集。",
        "再部署云端内测，增加学校租户、班级权限、对象存储、到期通知、备份与监控。",
        "硬件插件在软件闭环稳定后接入，优先采用标准 HTTP/WebSocket 接口，不让硬件型号锁死平台。",
    ):
        add_number(doc, text)

    new_page(doc)
    add_heading(doc, "十三、验收结果与剩余风险", 1)
    add_table(
        doc,
        ["验收项", "结果", "说明"],
        [
            ["学校产品自动测试", "52 项通过", "账号、会话、配额、上传、取消、下载、后台、资源访问、到期清理和原分析功能"],
            ["真实 HTTP 验证", "通过", "未登录拦截、通道过滤、越权拒绝、安全确认无副作用、管理员汇总"],
            ["桌面浏览器", "通过", "登录、上传、后台和课堂分析页面可访问"],
            ["390px 移动端", "通过", "上传页无横向溢出，账号、通道和主要操作完整显示"],
            ["多学校公网生产", "尚未完成", "缺少 tenant_id、多租户权限、正式云资源、HTTPS 与运维体系"],
            ["真实模型准确率", "尚未验证", "需要真实课程、教师标注、独立测试集和持续评估"],
            ["上传中断处理", "通过", "可取消未完成任务、删除临时分片并归还名额；跨会话断点恢复仍待增强"],
            ["静态资源边界", "通过", "课程图片按白名单读取；数据库、JSON、原视频和报告路径已阻断"],
            ["到期自动清理", "通过", "已执行 60/15 天规则、定时扫描、原视频删除、结果保留和审计记录"],
            ["公网账号安全", "尚未完成", "默认密码仅供本地演示；公网前需强密码、首次改密、限流、重置、HTTPS 与 CSRF 防护"],
        ],
        [4.0, 2.8, 10.3],
    )
    add_callout(
        doc,
        "当前可交付级别",
        "可以作为学校汇报、操作确认和受控单校软件试点版本交付，不应宣称为已经通过真实准确率验证、可直接覆盖全校、多学校隔离或可公开注册使用的正式生产系统。",
        accent=GREEN,
    )
    add_heading(doc, "十四、依据与说明", 1)
    add_text(doc, "1. 工业和信息化部《非经营性互联网信息服务备案管理办法》：https://www.miit.gov.cn/gyhxxhb/jgsj/cyzcyfgs/bmgz/xxtxl/art/2024/art_84a0cfa0ebd049bbbe751dca9a008e56.html", color=MUTED)
    add_text(doc, "2. 国家互联网信息办公室《中华人民共和国个人信息保护法》：https://www.cac.gov.cn/2021-08/20/c_1631050028355286.htm", color=MUTED)
    add_text(doc, "本方案用于产品与技术实施规划，不替代公司法务、学校主管部门或云服务接入商给出的正式合规意见。", color=MUTED)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUTPUT)
    print(OUTPUT)


if __name__ == "__main__":
    build()
