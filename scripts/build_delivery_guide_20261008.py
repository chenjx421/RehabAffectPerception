"""Internal screenshot guide; credentials are read only from private runtime files."""
import json
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path
from xml.sax.saxutils import escape
from PIL import Image, ImageDraw
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph

ROOT=Path(__file__).resolve().parents[1]
ASSETS=ROOT/'output/playwright/delivery_20261008'
OUT=ROOT/'output/pdf/Demo2_完整页面与四通道内测交付说明_20261008.pdf'
pdfmetrics.registerFont(TTFont('CN','C:/Windows/Fonts/msyh.ttc',subfontIndex=0))
pdfmetrics.registerFont(TTFont('CB','C:/Windows/Fonts/msyhbd.ttc',subfontIndex=0))
W,H=landscape(A4)
BLUE='#2468AC'; INK='#17364D'; MUTED='#526779'

def p(c,text,x,y,width,size=11,bold=False,color=INK):
    obj=Paragraph(escape(text).replace('\n','<br/>'),ParagraphStyle('x',fontName='CB' if bold else 'CN',fontSize=size,leading=size*1.55,textColor=colors.HexColor(color),wordWrap='CJK'))
    _,height=obj.wrap(width,H)
    assert y-height>=19*mm,(text[:50],y,height)
    obj.drawOn(c,x,y-height)
    return y-height

def frame(c,title,section,number):
    c.setFillColor(colors.white);c.rect(0,0,W,H,fill=1,stroke=0)
    c.setFillColor(colors.HexColor(BLUE));c.rect(0,H-3*mm,W,3*mm,fill=1,stroke=0)
    p(c,section,13*mm,H-10*mm,270*mm,9,color=MUTED)
    p(c,title,13*mm,H-20*mm,270*mm,19,True)
    c.setStrokeColor(colors.HexColor('#D7E4EE'));c.line(13*mm,16*mm,W-13*mm,16*mm)
    c.setFont('CN',7.3);c.setFillColor(colors.HexColor(MUTED))
    c.drawString(13*mm,10*mm,'2026-10-08 | 内部测试交付 | 截图使用合成资料，不代表真实教学结论')
    c.drawRightString(W-13*mm,10*mm,str(number))

def main():
    manifest=json.loads((ASSETS/'manifest.json').read_text(encoding='utf8'))
    assert not manifest['errors'],manifest['errors']
    items=[]
    def add(file,title,section,desc,boundary,change='已实现'):
        file=Path(file)
        source=Image.open(file)
        parts=math.ceil(source.height/(source.width*0.76)) if source.height/source.width>1.05 else 1
        for part in range(parts):
            target=file
            label=title
            if parts>1:
                target=ASSETS/f'{file.stem}_readable_{part+1}.png'
                source.crop((0,round(part*source.height/parts),source.width,round((part+1)*source.height/parts))).save(target)
                label=f'{title} · {part+1}/{parts}'
            items.append(dict(image=target,title=label,section=section,description=desc,boundary=boundary,change=change))
    for item in manifest['pages']:
        if item['id']=='22_measure_report':
            item['boundary']='单次测量报告与课程图文报告分开；当前生成依据是观察记录，不是大模型自动理解整堂课。'
        add(ASSETS/item['file'],item['title'],item['section'],item['description'],item['boundary'],item['change'].replace('现有功能','已实现'))
        if item['id']=='24_evaluation':
            base=ROOT/'output/playwright/context_evaluation_20260929'
            for name,title,desc,bound in [
                ('00_setup','双轨评价：学校模板与本课目标','设置评价模板、课程目标和学校评分。评价记录与学生掌握度分开。','项目6分参考线不是经过验证的官方合格标准。'),
                ('01_ordinary','普通课堂：学校分数作为基线','没有已复核的差异证据时，两轨保持同一基线；不因学生不说话或需要支持随意扣分。','这是明确的评分政策，不等于已证明模型比学校评价更准确。'),
                ('02_pending','待复核调整：暂不改变最终分数','新增建议和理由先进入待复核状态，避免不确定的识别结果直接影响老师得分。','不承诺完全无人参与；证据不足时保持待确认。'),
                ('03_reviewed','复核后的差异：允许有依据的调整','复核后按规则计算差异，并保留证据、理由与下一课改进方向。','不会为让分数好看而统一抬分，也不会把疑似安全事件直接认定为事实。'),
                ('03b_comparison','学校轨与系统轨：分差对照','同页对比两轨得分，查看差异来源和解释，便于校方逐项核对。','试行权重仍需校方样本校准，文献不能直接证明具体权重科学有效。')]:
                add(base/(name+'.png'),title,'课堂评价 · 10月8日验收截图',desc,bound,'已调整')
        if item['id']=='28_analysis':
            base=ROOT/'output/playwright/course_workspace_20260921'
            for name,title,desc in [
                ('01_task_picker','课程分析：任务选择','从自己的课程任务选择分析对象，不再默认展示历史固定学生。'),
                ('02_group_empty','群像分析：没有证据时保留空缺','展示视频与已关联学生；未复核的数据不伪装成可靠课堂结论。'),
                ('03_teacher_review','教师复核：具体到片段和观察项','结合课程任务、时间段、回应机会、提示程度和支持方式保存观察记录。'),
                ('03a_pending_filter','复核筛选：聚焦待处理记录','按记录状态筛选，减少教师在整段视频和全部记录中反复查找。'),
                ('03b_reuse_goal','复用目标：减少重复填写','复用课程目标，但清空旧证据，避免把上一节课的表现直接带入新课。'),
                ('04_group_reviewed','群像分析：复核后的课程总览','聚合已有观察，比较不同学生在本课目标与支持条件下的表现。'),
                ('05_individual','个体分析：学生与证据对应','查看所选学生、片段和观察结果；与群像切换而不混淆不同学生。'),
            ]:
                add(base/(name+'.png'),title,'课程分析 · 10月8日验收截图',desc,'使用合成且已复核的记录演示；不能据此宣称真实学生的掌握率或识别准确率。','已调整')
            report=Image.open(base/'06_illustrated_report.png')
            parts=max(1,math.ceil(report.height/(report.width*0.76)))
            for n in range(parts):
                top=round(n*report.height/parts);bottom=round((n+1)*report.height/parts)
                target=ASSETS/f'report_part_{n+1}.png';report.crop((0,top,report.width,bottom)).save(target)
                add(target,f'千字图文报告 · {n+1}/{parts}','课程报告','图表、目标、片段依据、观察结论与建议组合展示；支持HTML/JSON导出，浏览器可打印为PDF。','本次合成验收正文为1063字；正文采用证据模板，不是已接入外部大模型后的自动教学诊断。','已调整')
    OUT.parent.mkdir(parents=True,exist_ok=True)
    c=canvas.Canvas(str(OUT),pagesize=(W,H));c.setTitle('Demo2 完整页面与四通道内测交付说明');c.setAuthor('RehabAffectPerception')
    number=0
    def textpage(title,section,blocks):
        nonlocal number
        number+=1;frame(c,title,section,number);y=H-44*mm
        for heading,body in blocks:
            y=p(c,heading,13*mm,y,270*mm,12,True,BLUE)-2*mm
            y=p(c,body,13*mm,y,270*mm,10.5)-6*mm
        c.showPage()
    textpage('课堂分析平台 · 完整页面与内测交付','版本范围 / 2026年10月8日',[
        ('本册包含什么',f'{len(items)}个页面和关键状态截图，覆盖登录、上传、名册、身份匹配、IEP、群像/个体、图文报告、学生追踪、双轨评课、教学支持、安全复核及公司后台。末尾附四个测试账号、公司账号与公网测试入口。'),
        ('当前可以测试什么','四账号登录 → 视频手动上传 → 处理进度 → 原片/音轨/片段 → 人物匹配 → 观察复核 → 报告导出；公司后台可汇总任务并下载相应结果。'),
        ('必须明确的边界','当前是受控内测软件，不是已经验证准确率的无人值守评课产品。视频处理就绪指材料提取成功，不代表自动识别学生掌握度、疾病或课堂质量。外部模型接入暂缓。'),
        ('资料说明','主页面重新截图；结果页使用10月8日实际浏览器验收截图。全部使用隔离的合成资料，不展示儿童真实档案。内附测试凭证，仅内部流转。')])
    textpage('第一次使用：从上传到下载','教师与公司后台的分工',[
        ('教师：准备与上传','通过邀请链接进入，选择用户登录；确认城市、区县、学校。新建或选择课程批次，选择本地课程视频并上传。四个账号对应四路通道，默认每账号每课程5个名额，后台可管理。'),
        ('教师：核对与分析','等待处理完成，先检查原片和同期音轨，再将画面框与学生名册关联。自动候选不可靠时手动画框。根据任务选择课程适用范围，记录或复核学生表现；再查看群像、个体和图文报告。'),
        ('公司：查看与留存','管理员在后台查看四路任务、处理状态、保留期限，打开任务并下载可用结果。IEP和专业资料属于单独授权的敏感档案，管理员汇总页不默认显示正文。'),
        ('测试时怎样判断异常','记录账号、课程名、任务编号、时间、操作步骤和截图。上传成功但仍在处理不算报告完成；显示失败时保留错误信息，不用反复创建同一任务掩盖问题。')])
    for item in items:
        number+=1;frame(c,item['title'],item['section'],number)
        c.bookmarkPage(f'p{number}');c.addOutlineEntry(item['title'],f'p{number}',0,False)
        image=Image.open(item['image']);iw,ih=image.size
        scale=min(204*mm/iw,143*mm/ih);iw*=scale;ih*=scale
        x=13*mm+(204*mm-iw)/2;y=H-42*mm-ih
        c.drawImage(str(item['image']),x,y,iw,ih,mask='auto')
        c.setStrokeColor(colors.HexColor('#D7E4EE'));c.rect(x,y,iw,ih,stroke=1,fill=0)
        tx=225*mm;ty=H-43*mm;tw=59*mm
        ty=p(c,item['change'],tx,ty,tw,11,True,BLUE)-5*mm
        ty=p(c,'本页功能',tx,ty,tw,10.5,True)-2*mm
        ty=p(c,item['description'],tx,ty,tw,9.5)-6*mm
        ty=p(c,'使用说明',tx,ty,tw,10.5,True)-2*mm
        p(c,item['boundary'],tx,ty,tw,9.2,color=MUTED)
        c.showPage()
    textpage('公司后台：保存在哪里、能保存什么','数据落地与保留策略',[
        ('当前保存位置','任务与业务记录保存在本机SQLite：outputs/seewo_demo2/rehab_affect_demo2.sqlite3；上传视频、提取材料和结果在同级video_tasks目录；敏感档案原件采用独立加密存储。数据不是只在浏览器内，关闭浏览器不会自行消失。'),
        ('原视频和敏感档案','原媒体默认保留60天、到期前15天提醒；服务运行时有周期性到期扫描，是否执行删除受后台策略控制。IEP等档案受单独授权、到期和撤回规则约束。关机期间无法执行后台清理。'),
        ('长期资源与报告','获额外授权后可建立结构化结果归档记录，但当前是本地待公司同步状态，不代表已上传公司云库。归档不包含原视频、音频和IEP全文；课程名等自由文本仍需检查是否含个人信息。各类报告与备份不能笼统承诺无限保存。'),
        ('需要补齐的保障','正式托管需公司受控服务器、数据库与文件备份、恢复演练、稳定HTTPS入口、访问审计和到期任务监控。当前临时公网只转发到这台电脑，不提供云端备份。')])
    textpage('本次验证：已经跑过哪些真实流程','验收证据，不等同于模型准确率',[
        ('四路外网链路','四账号分别完成公开入口登录、合成视频上传、处理、原片和音轨读取、结果下载。公司管理员能看到四路任务并下载结果；匿名访问及跨账号访问被拒绝。'),
        ('队列与长视频','本机四账号并发提交短视频通过；32分钟合成视频上传、处理与结果下载通过，媒体为320×180、5fps、约10.9MB。尚未等同验证四路公网1080P整课并发或学校网络性能。'),
        ('交互与输出','真实鼠标/手机触摸画框、绑定、撤销、更正、同名学生区分、权限和过期帧拒绝通过。课程观察保存/修改/复用、图文报告导出、双轨评分与复核逻辑已验收。'),
        ('仍需学校实测','请先每账号上传1个获授权课例，确认声音、遮挡、处理耗时、学生对应和报告内容，再扩大数量。自动人物识别、语言理解和教学判断未完成校方真实准确率验证；部分符号链接测试受Windows环境限制跳过。')])
    textpage('尚需确认与下一步落地','建议在正式学校测试前统一口径',[
        ('一、测试目标与素材','确认本轮优先验收“上传、材料整理、复核、下载、公司留存”，还是要求完全自动评课。后者目前尚未完成，需要模型能力、标注样本及独立评测，不能靠页面存在替代。'),
        ('二、账号归属与权限','明确四账号分别属于哪所学校/哪个主体，谁可以更改学校信息、复核结果和申请长期归档。演示凭证只用于限定内测，正式上线应改用独立强密码和完整账号管理。'),
        ('三、数据与部署','确定学校上传授权、IEP使用范围、原件/结果/报告/备份各自保留期限，以及公司托管位置和运维负责人。临时分享链接到期或本机关机后不可用。'),
        ('四、后续实施方向','先验收真实课堂的视频与音频质量、处理失败与重试，再校准评分锚点和学校标准；外部模型仅在授权、费用、数据边界明确后接入。完善自动语音/课堂理解、稳定服务、备份恢复与监控。')])
    private=json.loads((ROOT/'.runtime/manager_share_state.json').read_text(encoding='utf-8-sig'))
    expire=datetime.fromtimestamp(private['expires_at'],timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M')
    credentials=[]
    for line in (ROOT/'.runtime/demo2_pilot_accounts_20260908.md').read_text(encoding='utf8').splitlines():
        parts=[v.strip() for v in line.split('|')]
        if len(parts)>4 and parts[2] in ['t1','t2','t3','t4','admin']:
            credentials.append(parts)
    assert len(credentials)==5
    number+=1;frame(c,'内测入口与账号 · 仅限内部转发','私密附页 / 请勿公开发布本册',number)
    y=H-44*mm
    y=p(c,'点击下方进入外网邀请入口（首次使用须完整打开邀请链接）',13*mm,y,270*mm,12,True,BLUE)-3*mm
    c.linkURL(private['invite_url'],(13*mm,y,280*mm,y+12*mm),relative=0,thickness=0)
    y=p(c,private['invite_url'],13*mm,y,270*mm,8.5,color=BLUE)-5*mm
    y=p(c,f'邀请有效期至北京时间 {expire}。临时链接依赖本机开机、联网、程序与隧道持续运行。',13*mm,y,270*mm,10)-7*mm
    for row in credentials:
        label='公司专用管理员，请勿发给学校' if row[2]=='admin' else f'学校测试通道 {row[4]}'
        y=p(c,f'{label}    账号：{row[2]}    密码：{row[3]}',13*mm,y,270*mm,12,True)-5*mm
    p(c,'学校账号选择“用户登录”；公司账号选择“管理员登录”。仅供已授权测试，勿公开传播账号、邀请码及含真实学生资料的截图。',13*mm,y,270*mm,10,color=MUTED)
    c.showPage();c.save()
    (ASSETS/'pdf_build_summary.json').write_text(json.dumps({'pdf':str(OUT),'pages':number,'screenshots':len(items)},ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'pdf':str(OUT),'pages':number,'screenshots':len(items)},ensure_ascii=False))

if __name__=='__main__':main()
