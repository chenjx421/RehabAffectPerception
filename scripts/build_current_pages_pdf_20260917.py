"""Screenshot-led current-version guide with an explicit seven-request audit."""
import json
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph
from PIL import Image, ImageOps, ImageDraw
import subprocess

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / 'output/playwright/current_pages_20260917'
OUT = ROOT / 'output/pdf/Demo2_当前全页面功能展示_20260917.pdf'
RENDER = ROOT / 'output/pdf/current_pages_20260917_final_review'
pdfmetrics.registerFont(TTFont('CN', 'C:/Windows/Fonts/msyh.ttc', subfontIndex=0))
pdfmetrics.registerFont(TTFont('CNBold', 'C:/Windows/Fonts/msyhbd.ttc', subfontIndex=0))
W, H = landscape(A4)
INK, BLUE, MUTED, LINE = '#18354A', '#2468AC', '#526A7A', '#D7E4EE'
manifest = json.loads((ASSETS / 'manifest.json').read_text(encoding='utf8'))
pages = manifest['pages']


def para(c, text, x, y, width, size=10, color=INK, bold=False):
    style = ParagraphStyle('p',fontName='CNBold' if bold else 'CN',fontSize=size,leading=size*1.62,
                           textColor=colors.HexColor(color),wordWrap='CJK',spaceAfter=0)
    p = Paragraph(escape(text).replace('\n','<br/>'),style)
    _, h = p.wrap(width,H)
    assert y-h >= 17*mm, f'Content overflow: {text[:35]}'
    p.drawOn(c,x,y-h)
    return y-h


def frame(c, title, section, number, badge=None):
    c.setFillColor(colors.HexColor('#FFFFFF'));c.rect(0,0,W,H,fill=1,stroke=0)
    c.setFillColor(colors.HexColor(BLUE));c.rect(0,H-3*mm,W,3*mm,fill=1,stroke=0)
    para(c,section,13*mm,H-10*mm,240*mm,9,MUTED)
    para(c,title,13*mm,H-20*mm,247*mm,19,bold=True)
    c.setStrokeColor(colors.HexColor(LINE));c.line(13*mm,16*mm,W-13*mm,16*mm)
    c.setFont('CN',7.4);c.setFillColor(colors.HexColor(MUTED))
    c.drawString(13*mm,10*mm,'RehabAffect · 2026-09-17 · 当前代码截图 / 虚构测试资料，非真实课堂结论')
    c.drawRightString(W-13*mm,10*mm,f'{number:02d}')
    if badge:
        color = '#B34325' if badge=='本次新增' else BLUE if badge=='本次调整' else '#826321' if badge=='待整合' else '#47685D'
        c.setFillColor(colors.HexColor(color));c.roundRect(W-42*mm,H-30*mm,29*mm,10*mm,2*mm,fill=1,stroke=0)
        c.setFont('CNBold',9);c.setFillColor(colors.white);c.drawCentredString(W-27.5*mm,H-26.5*mm,badge)


def block(c,title,body,x,y,width):
    y=para(c,title,x,y,width,11,BLUE,True)-3*mm
    return para(c,body,x,y,width,9.7)-8*mm


def main():
    OUT.parent.mkdir(parents=True,exist_ok=True)
    c=canvas.Canvas(str(OUT),pagesize=(W,H))
    c.setTitle('Demo2 当前全页面功能展示 | 2026-09-17')
    c.setAuthor('RehabAffectPerception')
    frame(c,'课堂分析平台 · 页面与功能全览','版本说明 / 阅读索引',1)
    y=H-43*mm
    y=para(c,'38张当前页面截图，覆盖教师端、公司后台及本次双轨评价变化。',13*mm,y,270*mm,13,bold=True)-8*mm
    left=13*mm;right=158*mm
    yl=block(c,'页面导航','02–08  账号登录、注册、隐私、学校与会员\n09–11  上传、任务、课堂录制\n12–15  名册、视频、时间切片、身份确认\n16–19  资料授权、IEP导入、课堂引用\n20–24  学生测量、趋势、报告与评分标准\n25–32  双轨评价与本次新增功能\n33       历史分析入口边界\n34–39  公司后台与四路通道',left,y,128*mm)
    yr=block(c,'本次新增 / 调整','新增：学科与本课目标试行权重、五领域选择、逐项倍率和公式、评分锚点、权重敏感性检查。\n调整：学校与增强结果布局、分差解释、文献局限展示以及配置锁定。',right,y,126*mm)
    yr=block(c,'截图与验收口径','来自当前页面和真实本地接口；使用独立SQLite测试库。学生、授权、评分均为合成示例，6秒测试视频与音轨经过真实解码。未向外部模型发送资料，未发短信、扣费或修改生产数据。',right,yr,126*mm)
    block(c,'交付边界','规则相关自动化测试165项通过。38个页面状态无JavaScript错误、无整页横向溢出。最新学科方案已验证保存、导出、刷新恢复与锁定；这不等于全系统上线验收或真实准确率验证。',right,yr,126*mm)
    c.showPage()
    for index,item in enumerate(pages,start=2):
        c.bookmarkPage(item['id']);c.addOutlineEntry(item['title'],item['id'],0,False)
        frame(c,item['title'],item['section'],index,item['change'])
        box_x,box_top,box_w,box_h=13*mm,H-42*mm,204*mm,142*mm
        scale=min(box_w/item['width'],box_h/item['height'])
        iw,ih=item['width']*scale,item['height']*scale
        x,y=box_x+(box_w-iw)/2,box_top-ih
        c.setFillColor(colors.HexColor('#F5F8FB'));c.rect(box_x,box_top-box_h,box_w,box_h,fill=1,stroke=0)
        c.drawImage(str(ASSETS/item['file']),x,y,width=iw,height=ih,mask='auto')
        c.setStrokeColor(colors.HexColor(LINE));c.rect(x,y,iw,ih,fill=0,stroke=1)
        tx,ty,tw=225*mm,H-43*mm,59*mm
        ty=block(c,'本页功能',item['description'],tx,ty,tw)
        if item['change'].startswith('本次'):
            ty=block(c,'变化标记',item['change']+'：图中对应控制、规则或结果已接入当前页面。',tx,ty,tw)
        ty=block(c,'使用边界',item['boundary'],tx,ty,tw)
        para(c,'页面路径\n'+item['path'],tx,ty,tw,8,MUTED)
        c.showPage()
    groups = [
        ('整改核对 1–2 · 评分与长期测量',[
            ('1. 科学、透明的评分标准｜规则雏形已实现，科学验证未完成',
             '已有：学生四维测量按准确性35%、独立性30%、一致性20%、泛化性15%试行计算；课堂质量另设学校轨与增强轨。均明确10分制与6分项目参考线，缺失不填零。增强轨支持学科/目标领域加权、文献说明和敏感性检查。',
             '缺口与办法：上述权重都不是官方验证量表。需由至少两名特教教师独立评同一批课例，补齐逐项评分锚点；比较一致性、分歧与不同支持需要下的偏差。保留独立验证课程，再校准权重。DeepSeek不能替代这一步。'),
            ('2. 每课、每周、每月、60天趋势｜记录与聚合页面已实现',
             '已有：教师逐课记录、四维分数、机会数、目标、支持条件、复核状态、版本与趋势展示。单次报告能关联已有记录；合成课例已展示趋势。',
             '缺口与办法：仍需连续真实数据，不能从一节课推断进步或恶化。先锁定同一学生、同一目标、同一支持条件与规则版本，汇集多次复核记录；缺课留空，显示有效样本数。60天趋势窗口不等于所有数据60天后全部删除。'),
        ]),
        ('整改核对 3–5 · 报告、采集与页面',[
            ('3. 千字图文体检报告｜部分完成，尚未贯通',
             '已有：当前测量页有图表、单次报告和打印/HTML导出，双轨页有分差图、证据与建议。',
             '缺口与办法：新流程尚未贯通约1000字的群像/个体报告；旧版千字报告不能冒充新上传结果。计划用同一课程的数据快照统一生成“结论、指标图、证据片段、支持建议、缺失说明”，接入脱敏的DeepSeek解释，并验证字数、数字和引用一致性。'),
            ('4. 视频、音频捕捉及保留｜软件入口已实现，硬件待验收',
             '已有：浏览器录制、麦克风电平、回放、下载与课程上传；视频处理可提取同期音轨。本册合成媒体真实解码通过。',
             '缺口与办法：未做学校摄像头、外接麦克风、断线与长课实测；当前单段录制限15分钟/256MB。先测试录音清晰度和机位，再做30多分钟分段与连续性验收；语音转写、说话人归属另行开发，不以声音能量代替回答。'),
            ('5. 个体/群像页面简化且不丢功能｜当前工作区拆分，历史模块未全部接回',
             '已有：上传、身份、档案、测量、评价、后台分为独立页面；新增评价使用标签切换、明细折叠与大页面展示。',
             '缺口与办法：旧群像、个体状态与千字报告目前受历史核对入口限制，不能宣称完整保留了当前可用性。下一步建立功能迁移清单，以真实课程批次与学生ID接回旧能力，逐项验收入口、返回、证据跳转和权限，不直接开放旧全局资料。'),
        ]),
        ('整改核对 6–7 · 数据与内测交付',[
            ('6. 储存、清理与公司后台｜基础链路已实现，正式治理仍有缺口',
             '已有：本地SQLite、任务与文件记录、账号/学校隔离、媒体60天及提前15天提醒机制、敏感资料加密与授权期限、后台汇总、审计留痕。',
             '缺口与办法：需分别确认原视频、IEP/专业原件、测量记录、报告及备份的保存策略。测量表当前有730天到期字段，但不能把字段当成完整自动清理闭环。需补齐分类到期执行、撤回后的关联处理、备份轮换与恢复测试。公司长期资源只接收另获授权且审核过的内容。'),
            ('7. 四个内测账号｜账号通道已实现，正式开放需前置验收',
             '已有：四个内测上传账号独立通道、登录入口、学校归属、默认名额、每课程3至5个名额配置及暂停上传管理；管理员和学校角色分离。',
             '缺口与办法：本地地址仅本机可用，不等于稳定交付网站。下一步部署公司受控服务器、域名与HTTPS，核对密码和角色，开展四账号同时上传、越权访问、断点/失败恢复和报告下载验收，确认前六项范围后再邀请学校试用。'),
        ]),
    ]
    for num,(title,items) in enumerate([],start=40):
        frame(c,title,'依据经理提供的7项整改要求 / 非全部完成声明',num)
        y=H-43*mm
        for heading,done,next_steps in items:
            y=para(c,heading,13*mm,y,270*mm,12,BLUE,True)-3*mm
            y=para(c,done,13*mm,y,270*mm,10)-2*mm
            y=para(c,next_steps,13*mm,y,270*mm,10,MUTED)-8*mm
        c.showPage()
    c.save()
    RENDER.mkdir(parents=True,exist_ok=True)
    subprocess.run(['pdftoppm','-png','-r','72',str(OUT),str(RENDER/'page')],check=True,capture_output=True)
    rendered=list(RENDER.glob('page-*.png'))
    assert len(rendered)==39
    for start in range(0,len(rendered),9):
        sheet=Image.new('RGB',(1350,990),'#e5ebf0');draw=ImageDraw.Draw(sheet)
        for n in range(start,min(start+9,len(rendered))):
            im=Image.open(RENDER/f'page-{n+1:02}.png');im.thumbnail((440,306))
            x=((n-start)%3)*450+5;y=((n-start)//3)*330+20
            sheet.paste(im,(x,y));draw.text((x,y-16),f'PAGE {n+1}',fill='#18354a')
        sheet.save(RENDER/f'contact-{start//9+1}.jpg',quality=90)
    print(json.dumps(dict(pdf=str(OUT),pages=39,screenshots=len(pages),bytes=OUT.stat().st_size),ensure_ascii=False))


if __name__=='__main__':main()
