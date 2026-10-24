"""Screenshot-led product guide; no student documents or access tokens."""
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.colors import HexColor
from reportlab.platypus import Paragraph
from reportlab.lib.styles import ParagraphStyle

ROOT=Path(__file__).resolve().parents[1]
NEW=ROOT/'output/playwright/support_20260928'
COURSE=ROOT/'output/playwright/course_workspace_20260921'
DUAL=ROOT/'output/playwright/dual_evaluation_20260916'
OUT=ROOT/'output/pdf/Demo2_网页使用与教学支持说明_20260928.pdf'

PAGES=[
('访问与使用路径','登录后，从学校与课程开始',NEW/'00_external_login.png',[
    '通过受保护的外部邀请链接打开登录页，再使用已有内测账号登录。邀请并不替代账号验证。教师与管理员有不同的数据权限。',
    '建议顺序：确认学校 → 上传短视频 → 确认学生身份 → 试听并复核片段 → 查看图文报告 → 记录下次教学调整。',
    '当前外部访问为限时演示通道，依赖本机和网络保持在线，不等于已部署长期生产服务器。本文使用隔离环境的合成验收素材，不展示真实儿童资料。']),
('上传课堂视频','输入什么，上传后得到什么',NEW/'06_upload.png',[
    '教师手动选择视频并填写课程信息；系统保存上传任务及处理状态。当前没有自动从希沃同步课堂视频的接口。',
    '视频处理后提供媒体信息与抽帧证据。教师仍需确认学生身份和关键回应；处理完成不等于自动判断学生已经学会。']),
('学生与画面对应','姓名档案与视频框选分别确认',NEW/'08_identity.png',[
    '选择本校学生档案，把画面中的人物区域关联到对应学生。检测漏人、遮挡或候选不可靠时，可手动框选并核对。',
    '身份关联会记录画面版本；关联被撤销或原始证据变化后，相关观察需重新确认，避免旧分数继续归入错误学生。单帧绑定不等于已完成全程可靠追踪。']),
('群像与个体分析','从已复核证据查看课堂情况',COURSE/'04_group_reviewed.png',[
    '群像页展示本次视频已关联学生、目标记录和复核覆盖。个体页按学生查看目标、支持方式和量化结果。',
    '统计仅覆盖本账号、本学校及当前视频。没有记录不按零分处理，复核条数也不代表整节课的专注时长。']),
('新增：沟通与音频记录','不把“没录到”当成“没回应”',NEW/'05_communication_review.png',[
    '复核时可以记录口语、手势、图卡、AAC、动作等回应方式，并标记音频清晰、部分缺失或未采集。',
    '哭声、笑声及其他非言语发声可作为观察记录；未确认说话人时保留为场景声音，不直接归因到学生。当前不是自动声纹、发声分类或诊断模型。',
    '音频缺失字段不降低评分；能否评分仍取决于教师确认的目标证据与维度完整性。']),
('图文课堂报告','约千字分析与量化证据一起看',COURSE/'06_illustrated_report.png',[
    '具备可用复核记录后，报告整理教学任务、学生回应、支持方式、目标得分与下一次观察建议，并配量化图形。可下载HTML、JSON或打印为PDF。',
    '当前报告由确定性规则生成，尚未调用DeepSeek。证据不足时显示待补充，不强行填满千字。多视频同课汇总需先复核来源，不把重复记录直接相加。']),
('双轨课堂评价','学校规则与系统试行规则对照',DUAL/'10_comparison_result.png',[
    '保留学校规则与增强规则两个视角，展示总分差异、条目证据、原因及调整建议；原始录入和试行权重可追溯。',
    '当前评分来自人工录入和规则计算，不是视频自动评分。6分为项目参考线；增强权重尚未完成真实样本校准，不能称为官方标准。',
    '对教师更友好的方式是呈现支持条件、缺失证据与进步方向，而不是人为保底或抬高分数。此图为9月16日同一评价功能的合成验收示例。']),
('新增：上传测试检查','进入测试前知道还缺哪一步',NEW/'01_upload_readiness.png',[
    '按照学校归属、上传完成、证据处理、学生确认、教师复核五步展示准备情况，可直接跳转相应页面。',
    '先跑一段短视频，再测完整课堂。检查开头、中间、结尾，目标学生的可见性、远处声音和重叠说话；记录上传失败、识别漏人和音轨缺失等异常。']),
('新增：按支持需求选建议','以IEP和教师判断为前提',NEW/'02_support.png',[
    '提供口语受限与辅助沟通、感官环境适配、任务步骤支持三类教学建议。教师主动选择，不从视频猜测疾病。',
    '少语不等于失语症。确诊信息应来自专业资料；当前尚未自动读取诊断并生成个体化干预处方。建议用于课堂支持讨论，不替代医疗或专业评估。',
    '参考CAST UDL 3.0（2024）及AAC相关研究；这些材料支持教学设计思路，不证明系统评分权重或个体疗效。']),
('新增：教师逐课改进','每次聚焦一个可核对的调整',NEW/'03_teacher_growth.png',[
    '记录本课目标、做得好的地方、下次调整、实施后的观察以及下次核对证据。保存后可重新打开，修改保留版本。',
    '学生进步继续在长期测量中以相同目标和条件比较。教师自评记录与已验证的教学效果不同；需要后续课堂证据才能判断改善。']),
('新增：DeepSeek预留入口','先看将发送什么，再谈模型解释',NEW/'04_deepseek.png',[
    '页面可查看接入状态和拟发送的白名单结构化摘要。目前不发起模型请求，不发送姓名、视频、诊断及教师自由文本。',
    '收到API配置后还需完成服务端调用、数据授权、引用和数值校验、失败回退及教师确认。模型适合解释证据，不负责随意更改权重或作医学诊断。']),
]

def main():
    pdfmetrics.registerFont(TTFont('CN','C:/Windows/Fonts/simhei.ttf'))
    OUT.parent.mkdir(parents=True,exist_ok=True)
    c=canvas.Canvas(str(OUT),pagesize=(842,595))
    c.setTitle('Demo2 网页使用与教学支持说明')
    style=ParagraphStyle('body',fontName='CN',fontSize=11,leading=17,textColor=HexColor('#33465d'))
    for index,(title,subtitle,img,notes) in enumerate(PAGES,1):
        c.setFillColor(HexColor('#f4f8fd'));c.rect(0,0,842,595,fill=1,stroke=0)
        c.setFillColor(HexColor('#2463dc'));c.setFont('CN',10);c.drawString(28,566,'课堂观察与教学支持 / Demo2 / 2026.09.28')
        c.setFillColor(HexColor('#20344b'));c.setFont('CN',23);c.drawString(28,532,title)
        c.setFont('CN',11);c.setFillColor(HexColor('#63758b'));c.drawString(28,510,subtitle)
        w,h=Image.open(img).size;scale=min(520/w,438/h);dw,dh=w*scale,h*scale
        c.setFillColor(HexColor('#ffffff'));c.rect(28,51,528,442,fill=1,stroke=0)
        c.drawImage(str(img),32+(520-dw)/2,55+(434-dh)/2,width=dw,height=dh)
        y=482
        for n,note in enumerate(notes,1):
            p=Paragraph(f'{n}. '+escape(note),style);_,ph=p.wrap(230,430)
            p.drawOn(c,581,y-ph);y-=ph+17
        if y<42:raise ValueError(f'text overflow on page {index}')
        c.setFont('CN',9);c.setFillColor(HexColor('#63758b'));c.drawString(28,24,'页面截图为功能演示；历史示例不代表学校真实评价结果。');c.drawRightString(814,24,f'{index} / {len(PAGES)}');c.showPage()
    c.save();print(OUT)

if __name__=='__main__':main()
