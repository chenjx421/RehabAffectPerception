from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph


ROOT = Path(__file__).resolve().parents[1]
SHOT_DIR = ROOT / "output" / "playwright" / "demo2_v15_premium_thousand"
OUTPUT = ROOT / "output" / "pdf" / "RehabAffect_Demo2_逐页图文功能说明_20260827.pdf"
DISPLAY_DATE = "2026.08.27"

PAGE_W, PAGE_H = landscape(A4)

NAVY = colors.HexColor("#173B57")
BLUE = colors.HexColor("#2878D0")
CYAN = colors.HexColor("#49B6D6")
PALE_BLUE = colors.HexColor("#EDF6FD")
PALE_CYAN = colors.HexColor("#EAF8FA")
INK = colors.HexColor("#1C2F3C")
MUTED = colors.HexColor("#607786")
LINE = colors.HexColor("#D8E6EF")
WHITE = colors.white
ORANGE = colors.HexColor("#F2A65A")
GREEN = colors.HexColor("#4A9B80")
RED = colors.HexColor("#C85D5D")


def register_fonts() -> None:
    pdfmetrics.registerFont(TTFont("DemoSans", r"C:\Windows\Fonts\msyh.ttc"))
    pdfmetrics.registerFont(TTFont("DemoSans-Bold", r"C:\Windows\Fonts\msyhbd.ttc"))


register_fonts()


def style(size: float, *, bold: bool = False, color=INK, leading: float | None = None, align=TA_LEFT) -> ParagraphStyle:
    return ParagraphStyle(
        name=f"s-{size}-{bold}-{align}",
        fontName="DemoSans-Bold" if bold else "DemoSans",
        fontSize=size,
        leading=leading or size * 1.55,
        textColor=color,
        alignment=align,
        wordWrap="CJK",
        spaceAfter=0,
        spaceBefore=0,
    )


def paragraph(c: canvas.Canvas, text: str, x: float, y_top: float, width: float, *, size=9, bold=False, color=INK, leading=None, align=TA_LEFT) -> float:
    item = Paragraph(text, style(size, bold=bold, color=color, leading=leading, align=align))
    _, height = item.wrap(width, PAGE_H)
    item.drawOn(c, x, y_top - height)
    return height


def rounded_box(c: canvas.Canvas, x: float, y: float, w: float, h: float, *, fill=WHITE, stroke=LINE, radius=8, line_width=0.8) -> None:
    c.setFillColor(fill)
    c.setStrokeColor(stroke)
    c.setLineWidth(line_width)
    c.roundRect(x, y, w, h, radius, fill=1, stroke=1)


def draw_header(c: canvas.Canvas, title: str, section: str, page_no: int, total: int) -> None:
    c.setFillColor(colors.HexColor("#F8FBFD"))
    c.rect(0, PAGE_H - 54, PAGE_W, 54, fill=1, stroke=0)
    c.setFillColor(NAVY)
    c.setFont("DemoSans-Bold", 10)
    c.drawString(31, PAGE_H - 31, "RehabAffect · 辅读课堂学习支持与追踪 Demo2")
    c.setFillColor(BLUE)
    c.roundRect(PAGE_W - 184, PAGE_H - 38, 119, 23, 11.5, fill=1, stroke=0)
    c.setFillColor(WHITE)
    c.setFont("DemoSans-Bold", 8.2)
    c.drawCentredString(PAGE_W - 124.5, PAGE_H - 30, section)
    c.setFillColor(MUTED)
    c.setFont("DemoSans", 8)
    c.drawRightString(PAGE_W - 31, PAGE_H - 30, f"{page_no:02d} / {total:02d}")
    c.setStrokeColor(LINE)
    c.line(31, PAGE_H - 54, PAGE_W - 31, PAGE_H - 54)
    c.setFillColor(INK)
    c.setFont("DemoSans-Bold", 17)
    c.drawString(31, PAGE_H - 83, title)


def draw_footer(c: canvas.Canvas, text: str = "演示系统仅提供课堂观察与教育支持参考，不构成医学诊断。") -> None:
    c.setStrokeColor(LINE)
    c.line(31, 26, PAGE_W - 31, 26)
    c.setFillColor(MUTED)
    c.setFont("DemoSans", 7.4)
    c.drawString(31, 13, text)
    c.drawRightString(PAGE_W - 31, 13, DISPLAY_DATE)


def draw_image_contain(c: canvas.Canvas, image_path: Path, x: float, y: float, w: float, h: float, *, background=colors.HexColor("#F5F8FA")) -> None:
    if not image_path.exists():
        raise FileNotFoundError(image_path)
    with PILImage.open(image_path) as image:
        iw, ih = image.size
    scale = min(w / iw, h / ih)
    dw, dh = iw * scale, ih * scale
    rounded_box(c, x, y, w, h, fill=background, stroke=LINE, radius=7)
    c.drawImage(ImageReader(str(image_path)), x + (w - dw) / 2, y + (h - dh) / 2, dw, dh, preserveAspectRatio=True, mask="auto")


def info_block(c: canvas.Canvas, x: float, y_top: float, w: float, label: str, text: str, accent) -> float:
    h_text = Paragraph(text, style(8.25, color=INK, leading=12.6)).wrap(w - 24, 120)[1]
    height = max(64, h_text + 35)
    rounded_box(c, x, y_top - height, w, height, fill=WHITE, stroke=LINE, radius=6)
    c.setFillColor(accent)
    c.roundRect(x, y_top - height, 4, height, 2, fill=1, stroke=0)
    c.setFillColor(accent)
    c.setFont("DemoSans-Bold", 8.4)
    c.drawString(x + 12, y_top - 18, label)
    paragraph(c, text, x + 12, y_top - 27, w - 24, size=8.25, leading=12.6)
    return height


@dataclass(frozen=True)
class FeaturePage:
    title: str
    section: str
    screenshot: str
    input_text: str
    process_text: str
    output_text: str
    value_text: str


FEATURES = [
    FeaturePage("一人一案", "学生资料", "05_profile_desktop.png", "选择学生；读取基础档案、IEP 与既有评估摘要。", "把学生基线、优势、当前目标和支持边界放在同一档案中。", "个体画像、当前支持重点、课程适配提示。", "避免只看单节课，把课堂表现放回学生自己的发展基线。"),
    FeaturePage("历史记录", "学生资料", "06_tracking_desktop.png", "选择学生与历史课程记录。", "按课程时间整理参与、掌握、支持效果与教师复核结果。", "跨课次记录、变化提示和下一次观察重点。", "支持长期追踪，而不是用一次课堂片段给学生下结论。"),
    FeaturePage("资料导入", "学生资料", "06a_profile_import_desktop.png", "上传 IEP、五大领域评估、专业评估、表格、图片或文本，并确认授权。", "保存原文件、计算文件摘要、提取可读预览并登记资料来源和日期。", "可下载原件、解析预览、教师确认的结构化支持摘要。", "把校方已有材料转为课堂分析可引用的可靠背景信息。"),
    FeaturePage("状态时间线", "课堂证据", "07_state_timeline_desktop.png", "课堂视频切片、人物身份、课程时间轴。", "把专注、困惑、疲劳、抗拒、需要帮助等状态按时间整理和平滑。", "状态区间、置信度、证据和待复核窗口。", "老师可快速定位关键时段，不需要重新观看整节录像。"),
    FeaturePage("师生互动", "课堂证据", "05_interaction_desktop.png", "教师指令、提问、等待、提示与学生回应事件。", "对齐互动双方和时间，计算回应延迟、提示层级及完成情况。", "互动链路、独立回应与支持后回应的区别。", "回答“学生为什么有这个表现”，而不只是罗列动作。"),
    FeaturePage("教师复核", "课堂证据", "06_teacher_review_desktop.png", "系统推荐的关键切片与初步标签。", "老师逐条选择确认、需修正或无法判断，并可补充备注。", "具有人类复核状态的可靠标签和可追溯修改记录。", "降低学校标注负担，同时把最终解释权留给教师。"),
    FeaturePage("支持效果", "课堂证据", "07_support_effect_desktop.png", "支持前状态、教师支持方式和支持后表现。", "比较支持前后参与度、回应质量与风险变化。", "有效、部分有效或效果不明确的支持结论。", "帮助学校积累“对这个学生什么方式更有效”的个体经验。"),
    FeaturePage("学习判断", "教学决策", "08_mastery_desktop.png", "课程目标、考核标准、互动证据和独立完成情况。", "区分独立掌握、支持下掌握、正在学习与证据不足。", "目标级掌握判断、证据依据和下一课建议。", "将注意力观察落到学生到底学会了什么。"),
    FeaturePage("支持工具", "教学决策", "09_support_tools_desktop.png", "学生当前状态、课堂风险和教师可用支持方式。", "按低刺激、可撤销、教师可控原则筛选支持策略。", "等待计时、简化指令、视觉提示和暂停询问等工具。", "让分析结果能够立即转成尊重学生的课堂支持。"),
    FeaturePage("动作方案", "教学决策", "10_action_plan_desktop.png", "学生状态、风险等级、课程阶段和既往有效策略。", "根据安全规则决定继续、重复说明、降低难度、暂停或交由教师。", "可供教师、屏幕设备或未来机器人调用的动作建议。", "保留具身智能的 Perception → State → Action 闭环。"),
    FeaturePage("五域趋势", "成长轨迹", "08_growth_desktop.png", "多节课程数据与五大领域评估记录。", "按学生个人基线观察认知、语言、运动、社会适应和感知等维度变化。", "趋势图、稳定变化、需继续观察的领域。", "为阶段性 IEP 复盘提供课堂侧证据，不作跨学生排名。"),
    FeaturePage("课程分析", "成长轨迹", "09_course_report_desktop.png", "课程信息、三名学生表现、目标掌握和教师复核。", "汇总群像与个体差异，形成课堂层面的结构化复盘。", "课程适配、学生掌握、支持效果和下一课调整建议。", "让学校看到一节课对不同学生是否真正有效。"),
    FeaturePage("深度报告", "成长轨迹", "11_deep_report_start_desktop.png", "已确认的课堂证据、课程标准、学生档案和教师复核。", "按固定教育分析结构生成约一千字报告，保留依据与不确定性。", "可复制、归档和继续人工修改的课堂分析报告。", "减少重复整理工作，同时避免脱离证据的自动结论。"),
    FeaturePage("数据来源", "成长轨迹", "12_data_source_desktop.png", "原视频、评课资料、学生资料及教师复核记录。", "记录每类结论对应的数据来源、处理状态和可信边界。", "来源清单、缺失项和数据可追溯关系。", "展示结论从哪里来，便于校方审查和复盘。"),
    FeaturePage("四路上传", "数据治理", "12a_four_channel_upload_desktop.png", "四个主体分别填写上传人、观察对象、课程、批次号并选择视频。", "浏览器分片上传；任务、权限与结果相互隔离；同批次经授权后才能对齐。", "独立任务编号、上传进度、质量预检、60天期限、下载与授权归档入口。", "支持多主体并行提交，不需要部署四套系统。"),
    FeaturePage("数据存储", "数据治理", "12b_storage_governance_desktop.png", "保存周期、提前提醒、自动删除和长期资源授权。", "SQLite 保存结构化数据，受控目录保存原文件，并记录安全协议、上传、修改、归档和删除审计。", "60天/15天规则、到期列表、授权归档队列、真实路径、容量和下载。", "让学校知道数据存在哪里、保存多久、由谁授权以及如何处理。"),
    FeaturePage("结构化数据", "数据治理", "13_json_desktop.png", "课堂分析、学生身份、证据、风险和动作建议。", "按统一 human_state 与课堂报告结构组织字段。", "可供 WebSocket、ROS2、App 或其他系统调用的 JSON。", "把网页 Demo 的结果转成后续工程接口，而不是只停留在页面展示。"),
]


def cover_page(c: canvas.Canvas, page_no: int, total: int) -> None:
    c.setFillColor(colors.HexColor("#F7FBFE"))
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    c.setFillColor(NAVY)
    c.rect(0, 0, 235, PAGE_H, fill=1, stroke=0)
    c.setFillColor(CYAN)
    c.rect(0, PAGE_H - 9, PAGE_W, 9, fill=1, stroke=0)
    c.setFillColor(WHITE)
    c.setFont("DemoSans-Bold", 11)
    c.drawString(33, PAGE_H - 59, "RehabAffect")
    c.setFont("DemoSans", 8.5)
    c.drawString(33, PAGE_H - 78, "辅读课堂学习支持与追踪系统")
    c.setFont("DemoSans-Bold", 27)
    paragraph(c, "Demo2<br/>逐页图文<br/>功能说明", 33, PAGE_H - 137, 170, size=27, bold=True, color=WHITE, leading=39)
    c.setFillColor(colors.HexColor("#B7D8E9"))
    c.setFont("DemoSans", 9.5)
    c.drawString(33, 86, "课堂观察 · 学习判断 · 支持决策")
    c.drawString(33, 68, "长期追踪 · 教师复核 · 数据治理")
    c.setFont("DemoSans", 8)
    c.drawString(33, 36, f"功能说明册  |  {DISPLAY_DATE}  |  {page_no:02d}/{total:02d}")

    draw_image_contain(c, SHOT_DIR / "03_workspace_desktop.png", 268, 105, PAGE_W - 300, 385, background=WHITE)
    c.setFillColor(INK)
    c.setFont("DemoSans-Bold", 13)
    c.drawString(270, 71, "面向特殊教育课堂的个体化学习支持闭环")
    c.setFillColor(MUTED)
    c.setFont("DemoSans", 8.7)
    c.drawString(270, 51, "覆盖课程确认、三人群像、个体追踪、教师复核、报告生成、四路上传与本地数据治理。")


def overview_page(c: canvas.Canvas, page_no: int, total: int) -> None:
    draw_header(c, "系统全景：从课堂数据到下一步支持", "总览", page_no, total)
    steps = [
        ("01", "课程确认", "课程名称、课程标准、考核指标"),
        ("02", "多模态证据", "视频、声音、互动与已有资料"),
        ("03", "状态与学习判断", "时间平滑、目标掌握、支持效果"),
        ("04", "教师复核", "确认、修正、备注和证据留痕"),
        ("05", "支持与追踪", "动作建议、报告、五域趋势和数据接口"),
    ]
    x0, y, gap = 31, PAGE_H - 147, 11
    w = (PAGE_W - 62 - gap * 4) / 5
    for index, (num, name, desc) in enumerate(steps):
        x = x0 + index * (w + gap)
        rounded_box(c, x, y - 110, w, 110, fill=PALE_BLUE if index % 2 == 0 else PALE_CYAN, stroke=LINE, radius=8)
        c.setFillColor(BLUE if index < 3 else GREEN)
        c.setFont("DemoSans-Bold", 9)
        c.drawString(x + 13, y - 20, num)
        c.setFillColor(INK)
        c.setFont("DemoSans-Bold", 11)
        c.drawString(x + 13, y - 43, name)
        paragraph(c, desc, x + 13, y - 55, w - 26, size=8, color=MUTED, leading=12.2)
    c.setFillColor(INK)
    c.setFont("DemoSans-Bold", 13)
    c.drawString(31, 305, "17 个功能页面")
    groups = [
        ("学生资料", ["一人一案", "历史记录", "资料导入"], BLUE),
        ("课堂证据", ["状态时间线", "师生互动", "教师复核", "支持效果"], CYAN),
        ("教学决策", ["学习判断", "支持工具", "动作方案"], ORANGE),
        ("成长轨迹", ["五域趋势", "课程分析", "深度报告", "数据来源"], GREEN),
        ("数据治理", ["四路上传", "数据存储", "结构化数据"], colors.HexColor("#7A77C8")),
    ]
    y_top = 276
    for i, (group, items, accent) in enumerate(groups):
        col = i % 3
        row = i // 3
        x = 31 + col * 261
        yy = y_top - row * 112
        rounded_box(c, x, yy - 90, 244, 90, fill=WHITE, stroke=LINE, radius=7)
        c.setFillColor(accent)
        c.rect(x, yy - 90, 5, 90, fill=1, stroke=0)
        c.setFont("DemoSans-Bold", 9)
        c.drawString(x + 16, yy - 22, group)
        paragraph(c, "　·　".join(items), x + 16, yy - 34, 210, size=8.2, color=MUTED, leading=13)
    draw_footer(c)


def screenshot_page(c: canvas.Canvas, title: str, section: str, screenshot: str, page_no: int, total: int, caption: str) -> None:
    draw_header(c, title, section, page_no, total)
    draw_image_contain(c, SHOT_DIR / screenshot, 31, 60, 552, 420, background=WHITE)
    rounded_box(c, 600, 60, PAGE_W - 631, 420, fill=colors.HexColor("#F8FBFD"), stroke=LINE, radius=8)
    c.setFillColor(BLUE)
    c.setFont("DemoSans-Bold", 9)
    c.drawString(619, 446, "页面说明")
    paragraph(c, caption, 619, 430, PAGE_W - 668, size=9.1, leading=15.2)
    draw_footer(c)


def feature_page(c: canvas.Canvas, feature: FeaturePage, page_no: int, total: int) -> None:
    draw_header(c, feature.title, feature.section, page_no, total)
    draw_image_contain(c, SHOT_DIR / feature.screenshot, 31, 60, 545, 420, background=WHITE)
    x, y_top, w = 593, 480, PAGE_W - 624
    for label, text, accent in [
        ("输入", feature.input_text, BLUE),
        ("系统处理", feature.process_text, CYAN),
        ("页面输出", feature.output_text, GREEN),
        ("实际价值", feature.value_text, ORANGE),
    ]:
        used = info_block(c, x, y_top, w, label, text, accent)
        y_top -= used + 9
    draw_footer(c)


def responsive_page(c: canvas.Canvas, page_no: int, total: int) -> None:
    draw_header(c, "多终端适配", "页面适配", page_no, total)
    shots = [
        ("学生档案", "13_profile_mobile.png"),
        ("课堂分析", "14_course_report_mobile.png"),
        ("四路上传", "17b_four_channel_upload_mobile.png"),
        ("数据存储", "17c_storage_governance_mobile.png"),
    ]
    x = 31
    for title, filename in shots:
        draw_image_contain(c, SHOT_DIR / filename, x, 92, 181, 374, background=WHITE)
        c.setFillColor(INK)
        c.setFont("DemoSans-Bold", 8.5)
        c.drawCentredString(x + 90.5, 72, title)
        x += 198
    paragraph(c, "页面已在 1440 桌面、1366 学校笔记本、1024/768 平板以及 390/360 手机宽度下完成浏览器检查。导航、表单和长路径均可在窄屏内使用。", 31, 51, PAGE_W - 62, size=8.3, color=MUTED, align=TA_CENTER)
    draw_footer(c)


def io_page(c: canvas.Canvas, page_no: int, total: int) -> None:
    draw_header(c, "Demo 输入、处理与输出", "交付边界", page_no, total)
    columns = [
        ("输入", BLUE, ["课程名称与标准", "课堂视频与声音", "学生 IEP / 五域评估", "教师复核和备注", "四个主体独立上传"]),
        ("处理", CYAN, ["视频切片与质量预检", "状态时间线和平滑", "师生互动对齐", "目标掌握与支持效果", "本地存储与审计"]),
        ("输出", GREEN, ["个体课堂状态", "目标掌握结论", "支持与动作建议", "课程/深度报告", "JSON 与下载文件"]),
    ]
    x, box_w = 31, 247
    for title, accent, items in columns:
        rounded_box(c, x, 205, box_w, 270, fill=WHITE, stroke=LINE, radius=9)
        c.setFillColor(accent)
        c.roundRect(x, 427, box_w, 48, 9, fill=1, stroke=0)
        c.rect(x, 427, box_w, 24, fill=1, stroke=0)
        c.setFillColor(WHITE)
        c.setFont("DemoSans-Bold", 13)
        c.drawString(x + 18, 445, title)
        yy = 397
        for index, item in enumerate(items, 1):
            c.setFillColor(accent)
            c.circle(x + 23, yy + 2, 10, fill=1, stroke=0)
            c.setFillColor(WHITE)
            c.setFont("DemoSans-Bold", 7)
            c.drawCentredString(x + 23, yy - 0.5, str(index))
            c.setFillColor(INK)
            c.setFont("DemoSans", 9.2)
            c.drawString(x + 42, yy - 1, item)
            yy -= 40
        x += box_w + 19
    rounded_box(c, 31, 66, PAGE_W - 62, 107, fill=PALE_BLUE, stroke=colors.HexColor("#C7DEEE"), radius=8)
    c.setFillColor(NAVY)
    c.setFont("DemoSans-Bold", 10)
    c.drawString(48, 146, "四路视频上传的当前实现")
    paragraph(c, "四个通道已经支持真实分片上传、任务隔离、进度显示、视频完整性与画面质量预检、JSON 结果下载。对任意新视频生成完整学生状态与课程掌握结论，仍需部署视觉/音频模型工作节点，并由教师复核。", 48, 131, PAGE_W - 96, size=8.6, leading=14)
    draw_footer(c)


def deployment_page(c: canvas.Canvas, page_no: int, total: int) -> None:
    draw_header(c, "运行条件、数据治理与当前边界", "交付边界", page_no, total)
    items = [
        ("已经实现", GREEN, "数据安全协议留痕、课程确认、三学生切换、17 个分析页面、教师复核、千字报告、本地 SQLite、资料导入、四路分片上传、60天/15天规则和脱敏归档队列。"),
        ("试点硬件", BLUE, "上传端普通 i5/R5、8-16GB 内存即可；四路并发建议学校总上行不少于 40Mbps；试点服务端建议 8 核 CPU、32GB 内存、1TB NVMe。"),
        ("模型扩展", CYAN, "完整课堂状态模型建议配置 12-24GB 显存 GPU 工作节点，并加入任务队列、失败重试、教师校准和模型评估。上传电脑本身不需要独立显卡。"),
        ("数据原则", ORANGE, "新上传原始音视频默认本地保存 60 天并提前 15 天提醒；脱敏结构化结果只有获得单独授权才进入长期资源队列，原始学生视频默认不进入公司数据库。"),
        ("必须说明", RED, "系统提供课堂观察和教育支持参考，不进行医学诊断，不跨学生排名，不用一次课堂表现定义学生，最终判断和干预由教师或照护者负责。"),
    ]
    y = 474
    for title, accent, text in items:
        rounded_box(c, 31, y - 72, PAGE_W - 62, 72, fill=WHITE, stroke=LINE, radius=7)
        c.setFillColor(accent)
        c.roundRect(31, y - 72, 6, 72, 3, fill=1, stroke=0)
        c.setFillColor(accent)
        c.setFont("DemoSans-Bold", 9)
        c.drawString(49, y - 22, title)
        paragraph(c, text, 129, y - 15, PAGE_W - 177, size=8.5, leading=13.5)
        y -= 83
    draw_footer(c, "当前 Demo 可用于需求确认和校内受控演示；正式学生试点需完成授权、权限、模型验证和运行保障。")


def build() -> Path:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    total = 26
    c = canvas.Canvas(str(OUTPUT), pagesize=landscape(A4), pageCompression=1)
    c.setTitle("RehabAffect Demo2 Illustrated Feature Guide")
    c.setAuthor("RehabAffectPerception")
    page = 1

    cover_page(c, page, total)
    c.showPage(); page += 1
    overview_page(c, page, total)
    c.showPage(); page += 1
    screenshot_page(c, "上传前数据安全协议", "进入流程", "00_entry_viewport_desktop.png", page, total, "课程开始前先确认数据用途、下载范围和安全边界。新上传原始视频本地保存 60 天，到期前 15 天提醒；教师可另行授权脱敏结构化结果进入公司长期资源库，原始视频默认不进入。")
    c.showPage(); page += 1
    screenshot_page(c, "课程标准与责任人确认", "进入流程", "01_confirm_viewport_desktop.png", page, total, "安全协议通过后，使用者逐步确认课程类型、课程名称、学校目标、教学安排、考核标准和责任人。确认记录写入本地审计，用作学习判断和报告生成的共同参照。")
    c.showPage(); page += 1
    screenshot_page(c, "班级群像与个体切换", "课堂总览", "03_workspace_desktop.png", page, total, "总览页同时保留课堂画面、三名学生切换、群像/个体视角、参与指数、课程适配和教师复核进度。点击学生后，后续 17 个页面均切换到对应个体。")
    c.showPage(); page += 1

    for feature in FEATURES:
        feature_page(c, feature, page, total)
        c.showPage(); page += 1

    screenshot_page(c, "千字深度报告生成结果", "成长轨迹", "14_deep_report_generated_desktop.png", page, total, "报告按课程背景、学生表现、目标掌握、支持效果、教师复核、限制条件和下一课建议组织。当前为本地模板化生成，可复制和继续修改；后续可接入受控 Agent，但必须保留来源引用和教师确认。")
    c.showPage(); page += 1
    responsive_page(c, page, total)
    c.showPage(); page += 1
    io_page(c, page, total)
    c.showPage(); page += 1
    deployment_page(c, page, total)
    c.save()
    if page != total:
        raise RuntimeError(f"Expected {total} pages, generated {page}")
    return OUTPUT


if __name__ == "__main__":
    print(build())
