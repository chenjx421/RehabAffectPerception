"""Evidence-labelled history and current UX screenshot guide."""
from pathlib import Path
from xml.sax.saxutils import escape
from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.colors import HexColor
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/pdf'
SHOTS=ROOT/'output/playwright/course_workspace_20260921'

# Dates are documentary checkpoints, not reconstructed release dates.
HISTORY=[
('2026-06-26至06-29（文件线索）','初始课堂AI演示','原型','需要在拿不到充分校方数据时展示分析思路。','建立education_demo网页和演示入口，用结构化状态与交互说明初步流程。','先让方案可见，再进入真实录像场景；当前仅能确认模块存在与文件时间，不能恢复当日所有按钮和算法。','src/rehab_affect/education_demo.py；scripts/build_education_demo_ppt.mjs'),
('2026-07-01至07-02','从通用演示转到单学生课堂视频','功能','学校可导出视频和评课详情，关注的是具体学生而非泛化课堂仪表盘。','人工确定目标区域，把视频、课堂背景和30秒窗口放在同一界面；提供窗口复核和结构化JSON。','可以定位课堂时段；早期窗口比例、状态与动作建议是原型输出，不是经过校方标注验证的识别准确率。','docs/seewo_student_demo_readme_zh.md；src/rehab_affect/seewo_student_demo.py'),
('2026-07-03','结合学生资料形成个体支持背景','功能','仅看动作难以说明学生需要什么支持，需要结合基础资料和IEP。','方案与页面组织为学生画像、数据来源、课堂结论、支持重点及后续追踪。','资料参与演示背景；这一阶段不等于已经拥有后来的加密、授权、版本化档案体系。','docs/seewo_student_ai_support_solution_zh.docx'),
('2026-07-06','明确学校演示的输入输出与支持效果','交付','校方需要知道文件从哪里来、结果是什么，以及老师如何使用。','明确先人工导出和预置素材演示，介绍课堂支持效果复盘；机器人保留为动作建议载体。','没有希沃自动同步；不能把相邻时段状态改善当作教师干预的因果证明。','docs/seewo_school_demo_plan_zh.docx；docs/seewo_demo_io_flow_for_school_zh.docx'),
('2026-07-22','整理校方演示路线','交付','需要重开旧Demo并熟悉现场展示顺序。','形成演示排练说明，把学生、时间窗、证据与建议按讲解顺序组织。','主要改进交付可讲解性，不单独计为算法升级。','docs/seewo_school_demo_rehearsal_zh.md'),
('2026-07-31','源码汇编与系统说明','交付','需要把代码和产品结构交给公司留档。','汇编源代码及模块说明，形成可查阅的Word。','代码汇编不是当日完整Git快照，也不证明代码已上线。','docs/辅读学校Demo_源码汇编与通俗说明_20260731.docx'),
('2026-08-11','Demo2：从单人状态到三人学习成效','功能','学校提出同时分析三名学生，并关注这节课学会多少；保留Demo1功能。','加入课程目标、多人固定区域观察、个体能力背景、群像/个体视图、学习掌握初评和支持建议。','将是否参与和是否掌握分开；早期初评包含规则与演示假设，不能直接迁入新上传学生的真实成绩。','docs/辅读学校课堂学习成效分析_Demo2介绍文档.docx'),
('2026-08-12','教师复核与App方向说明','交付','教师不知道需要标什么，同时公司讨论移动端落地。','整理关键片段的标注/复核操作，说明App需要的服务与部署条件。','文档说明不代表App已经开发，也不代表教师修正后已有自动训练管线。','docs/Demo2_教师关键片段复核与标注操作说明.docx；docs/Demo2_App化产品方向与实施条件说明.docx'),
('2026-08-14','逐页截图与前端展示整理','交付','需要看到所有细分页面，检查布局与展示效果。','生成页面截图文档，梳理群像、个体、时间片和报告等页面。','属于界面及说明交付；不能由截图证明所有按钮均可写入后端。','docs/Demo2_全部细分页面截图展示_20260814.docx'),
('2026-08-17','重点页面图文说明与价值说明','交付','经理需要快速理解产品分析维度和有竞争力的功能。','围绕课程指标、群像与个体、时间片、报告制作PDF和简短功能说明。','强调证据与个体化支持，不把商业差异化写成已验证的准确率领先。','output/pdf/Demo2_重点页面图文说明_20260817.pdf；docs/Demo2_核心竞争力与课堂表现分析维度_20260817.docx'),
('2026-08-20','以学校试点为目标复盘、蓝白界面调整','功能','公司要求落实到具体学生收益、老师操作和实体测试条件。','围绕课程目标、课堂证据、教师调整、学生结果与后续支持重新组织页面，并形成前端验收和准备度报告。','页面已有落点不等于真实识别可靠；复盘明确数据质量、标注成本和学校条件是主要短板。','docs/Demo2_产品复盘与学校实体测试准备度报告_20260820.docx；docs/demo2_frontend_acceptance_zh.md'),
('2026-08-26','资料导入、本地数据库和四路上传规划','功能','公司提出IEP/专业资料上传、本地数据库、四个独立上传主体。','组织SQLite与受控文件目录，区分资料原件、结构摘要、视频任务和结果；梳理四路上传流程。','该日期包含规划内容；四个通道不等于四机位已同步融合，四主体的实际业务含义仍需确认。','docs/demo2_local_database_and_four_channel_plan_zh.md；docs/RehabAffect_Demo2_规划_20260826.docx'),
('2026-08-27','保存期限、协议入口与逐页展示','交付','原始视频希望60天保存、提前15天提醒，上传前说明数据安全。','全页面材料呈现存储与安全流程，补充逐页说明。','现有文件可确认该轮交付；删除任务和长期归档的后端能力要按后续版本核对，不能仅据页面认定。','output/pdf/RehabAffect_Demo2_逐页图文功能说明_20260827.pdf'),
('2026-08-31','系统与源码再次汇编','交付','需要一份反映新版平台结构的源码说明与整合方向。','更新系统汇总、代码说明和后续路线。','属于阶段交付，不应把文档更新次数直接累加成新功能发布次数。','docs/辅读学校Demo2_系统汇总与源码说明_20260831.docx'),
('2026-09-07','四账号内测平台与管理员后台','功能','每个上传主体需要独立账号、每课3至5个名额，并能看进度和下载结果。','预设四个上传通道与独立管理员，按账号管理任务、名额、结果和存储状态，明确本地、局域网、云端区别。','四账号默认每课最多20项任务是配置上限，不是同时分析20路的性能承诺。','docs/demo2_school_pilot_platform_plan_zh.md；docs/辅读学校课堂分析平台_四账号上传与落地实施结果方案_20260907.docx'),
('2026-09-08','入口整理与分析路线重新收敛','功能','领导要易用登录、学校归属、用户/管理员区别，同时要求分析更扎实。','整理账号、学校、城市区县与上传路径；明确旧案例演示和新上传真实分析必须分开。','学校名称最初只是元信息，后续身份模块才进一步建立范围校验；不能说填写同一学校即可共享档案。','docs/demo2_market_research_and_analysis_plan_20260908_zh.md；docs/demo2_analysis_execution_plan_20260908_zh.md'),
('2026-09-08','新上传接入真实媒体处理','功能','上传成功不能停留在文件预检或展示旧案例。','接入任务队列、FFmpeg解码、采样图、音轨、媒体质量测量、时间窗及受保护回放。','形成真实证据产物，但没有在这条管线中完成ASR、姿态语义、情绪或掌握度识别。','docs/demo2_media_pipeline_zh.md；docs/media_pipeline_iteration_20260908_zh.md'),
('2026-09-09','手机号会员与外部邀请访问','功能','会员是付费业务，不是学校申请表；经理需要异地登录。','分离手机号注册、会员权益、订单与学校访问授权；用带账号登录的邀请网关提供临时访问。','短信和支付服务未配置时拒绝真实注册/付款；临时隧道不是稳定生产域名。','scripts/build_demo2_membership_guide_20260909.py；src/rehab_affect/demo2_manager_gateway.py'),
('2026-09-10','人脸位置与姓名身份拆开','功能','其他学校上传新视频后，必须对应本校学生，而不是套用原三人名单。','创建稳定student_id和本校名册，检测人脸候选；教师选择学生并确认框选，保存帧版本和任务归属。','检测到人脸不等于识别姓名；尚未建立跨视频自动人脸身份匹配。','docs/demo2_student_identity_flow_20260910_zh.md；docs/demo2_face_detection_zh.md'),
('2026-09-11','回看体验与缓存性能优化','功能','需要清楚画面、易找任务，并减少重复检测等待。','增加任务筛选、片段循环、只读彩色原片参考、有限缓存与解码预算；移动端检查。','原片参考不是超分辨率；缓存命中仍核查权限。文档中的耗时对照为本机暖缓存，不是全校压测。','docs/demo2_upgrade_20260911_zh.md'),
('2026-09-11','手动画框可用、三步对应与通道实操','功能','老师不愿复杂操作，漏检要能人工补框；后台不能只有展示。','把选人、选姓名、确认简化为三步；可就地新增学生；增加后续5秒位置建议；管理员可调整通道名额和暂停。','位置建议是短时光流，不是整节课追踪。管理员不替学校猜测身份，完全遮挡不强行绑定。','docs/demo2_teacher_identity_flow_20260911_zh.md'),
('2026-09-11','学生资料授权、加密与版本引用','功能','姓名、视频、IEP和专业评估要正确关联，也不能无限留存敏感材料。','新增受授权约束的档案原件/摘要、版本、课程引用、撤回到期处理；公司后台仅看运维元数据。','新增资料加密不代表整个数据库和所有旧视频加密；未自动进入训练集，也未形成跨教师共享。','docs/demo2_dossier_delivery_20260911_zh.md；docs/contracts_demo2_dossier_v1_20260911.md'),
('2026-09-15至09-17','长期测量、图文报告与采集入口','功能','需要逐课/周/月/60天趋势，约千字报告，保存音视频而非大量纯文字。','引入四维目标观察、分数与证据关联、长期测量视图、图文报告和浏览器采集入口。','早期契约写6分及格、缺证据记0等内容；后续实现修正为项目参考线、证据不足不形成完整总分。具体变更日无法从Git复原。','docs/assessment_and_longitudinal_spec_zh.md；src/rehab_affect/assessment_rubric.py；src/rehab_affect/media_capture.py'),
('2026-09-16','学校与系统双轨课堂评价','功能','经理要求学校规则和增强规则切换，解释分数为何不同，并有依据。','保留校表原分和折算，增加增强权重、逐项证据、分差分解、理由建议与参考文献。','两轨仍需人工录入；学科观察重点没有实际动态调权，精确权重未验证，DeepSeek解释Agent未接通。','docs/dual_track_delivery_review_20260916.md；docs/dual_track_api_20260916.md'),
('2026-09-17','全页面与整改展示材料','交付','开会需要直接看现有功能，不再等完整新模型。','生成全页面截图PDF，整理当时整改情况与后续办法。','作为当时页面证据，不把尚未实现的科学评分、训练或新增资料处理写成已完成。','output/pdf/Demo2_当前全页面功能展示_20260917.pdf'),
('2026-09-21 / 单视频','新课证据、教师复核与报告打通','功能','新上传视频需要真正产生自己的群像、个体、片段与报告。','用当前任务身份及媒体版本关联观察；实现保存、修改、撤销、群像/个体视图及约千字确定性报告和导出。','证据不足不填满千字，不借用旧示例分数；身份撤销或版本变化使相关分数失效。','docs/course_workspace_delivery_20260921.md；src/rehab_affect/demo2_course_analysis.py'),
('2026-09-21 / 同课多视频','同一课堂多来源去重复核','功能','同一学生同一目标可能来自多个视频，不能重复统计或直接平均。','按课程、日期、学生、目标和条件分组；教师选代表记录并说明，指纹与版本变化会要求重确认。','同课汇总仍在当前账号内，尚未自动多机位时间对齐，也不是跨账号共享。','docs/batch_review_delivery_20260921.md；src/rehab_affect/demo2_batch_review.py'),
('2026-09-28 / 教学支持','照顾沟通差异、逐课改进与模型入口','功能','老师希望支持措施更有针对性，关注学生进步、教学改进和非言语发声。','增加回应媒介/采音质量/声源确认、三类教学支持、逐课反思、上传五步检查及DeepSeek白名单预览。','支持建议由教师选择，不由视频诊断；发声人工记录；模型没有联网，教师反思不等于已验证的教学改善。','docs/teaching_support_delivery_20260928.md；src/rehab_affect/teaching_support.py'),
('2026-09-28 / 使用体验','边看边记、复用目标与减少误操作','功能','使用者复核时反复切页、重复填目标、容易丢失修改。','播放器进入复核页；当前位置设起止点、片段到点暂停；沿用目标但清空证据分数；待办筛选、课程搜索、未保存提醒、手机入口与蓝白布局。','已用合成素材验证操作；没有借此宣称自动识别提升。真实老师的操作耗时与学习成本仍需现场试用。','docs/teacher_workflow_review_20260928.md；output/playwright/course_workspace_20260921/acceptance.json'),
]

def setup():
    OUT.mkdir(parents=True,exist_ok=True)
    pdfmetrics.registerFont(TTFont('CN','C:/Windows/Fonts/simhei.ttf'))

def para(c,text,x,y,w,size=11,leading=17,color='#31465e'):
    p=Paragraph(escape(text),ParagraphStyle('p',fontName='CN',fontSize=size,leading=leading,textColor=HexColor(color),wordWrap='CJK'))
    _,h=p.wrap(w,2000);p.drawOn(c,x,y-h);return y-h

def frame(c,title,page,total,w=842,h=595):
    c.setFillColor(HexColor('#f5f8fc'));c.rect(0,0,w,h,fill=1,stroke=0)
    para(c,'RehabAffect / 课堂观察平台 / 2026.09.28',30,h-25,w-60,10,14,'#2463dc')
    para(c,title,30,h-55,w-60,22,30,'#20344b')
    c.setFont('CN',9);c.setFillColor(HexColor('#63758b'));c.drawString(30,20,'项目记录 · 历史方案不等同于当前已实现能力');c.drawRightString(w-30,20,f'{page} / {total}')

def current_pdf():
    pages=[
        ('课程列表：更快找到本节课','01_task_picker',None,'新增课程和文件名搜索，处理状态显示中文。上传入口直接放在课程列表，不必回到另一层菜单。','进入课堂列表 → 搜索 → 选择课程。列表限当前账号最近200个未取消任务。'),
        ('片段复核：视频与表单同屏','03_teacher_review',(0,0,2160,1770),'桌面端左侧回看、右侧记录；窄屏上下排列。可从播放器当前位置设置片段起止点，回放到结束点自动暂停。','减少在群像和复核页之间往返。播放器是同一个媒体实例，不重复加载两份视频。'),
        ('新增观察：沿用目标，不复制结果','03b_reuse_goal',(1000,650,2160,2920),'“沿用目标新增”保留学生、日期、目标、条件和达成标准。回应、证据、评分和已复核状态全部重新填写。','未保存时清空、切换编辑和刷新会确认；离开页面使用浏览器原生提醒。没有将敏感草稿长期写入浏览器。'),
        ('待办与表单：减少一次性信息量','03a_pending_filter',(900,480,2160,3100),'记录可以筛选为全部、待复核/待重确认、已复核。音频与沟通方式默认折叠；评分仍然可留空。','已复核但不能计分不等于失败，未观察到的维度不强行补零。待处理筛选不改变原记录。'),
        ('手机入口：本课操作不再藏起来','mobile_390_group',None,'学生对应、课程资料、教学支持入口移到窄屏仍可见的位置；保留群像、个体、复核和报告切换。','已检查320和390像素宽度，没有页面横向溢出。截图使用虚构验收学生及合成视频。'),
        ('验收与下一步','06_illustrated_report',None,'本轮23项定向测试通过；浏览器完成保存、重载、撤销、导出、筛选、搜索、片段暂停和目标复用验收。','还需推进自动候选片段、跨课目标模板、可靠人物追踪、模型解释及稳定公网部署。这次主要改善操作，不宣称模型准确率提高。'),
    ]
    path=OUT/'Demo2_本次前端与操作优化_20260928.pdf';c=canvas.Canvas(str(path),pagesize=(842,595));c.setTitle('Demo2 本次前端与操作优化')
    for n,(title,name,crop,desc,boundary) in enumerate(pages,1):
        frame(c,title,n,len(pages));image=Image.open(SHOTS/(name+'.png'))
        if crop:image=image.crop((crop[0],crop[1],min(crop[2],image.width),min(crop[3],image.height)))
        from reportlab.lib.utils import ImageReader
        scale=min(520/image.width,420/image.height);w,h=image.width*scale,image.height*scale
        c.drawImage(ImageReader(image),30+(520-w)/2,55+(420-h)/2,w,h)
        y=para(c,'本次变化',578,474,230,15,22);y=para(c,desc,578,y-14,230,12,20)
        y=para(c,'操作与边界',578,y-25,230,15,22);para(c,boundary,578,y-14,230,11,18)
        c.showPage()
    c.save();return path

def history_files():
    path=OUT/'Demo_从首版至今的迭代记录_20260928.pdf'
    def block_lines(i,item):
        date,title,kind,need,change,boundary,source=item
        return [(f'R{i+1:02d} / {date} / {kind}',10,15,'#2463dc'),(title,16,23,'#20344b'),
            ('需求：'+need,10.5,16,'#31465e'),('做法：'+change,10.5,16,'#31465e'),
            ('结果与边界：'+boundary,10.5,16,'#31465e'),('依据：'+source,9,13,'#63758b')]
    groups=[];group=[];used=0
    for i,item in enumerate(HISTORY):
        height=0
        for text,size,leading,color in block_lines(i,item):
            p=Paragraph(escape(text),ParagraphStyle('measure',fontName='CN',fontSize=size,leading=leading,wordWrap='CJK'))
            height+=p.wrap(525,2000)[1]+7
        if group and used+height+20>680:groups.append(group);group=[];used=0
        group.append((i,item));used+=height+20
    if group:groups.append(group)
    total=3+len(groups);c=canvas.Canvas(str(path),pagesize=(595,842));c.setTitle('Demo 从首版至今的迭代记录')
    frame(c,'从首版演示到课堂证据工作台',1,total,595,842)
    y=735
    for text in [f'统计到2026年9月28日：整理{len(HISTORY)}个可追溯迭代/交付节点，另记录3个前期方案节点。编号R01等是本次整理号，不是历史正式版本号。',
        '统计方法：交叉核对本地方案、README、历次PDF、构建脚本、源码和验收记录。Git只有2026年6月4日初始化提交，不能据此精确恢复每次代码变更。文件时间也不能当成正式发布日期。',
        '同一天的不同工作流可分开记录；文档、截图、源码汇编单列为交付节点。本文不是29次上线记录，也不是29套模型。未把用户仅提出但未实现的需求算成功能完成。',
        '技术主线：通用演示 → 单学生课堂视频 → 三人Demo2 → 四账号上传平台 → 媒体与身份关联 → 受保护档案 → 双轨评价 → 新上传证据与复核报告 → 教师工作流优化。',
        '不统计：另行开展的MuJoCo个人开发、AI课程和PPT制作。暂停的额外三名学生资料不作为已完成导入记录。']:
        y=para(c,text,35,y,525,12,20)-22
    c.showPage();frame(c,'前期方案与统计总览',2,total,595,842);y=735
    for title,text in [
        ('P01 / 2026-06-22 / 具身课堂辅助方案','提出状态感知、学生支持与机器人动作闭环。来源：special_education_embodied_classroom_design_zh.docx。属于方案，不代表机器人系统完成。'),
        ('P02 / 2026-06-24 / 会议后软件优先','根据成本与可行性讨论，将软件互动和学生收益放在前面，硬件后置。来源：同名会议后红字修改版。'),
        ('P03 / 2026-06-25 / 落地任务收敛','将首个场景写为课堂常规与物品整理等短任务，并明确输入、提示和复盘。来源：special_education_ai_tutor_practical_solution_zh.docx。'),
        ('节点统计','原型1项、功能19项、交付9项，共29项。前期方案3项另列。功能节点数是文档追溯的分类，不是验收通过次数，也不等于每项都已生产可用。'),
        ('阅读方式','每个节点依次记录：当时需求、怎么实现/组织、实际变化与边界、可核对来源。日期不确定处明确写文件线索或时间区间。')]:
        y=para(c,title,35,y,525,14,22)-6;y=para(c,text,35,y,525,11,17)-20
    c.showPage()
    for page,group in enumerate(groups,3):
        frame(c,'逐次迭代记录',page,total,595,842);y=738
        for index,item in group:
            for text,size,leading,color in block_lines(index,item):
                y=para(c,text,35,y,525,size,leading,color)-7
            y-=20
            if y<38:raise ValueError(f'History layout overflow {index}: {y}')
        c.showPage()
    frame(c,'几次最重要的纠正与剩余工作',total,total,595,842);y=735
    for title,text in [
        ('从展示假设转向可回查证据','早期固定案例的状态和掌握初评，不能自动成为新上传学生的成绩。9月媒体、身份与复核链路将真实录像、教师记录和报告限定到同一任务。'),
        ('从动作多少转向目标达成','单纯安静、动作少、抬头不能证明学会。当前以任务、学生回应、支持条件、观察次数和教师复核作为记录基础。'),
        ('从“6分及格”转向试行参考线','历史草案存在不严谨评分描述。当前缺失不补零；教师质量、学生目标和IEP领域不是同一种分数，试行权重尚未经过真实校准。'),
        ('从公司全存转向目的与授权限制','新增IEP原件/摘要受授权、版本、期限和权限控制。公司运维汇总不等于能读取全部敏感正文；不自动进入训练集。'),
        ('还需要完成','自动互动候选片段与声源归属、稳健的连续身份追踪、DeepSeek实际调用及校验、跨课目标模板、多教师授权协作、正式托管和真实课堂效度验证。'),
        ('验收数字怎么读','93项、23项等是不同范围的工程测试，不相加当作独立测试总量，更不能当成识别准确率。本轮界面检查采用合成素材。')]:
        y=para(c,title,35,y,525,13,20)-5;y=para(c,text,35,y,525,11,17)-17
    c.save()
    md=['# Demo 从首版至今的迭代记录','',f'共{len(HISTORY)}个有据节点，另有3个前期方案节点。并非完整Git变更历史；仅有初始化提交。日期为材料日期或明确标注的文件线索。','']
    for i,item in enumerate(HISTORY,1):
        date,title,kind,need,change,boundary,source=item
        md += [f'## R{i:02d} {date} | {title} | {kind}',f'- 需求：{need}',f'- 做法：{change}',f'- 结果与边界：{boundary}',f'- 依据：{source}','']
    (ROOT/'docs/demo_iteration_history_20260928.md').write_text('\n'.join(md),encoding='utf-8')
    return path

if __name__=='__main__':
    setup();print(current_pdf());print(history_files())
