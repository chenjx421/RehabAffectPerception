"""Create a screenshot-led PDF explaining current, verified Demo2 boundaries."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image, ImageDraw
from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.pagesizes import A3, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph

ROOT = Path(__file__).resolve().parents[1]
SHOTS = ROOT / 'output/playwright/demo2_version_guide_20260910'
HISTORY = ROOT / 'output/playwright/demo2_membership_guide_20260909'
OUT = ROOT / 'output/pdf/RehabAffect_Demo2_新版功能与操作说明_20260910.pdf'
QA = ROOT / 'tmp/pdfs/demo2_version_guide_20260910'
W, H = landscape(A3)
BLUE = colors.HexColor('#2363BD')
INK = colors.HexColor('#23364A')
GRAY = colors.HexColor('#627489')
LINE = colors.HexColor('#D7E3F0')
PALE = colors.HexColor('#F3F7FD')
AMBER = colors.HexColor('#8A611E')

# Each screenshot is either the read-only live capture or an explicitly labelled
# existing course example. No generated classroom result is presented as measured.
PAGES = [
    ('登录与角色入口', '用户和管理员使用不同的权限进入平台', 'login',
     '教师或上传人员选择用户登录，管理员切换管理员登录。学校内测账号沿用已有授权，不要求现场重新注册。',
     '登录成功后，教师进入学校选择和上传工作台；管理员进入公司后台。选择管理员按钮本身不会获得管理员权限。',
     '账号密码由项目联系人另行提供，本册不包含密码、私密邀请密钥。当前本机地址不能直接供其他电脑访问。'),
    ('手机号注册与付费会员', '注册账号、开通会员、获得学校权限分别处理', 'register',
     '注册页采用手机号、短信验证码及密码。会员中心用于查看套餐、会员状态和订单；注册不等于完成购买。',
     '当前页面已按手机号会员流程设置。截图如实显示短信服务尚未开通，支付和服务套餐是否开放以后台配置为准。',
     '本版没有演示真实短信发送或扣费成功。新注册会员不会自动取得其他学校的视频、学生档案或上传通道权限。'),
    ('学校归属与使用范围', '先明确本次工作的学校，再建立名册和视频任务', 'school',
     '填写城市、区县和学校，核对后进入上传工作台。已有账号可以查看当前学校信息；截图中的内容是账号原有填写值。',
     '新视频保存上传时的学校信息，新身份名册按上传账号和学校上下文隔离。更换当前学校不会自动迁移旧视频。',
     '填写同一个学校名称不会让两个账号自动共享学生。跨教师协作授权和完整学校组织管理仍需进一步建设。'),
    ('视频从哪里上传', '学校先导出文件，上传人员在这里手动提交', 'upload_file',
     '先填课程批次号和课程名称，再点击“选择课堂视频”，核对授权后上传。同一节课的四个账号使用一致的批次号。',
     '平台按账号绑定上传通道，每账号每课程最多5个有效名额。文件分片上传；传输过程中保持页面打开。',
     '不是从希沃自动拉取数据，也不是实时摄像机接入。“计划关注学生”只是上传元信息，不等于已认出视频中的人。'),
    ('任务进度与结果入口', '上传完成、后台处理和身份确认是三个不同环节', 'upload_tasks',
     '在“本课程任务”查看上传、排队、处理和证据就绪状态。根据任务状态使用重试、重新处理或查看结果入口。',
     '任务就绪后可打开“查看视频证据”，或进入“确认画面中的学生”。任务编号把课程、原片和处理版本连接起来。',
     '证据就绪仅表示技术处理完成，不表示已经认出全部学生、理解师生问答，或生成经过验证的学习结论。'),
    ('真实视频与时间切片', '能回看原片、定位时段，并核对同期声音', 'video',
     '播放原视频、拖动时间轴，或点击时间切片跳到相应区间。配合同期音轨，回看老师与学生当时处于什么情境。',
     '新上传视频输出时长、画幅、采样帧、画面质量、变化幅度和音频可用性等技术记录，并提供证据记录下载。',
     '整幅画面的运动量和声音能量不能直接归给某位学生。本版没有把新视频自动转成说话人分离和问答理解结果。'),
    ('建立本校学生名册', '让姓名有稳定编号，而不是只在画面上贴一个名字', 'roster',
     '从上传工作台进入“本校学生名册”，填写姓名、校内编号和班级。可添加识别备注；同名学生通过编号和班级区分。',
     '系统为学生分配稳定 student_id。后续在视频帧里选择本任务范围的名册学生，形成可保存、可撤销的身份关联。',
     '新名册不会自动载入历史演示中的孩子，也不会按同名合并IEP或专业资料。当前还没有授权参考照片登记和自动姓名比对。'),
    ('旧视频为什么需要确认学校', '补齐旧任务信息，防止把画面绑定到错误学校', 'school_confirmation',
     '早期视频没有记录学校时，先核对页面列出的城市、区县和学校。信息不完整可先去填写，再返回原视频任务。',
     '由原上传教师明确确认该视频归属，服务端核对后才能继续绑定。系统不会仅因当前账号填过学校就自动替旧视频确认。',
     '已有学校快照或已有身份记录的任务不能从这里迁移。截图未替真实学校作确认，所以后续姓名保存仍处于禁用状态。'),
    ('自动检测人脸位置', '在真实画面中提出候选，让教师少做重复框选', 'identity',
     '进入身份确认页，选择采样时间，系统检测当前画面的人脸位置。点击候选框进行预览；允许编辑时也可手动画框。',
     '图中20分钟处检测到2个候选，但候选编号不是学生姓名，也不代表画面只有2人。这里展示的是本机实际检测结果。',
     '检测器为本地YuNet，不是大模型识别人名。640×360灰度采样图仍有明显漏检；未检出不能解释为学生缺席。'),
    ('确认姓名、保存与纠错', '将当前画面区域关联到教师核对过的学生', 'identity_fields',
     '在任务学校和权限有效时，选框、选角色；角色为学生时，再从名册选姓名并保存。教师和未知人员不挂入学生档案。',
     '保存学生编号、任务、时间戳、框坐标和处理版本。可以重新打开核对，下载身份确认JSON；撤销错误记录需填写原因。',
     '本次只绑定一张采样帧，不自动覆盖整节课。视频重新处理后旧确认保留为历史；原片失效后不再新增画面绑定。'),
    ('保留个体状态与课堂分析', '从课程目标、课堂情境和学生差异理解表现', '36_tab_state.png',
     '历史演示分析保留群像与个体切换、一人一案、资料导入、状态时间线、师生互动、学习判断和支持建议等入口。',
     '老师可围绕时间窗口核对“看到了什么、有哪些支持、是否出现回应”。IEP和五大领域材料提供背景，不替代课堂证据。',
     '本页是既有课堂示例，截图采集于2026-09-09。分数和状态为规则化初评，不是新上传任务已完成的通用模型分析。'),
    ('教师复核怎样操作', '把不确定的判断交给熟悉学生的老师核对', '38_tab_evidence.png',
     '选学生和待复核时段，回看原片；核对表现是否符合，必要时修正，填写正确性、提示等级及备注。看不清可保留不确定。',
     '复核围绕具体学生、具体时段和具体学习机会展开。核心复核字段可保存、回显并导出清单，方便后续整理标注数据。',
     '这是既有课堂复核界面。保存并不自动训练模型或重新校准所有评分；部分补充字段的持久化仍待完善。'),
    ('一节课一份千字分析', '把分散的证据整理成教师可阅读的课程反馈', '45_tab_courseReport.png',
     '课程分析页汇总本课目标、学生差异、课堂表现、支持和下一课建议。可阅读、复制，或通过打印入口导出PDF。',
     '输出口径是一节课一份约1000字分析，不是每名学生各生成一万字。报告需要保留证据来源、缺失信息与教师复核状态。',
     '当前展示来自既有课堂资料和规则，不是任意新视频都能自动生成同等学习分析；本次截图没有调用外部LLM。'),
    ('公司后台与数据留存', '看清账号、通道、任务和保存规则', 'storage',
     '管理员查看四个账号和通道、每课程名额、任务状态及原片期限。教师查看自己的任务；两种身份的操作范围不同。',
     '业务记录存于本地SQLite，媒体存于受控目录。原片按60天策略保存，到期前15天进入平台提醒范围；身份操作保留审计记录。',
     '平台提醒不等于已发送短信或微信通知。长期归档需要单独授权；目前没有已交付的云同步、异地备份或全校级生产运维。'),
]


def paragraph(c, value, x, top, width, size=14, leading=23, bold=False, color=INK):
    style = ParagraphStyle('text', fontName='YaHeiB' if bold else 'YaHei', fontSize=size,
                           leading=leading, textColor=color, wordWrap='CJK', spaceBefore=0, spaceAfter=0)
    p = Paragraph(escape(value), style)
    _, height = p.wrap(width, 2000)
    if top-height < 40:
        raise ValueError(f'Text extends past footer: {value[:35]}')
    p.drawOn(c,x,top-height)
    return height


def frame(c, title, subtitle, page, total, sample=False):
    c.setFillColor(BLUE);c.rect(38,H-34,30,3,fill=1,stroke=0)
    paragraph(c,'云图智航  /  RehabAffect Demo2',80,H-26,700,10,14,color=GRAY)
    paragraph(c,'新版功能与操作说明 · 2026.09.10',W-302,H-26,264,10,14,color=GRAY)
    paragraph(c,title,38,H-72,W-76,27,37,True)
    paragraph(c,subtitle,38,H-119,W-76,14,22,color=GRAY)
    c.setStrokeColor(LINE);c.line(38,43,W-38,43)
    c.setFillColor(GRAY);c.setFont('YaHei',9)
    c.drawString(38,19,'内部沟通材料 · 含课堂画面，分享前核对授权范围')
    c.setFillColor(GRAY);c.setFont('YaHei',10);c.drawRightString(W-38,19,f'{page:02d} / {total:02d}')
    c.bookmarkPage(f'p{page}');c.addOutlineEntry(title,f'p{page}',level=0)


def picture(c, filename, x, top, width, height):
    with Image.open(filename) as source:
        iw,ih=source.size
    scale=min(width/iw,height/ih)
    dw,dh=iw*scale,ih*scale
    left=x+(width-dw)/2
    c.setStrokeColor(LINE);c.setLineWidth(.7)
    c.rect(left-.5,top-dh-.5,dw+1,dh+1,fill=0,stroke=1)
    c.drawImage(ImageReader(str(filename)),left,top-dh,width=dw,height=dh)
    return top-dh


def overview(c, total):
    frame(c,'课堂学习分析平台','新版本说明：视频证据、学生名册与人物确认',1,total)
    picture(c,SHOTS/'detected_frame.png',38,H-182,640,385)
    paragraph(c,'真实课堂采样帧 · 候选框只表示检测位置，不代表姓名',38,H-568,645,11,18,color=GRAY)
    x=722;top=H-180
    for label,body in [
        ('01  先确定资料属于谁','学校与账号 → 本校学生名册 → 稳定学生编号。'),
        ('02  再把视频变成证据','手动上传 → 后台处理 → 原片回放、音轨和时间切片。'),
        ('03  明确画面中的身份','自动找脸 → 教师核对角色和姓名 → 保存当前帧关联。'),
        ('04  保留课堂业务能力','既有示例继续提供状态分析、教师复核、支持建议和千字报告。'),
    ]:
        paragraph(c,label,x,top,W-x-38,17,26,True,color=BLUE)
        used=paragraph(c,body,x,top-37,W-x-38,14,23)
        top-=used+65
    c.setFillColor(PALE);c.rect(38,83,W-76,94,fill=1,stroke=0)
    paragraph(c,'本册的关键区分',55,161,170,14,22,True,color=BLUE)
    paragraph(c,'新上传任务已接通真实技术处理与逐帧身份确认；已有课堂示例保留状态、学习与报告流程。自动姓名比对、整段视频追踪，以及任意新视频的完整学习分析，尚未完成。',242,161,W-300,14,24)
    c.showPage()


def screen_page(c, data, number, total):
    title,subtitle,key,operation,result,boundary=data
    historical=key.endswith('.png')
    file=HISTORY/key if historical else SHOTS/(key+'.png')
    frame(c,title,subtitle,number,total,historical)
    image_bottom=picture(c,file,38,H-171,812,545)
    paragraph(c,'既有课堂示例截图 · 2026.09.09' if historical else '当前版本实际页面 · 2026.09.10',38,image_bottom-13,812,10,16,color=AMBER if historical else GRAY)
    x=882;top=H-174;width=W-x-38
    for label,text,color in [('怎样操作',operation,BLUE),('得到什么',result,BLUE),('当前边界',boundary,AMBER)]:
        paragraph(c,label,x,top,width,15,23,True,color=color)
        used=paragraph(c,text,x,top-34,width,13,22)
        top-=used+63
    c.showPage()


def closing(c, number, total):
    frame(c,'当前能用到哪一步','输入、输出与下一步接入条件',number,total)
    rows=[
        ('现在可以演示','账号登录和权限区分、学校信息、四通道手动上传、任务处理、视频与音轨回看、学生名册、人脸候选、逐帧身份确认和JSON导出。'),
        ('需要正确理解','既有课堂中的状态、学习判断与约千字报告是规则化示例。确认了一张人脸，不代表自动识别了整节课，也不能把全班声音算到这名学生身上。'),
        ('还需继续实现','授权参考照片登记及姓名匹配、稳定的人物追踪、语音转写与互动理解、新校档案与IEP统一关联、经过教师核准的目标级评估及纵向跟踪。'),
        ('学校需要准备','获准使用的课堂视频、准确的班级名册和校内编号、课程目标，以及熟悉学生的教师。后续自动姓名匹配还需要核对过的清晰参考照片或截图。'),
        ('验收证据','本轮完整界面回归29项通过，真实服务只读检查26项通过；检查权限、画面可用性和手机操作。这些是工程验证，不是人脸识别或学习判断准确率。'),
        ('分享与部署','这份PDF无需连接本地服务即可阅读。网站仍需服务在线；本地回环地址不能供其他电脑直接访问。公网入口需另行配置访问控制，不在文档中嵌入临时密钥。'),
    ]
    top=H-175
    for label,body in rows:
        paragraph(c,label,38,top,177,15,25,True,color=BLUE)
        used=paragraph(c,body,239,top,W-282,14,24)
        top-=max(78,used+30)
        c.setStrokeColor(LINE);c.line(38,top+15,W-38,top+15)
    paragraph(c,'推荐展示顺序：上传工作台 → 视频证据 → 本校名册 → 画面身份确认 → 历史课堂分析 → 教师复核与报告 → 公司后台。不要为演示而替真实学生确认身份或修改学校归属。',38,top-10,W-76,13,22,color=GRAY)
    c.showPage()


def main():
    manifest=json.loads((SHOTS/'manifest.json').read_text(encoding='utf-8'))
    assert manifest['local_only'] and not manifest['record_writes'] and not manifest['errors']
    for name,file in [('YaHei','msyh.ttc'),('YaHeiB','msyhbd.ttc')]:
        pdfmetrics.registerFont(TTFont(name,str(Path('C:/Windows/Fonts')/file)))
    OUT.parent.mkdir(parents=True,exist_ok=True);QA.mkdir(parents=True,exist_ok=True)
    total=len(PAGES)+2
    c=canvas.Canvas(str(OUT),pagesize=(W,H),pageCompression=1)
    c.setTitle('课堂学习分析平台 Demo2 新版功能与操作说明')
    c.setAuthor('云图智航');c.setSubject('学生名册、视频身份确认及课堂分析流程；2026-09-10版本')
    overview(c,total)
    for number,data in enumerate(PAGES,2):screen_page(c,data,number,total)
    closing(c,total,total);c.save()
    reader=PdfReader(str(OUT));assert len(reader.pages)==total
    texts=[page.extract_text() for page in reader.pages]
    for text in texts:assert len(text)>100 and '\ufffd' not in text
    for secret in ['Teach101','Admin101','trycloudflare.com','capture-only-not-persisted']:
        assert secret not in '\n'.join(texts)
    report={'pdf':str(OUT),'page_count':total,'page_text_lengths':[len(t) for t in texts],'font_embedding_checked':False,'screenshots':len(manifest['shots']),'record_writes':False}
    (QA/'validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


def validate_rendered():
    reader=PdfReader(str(OUT))
    renders=sorted(QA.glob('page-*.png'))
    assert len(renders)==len(reader.pages)==len(PAGES)+2
    embedded=set()
    for page in reader.pages:
        for reference in page['/Resources']['/Font'].values():
            font=reference.get_object()
            if font['/Subtype']=='/TrueType':
                descriptor=font['/FontDescriptor'].get_object()
                assert descriptor.get('/FontFile2') and font.get('/ToUnicode')
                embedded.add(str(font['/BaseFont']))
    assert len(embedded)>=2
    assert len(reader.outline)==len(reader.pages)
    for page in reader.pages[:-1]:assert page['/Resources'].get('/XObject')
    sheets=[]
    for start in range(0,len(renders),8):
        sheet=Image.new('RGB',(1240,1836),'#E8EEF6')
        draw=ImageDraw.Draw(sheet)
        for index,file in enumerate(renders[start:start+8]):
            x=10+(index%2)*620;y=10+(index//2)*456
            with Image.open(file) as source:
                source.thumbnail((610,432));sheet.paste(source,(x,y+20))
            draw.text((x,y+2),f'PAGE {start+index+1:02d}',fill='#24364C')
        target=QA/f'contact-{start//8+1:02d}.png';sheet.save(target);sheets.append(str(target))
    report=json.loads((QA/'validation.json').read_text(encoding='utf-8'))
    report.update(font_embedding_checked=True,embedded_fonts=sorted(embedded),rendered_pages=len(renders),bookmarks=len(reader.outline),contact_sheets=sheets)
    (QA/'validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':
    if '--qa' in sys.argv:validate_rendered()
    else:main()
