"""Build the current UI guide from a freshly captured, local-only manifest."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image
from reportlab.lib import colors
from reportlab.lib.pagesizes import A3, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph


ROOT = Path(__file__).resolve().parents[1]
SHOTS = ROOT / "output/playwright/demo2_current_guide_20260909"
OUTPUT = ROOT / "output/pdf/RehabAffect_Demo2_全界面功能说明_20260909.pdf"
QA_DIR = ROOT / "tmp/pdfs/demo2_current_guide_20260909"
W, H = landscape(A3)
BLUE = colors.HexColor("#2464B5")
INK = colors.HexColor("#24364C")
MUTED = colors.HexColor("#60738A")
LINE = colors.HexColor("#DCE6F1")
PALE = colors.HexColor("#F4F8FE")
GOLD = colors.HexColor("#8A6417")
DATE = "2026.09.09"


@dataclass(frozen=True)
class Copy:
    title: str
    entry: str
    purpose: str
    operation: str
    result: str
    boundary: str
    kind: str = "实际页面"


COPIES = {
    "login_user": Copy("用户登录", "私密邀请入口 → 用户登录", "教师或上传人员使用自己的账号进入工作台。", "选择“用户登录”，输入分配的账号与密码；登录后进入学校归属确认。", "建立账号会话，并按账号分配上传通道和可访问任务。", "完整邀请链接与账号密码单独发送。本册不嵌入密码或会到期的访问密钥。"),
    "login_admin": Copy("管理员登录", "登录页面 → 管理员登录", "让公司内部人员查看账号、上传、处理与存储运行情况。", "先切换到管理员身份，再输入管理员账号；身份与账号不符时会被拒绝。", "进入公司后台，看到数据库汇总的账号、通道、任务和存储信息。", "管理员不是教师上传账号。当前后台主要是只读运营总览，不等于所有管理操作都已具备。"),
    "register": Copy("会员注册与开通申请", "登录页面 → 申请开通 / 会员注册", "收集学校和联系人信息，作为后续账号开通的申请。", "填写联系人、联系方式、城市、区县和学校，阅读说明后提交。", "形成待审核申请记录，管理员可在后台查看。", "提交申请不会立即生成可登录账号；当前没有自助付费会员或自动审核开通流程。"),
    "privacy": Copy("数据安全与隐私说明", "登录页、课程确认或上传页 → 隐私说明", "明确上传用途、访问范围、原视频期限和长期归档授权。", "在提交申请、确认课程、上传文件之前查看对应说明；按实际授权作出确认。", "用户知道哪些资料会被记录、能由谁访问以及如何申请导出或处理。", "说明页面不能代替学校、监护人或其他必要授权；原视频不默认进入公司长期资源库。"),
    "school": Copy("学校归属确认", "用户登录成功后 → 学校选择", "为账号补充城市、区县和学校，便于整理使用单位。", "填写或选择所属地区与学校，点击进入课程工作台。已有信息可再次修改。", "账号关联学校信息，后台同步显示上传账号的学校归属。", "这是账号归属登记，不代表已实现按地区建立的独立多学校数据库隔离。"),
    "upload": Copy("课堂视频上传工作台", "用户登录 → 学校选择 → 上传工作台", "把本地课堂录像与课程批次、课程名称和观察对象关联。", "填写课程批次号，读取工作区，选择视频及学生，确认授权后上传。新文件从这里手动选择。", "分片上传进度、任务编号、后台排队状态和本课程任务列表。每账号每课程最多5个有效名额。", "不是从希沃自动同步；需先获得授权并导出文件。四个账号对应四个上传通道，不是四个网址或四路自动直播。"),
    "upload_tasks": Copy("上传任务与处理结果", "上传工作台 → 本课程任务", "把文件传输和后台处理分开显示，避免“上传成功”被理解为“分析已经完成”。", "查看上传、排队、处理和证据就绪状态；打开任务详情，按状态使用取消、失败重试或历史任务重新处理入口。", "每个任务独立的进度、结果入口及可下载记录。离开上传页面后，已入队任务仍可继续处理。", "取消、重试和重新处理有状态与账号限制；证据就绪只表示技术处理完成。"),
    "video": Copy("新视频的实际证据记录", "上传任务列表 / 管理员近期上传 → 打开任务", "实际解码上传录像，并提供可定位、可复查的原片与技术记录。", "播放或暂停视频，拖动进度，点击20秒时间窗口，查看对应技术统计及处理状态。", "视频时长、画幅、抽帧、亮度、清晰度、运动变化和时间窗口等真实处理结果。", "这是整幅画面的技术证据。当前未自动识别人名、专注、情绪或知识掌握度。"),
    "video_audio": Copy("音轨与时间窗口核对", "任务证据页 → 音轨 / 窗口详情", "保留课堂声音并与原片时间轴对齐，方便人工核对声音是否可用。", "播放提取音轨、跳转到目标时间段，查看窗口音频覆盖及能量统计；用原片复核环境声音。", "可回听音轨、时间区间和音频可用性记录；无音轨时明确显示缺失。", "音量不等于情绪；当前没有自动转写、说话人识别或师生问答内容理解。"),
    "admin": Copy("公司后台：账号与通道", "管理员登录 → 后台总览", "集中查看四个上传账号、通道、学校归属与开通申请。", "查看账号列表和学校信息，点击刷新读取最新汇总。向下查看名额和任务。", "账号状态、通道绑定、学校归属、申请记录及每课程名额使用情况。", "这一页读取真实后台数据；没有将界面申请直接变成账号，也没有实现完整的角色权限管理控制台。"),
    "admin_storage": Copy("公司后台：处理与存储", "后台总览 → 任务状态 / 保存与到期提醒", "了解任务是否在上传、排队或处理，以及原片保存和提醒设置。", "查看上传状态与处理状态分布、保存周期、提前提醒和近期到期情况。", "本地数据库与受控文件目录的汇总；当前原视频策略为60天、到期前15天进入提醒范围。", "提醒在平台内展示，不等于已接入微信、短信或邮件通知；当前不是独立云端存储服务。"),
    "admin_recent": Copy("公司后台：授权与近期任务", "后台总览 → 安全授权确认 / 近期上传", "把上传记录、授权选择与可打开的任务结果放在一起。", "核对确认人、课程、时间和归档选择；从近期上传列表打开任务证据页。", "可追溯的操作记录，以及来源于真实任务的查看入口。", "原视频默认不长期归档；管理员也不能把未经授权的学生资料直接作为训练数据。"),
    "course_setup": Copy("课程基线与评价口径", "历史演示分析 → 展开课程与评价依据", "先确定这节课教什么、怎样算完成，再解释学生表现。", "查看课程类型、名称、课程标准与校方考核标准；通过适配建议检查个体目标是否需要调整。", "课程依据与三名学生的目标适配建议，供老师讨论和修正。", "当前适配建议基于已有资料和规则，不是对新上传录像自动形成的学习结论。", "既有课堂示例"),
    "group": Copy("三人群像与课堂环境", "历史演示分析 → 课堂证据画面 → 群像", "同时核对学生座位、课堂材料和周围的互动关系。", "切换课程和学生，选择群像模式，结合事件或时间片观察当前课堂上下文。", "已确认学生的课堂画面与个体信息，便于从群体情境理解个人表现。", "这里使用既有录像抽帧和校方确认的身份，不是对任意视频自动选人或自动人脸识别。", "既有课堂示例"),
    "portrait": Copy("个体画面与学生切换", "课堂证据画面 → 人像 / 学生选择", "把观察焦点切到某个学生，同时保留其课程和档案上下文。", "点击学生姓名或个体标签，再切换人像模式；返回群像核对周围情境。", "与当前学生关联的画面、状态摘要、课程目标和支持信息。", "人物对应来自已确认映射；遮挡和低清晰度片段不能凭裁剪画面补出不存在的细节。", "既有课堂示例"),
    "navigation": Copy("分析导航与模块关系", "课堂分析 → 学生结论与支持决策", "按学生资料、课堂证据、教学决策、成长轨迹和数据治理组织工作。", "先选择学生，再切换分析导航中的模块。用同一学生和课程上下文查看证据、复核与报告。", "17个分析功能页签及当前学生的初评摘要、复核进度。", "本册逐项展示页签；部分学习结论仍为既有课堂的规则化演示，不应当作验证后的准确率。", "既有课堂示例"),
    "profile": Copy("一人一案", "分析导航 → 学生资料 → 一人一案", "让课堂观察与学生已有能力、优势和支持需求关联，而非只看某个动作。", "选择学生，查看资料来源、当前目标、支持重点与需要谨慎解释的地方。", "整合已有档案与课堂证据的个体化摘要。", "专业资料只作为教育支持背景；系统不根据录像诊断病症，也不把个人差异当作异常评分。", "既有课堂示例"),
    "tracking": Copy("历史记录", "分析导航 → 学生资料 → 历史记录", "集中查看当前学生的基线、本课关键时刻和下一课支持计划。", "切换课程和学生，查看本课指标、上次等级参考及相关证据，明确继续观察的重点。", "用于跟进的个体追踪展示与下一次支持计划。", "上次等级来自既有课程配置，并非完整纵向数据库；新上传任务不会自动累积长期基线，也不能证明进步或退步。", "既有课堂示例"),
    "profileImport": Copy("IEP与专业资料导入", "分析导航 → 学生资料 → 资料导入", "把IEP、五大领域评估、专业建议等已有材料关联到指定学生。", "选择学生和资料类型，上传不超过10MB的文件，填写来源日期；人工核对支持摘要。", "原件登记、下载及人工支持摘要。DOCX、TXT、CSV、JSON可提取最多1200字符预览。", "PDF、Excel和图片当前仅保存原件，没有OCR或自动量表解析。摘要再次保存会更新当前值，不会触发模型训练。", "资料功能"),
    "state": Copy("状态时间线", "分析导航 → 课堂证据 → 状态时间线", "按时间查看参与、困惑、疲劳、拒绝或需要帮助等候选状态及其依据。", "点击状态区间或关键窗口，联动证据画面，检查置信度、线索和待复核标记。", "有时间定位的状态摘要与复核线索，减少重复观看整段录像的成本。", "示例状态由轻量特征和规则生成；不能把动作少、目光离开或单帧表情直接等同于学会或不会。", "既有课堂示例"),
    "interaction": Copy("师生互动", "分析导航 → 课堂证据 → 师生互动", "把教师指令、提示和学生回应组织为可核对的互动顺序。", "查看学习机会、提示方式、回应和结果，回到对应片段核对。", "回应延迟、提示程度和是否独立完成等示例证据。", "当前互动事件来自预设时间段及规则，不是新视频的自动语音转写或精确说话人分析。", "既有课堂示例"),
    "evidence": Copy("教师复核与标注", "分析导航 → 课堂证据 → 教师复核", "让老师集中确认关键片段，而不是要求学校先处理所有原始视频。", "打开待复核片段，核对学生和时段，选择符合、需修正或不确定；填写正确性、提示等级和备注后保存。", "核心复核字段保存到本地JSON，用于回显、进度和报告，也可导出复核清单。", "“教师调整”和“学生随后变化”等补充字段尚未完整持久化。保存不会自动重算旧评分或训练模型；截图未提交新意见。", "教师复核流程"),
    "teacher": Copy("教师支持效果", "分析导航 → 课堂证据 → 支持效果", "观察支持前后回应与参与变化，帮助老师复盘提示是否合适。", "查看分项、权重、证据覆盖和支持前后区间，再核对具体情境。", "支持效果的规则化量化摘要及进一步观察建议。", "这不是教师绩效评分，也不能仅凭一个学生状态变化证明教学方法导致了进步或退步。", "既有课堂示例"),
    "mastery": Copy("学习判断", "分析导航 → 教学决策 → 学习判断", "将“看起来参与”与“完成了学习目标”分开呈现。", "逐个查看课程目标、可用学习机会、提示后完成和独立完成证据；证据不足时交老师补充。", "目标级掌握初评与下一课目标调整建议。", "目前为规则化示例，不能据此认定孩子已掌握知识；必须结合明确测评与教师确认。", "既有课堂示例"),
    "specialSupport": Copy("低刺激支持工具", "分析导航 → 教学决策 → 支持工具", "为老师提供等待、简化指令和视觉提示等可控支持方式。", "按学生表达、感觉与等待需要选择支持工具，使用计时和提示卡，并随时停止。", "可见的课堂支持提示与使用记录形态。", "工具由教师决定是否使用，不能强迫学生互动；不代表已控制外部硬件或真实机器人。", "教师操作工具"),
    "action": Copy("动作方案与安全边界", "分析导航 → 教学决策 → 动作方案", "把学生状态与课程情境转成克制、可由教师选择的支持建议。", "查看继续、重复说明、降低难度、暂停询问或交由教师等候选动作及安全约束。", "便于讨论或对接的动作建议和结构化参数。", "当前是方案与接口层，不是已完成真机动作执行；高影响互动仍需教师决定。", "建议与接口预留"),
    "growth": Copy("五域趋势", "分析导航 → 成长轨迹 → 五域趋势", "从认知、语言、运动、感知和社会适应等领域整理观察方向。", "检查基础评估来源、已观察领域、缺失项和当前情景趋势。", "领域化的追踪视图与后续采集重点。", "图中的情景推演不是长期实测结果；缺失评估不能当作零分，也不能用单课数据判定恶化。", "情景趋势示例"),
    "courseReport": Copy("课程分析：一节课一份千字报告", "分析导航 → 成长轨迹 → 课程分析", "以一节课为单位汇总三名学生的差异、目标初评和支持建议。", "阅读课堂级分析，查看复核状态，使用复制或打印/导出PDF。", "约1000字的一份课程级分析，不是每个学生各生成一万字。", "当前文本基于已有课堂资料和规则，不代表新上传任务已完成同等语义分析；报告需要教师核准。", "既有课堂示例"),
    "feedback": Copy("深度报告与章节导航", "分析导航 → 成长轨迹 → 深度报告", "把课程确认、数据质量、个体分析、支持和下一课计划整理成章节化说明。", "生成约一千字综合报告；通过章节导航定位内容，复制全文或打印导出。", "带复核情况、来源边界及后续计划的报告。截图载入已有1261字本地规则报告，实际字数以页面为准。", "未启用第三方LLM。报告截图仅展示已有报告的阅读形态，本次没有新保存教师复核或重新生成生产报告。", "本地规则报告"),
    "summary": Copy("数据来源与课堂摘要", "分析导航 → 成长轨迹 → 数据来源", "说明课堂结果引用了哪些视频、评课信息和个体资料。", "检查课程阶段、问答口径、数据来源与缺失线索，再回到相关证据。", "支持审查的来源说明，帮助区分观测、既有资料和规则推断。", "有来源不代表每项解释都已被人工核准；来源不足或音画不清的部分仍需要保留不确定性。", "既有课堂示例"),
    "videoUpload": Copy("四路上传与任务归纳", "分析导航 → 数据治理 → 四路上传", "在课堂分析页查看上传主体、观察对象和相关任务记录。", "按当前账号查看可用通道、课程和文件信息；新任务优先从独立上传工作台建立。", "账号绑定通道、上传/处理状态、结果下载和授权归档入口。", "四通道是逻辑账号与数据来源划分，不表示已自动同步四台摄像机；历史记录与新证据任务应分别理解。", "账号任务功能"),
    "storage": Copy("数据存储与授权归档", "分析导航 → 数据治理 → 数据存储", "查看本地保存、到期提示、已登记资料、报告和长期资源授权记录。", "核对原片60天期限和提前15天提醒，下载资料或查看授权归档登记。课程报告优先在报告页复制或打印。", "SQLite业务记录、受控文件目录和本地归档登记。获准资源仍待接入公司长期存储同步。", "报告清单部分下载链接尚未打通；原片期限不同于资料和结构化记录，改策略也不批量更新旧任务。当前没有云同步或异地备份。", "本地存储功能"),
    "json": Copy("结构化数据", "分析导航 → 成长轨迹 → 结构化数据", "把人类可读页面中的状态、证据和建议组织成程序可使用的结构。", "查看当前学生/课程的JSON字段，核对状态、时间、置信度、风险及动作建议的对应关系。", "可供后续系统整合参考的结构化结果。", "页面展示JSON不等于已经接通App、ROS2或机器人；示例数据与新任务技术证据使用各自的数据来源。", "结果结构展示"),
}

ENTRY_STEPS = [
    ("安全与用途确认", "展开安全说明，核对课堂资料的使用授权与归档选择，再选择同意并继续。", "默认不长期归档原视频。截图演示确认步骤，没有因此向后台新增授权记录。"),
    ("选择本次课程", "选择要查看的既有课程，系统载入该课的基础资料。", "这里选择的是已有演示课程；新视频文件需在独立上传工作台提交。"),
    ("填写课程类型", "使用学校日常名称填写生活数学、生活语文等课程类型。", "课程类型用于说明情境，不按障碍类型给学生自动分班。"),
    ("确认课程名称", "确认本次课堂的名称，便于报告和复核表沿用一致表述。", "应与实际课程一致，不要用名称变化代替新的课程批次。"),
    ("录入学习目标", "填写学校教案要求与课程标准，尽量使用可观察、可复核的目标。", "有目标文本不等于系统已能自动判断目标完成；仍需课堂学习证据。"),
    ("确认教学安排", "填写关键步骤、材料、提示方式及给予学生作答的机会。", "教学安排是解释课堂表现的上下文，不是固定的教师优劣评分标准。"),
    ("明确考核标准", "写明独立完成、提示后完成、未观察到与证据不足的判定口径。", "应由学校确认评价标准；不能把注意力分数直接替换为知识掌握分数。"),
    ("确认并进入分析", "填写确认人，检查课程信息，再进入课堂分析工作台。", "本册仅展示配置界面，没有代替真实教师作出授权或标注核准。"),
]


def text(c, value, x, top, width, size=12.5, leading=20, bold=False, color=INK, min_bottom=36):
    style = ParagraphStyle("guide", fontName="Guide-Bold" if bold else "Guide", fontSize=size,
                           leading=leading, textColor=color, wordWrap="CJK", spaceBefore=0, spaceAfter=0)
    para = Paragraph(escape(str(value)).replace("\n", "<br/>"), style)
    _, height = para.wrap(width, H)
    if top - height < min_bottom:
        raise ValueError(f"Text overflows page: {str(value)[:45]}")
    para.drawOn(c, x, top - height)
    return height


def frame(c, title, chapter, page, total):
    c.setFillColor(colors.white)
    c.rect(0, 0, W, H, fill=1, stroke=0)
    c.setFillColor(BLUE)
    c.rect(0, H - 5, W, 5, fill=1, stroke=0)
    text(c, "云图智航  /  RehabAffect", 34, H - 27, 600, 11, 17, True, BLUE)
    c.setFont("Guide", 10)
    c.setFillColor(MUTED)
    c.drawRightString(W - 35, H - 39, f"全界面功能说明  |  {DATE}")
    text(c, title, 34, H - 67, W - 68, 25, 36, True)
    text(c, chapter, 35, H - 111, W - 70, 11, 17, color=MUTED)
    c.setStrokeColor(LINE)
    c.line(35, 43, W - 35, 43)
    text(c, "授权示例截图，仅供内部及授权沟通；课堂观察不构成医学诊断。", 35, 31, W - 180, 9, 13, color=MUTED, min_bottom=8)
    c.setFont("Guide", 10)
    c.drawRightString(W - 35, 19, f"{page:02d} / {total:02d}")


def section(c, label, body, x, top, width):
    text(c, label, x, top, width, 12.5, 20, True, BLUE)
    used = text(c, body, x, top - 28, width, 12.1, 20)
    return 28 + used + 27


def screenshot(c, file, x, y, width, height):
    with Image.open(file) as im:
        iw, ih = im.size
    scale = min(width / iw, height / ih)
    dw, dh = iw * scale, ih * scale
    left, bottom = x + (width - dw) / 2, y + (height - dh) / 2
    c.setFillColor(PALE)
    c.rect(x, y, width, height, fill=1, stroke=0)
    c.drawImage(ImageReader(str(file)), left, bottom, dw, dh, mask="auto")
    c.setLineWidth(.6)
    c.setStrokeColor(LINE)
    c.rect(left, bottom, dw, dh, fill=0, stroke=1)


def identify(row):
    raw = " ".join(str(row.get(key, "")) for key in ("id", "tab", "filename", "title"))
    tab = row.get("tab")
    key = str(row.get("id", ""))
    match = re.search(r"entry[_-]step[_-]([0-7])", raw)
    if match:
        return f"entry_{match[1]}"
    if key in COPIES:
        return key
    # The capture manifest also records the active tab behind entry/overview
    # screens. Only real tab captures should use it as their page identity.
    if (key.startswith("tab_") or key.startswith("report_")) and tab in COPIES:
        return tab
    aliases = [
        (r"login.*(admin|管理员)", "login_admin"), (r"login|用户登录", "login_user"),
        (r"register|会员", "register"), (r"privacy|隐私", "privacy"),
        (r"admin.*(bottom|recent|下|近期|授权)", "admin_recent"),
        (r"admin.*(middle|storage|中|存储|任务状态)", "admin_storage"),
        (r"admin|后台", "admin"), (r"school|学校选择", "school"),
        (r"video.*(audio|window|detail|bottom)|音轨|窗口详情", "video_audio"),
        (r"video_evidence|video_review|真实视频|视频证据", "video"),
        (r"upload.*(bottom|task|下)|任务列表", "upload_tasks"),
        (r"upload_workspace|真实上传|上传工作台", "upload"),
        (r"course_setup|course_standards|课程标准|课程基线", "course_setup"),
        (r"portrait|个体画面|人像", "portrait"),
        (r"group|群像|workspace", "group"), (r"nav|导航", "navigation"),
    ]
    for pattern, value in aliases:
        if re.search(pattern, raw, re.I):
            return value
    for key in sorted(COPIES, key=len, reverse=True):
        if re.search(rf"(?:^|[_\s-]){re.escape(key)}(?:$|[_\s.-])", raw):
            return key
    raise ValueError(f"No approved description for screenshot: {raw}")


def copy_for(row):
    key = identify(row)
    if key.startswith("entry_"):
        index = int(key.rsplit("_", 1)[1])
        title, operation, boundary = ENTRY_STEPS[index]
        return Copy(f"课程准备 {index + 1}/8：{title}", "历史演示分析 → 首次课程确认", "在查看结论前，明确本次分析的课程背景和解释口径。", operation,
                    "为后续课程适配、证据复核和报告提供一致的课堂上下文。", boundary, "课程配置流程")
    if key == "feedback" and not row.get("existing_report_replay"):
        return Copy("深度报告：生成入口", "分析导航 → 成长轨迹 → 深度报告", "在生成之前查看报告内容范围和当前写作引擎。", "检查复核情况和本地证据模板；点击生成后，系统会先保存核心复核信息，再生成报告。", "报告生成按钮、章节组成说明和LLM配置状态；下一组截图展示已有报告的阅读形态。", "此图是待生成界面。当前未配置第三方LLM；为避免修改真实复核记录，本次截图没有提交生成。", "本地规则报告")
    return COPIES[key]


def feature_page(c, row, number, total):
    copy = copy_for(row)
    title = copy.title
    raw_id = str(row.get("id", ""))
    if re.search(r"bottom|lower|end", raw_id):
        title += "：下半页 / 细节"
    frame(c, title, copy.entry, number, total)
    c.bookmarkPage(f"page_{number}")
    c.addOutlineEntry(title, f"page_{number}", level=1, closed=False)
    filename = row.get("filename") or row.get("file") or row.get("path")
    file = Path(filename)
    if not file.is_absolute():
        file = SHOTS / file
    if not file.is_file() or not file.resolve().is_relative_to(SHOTS.resolve()):
        raise ValueError("Screenshot is missing or outside the capture directory")
    screenshot(c, file, 35, 129, 825, 560)
    text(c, "界面用途", 35, 107, 825, 11, 17, True, BLUE)
    text(c, copy.purpose, 105, 107, 753, 11, 18, color=MUTED)
    x, top, width = 892, 697, W - 927
    color = BLUE if copy.kind == "实际页面" else GOLD
    text(c, copy.kind, x, top, width, 12, 18, True, color)
    top -= 48
    for label, body in (("怎样操作", copy.operation), ("可以得到什么", copy.result), ("理解边界", copy.boundary)):
        top -= section(c, label, body, x, top, width)
    if row.get("existing_report_replay"):
        text(c, "截图载入已有本地报告；未新提交教师复核。", x, top, width, 10, 17, color=MUTED)
    c.showPage()


def intro(c, count, total):
    frame(c, "课堂学习分析平台", "当前版本全界面与操作说明  |  经理演示与内部沟通用", 1, total)
    c.bookmarkPage("overview")
    c.addOutlineEntry("阅读说明", "overview", level=0)
    text(c, "从账号入口，到课堂证据、教师复核和数据管理", 35, 661, W - 70, 22, 32, True)
    text(c, f"本册使用2026年9月9日当前运行版本的{count}张实时界面截图。按实际操作顺序介绍每个页面，而不是将规划中的能力作为已完成功能展示。", 35, 605, W - 100, 15, 26)
    columns = [
        ("01  进入与提交", "私密邀请入口、用户/管理员登录、开通申请、学校选择和手动视频上传。四个账号绑定四个通道，每账号每课程5个有效上传名额。"),
        ("02  处理与查看", "新视频已接通本地解码、抽帧、音轨提取、20秒时间窗口和任务结果。历史课堂工作台另展示三人群像、档案、状态、复核和约千字报告。"),
        ("03  复核与留存", "教师可以围绕既有课堂关键片段核对初评。管理员查看真实任务与存储汇总。原片期限、到期提醒与长期归档授权分别管理。"),
    ]
    for index, (label, body) in enumerate(columns):
        x = 35 + index * 378
        c.setStrokeColor(LINE)
        c.line(x, 497, x + 340, 497)
        text(c, label, x, 475, 337, 16, 24, True, BLUE)
        text(c, body, x, 431, 337, 14, 24)
    text(c, "阅读时请区分两条数据链路", 35, 260, W - 70, 17, 26, True)
    text(c, "新上传视频 → 实际技术证据与任务结果；既有课堂资料 → 规则化状态与学习分析示例。后者还没有自动套用到任意新视频，不能把“证据就绪”理解成已识别专注、情绪或学会程度。", 35, 215, W - 100, 14, 25)
    text(c, "访问链接和账号由项目联系人另行提供；链接有效期与本机服务在线状态有关。本册不包含账号密码、私密邀请密钥或公开学生数据的链接。", 35, 111, W - 100, 11.5, 20, color=MUTED)
    c.showPage()


def index_page(c, rows, total):
    frame(c, "页面导览", "按顺序演示，也可使用PDF书签直接跳转", 2, total)
    c.bookmarkPage("contents")
    c.addOutlineEntry("页面导览", "contents", level=0)
    per_col = 19
    if len(rows) > per_col * 3:
        raise ValueError("Too many screenshots for this guide's navigation page")
    for i, row in enumerate(rows):
        col, line = divmod(i, per_col)
        x, top = 35 + col * 378, 684 - line * 30
        title = copy_for(row).title
        page_number = i + 3
        if len(title) > 23:
            title = title[:22] + "…"
        text(c, f"{page_number:02d}  {title}", x, top, 343, 10.5, 17)
        c.linkRect("", f"page_{page_number}", (x, top - 20, x + 340, top + 2), relative=0, thickness=0)
    c.showPage()


def closing(c, number, total):
    frame(c, "输入、输出与当前能力边界", "完整理解这一版，而不是只看页面数量", number, total)
    c.bookmarkPage("boundaries")
    c.addOutlineEntry("输入输出与当前边界", "boundaries", level=0)
    entries = [
        ("视频输入", "经授权导出的本地录像，由用户手动选择并上传；当前不是希沃自动同步、实时全校监控或自动识别人名。"),
        ("资料输入", "课程标准、学校考核口径、IEP及专业支持资料提供上下文；新文件提取结果和支持摘要仍须人工核对。"),
        ("实际输出", "任务进度、原片回放、音轨、按时间划分的技术证据及JSON结果；管理员可读取后台真实汇总。"),
        ("示例业务输出", "已有课堂资料驱动的状态、学习目标初评、支持效果、教师复核与约1000字课程报告；不是新视频已完成的通用语义理解。"),
        ("保留与访问", "本机SQLite与受控文件目录保存业务记录及文件；原片60天、提前15天平台内提醒。公司长期资源需单独授权与脱敏审核。"),
        ("尚待接通", "新录像的学生追踪、语音转写、师生互动识别、经过验证的学习判断、跨课长期测量及完整多学校隔离，需要后续实现与验证。"),
    ]
    top = 677
    for label, body in entries:
        text(c, label, 35, top, 140, 14, 23, True, BLUE)
        height = text(c, body, 204, top, W - 242, 13, 23)
        top -= max(61, height + 27)
        c.setStrokeColor(LINE)
        c.line(35, top + 12, W - 35, top + 12)
    text(c, "适合当前用途：内部演示、需求确认、授权资料整理与受控流程试用。不能据本册宣称已经达到临床诊断、教师绩效评定、学习成效因果验证或大规模无人值守部署水平。", 35, top - 19, W - 80, 13, 23, color=MUTED)
    c.showPage()


def main():
    data = json.loads((SHOTS / "manifest.json").read_text(encoding="utf-8-sig"))
    rows = data if isinstance(data, list) else data.get("pages", data.get("screenshots", []))
    if not rows:
        raise ValueError("No fresh screenshots in manifest")
    for row in rows:
        copy_for(row)
    expected_tabs = {"profile", "tracking", "profileImport", "state", "interaction", "evidence", "teacher", "mastery", "specialSupport", "action", "growth", "courseReport", "feedback", "summary", "videoUpload", "storage", "json"}
    covered = {identify(row) for row in rows}
    if not expected_tabs <= covered:
        raise ValueError(f"Missing analysis tabs: {sorted(expected_tabs - covered)}")
    expected_views = {f"entry_{i}" for i in range(8)} | {"group", "portrait", "course_setup", "navigation", "login_user", "login_admin", "school", "upload", "video", "admin"}
    if not expected_views <= covered:
        raise ValueError(f"Missing or misidentified interface views: {sorted(expected_views - covered)}")
    for name, file in (("Guide", "msyh.ttc"), ("Guide-Bold", "msyhbd.ttc")):
        pdfmetrics.registerFont(TTFont(name, str(Path("C:/Windows/Fonts") / file)))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    QA_DIR.mkdir(parents=True, exist_ok=True)
    total = len(rows) + 3
    c = canvas.Canvas(str(OUTPUT), pagesize=(W, H), pageCompression=1)
    c.setTitle("RehabAffect Demo2 全界面功能说明")
    c.setAuthor("云图智航 | RehabAffectPerception")
    c.setSubject("2026年9月9日当前版本：界面截图、操作、输入输出与实现边界")
    intro(c, len(rows), total)
    index_page(c, rows, total)
    c.bookmarkPage("screens")
    c.addOutlineEntry("逐页功能说明", "screens", level=0, closed=False)
    for i, row in enumerate(rows, 3):
        feature_page(c, row, i, total)
    closing(c, total, total)
    c.save()
    from pypdf import PdfReader
    reader = PdfReader(OUTPUT)
    assert len(reader.pages) == total
    extracted = "\n".join(page.extract_text() for page in reader.pages)
    assert all(word in extracted for word in ("管理员", "教师复核", "1000", "60天", "音轨"))
    assert "trycloudflare.com" not in extracted and "Teach101" not in extracted and "Admin101" not in extracted
    qa = {"pdf": str(OUTPUT), "pages": total, "screenshots": len(rows), "tabs": sorted(expected_tabs), "bytes": OUTPUT.stat().st_size,
          "all_expected_tabs": True, "contains_credentials": False, "needs_visual_qa": True}
    (QA_DIR / "build_summary.json").write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(qa, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
