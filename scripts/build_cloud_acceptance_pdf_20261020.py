"""Build the local Chinese acceptance brief; no network, cloud or DB access.

Re-run after public-large-upload-2202.json is finalized. Missing, partial or
insufficient worker evidence is always reported as pending, never as a pass.
All figures are crops of supplied screenshots, not reconstructed interfaces.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
from xml.sax.saxutils import escape
import zipfile

from PIL import Image
from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph, Table, TableStyle


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / 'output/pdf/云端迁移与上传修复验收_20261020.pdf'
INK, MUTED, TEAL, AMBER = map(HexColor, ('#22313b', '#5c6b73', '#127b70', '#9a5b13'))
LINE, WASH = HexColor('#dce5e8'), HexColor('#f1f6f6')


def read_json(path):
    try:
        value = json.loads(path.read_text(encoding='utf-8-sig'))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def worker_verdict(value):
    """Fail closed; a successful upload alone is not a completed worker run."""
    if not value:
        return '待验收', '最终报告尚未生成或尚未写完；不据此宣称处理完成。'
    if value.get('status') == 'failed' or value.get('ok') is False:
        return '未通过 / 待复验', '最终报告记录失败；需定位并复验，不能标为完成。'
    upload, analysis = value.get('large_upload'), value.get('analysis')
    if isinstance(upload,dict) and isinstance(analysis,dict):
        seconds = analysis.get('seconds_including_queue')
        valid_seconds = type(seconds) in (float,int) and math.isfinite(seconds) and seconds > 0
        if (value.get('ok') is True and upload.get('sha256_verified') is True and valid_seconds
                and all(analysis.get(k) is True for k in
                    ('technical_report_available','admin_report_download','admin_media_range'))):
            return '已通过', ('视频处理摘要可用、后台报告下载与视频读取检查通过；'
                f'分析含队列耗时 {seconds:.3f} 秒（约 {round(seconds)//60} 分 {round(seconds)%60} 秒），'
                '上传源文件 hash 已核验。')
    checks = value.get('checks', [])
    passed = {c.get('name') for c in checks if isinstance(c, dict) and c.get('passed') is True}
    finished = value.get('status') == 'passed' or value.get('ok') is True
    ready = value.get('analysis_status') in {'evidence_ready', 'completed'} or 'worker_ready' in passed
    bound = 'worker_result_source_sha256' in passed
    if finished and ready and bound:
        return '已通过', '最终报告确认 worker 就绪，且处理结果与原视频 SHA-256 对应。'
    return '待验收', '报告未同时确认 worker 就绪与结果来源 hash；上传完成不等于处理完成。'


class Brief:
    def __init__(self, output, screenshots):
        self.output, self.screenshots = output, screenshots
        self.w, self.h = landscape(A4)
        self.c = Canvas(str(output), pagesize=(self.w, self.h), pageCompression=1)
        self.c.setTitle('云端迁移与上传修复验收 | 2026-10-20')
        self.c.setAuthor('RehabAffect 项目验收')
        self.c.setSubject('迁移一致性、上传链路、真实样本技术证据及已知边界')
        self.page, self.figures = 0, []
        self.styles = {}
        for name, size, leading, color in [('body',11,18,INK), ('small',9,14,MUTED),
                ('caption',8.5,12,MUTED), ('lead',14,23,INK)]:
            self.styles[name] = ParagraphStyle(name, fontName='YaHei', fontSize=size,
                leading=leading, textColor=color, wordWrap='CJK', spaceAfter=0)

    def text(self, text, x, top, width, style='body'):
        p = Paragraph(text, self.styles[style])
        _, height = p.wrap(width, 1000)
        if top + height > self.h - 35:
            raise ValueError(f'Text overflow on page {self.page}')
        p.drawOn(self.c, x, self.h - top - height)
        return top + height

    def start(self, title, subtitle):
        if self.page:
            self.c.showPage()
        self.page += 1
        c = self.c
        c.setFillColor(TEAL)
        c.rect(0, self.h - 7, self.w, 7, fill=1, stroke=0)
        c.setFont('YaHei',9)
        c.setFillColor(MUTED)
        c.drawString(40, self.h - 31, 'REHABAFFECT  /  云端阶段验收  /  2026-10-20')
        c.setFont('YaHei-Bold',23)
        c.setFillColor(INK)
        c.drawString(40, self.h - 66, title)
        self.text(subtitle, 40, 79, self.w - 80, 'small')
        c.setStrokeColor(LINE)
        c.line(40, 29, self.w - 40, 29)
        c.setFont('YaHei',8)
        c.setFillColor(MUTED)
        c.drawString(40, 15, '迁移与上传链路验收，不是全功能图册；截图遮罩为隐私处理。')
        c.drawRightString(self.w - 40, 15, f'{self.page:02d} / 08')

    def table(self, rows, top, widths, x=40):
        cells = [[Paragraph(escape(str(v)), self.styles['body']) for v in row] for row in rows]
        table = Table(cells, colWidths=widths, hAlign='LEFT')
        table.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,0),WASH), ('LINEBELOW',(0,0),(-1,0),0.8,LINE),
            ('LINEBELOW',(0,1),(-1,-1),0.4,LINE), ('VALIGN',(0,0),(-1,-1),'TOP'),
            ('LEFTPADDING',(0,0),(-1,-1),10), ('RIGHTPADDING',(0,0),(-1,-1),10),
            ('TOPPADDING',(0,0),(-1,-1),9), ('BOTTOMPADDING',(0,0),(-1,-1),9),
        ]))
        _, height = table.wrap(self.w - 80, self.h)
        if top + height > self.h - 40:
            raise ValueError(f'Table overflow on page {self.page}')
        table.drawOn(self.c, x, self.h - top - height)
        return top + height

    def figure(self, relative, box, x, top, maxw, maxh, label):
        path = self.screenshots / relative
        with Image.open(path) as original:
            if not (0 <= box[0] < box[2] <= original.width and 0 <= box[1] < box[3] <= original.height):
                raise ValueError(f'Invalid crop: {relative}')
            crop = original.crop(box).convert('RGB')
            scale = min(maxw / crop.width, maxh / crop.height)
            width, height = crop.width * scale, crop.height * scale
            self.c.drawImage(ImageReader(crop), x, self.h - top - height,
                width=width, height=height, mask='auto')
        caption = f'{label}  |  {relative}  |  选区 x={box[0]}..{box[2]}, y={box[1]}..{box[3]} px'
        self.text(escape(caption), x, top + height + 6, maxw, 'caption')
        self.figures.append({'page':self.page, 'source':relative, 'crop_px':list(box),
                             'width_pt':round(width,2), 'height_pt':round(height,2)})
        return top + height + 34


def validate_browser(value, directory, expected):
    if not value or value.get('ok') is not True or value.get('mocked_responses') is not False:
        raise ValueError(f'Browser acceptance not passed: {directory.name}')
    accounts = value.get('accounts', {})
    if not accounts or not all(r.get('ok') is True for r in accounts.values()):
        raise ValueError('Incomplete account browser evidence')
    listed = [name for row in accounts.values() for name in row.get('screenshots', [])]
    actual = sorted(p.name for p in directory.glob('*.png'))
    if len(actual) != expected or sorted(listed) != actual:
        raise ValueError('Screenshot list/count mismatch')


def build(args):
    pdfmetrics.registerFont(TTFont('YaHei', str(args.font)))
    pdfmetrics.registerFont(TTFont('YaHei-Bold', str(args.bold_font)))
    pdfmetrics.registerFontFamily('YaHei', normal='YaHei', bold='YaHei-Bold')
    synthetic = read_json(args.screenshots / 'synthetic/acceptance.json')
    real = read_json(args.screenshots / 'real/acceptance.json')
    validate_browser(synthetic, args.screenshots / 'synthetic', 22)
    validate_browser(real, args.screenshots / 'real', 12)
    final = read_json(args.final_report)
    verdict, detail = worker_verdict(final)
    recheck = read_json(ROOT / '.runtime/cloud_deploy_20261020/real-sample-recheck-20261020c.json')
    login = read_json(ROOT / '.runtime/cloud_deploy_20261020/public-login-smoke-2201.json')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    b = Brief(args.output, args.screenshots)
    width = b.w - 80

    b.start('云端迁移与上传修复验收', '阶段验收草稿' if verdict != '已通过' else '阶段验收更新版')
    b.text('迁移数据保持一致，四真实样本技术链路复验通过。<br/>公网大文件上传已测得传输耗时，其 worker 结论单独验收。',40,118,width,'lead')
    end = b.table([
        ['验收层面','本轮证据与结论'],
        ['来源数据迁移','原 5 账号、44 任务、45 张表与 source snapshot 完全一致；41 个原视频 hash 校验通过。'],
        ['云端回归','Linux：240 passed、8 skipped；跳过项与 Node 未安装有关，不算通过。'],
        ['真实浏览器','合成样本 22 张 + 真实样本 12 张 PNG；两份 acceptance.json 均 ok=true。'],
        ['公网访问','HTTPS 公网 4 个学校账号 + 1 个管理员实际登录成功；与 loopback 浏览器证据分开统计。'],
        ['大文件 worker',verdict + '。' + detail],
    ],188,[130,width-130])
    b.text('本报告只验收云端迁移、上传修复及视频技术处理结果，不据此宣称教育评分、课堂语义理解或人脸识别已经全自动实现。',40,end+16,width)

    b.start('公网直传：传输与处理分开验收', '测速对象为本次电脑到云端的链路，不是校方网络承诺。')
    end = b.table([
        ['项目','测得值 / 当前状态'],
        ['上传体积','553,697,450 bytes（十进制约 553.7 MB）；SHA-256 verified = true'],
        ['上传耗时','206.859 秒，约 3 分 27 秒'],
        ['平均传输速率','21.414 Mbps；以 bytes × 8 ÷ seconds ÷ 1,000,000 计算'],
        ['本次大文件 worker',verdict + '。' + detail],
    ],118,[155,width-155])
    b.text('<b>四真实视频首轮 worker 等待</b>（包含排队）：Sample01 351.243 秒；Sample02 305.924 秒；Sample03 330.869 秒；Sample04 280.733 秒。它们是另一轮样本运行，不能替代本次公网大文件结果。',40,end+16,width)
    b.text('<b>修复与复验：</b>第 4 个样本因音频尾点舍入相差 21 微秒，触发摘要拒绝；该问题已修复，既有四真实样本 HTTP 复验 4/4 通过。此处不把首轮失败抹去，也不把等待时间解释为纯推理时间。',40,end+80,width)
    rule = ('本次构建已读取最终公网报告，上传 hash、技术报告、管理员报告下载与媒体 Range 均已确认。'
        '重建仍会重新检查报告字段，不沿用上一次构建状态。' if verdict == '已通过' else
        '自动重建规则：按最终报告核对上传 hash 与技术报告 / 下载 / Range。'
        '文件缺失、JSON 未写完或证据字段不足，一律保留“待验收”。')
    b.text(rule,40,510,width,'small')

    b.start('合成任务：任务状态与管理视图', '以下为实际页面截图选区；不是重新绘制的界面。合成样本 runner 另行验证浏览器播放。')
    b.figure('synthetic/school-1-02-upload-list.png',(120,855,1000,1315),40,118,490,270,'本课任务：上传完成与证据就绪分开记录')
    b.text('合成浏览器验收覆盖四校及管理员；每校包括登录、上传列表、处理结果、移动端及下载。管理员包括登录与管理页。',555,122,245)
    b.text('22 张截图整体通过。截图本身只展示页面状态；播放与下载结果来自 runner 的实际断言和下载事件。',555,220,245)
    b.figure('synthetic/admin-02-dashboard.png',(110,75,1320,360),40,407,width,110,'管理员页顶部选区；管理查询通过不等于可读取学生档案')

    b.start('真实视频：技术指标与分片', '示例为 Sample01；其余三校同样通过 source-bound 校验，人员与观察记录均为空。')
    b.figure('real/school-1-01-analysis-desktop.png',(240,270,1410,480),40,118,width,143,'桌面端：当前源视频的技术指标')
    b.figure('real/school-1-01-analysis-desktop.png',(900,490,1410,800),450,290,350,225,'分片列表上部选区；不要求播放真实人脸')
    b.text('<b>技术事实，不是教育结论</b><br/>页面展示视频时长、解码帧、采样帧、处理时间片与音频覆盖。音频覆盖不是说话时长，画面变化也不是学生参与度。',40,300,380)
    b.text('每校读取精确命名任务及受控清单 hash，验证技术证据与自动报告对应当前任务 / 视频版本；出现人员或观察记录即拒绝截图。',40,405,380)

    b.start('移动端：保留可读的实际选区', '同一张 390 px 宽截图分区展示，不把整张长图缩成不可读的缩略图。坐标以原 PNG 左上角为原点。')
    b.figure('real/school-1-02-analysis-mobile.png',(0,460,390,780),40,118,320,275,'移动端技术指标选区')
    b.figure('real/school-1-02-analysis-mobile.png',(0,1120,390,1640),445,118,310,403,'移动端时间片选区')
    b.text('真实样本 runner 不等待视频播放，也不以 videoWidth 证明回放。真实媒体区域已遮罩；浏览器播放由合成样本另验。',40,430,350)

    b.start('自动报告：来源绑定与下载', '技术摘要报告只记录视频处理事实；尚未形成学生学习或教学效果评价。')
    b.figure('real/school-1-03-report.png',(240,330,1235,570),40,118,width,255,'真实自动报告顶部选区；完整长图另附')
    b.text('四校均产生真实 UI 下载事件，记录字节数与 SHA-256；未保留原始下载 HTML。以下为各样本下载大小，事件均通过。',40,395,width)
    rows = [['样本','报告下载大小','样本','报告下载大小']]
    for left,right in ((1,2),(3,4)):
        rows.append([f'Sample{left:02d}',f"{real['accounts'][f'school-{left}']['download']['bytes']:,} bytes",
            f'Sample{right:02d}',f"{real['accounts'][f'school-{right}']['download']['bytes']:,} bytes"])
    b.table(rows,440,[120,width/2-120,120,width/2-120])

    b.start('HTTP 复验与隐私边界', '四真实样本均复验，不只依赖截图“看起来正常”。')
    recheck_ok = bool(recheck and recheck.get('ok') is True and len(recheck.get('samples',[])) == 4
        and all(s.get('passed') is True for s in recheck['samples']))
    b.table([
        ['检查项','四真实样本结果'],
        ['报告及来源','下载处理报告与原视频 source hash 对应；技术摘要重复读取仍为当前版本。'],
        ['媒体完整性','全量媒体下载 hash、128-byte Range、音频 WAV 头及任务刷新均通过。'],
        ['管理员与账号隔离','管理员技术查询通过；管理员课堂分析被拒绝，其他三校与匿名请求均被拒绝。'],
        ['本地复验报告','4/4 passed（已核对本地报告）' if recheck_ok else '复验 4/4 通过由本轮操作汇总提供；本地报告需另核对。'],
    ],118,[155,width-155])
    b.text('<b>遮罩不代表空功能。</b>页面中的灰蓝色块用于遮挡账号、学校信息、输入字段及真实视频 / 图片 / canvas；PDF 沿用已脱敏 PNG，不移除遮罩，不展示原始人脸与档案。',40,410,width)
    b.text('最小访问：浏览器验收只允许登录 / 登出写请求，不新建任务或学生，不读档案；四真实样本工作区 people / records 为空。HTTP 复验同样未新建任务，也未请求重新处理。',40,478,width)

    b.start('交付与尚未覆盖的能力', '结论按证据层级划分；公网登录、loopback 功能与实际校方网络条件不混为一谈。')
    b.text('<b>仍需后续验收</b><br/>教育分数仍依赖身份确认与教师证据；没有全自动课堂语义模型。本轮未完成真实 IEP 正向授权导入，也未验证人脸识别准确性。技术处理完成不代表授权、诊断或教学效果已获证明。',40,118,width)
    b.text('<b>学校首次填写</b><br/>原有 t2 / t3 / t4 账号尚未填写学校，首次登录需先选择真实学校；视频处理与下载复验已通过。学校信息首填不代表视频处理失败。',40,219,width)
    b.text('<b>公网与运行维护</b><br/>Windows Edge 已通过既有密钥进入新 IP 的可信 HTTPS 登录页；4 校 + 1 管登录完成。app、gateway、nginx 自启，renew timer 每 6 小时启用（据本轮操作确认；未以重启或续期演练代替验证）。',40,315,width)
    b.text('<b>地址与私密入口</b><br/>服务器地址：https://YOUR_SERVER_IP（不是登录入口）。<br/>'
        '<b>首次访问需使用另行私密交付的完整邀请链接，单独地址不是登录入口。</b><br/>'
        '测试邀请到期：2026-11-06 23:59:59（UTC+08:00）；PDF / 截图 ZIP 不包含密钥、完整邀请 URL 或跳转文件。<br/>'
        '截图附件：22 张合成 + 12 张真实，共 34 张原 PNG；保留目录与文件名。',40,403,width)
    login_ok = bool(login and login.get('ok') is True and login.get('school_logins') == 4
                    and login.get('administrator_login') is True)
    b.text('证据：两份浏览器 acceptance.json、四真实任务 HTTP 复验及公网登录报告'
        + ('（已核对 4 校 + 1 管理员）' if login_ok else '（本轮操作汇总提供）')
        + '。迁移、Linux 回归、首轮等待及运行维护据本轮汇总；公网大文件结论据最终 JSON。',40,530,width,'small')
    b.c.save()

    archive = args.output.parent / '云端验收完整截图_20261020.zip'
    screenshot_manifest = []
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as bundle:
        for folder in ('synthetic','real'):
            for image in sorted((args.screenshots / folder).glob('*.png')):
                relative = image.relative_to(args.screenshots).as_posix()
                bundle.write(image,relative)
                screenshot_manifest.append({'source':relative,'sha256':hashlib.sha256(image.read_bytes()).hexdigest()})
    manifest = {'pages':b.page, 'built_at':datetime.now().isoformat(timespec='seconds'),
        'worker_verdict':verdict, 'final_report_readable':final is not None,
        'screenshots':screenshot_manifest, 'figures':b.figures,
        'pdf_sha256':hashlib.sha256(args.output.read_bytes()).hexdigest()}
    (args.output.parent / 'cloud_acceptance_pdf_build_20261020.json').write_text(
        json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    if args.render:
        import fitz
        render_dir = ROOT / 'tmp/pdfs/cloud_acceptance_20261020'
        render_dir.mkdir(parents=True,exist_ok=True)
        with fitz.open(args.output) as doc:
            for i in range(len(doc)):
                doc[i].get_pixmap(matrix=fitz.Matrix(1.5,1.5)).save(render_dir / f'page-{i+1:02d}.png')
            text = '\n\n'.join(f'=== PAGE {i+1} ===\n{page.get_text()}' for i,page in enumerate(doc))
            args.output.with_suffix('.txt').write_text(text,encoding='utf-8')
    print(json.dumps({'pages':b.page,'worker_verdict':verdict,'screenshots':len(screenshot_manifest),
        'output':str(args.output),'archive':str(archive)},ensure_ascii=False))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--screenshots',type=Path,default=ROOT / 'output/cloud_acceptance_20261020')
    parser.add_argument('--final-report',type=Path,
        default=ROOT / '.runtime/cloud_deploy_20261020/public-large-upload-2202.json')
    parser.add_argument('--output',type=Path,default=DEFAULT_OUTPUT)
    parser.add_argument('--font',type=Path,default=Path('C:/Windows/Fonts/msyh.ttc'))
    parser.add_argument('--bold-font',type=Path,default=Path('C:/Windows/Fonts/msyhbd.ttc'))
    parser.add_argument('--render',action='store_true',help='Render all pages with PyMuPDF for local QA.')
    build(parser.parse_args(argv))


if __name__ == '__main__':
    main()
