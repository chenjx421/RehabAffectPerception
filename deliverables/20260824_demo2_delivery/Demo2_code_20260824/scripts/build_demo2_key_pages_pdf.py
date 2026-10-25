from pathlib import Path

from PIL import Image
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


ROOT = Path(r"D:\GIT\RehabAffectPerception")
SCREEN_DIR = ROOT / "output" / "playwright" / "demo2_doc_20260814"
ASSET_DIR = ROOT / "tmp" / "pdfs" / "demo2_key_pages_assets"
OUTPUT_DIR = ROOT / "output" / "pdf"
OUTPUT_PDF = OUTPUT_DIR / "Demo2_重点页面图文说明_20260817.pdf"

PAGE_W, PAGE_H = landscape(A4)
MARGIN = 30

FONT_SANS = "NotoSansSC"
FONT_SERIF = "NotoSerifSC"

BG = HexColor("#F4F7F4")
PAPER = HexColor("#FFFFFF")
INK = HexColor("#153A34")
BODY = HexColor("#314E49")
MUTED = HexColor("#6A7E79")
TEAL = HexColor("#118A7E")
TEAL_SOFT = HexColor("#E8F3EF")
BLUE = HexColor("#315EAE")
BLUE_SOFT = HexColor("#EDF2FB")
ORANGE = HexColor("#D9603D")
ORANGE_SOFT = HexColor("#FFF0E8")
BORDER = HexColor("#D7E0DD")
DARK = HexColor("#17322E")


def register_fonts():
    pdfmetrics.registerFont(TTFont(FONT_SANS, r"C:\Windows\Fonts\NotoSansSC-VF.ttf"))
    pdfmetrics.registerFont(TTFont(FONT_SERIF, r"C:\Windows\Fonts\NotoSerifSC-VF.ttf"))


def crop_image(source: Path, name: str, box):
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    target = ASSET_DIR / name
    with Image.open(source) as image:
        image.crop(box).save(target, quality=95)
    return target


def wrap_text(text, font_name, font_size, max_width):
    lines = []
    current = ""
    for char in text:
        candidate = current + char
        if not current or pdfmetrics.stringWidth(candidate, font_name, font_size) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = char
    if current:
        lines.append(current)
    return lines


def draw_text_block(c, text, x, y, width, font_size=10.2, leading=15, color=BODY, max_lines=None):
    c.setFont(FONT_SANS, font_size)
    c.setFillColor(color)
    lines = []
    for paragraph in text.split("\n"):
        if not paragraph:
            lines.append("")
        else:
            lines.extend(wrap_text(paragraph, FONT_SANS, font_size, width))
    if max_lines is not None:
        lines = lines[:max_lines]
    for line in lines:
        c.drawString(x, y, line)
        y -= leading
    return y


def draw_bullet(c, title, text, x, y, width, color=TEAL):
    c.setFillColor(color)
    c.roundRect(x, y - 4, 5, 5, 1.5, fill=1, stroke=0)
    c.setFillColor(INK)
    c.setFont(FONT_SANS, 10.4)
    c.drawString(x + 13, y, title)
    y -= 17
    return draw_text_block(c, text, x + 13, y, width - 13, font_size=9.4, leading=14, color=BODY)


def draw_image_fit(c, image_path, x, y, width, height, padding=4):
    c.setFillColor(HexColor("#DCE5E2"))
    c.roundRect(x + 3, y - 3, width, height, 5, fill=1, stroke=0)
    c.setFillColor(PAPER)
    c.setStrokeColor(BORDER)
    c.roundRect(x, y, width, height, 5, fill=1, stroke=1)

    with Image.open(image_path) as image:
        iw, ih = image.size
    usable_w = width - 2 * padding
    usable_h = height - 2 * padding
    scale = min(usable_w / iw, usable_h / ih)
    draw_w = iw * scale
    draw_h = ih * scale
    draw_x = x + (width - draw_w) / 2
    draw_y = y + (height - draw_h) / 2
    c.drawImage(str(image_path), draw_x, draw_y, draw_w, draw_h, preserveAspectRatio=True, mask="auto")


def draw_page_header(c, index, kicker, title, subtitle):
    c.setFillColor(BG)
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)

    c.setFillColor(TEAL)
    c.setFont(FONT_SANS, 8.5)
    c.drawString(MARGIN, PAGE_H - 31, kicker.upper())

    c.setFillColor(INK)
    c.setFont(FONT_SERIF, 22)
    c.drawString(MARGIN, PAGE_H - 60, title)

    c.setFillColor(MUTED)
    c.setFont(FONT_SANS, 9.5)
    c.drawString(MARGIN, PAGE_H - 79, subtitle)

    c.setStrokeColor(BORDER)
    c.line(MARGIN, PAGE_H - 91, PAGE_W - MARGIN, PAGE_H - 91)

    c.setFillColor(MUTED)
    c.setFont(FONT_SANS, 8)
    c.drawRightString(PAGE_W - MARGIN, 18, f"RehabAffectPerception  |  Demo2  |  {index}/6")


def draw_info_card(c, x, y, width, title, body, accent=TEAL, fill=TEAL_SOFT):
    lines = []
    for paragraph in body.split("\n"):
        lines.extend(wrap_text(paragraph, FONT_SANS, 9.2, width - 24))
    height = 37 + max(1, len(lines)) * 13
    c.setFillColor(fill)
    c.setStrokeColor(BORDER)
    c.roundRect(x, y - height, width, height, 5, fill=1, stroke=1)
    c.setFillColor(accent)
    c.rect(x, y - height, 4, height, fill=1, stroke=0)
    c.setFillColor(INK)
    c.setFont(FONT_SANS, 10.2)
    c.drawString(x + 13, y - 20, title)
    c.setFillColor(BODY)
    c.setFont(FONT_SANS, 9.2)
    line_y = y - 38
    for line in lines:
        c.drawString(x + 13, line_y, line)
        line_y -= 13
    return y - height - 10


def page_course_baseline(c):
    draw_page_header(
        c,
        1,
        "COURSE BASELINE",
        "课程指标先行，让分析有明确参照",
        "开课前录入课程名称、课程标准和校方考核口径，再进入视频分析。",
    )
    image = SCREEN_DIR / "03_course_setup.png"
    draw_image_fit(c, image, MARGIN, 115, 525, 360)

    x = 580
    y = 475
    y = draw_info_card(
        c, x, y, 232, "分析输入", "课程类型与名称\n官方课程标准\n校方四级表现量表", TEAL, TEAL_SOFT
    )
    y = draw_info_card(
        c, x, y, 232, "评价口径", "4级独立完成，3级提示后完成，2级示范或部分协助，1级尚未表现；证据不足标记为U。", BLUE, BLUE_SOFT
    )
    draw_info_card(
        c, x, y, 232, "关键价值", "系统不是泛化地判断“是否专注”，而是回答：学生是否在本节课的具体目标上出现了可核验的学习表现。", ORANGE, ORANGE_SOFT
    )


def page_group_and_individual(c):
    draw_page_header(
        c,
        2,
        "GROUP AND INDIVIDUAL",
        "同一课堂内，同时查看群像与个体",
        "群像用于定位课堂关系，个体页用于查看可复核证据，不根据外观推断障碍类型。",
    )
    image = SCREEN_DIR / "04_classroom_workbench.png"
    draw_image_fit(c, image, MARGIN, 108, 548, 366)

    x = 603
    y = 470
    y = draw_bullet(c, "三人同步定位", "固定座位区域与校方确认身份，降低低清监控下的错配风险。", x, y, 205, TEAL)
    y -= 7
    y = draw_bullet(c, "群像视角", "看到学生与教师、材料和同伴的空间关系，为互动事件提供课堂语境。", x, y, 205, BLUE)
    y -= 7
    y = draw_bullet(c, "个体证据链", "按学生切换状态、参与度、学习线索、证据质量及下一步支持建议。", x, y, 205, ORANGE)
    y -= 9
    draw_info_card(
        c,
        x,
        y,
        208,
        "适合校方展示的结论",
        "系统将一段全局课堂视频拆成三套独立档案，同时保留班级整体参照。",
        TEAL,
        TEAL_SOFT,
    )


def page_right_evidence(c, right_crop):
    draw_page_header(
        c,
        3,
        "INDIVIDUAL EVIDENCE",
        "右侧个体证据区，把结论拆回可解释指标",
        "每个学生拥有独立页面，教师可从总分回到证据、提示等级和任务表现。",
    )
    draw_image_fit(c, right_crop, MARGIN, 74, 292, 404)

    c.setFillColor(PAPER)
    c.setStrokeColor(BORDER)
    c.roundRect(344, 310, 468, 168, 6, fill=1, stroke=1)
    c.setFillColor(INK)
    c.setFont(FONT_SANS, 12)
    c.drawString(364, 450, "四项学习证据")

    items = [
        ("正确性", "学生的回答或操作是否与课程目标一致。", TEAL),
        ("独立程度", "完成任务时是否依赖语言、视觉或动作提示。", BLUE),
        ("重复一致性", "同类任务在不同时间片中能否稳定复现。", ORANGE),
        ("迁移表现", "能否把本节课学到的内容用于新材料或新情境。", HexColor("#7A5FA6")),
    ]
    for i, (title, body, color) in enumerate(items):
        col = i % 2
        row = i // 2
        x = 364 + col * 220
        y = 414 - row * 66
        c.setFillColor(color)
        c.circle(x + 4, y + 4, 4, fill=1, stroke=0)
        c.setFillColor(INK)
        c.setFont(FONT_SANS, 10.2)
        c.drawString(x + 16, y, title)
        draw_text_block(c, body, x + 16, y - 18, 190, font_size=8.8, leading=12, color=BODY)

    draw_info_card(
        c,
        344,
        285,
        468,
        "系统如何使用这些指标",
        "先给出机器初判，再显示证据质量、置信度和待教师复核项。教师确认后，结果才进入学生档案，并用于下一节课的目标适配与支持建议。",
        TEAL,
        TEAL_SOFT,
    )


def page_timeline(c):
    draw_page_header(
        c,
        4,
        "TIME-SLICE ANALYSIS",
        "30秒时间切片，让课堂变化可追溯",
        "把37分钟课程转成连续状态窗口，并保留视频、语音、任务与教师复核证据。",
    )
    image = SCREEN_DIR / "08_state_timeline.png"
    draw_image_fit(c, image, MARGIN, 105, 553, 370)

    x = 608
    y = 469
    y = draw_bullet(c, "每30秒一个窗口", "记录阶段、状态、置信度、证据质量、风险等级和建议动作。", x, y, 201, TEAL)
    y -= 8
    y = draw_bullet(c, "跨窗口时间平滑", "EMA与滑动窗口减少单帧误判，避免把短暂回头或动作直接等同于分心。", x, y, 201, BLUE)
    y -= 8
    y = draw_bullet(c, "课堂事件对齐", "将教师提问、材料操作、学生回应和语音片段放到同一时间轴。", x, y, 201, ORANGE)
    y -= 10
    draw_info_card(
        c,
        x,
        y,
        204,
        "教师可直接复核",
        "时间段、观察内容、系统判断和提示等级明确列出，老师只需确认、纠正或标记证据不足。",
        TEAL,
        TEAL_SOFT,
    )


def page_course_report(c):
    draw_page_header(
        c,
        5,
        "COURSE-LEVEL REPORT",
        "一节课生成一份约1000字的证据化分析",
        "报告将班级概况、三名学生结果、支持效果和下一课建议合并为校方可阅读材料。",
    )
    image = SCREEN_DIR / "07_course_report.png"
    draw_image_fit(c, image, MARGIN, 105, 560, 370)

    x = 615
    y = 469
    y = draw_bullet(c, "班级整体概况", "总结课堂阶段、参与走势、可复核窗口数和证据完整度。", x, y, 194, TEAL)
    y -= 6
    y = draw_bullet(c, "个体学习结论", "分别说明每名学生当前掌握、可能掌握、待复核与暂未观察到的内容。", x, y, 194, BLUE)
    y -= 6
    y = draw_bullet(c, "支持效果评估", "比较教师提示前后的学生响应，不把学生表现简单转化成教师打分。", x, y, 194, ORANGE)
    y -= 6
    y = draw_bullet(c, "下一课可执行建议", "输出目标拆分、提示方式、材料难度和复核重点。", x, y, 194, TEAL)
    y -= 8
    draw_info_card(
        c,
        x,
        y,
        197,
        "报告边界",
        "报告是教学观察与辅助决策材料，不做医疗诊断；证据不足时明确写出不确定性。",
        ORANGE,
        ORANGE_SOFT,
    )


def draw_flow_node(c, x, y, width, title, subtitle, fill, accent):
    c.setFillColor(fill)
    c.setStrokeColor(BORDER)
    c.roundRect(x, y, width, 60, 6, fill=1, stroke=1)
    c.setFillColor(accent)
    c.setFont(FONT_SANS, 10.2)
    c.drawString(x + 12, y + 37, title)
    c.setFillColor(BODY)
    c.setFont(FONT_SANS, 8.5)
    for index, line in enumerate(wrap_text(subtitle, FONT_SANS, 8.5, width - 24)[:2]):
        c.drawString(x + 12, y + 20 - index * 11, line)


def page_navigation(c, nav_crop, selector_crop):
    draw_page_header(
        c,
        6,
        "NAVIGATION AND REVIEW LOOP",
        "导航围绕证据闭环组织，而不是功能堆叠",
        "课程、学生、证据、复核、支持和档案可以在同一工作台内顺序完成。",
    )

    draw_image_fit(c, nav_crop, MARGIN, 106, 180, 365)
    draw_image_fit(c, selector_crop, 229, 340, 583, 131)

    c.setFillColor(INK)
    c.setFont(FONT_SANS, 11.5)
    c.drawString(229, 315, "从感知到行动建议的闭环")

    nodes = [
        ("课程基线", "录入目标与评价口径", TEAL_SOFT, TEAL),
        ("多模态感知", "视频、语音、任务事件", BLUE_SOFT, BLUE),
        ("状态估计", "时间平滑与证据质量", ORANGE_SOFT, ORANGE),
        ("教师复核", "确认、纠正或标U", TEAL_SOFT, TEAL),
        ("支持输出", "屏幕、语音、机器人动作", BLUE_SOFT, BLUE),
    ]
    start_x = 229
    gap = 9
    node_w = (583 - gap * 4) / 5
    for i, node in enumerate(nodes):
        x = start_x + i * (node_w + gap)
        draw_flow_node(c, x, 225, node_w, *node)
        if i < len(nodes) - 1:
            c.setStrokeColor(MUTED)
            c.setLineWidth(1.1)
            c.line(x + node_w + 2, 255, x + node_w + gap - 2, 255)

    draw_info_card(
        c,
        229,
        201,
        583,
        "页面使用逻辑",
        "顶部课程切换负责确定分析上下文；左侧功能导航依次进入学习判断、时间线、教师复核、支持工具与学生档案；个体证据侧栏随所选学生同步更新。最终输出既能服务教师，也能映射成屏幕提示、语音提示或机器人克制动作。",
        TEAL,
        TEAL_SOFT,
    )


def build_pdf():
    register_fonts()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ASSET_DIR.mkdir(parents=True, exist_ok=True)

    workbench = SCREEN_DIR / "04_classroom_workbench.png"
    report = SCREEN_DIR / "07_course_report.png"
    right_crop = crop_image(workbench, "right_individual_evidence.png", (930, 95, 1384, 777))
    nav_crop = crop_image(report, "left_feature_navigation.png", (18, 385, 250, 777))
    selector_crop = crop_image(report, "top_course_selector.png", (770, 0, 1384, 145))

    c = canvas.Canvas(str(OUTPUT_PDF), pagesize=landscape(A4))
    c.setTitle("Demo2 重点页面图文说明")
    c.setAuthor("RehabAffectPerception")

    page_course_baseline(c)
    c.showPage()
    page_group_and_individual(c)
    c.showPage()
    page_right_evidence(c, right_crop)
    c.showPage()
    page_timeline(c)
    c.showPage()
    page_course_report(c)
    c.showPage()
    page_navigation(c, nav_crop, selector_crop)
    c.save()
    print(OUTPUT_PDF)


if __name__ == "__main__":
    build_pdf()
