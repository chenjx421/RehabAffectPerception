"""Illustrated change note, using verified screenshots without real pupils."""

from pathlib import Path
import json

from PIL import Image
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph
from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
LIVE = ROOT / 'output/playwright/demo2_teacher_flow_20260911_live'
ISOLATED = ROOT / 'output/playwright/demo2_teacher_flow_20260911_isolated'
OUTPUT = ROOT / 'output/pdf/Demo2_人员匹配与通道管理改动说明_20260911.pdf'
W, H = landscape(A4)
M, CW = 38, W - 76
BLUE = colors.HexColor('#2163C4')
INK = colors.HexColor('#252C36')
MUTED = colors.HexColor('#586677')
LINE = colors.HexColor('#DAE3EE')
PALE = colors.HexColor('#F0F6FE')


def paragraph(c, text, x, top, width, size=10.5, bold=False, color=INK, max_h=None):
    style = ParagraphStyle('body', fontName='YaHeiBold' if bold else 'YaHei',
                           fontSize=size, leading=size * 1.48, textColor=color, wordWrap='CJK')
    p = Paragraph(text, style)
    _, height = p.wrap(width, H)
    if max_h is not None and height > max_h:
        raise ValueError(f'Text exceeds allocated area: {text[:25]}')
    if top - height < 35:
        raise ValueError('Text overlaps footer')
    p.drawOn(c, x, top - height)
    return height


def header(c, n, title, subtitle):
    c.setFillColor(BLUE)
    c.rect(M, H - 32, 23, 3, fill=1, stroke=0)
    paragraph(c, 'RehabAffect  /  课堂学习分析平台 Demo2', M + 32, H - 25, 500, 8.5, color=MUTED)
    paragraph(c, title, M, H - 54, CW, 22, True)
    paragraph(c, subtitle, M, H - 90, CW, 10, color=MUTED)
    c.setStrokeColor(LINE)
    c.line(M, 29, W - M, 29)
    c.setFillColor(MUTED)
    c.setFont('YaHei', 8)
    c.drawString(M, 15, '功能改动说明  |  2026.09.11  |  不含真实学生画面或登录凭据')
    c.drawRightString(W - M, 15, f'{n:02d} / 05')


def shot(c, path, crop, x, top, width, label=None):
    # Clip in the PDF; keep the original screenshot bytes and aspect ratio.
    with Image.open(path) as im:
        iw, ih = im.size
    sx, sy, sw, sh = crop
    if min(sx, sy) < 0 or sx + sw > iw or sy + sh > ih:
        raise ValueError(f'Invalid screenshot crop: {path.name}')
    scale, dh = width / sw, sh * width / sw
    if top - dh < 35:
        raise ValueError('Screenshot overlaps footer')
    c.saveState()
    clip = c.beginPath()
    clip.rect(x, top - dh, width, dh)
    c.clipPath(clip, stroke=0, fill=0)
    c.drawImage(ImageReader(str(path)), x - sx * scale,
                top - dh - (ih - sy - sh) * scale, iw * scale, ih * scale)
    c.restoreState()
    c.setStrokeColor(LINE)
    c.setLineWidth(.5)
    c.rect(x, top - dh, width, dh, fill=0, stroke=1)
    if label:
        paragraph(c, label, x, top - dh - 6, width, 8.5, color=MUTED)
    return dh


def text_section(c, title, body, x, top, width):
    paragraph(c, title, x, top, width, 12, True, BLUE)
    return paragraph(c, body, x, top - 24, width, 10.5) + 36


def table(c, rows, widths, top, row_heights, x=M):
    cursor = top
    for index, (row, height) in enumerate(zip(rows, row_heights, strict=True)):
        c.setFillColor(PALE if index == 0 else colors.white)
        c.rect(x, cursor - height, sum(widths), height, fill=1, stroke=0)
        column_x = x
        for text, width in zip(row, widths, strict=True):
            paragraph(c, text, column_x + 11, cursor - 11, width - 22,
                      size=10 if index == 0 else 10.5, bold=index == 0,
                      color=BLUE if index == 0 else INK, max_h=height - 18)
            column_x += width
        c.setStrokeColor(LINE)
        c.line(x, cursor - height, x + sum(widths), cursor - height)
        cursor -= height
    return cursor


def build():
    for font, path in [('YaHei', 'C:/Windows/Fonts/msyh.ttc'), ('YaHeiBold', 'C:/Windows/Fonts/msyhbd.ttc')]:
        pdfmetrics.registerFont(TTFont(font, path))
    live_report = json.loads((LIVE / 'screenshots.json').read_text(encoding='utf-8'))
    isolated_report = json.loads((ISOLATED / 'teacher_flow.json').read_text(encoding='utf-8'))
    assert live_report['complete'] and isolated_report['complete']
    assert isolated_report['savedThroughPointerAndForm'] and isolated_report['reopened_db_bindings_preserved']
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(OUTPUT), pagesize=(W, H), pageCompression=1)
    c.setTitle('Demo2 人员匹配与通道管理改动说明')
    c.setAuthor('RehabAffectPerception')
    c.setSubject('教师姓名匹配、人工补框、短时位置建议及真实通道管理')

    header(c, 1, '从画面到姓名，让教师更容易完成确认', '本次重点：简化常用操作，补齐自动检测失败时的人工路径，并让后台通道配置真正生效。')
    rows = [
        ['改动', '现在可以做什么', '对使用者的作用'],
        ['姓名匹配简化', '选中画面中的人，选择姓名，再确认；默认角色为学生。', '普通操作不用填写坐标或先选择人员角色。'],
        ['手动补框可保存', '没有检测候选时，仍可拖动画框并绑定姓名；确认记录写入数据库。', '遇到漏检也能继续核对，不必等待检测成功。'],
        ['后续 5 秒位置建议', '从已确认的学生记录查看短时位置变化；需要教师逐条核对。', '辅助观察相邻时刻，跟丢时停止，避免自动记错人。'],
        ['后台通道可管理', '编辑通道名称、负责人备注、每课 3 至 5 个名额，并暂停或恢复新上传。', '设置保存后生效，暂停不影响历史视频及已开始任务。'],
    ]
    end = table(c, rows, [122, 345, CW - 467], H - 129, [36, 66, 66, 66, 66])
    text_section(c, '教师常用路径', '课程上传工作台 → 打开对应视频的人员确认 → 选中人或画框 → 选择姓名 → 确认。<br/>首次使用仍需核对学校和准备学生名单；已有名单的日常操作更短。', M, end - 20, CW)
    paragraph(c, '范围说明：本次围绕人员确认与通道管理改进；保留既有课程、档案、教师复核和报告入口，不代表新增了完整自动学情判断能力。', M, 74, CW, 9, color=MUTED)
    c.showPage()

    header(c, 2, '姓名匹配：常用操作收敛为三步', '点击检测候选或手动画框，选择本校姓名，点击“确认姓名”。名单缺人时，可直接在当前页新增。')
    shot(c, ISOLATED / 'manual_reloaded.png', (18, 280, 1334, 660), M, H - 126, CW,
         '合成验证页面：右侧为姓名匹配区；坐标和其他人员角色收在“高级”内。绿色框对应已经保存的教师确认。')
    paragraph(c, '同名学生通过编号和班级区分；系统检测人脸位置，不自动猜测姓名。', M, 62, CW, 9.5, color=MUTED)
    c.showPage()

    header(c, 3, '漏检时能手动补框，保存后能回看核对', '手动框选不依赖人脸检测成功。下方截图来自实际提交表单、刷新页面并重开测试数据库后的结果。')
    shot(c, ISOLATED / 'manual_reloaded.png', (88, 552, 510, 380), M, H - 130, 292,
         '合成画面局部：绿色区域和姓名为已保存的确认，非真实学生。')
    x, y, width = M + 323, H - 130, CW - 323
    y -= text_section(c, '漏检与部分遮挡', '点击“手动画框”并拖出矩形，再选择姓名确认。与另一名学生区域高度重叠时会要求核对；几乎相同的框不能绑定成两个人，完全遮挡时应换一个清楚时刻。', x, y, width)
    y -= text_section(c, '短时位置跟随', '在确认记录上点击“查看后续5秒”。系统最多读取起始帧和后续五张采样帧，提供位置建议；采用建议后仍需确认姓名才保存，跟丢即停止。', x, y, width)
    paragraph(c, '这不是整节课自动身份追踪；低清晰度、快速移动、相似人物干扰或遮挡，都可能使建议不可用。', x, y, width, 9.5, color=MUTED)
    paragraph(c, '确认记录与后续操作', M, 173, CW, 11.5, True, BLUE)
    shot(c, ISOLATED / 'manual_reloaded.png', (18, 1335, 1334, 133), M, 151, CW,
         '记录保留姓名、时间和确认状态，可返回画面、查看后续位置或撤销误认。撤销不会删除其他学生的记录。')
    c.showPage()

    header(c, 4, '公司后台：四个通道现在可以实际配置', '入口：公司后台 → 管理上传通道 → 选择“设置”。可修改名称、负责人备注、名额及新上传状态。')
    shot(c, LIVE / 'admin_channels_1366.png', (91, 275, 1183, 472), M, H - 128, CW,
         '当前实际后台页面。截图为未修改状态，所以“保存设置”呈禁用；修改有效字段后才能提交。')
    top = 134
    text_section(c, '暂停不影响已有任务', '仅阻止新建上传；历史视频、已有上传的续传与分析保持可用。', M, top, 235)
    text_section(c, '名额调整有约束', '每个绑定账号按课程设置 3 至 5 个名额；已有课程占用超限时，不能继续下调。', M + 263, top, 235)
    text_section(c, '保存结果可核对', '保存后重读数据库确认。配置冲突会提示核对，修改前后值写入审计记录。', M + 526, top, CW - 526)
    c.showPage()

    header(c, 5, '哪些需要确认，哪些已经验证', '把“不能操作的原因”说明白，同时避免把演示和测试结果当成真实课堂识别准确率。')
    rows = [
        ['使用中遇到的情况', '页面如何处理 / 使用者怎么做'],
        ['旧视频未记录学校', '可以画草稿；先核对城市、区县及实际学校归属，再保存姓名。确认学校后保留原框选草稿。'],
        ['人员确认与后台权限', '学校教师确认视频中的学生；公司管理员只读查看人员记录，并管理通道，不能代替学校绑定姓名。'],
        ['图片不可用或视频到期', '显示原因，停止新增确认；不能在没有有效画面的情况下生成身份记录。'],
        ['保存后遇到网络异常', '先刷新核对是否已经保存，避免重复创建；迟到的检测结果不会覆盖人工画框。'],
    ]
    end = table(c, rows, [182, CW - 182], H - 128, [34, 53, 53, 48, 48])
    left, right = 367, CW - 395
    text_section(c, '已完成的功能验证', '教师流程接口 53 项通过；身份界面回归 44 项通过。<br/>隔离浏览器已验证：检测不可用时拖框保存成功，刷新和数据库重开后姓名与位置保留。<br/>本地教师 / 管理员页面完成桌面和手机 16 组检查。', M, end - 20, left)
    text_section(c, '当前仍需注意', '首次学校设置和名单准备还不是完全自动的引导流程。短时跟随可能失败，尚未完成真实课堂连续身份追踪的准确率验证。<br/>本次未改变保留期限，也未新增外部模型 API。当前运行入口仍是本机地址，不是可直接转发的公网链接。', M + 395, end - 20, right)
    c.showPage()
    c.save()

    reader = PdfReader(str(OUTPUT))
    assert len(reader.pages) == 5
    texts = [page.extract_text() for page in reader.pages]
    for index, text in enumerate(texts):
        assert len(text) > 160, (index, 'Missing selectable Chinese text')
        assert '\ufffd' not in text
    assert all(word in '\n'.join(texts) for word in ['手动画框', '后续5秒', '通道', '53', '44'])
    qa = {'pages': len(reader.pages), 'page_text_characters': list(map(len, texts)),
          'output_bytes': OUTPUT.stat().st_size, 'contains_real_student_screenshots': False,
          'screenshots': ['isolated/manual_reloaded.png', 'live/admin_channels_1366.png']}
    qa_dir = ROOT / 'tmp/pdfs/demo2_teacher_changes_20260911'
    qa_dir.mkdir(parents=True, exist_ok=True)
    (qa_dir / 'build_qa.json').write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding='utf-8')
    print(OUTPUT)
    print(json.dumps(qa, ensure_ascii=False))


if __name__ == '__main__':
    build()
