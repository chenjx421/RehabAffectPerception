"""Illustrated dossier delivery note. Requires completed isolated browser QA."""

import json
from pathlib import Path

from PIL import Image
from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph


ROOT = Path(__file__).resolve().parents[1]
SHOTS = ROOT / 'output/playwright/demo2_dossier_20260911_isolated'
QA = ROOT / 'tmp/dossier_delivery_verification_20260911.json'
OUTPUT = ROOT / 'output/pdf/Demo2_学生档案关联与资料管理说明_20260911.pdf'
W, H = landscape(A4)
M, CW = 38, W - 76
INK, BLUE, MUTED = map(colors.HexColor, ['#203044', '#215FB4', '#58697E'])
LINE, PALE = map(colors.HexColor, ['#D6E1ED', '#F0F6FF'])


def text(c, value, x, top, width, size=10.5, bold=False, color=INK, max_height=None):
    paragraph = Paragraph(value, ParagraphStyle('dossier', fontName='YaHeiBold' if bold else 'YaHei',
                          fontSize=size, leading=size * 1.5, textColor=color, wordWrap='CJK'))
    _, height = paragraph.wrap(width, H)
    if top - height < 39 or (max_height is not None and height > max_height):
        raise ValueError('Text outside allocated area: ' + value[:35])
    paragraph.drawOn(c, x, top - height)
    return height


def header(c, number, title, subtitle):
    c.setFillColor(BLUE)
    c.rect(M, H - 31, 22, 3, fill=1, stroke=0)
    text(c, 'RehabAffect  /  课堂学习分析平台 Demo2', M + 31, H - 25, 520, 8.5, color=MUTED)
    text(c, title, M, H - 53, CW, 22, True)
    text(c, subtitle, M, H - 91, CW, 10, color=MUTED)
    c.setStrokeColor(LINE)
    c.line(M, 29, W - M, 29)
    c.setFont('YaHei', 8)
    c.setFillColor(MUTED)
    c.drawString(M, 15, '2026.09.11  |  功能与使用说明  |  页面内容均为隔离环境虚构资料')
    c.drawRightString(W - M, 15, f'{number:02d} / 07')


def screenshot(c, filename, x, top, width, height_limit, *, crop=None):
    path = SHOTS / filename
    with Image.open(path) as im:
        iw, ih = im.size
    sx, sy, sw, sh = crop or (0, 0, iw, ih)
    if min(sx, sy) < 0 or sx + sw > iw or sy + sh > ih:
        raise ValueError('Invalid image crop ' + filename)
    scale = min(width / sw, height_limit / sh)
    dw, dh = sw * scale, sh * scale
    if top - dh < 39:
        raise ValueError('Screenshot overlaps footer')
    c.saveState()
    clip = c.beginPath()
    clip.rect(x, top - dh, dw, dh)
    c.clipPath(clip, stroke=0, fill=0)
    c.drawImage(ImageReader(str(path)), x - sx * scale,
                top - dh - (ih - sy - sh) * scale, iw * scale, ih * scale)
    c.restoreState()
    c.setLineWidth(.5)
    c.setStrokeColor(LINE)
    c.rect(x, top - dh, dw, dh, fill=0, stroke=1)
    return dh


def section(c, title, body, x, top, width):
    text(c, title, x, top, width, 12, True, BLUE)
    return 25 + text(c, body, x, top - 25, width) + 17


def table(c, rows, widths, heights, top):
    for index, (row, height) in enumerate(zip(rows, heights, strict=True)):
        c.setFillColor(PALE if index == 0 else colors.white)
        c.rect(M, top - height, CW, height, fill=1, stroke=0)
        x = M
        for cell, width in zip(row, widths, strict=True):
            text(c, cell, x + 10, top - 10, width - 20, 10.3, index == 0,
                 BLUE if index == 0 else INK, max_height=height - 16)
            x += width
        c.setStrokeColor(LINE)
        c.line(M, top - height, W - M, top - height)
        top -= height
    return top


def build():
    global SHOTS
    verification = json.loads(QA.read_text(encoding='utf-8'))
    assert verification['isolated_browser_passed'] and verification['local_smoke_passed']
    assert verification['contains_real_student_material'] is False
    SHOTS = (ROOT / verification['screenshot_directory']).resolve()
    assert SHOTS.is_relative_to(ROOT / 'output/playwright/demo2_dossier_20260911_isolated')
    browser = json.loads((SHOTS / 'browser_report.json').read_text(encoding='utf-8'))
    assert browser['ok'] and browser['fixture_only'] and browser['fictional_authorization']
    assert not browser['page_errors'] and not browser['server_errors'] and not browser['external_requests']
    assert json.loads((SHOTS / 'harness_report.json').read_text())['isolated_server_closed']
    for name, filename in [('YaHei', 'msyh.ttc'), ('YaHeiBold', 'msyhbd.ttc')]:
        pdfmetrics.registerFont(TTFont(name, 'C:/Windows/Fonts/' + filename))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(OUTPUT), pagesize=(W, H), pageCompression=1)
    c.setTitle('Demo2 学生档案关联与资料管理说明')
    c.setAuthor('RehabAffectPerception')
    c.setSubject('学生身份、授权资料版本、课堂引用、公司运维元数据与使用边界')

    header(c, 1, '让视频与资料对应到同一个学生', '不是只存视频，也不是把所有文件混在一起；通过学生编号、版本和课堂身份确认建立可核对的关联。')
    rows = [
        ['资料', '在本轮功能中如何保存和关联', '使用者能得到什么'],
        ['学生与视频', '使用学校范围内的学生编号，<br/>关联教师确认的画面位置、时间及视频采样版本。', '同名不自动合并；<br/>漏检仍可人工框选后确认。'],
        ['IEP / 专业评估', '按学生保存授权摘要，可选上传原件；<br/>每次更新生成独立版本。', '知道资料来自哪里、何时形成、<br/>哪一版有效。'],
        ['课堂引用', '选择已确认学生与材料版本，<br/>记录本节课采用的资料依据。', '新IEP不覆盖旧课堂引用；<br/>失效来源有标记。'],
        ['公司运维后台', '显示资料数量、可用与到期状态、<br/>待清理数量和密文存储占用。', '管理系统运行，<br/>不默认查看学生诊断内容。'],
    ]
    end = table(c, rows, [112, 374, CW - 486], [34, 65, 65, 65, 65], H - 129)
    section(c, '一条完整的教师操作路径', '登录并核对学校 → 选择学生 → 登记资料授权 → 录入IEP或评估版本 → 在视频中确认学生 → 保存课堂资料引用 → 复核或下载引用记录。', M, end - 20, CW)
    text(c, '本轮新增的是资料关联与受限存储能力，不是通过视频推断疾病，也不代表已完成全校自动学情分析。', M, 68, CW, 9.5, color=MUTED)
    c.showPage()

    header(c, 2, '先确认学生，再登记资料授权', '教师入口：学生名册 → 资料档案 → 授权与期限。所有资料都先归属到明确的学生，不按名称猜测。')
    screenshot(c, 'student_authorization.png', M, H - 129, 357, 373, crop=(710, 523, 585, 612))
    x, y, width = M + 390, H - 134, CW - 390
    y -= section(c, '授权需要写清楚', '填写学校授权依据或编号、资料处理方式及截止日期。界面确认是教师的操作留痕，不能代替实际授权。', x, y, width)
    y -= section(c, '摘要模式可以不传原件', '只保存获准且必要的教学摘要，原件仍可由学校保管。摘要仍与学生关联，也需要限制用途和期限。', x, y, width)
    section(c, '保存期限有上限', '新增资料最长60天，可设置更短期限。所选日期零点起停止访问；资料不得超出授权期限。', x, y, width)
    text(c, '截图来自真实表单操作，但学生和授权编号均为虚构测试数据，不是校方签署记录。', M, 64, CW, 9, color=MUTED)
    c.showPage()

    header(c, 3, 'IEP与评估资料：有来源、有版本、有期限', '资料类型覆盖IEP、专业评估、五领域评估、安全与支持资料；专业结论只能依据已有材料录入。')
    first = screenshot(c, 'student_documents.png', M, H - 128, 360, 294, crop=(82, 664, 586, 470))
    screenshot(c, 'student_documents.png', M, H - 138 - first, 360, 88, crop=(82, 1143, 586, 142))
    x, y, width = M + 390, H - 132, CW - 390
    y -= section(c, '录入四类必要信息', '学习目标、支持方法、安全注意事项和已有专业结论。未获得材料支持的项目应留空，系统不生成诊断。', x, y, width)
    y -= section(c, '更新不覆盖历史', '新增版本保留各自来源和有效期限。教师可核对原件、保存新版本或删除指定版本。', x, y, width)
    section(c, '原件按需保存', '单份原件不超过8 MiB，支持PDF、DOCX、PNG、JPG和UTF-8文本。原件与新增摘要均加密保存。', x, y, width)
    text(c, '原件不自动OCR或抽取结论；页面中的摘要由教师录入。15天内将到期的有效资料显示站内提示，不发送短信。', M, 64, CW, 9, color=MUTED)
    c.showPage()

    header(c, 4, '把这节课与当时采用的资料版本连起来', '视频任务 → 关联学生资料。只有当前视频版本中已经确认身份的学生，才可以新增课堂引用。')
    screenshot(c, 'course_reference.png', M, H - 126, CW, 324, crop=(76, 366, 1220, 648))
    y = 131
    section(c, '身份依据', '记录视频来源、采样版本和已确认画面；撤销或重处理后，旧引用显示身份依据失效。', M, y, 238)
    section(c, '资料依据', '记录所选1至10个具体版本，不会因为后来更新IEP就自动替换以前的依据。', M + 264, y, 238)
    section(c, '下载与复核', '导出JSON引用记录时重新检查有效性；这不是新增的千字报告或自动医学分析。', M + 529, y, CW - 529)
    c.showPage()

    header(c, 5, '公司后台管理存储状态，不默认展示隐私正文', '公司后台 → 资料存储概览。管理员与学校教师使用不同权限，知道“存了多少”和“是否需要清理”。')
    screenshot(c, 'admin_dossiers.png', M, H - 127, CW, 333, crop=(80, 209, 1210, 518))
    y = 121
    section(c, '后台可见', '数量、可用/到期状态、待清理与密文占用。图中已撤回授权，因此可用版本和文件占用为0。', M, y, 354)
    section(c, '后台不可见', '本模块不返回学生姓名、摘要、专业结论、原件文件名或原件下载内容。', M + 391, y, CW - 391)
    c.showPage()

    header(c, 6, '撤回或到期后，停止访问并清理', '不能只把页面上的“有效”改成“无效”；下载接口、课堂引用和后台清理也要一起处理。')
    screenshot(c, 'authorization_withdrawn.png', M, H - 128, 369, 260, crop=(80, 597, 593, 361))
    text(c, '同一位学生的版本1已撤回、版本2已删除。来源、摘要、原件名和下载按钮不再显示。', M, 200, 363, 10, color=MUTED)
    x, y, width = M + 400, H - 132, CW - 400
    y -= section(c, '撤回有实际作用', '撤回授权后，相应摘要与原件不再提供；旧课堂引用保留失效标记，不恢复删除内容。', x, y, width)
    y -= section(c, '失败清理会留状态', '文件无法删除时标记为待清理并重试，期间仍拒绝访问，不报称已经彻底删除。', x, y, width)
    section(c, '仍需组织管理', '用户已下载副本、历史备份、磁盘快照与旧案例库，不在本轮自动删除范围内。', x, y, width)
    text(c, '后台定时维护间隔不超过60秒；资料请求也检查期限。60天是试点技术上限，不是法律统一要求的保存时长。', M, 64, CW, 9, color=MUTED)
    c.showPage()

    header(c, 7, '本轮完成什么，正式落地还需要什么', '本版本适合演示流程与受控功能测试；不能把自动化测试通过数表述为真实课堂识别准确率。')
    rows = [
        ['项目', '本版本范围与仍需落实的条件'],
        ['学生与资料关系', '新版名册、授权资料与视频身份记录可关联；旧全局案例入口暂停，原代码与数据保留，待核对后重新导入。'],
        ['存储与访问', '新增敏感元数据和原件加密，教师按账号及学校隔离，管理员仅看本模块运维汇总。旧数据库、视频与备份不是因此全部加密。'],
        ['验证与演示', verification['pdf_test_summary']],
        ['部署准备', '当前为本机运行。正式服务仍需HTTPS、独立服务账号、密钥备份与恢复演练、访问审计和学校多人协作权限。'],
        ['实际数据使用', '明确学校与公司职责、处理目的、授权范围及删除程序；本轮未接外部LLM、未授权模型训练或公司永久归档。'],
    ]
    end = table(c, rows, [113, CW - 113], [34, 52, 58, 58, 53, 54], H - 127)
    text(c, '重要边界：教师仍需判断材料是否适用。本次课堂引用只是可核对的资料依据，尚未自动进入既有千字分析报告。', M, end - 16, CW, 10)
    text(c, '规则参考：《中华人民共和国个人信息保护法》第19、21、28至31、51、55条。实际法律适用需结合学校与公司的处理关系核定；加密和页面确认不等于完成合规验收。', M, 96, CW, 8.8, color=MUTED)
    text(c, '<link href="https://www.cac.gov.cn/2021-08/20/c_1631050028355286.htm" color="#215FB4">来源：中国网信网《中华人民共和国个人信息保护法》全文（本次核对：2026-09-11）</link>', M, 61, CW, 8.8)
    c.showPage()
    c.save()

    reader = PdfReader(str(OUTPUT))
    assert len(reader.pages) == 7
    page_text = [page.extract_text() for page in reader.pages]
    assert all(len(value) > 150 and '\ufffd' not in value for value in page_text)
    report = {'pages': 7, 'page_text_characters': list(map(len, page_text)),
              'bytes': OUTPUT.stat().st_size, 'real_student_material': False}
    directory = ROOT / 'tmp/pdfs/demo2_dossier_20260911'
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'build_qa.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))
    print(OUTPUT)


if __name__ == '__main__':
    build()
