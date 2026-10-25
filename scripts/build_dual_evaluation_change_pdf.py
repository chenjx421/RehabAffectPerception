from pathlib import Path
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, PageBreak, Table, TableStyle

ROOT = Path('D:/GIT/RehabAffectPerception')
OUT = ROOT / 'output/pdf/demo2_双轨评价整改与DeepSeek接入说明_20260916.pdf'
FONT = 'C:/Windows/Fonts/simhei.ttf'
IMG = ROOT / 'output/playwright/demo2_teacher_flow_20260911_isolated/manual_saved.png'
IMG2 = ROOT / 'output/playwright/demo2_current_guide_20260909/35_tab_teacher.png'

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
pdfmetrics.registerFont(TTFont('SimHei', FONT))

styles = getSampleStyleSheet()
title = ParagraphStyle('title', parent=styles['Title'], fontName='SimHei', fontSize=22, leading=30, textColor=colors.HexColor('#173A70'), alignment=TA_LEFT, spaceAfter=12)
h = ParagraphStyle('h', parent=styles['Heading2'], fontName='SimHei', fontSize=15, leading=22, textColor=colors.HexColor('#087C72'), spaceBefore=8, spaceAfter=7)
body = ParagraphStyle('body', parent=styles['BodyText'], fontName='SimHei', fontSize=10.5, leading=18, textColor=colors.HexColor('#28394E'), spaceAfter=7)
small = ParagraphStyle('small', parent=body, fontSize=8.5, leading=13, textColor=colors.HexColor('#5B6B7D'))

def p(text, style=body): return Paragraph(text.replace('\n','<br/>'), style)
def footer(canvas, doc):
    canvas.saveState(); canvas.setFont('SimHei', 8); canvas.setFillColor(colors.HexColor('#718096'))
    canvas.drawString(20*mm, 12*mm, 'RehabAffectPerception · Demo2 整改说明')
    canvas.drawRightString(190*mm, 12*mm, f'{doc.page}')
    canvas.restoreState()

story = [p('Demo2 双轨评价整改与 DeepSeek 接入说明', title),
         p('版本：2026-09-16　范围：课堂教学质量评价、长期测量、视频音频留痕与后续智能报告', small), Spacer(1, 5*mm),
         p('本次交付目标', h),
         p('围绕学校提出的七项整改要求，将课堂评价从单一分数展示整理为一条可追溯的工作流：课前锁定评价口径，课中保留视频和音频证据，课后分别呈现学校原始评分与系统增强评分，并支持长期趋势、报告、存储治理和四个内测上传账号。', body),
         p('当前实现采用确定性服务端计算。模型或大模型不能绕过教师确认、学校授权、数据期限和权限边界。', body),
         PageBreak(),
         p('一、双轨课堂评价', title),
         p('学校评价轨', h), p('保留学校原有评价表。基本评价模板为 10 项 1 至 10 分；另保留 15 项学校历史模板，只接受原表 2 至 5 的枚举评分，不擅自推断学校综合等第。系统明确区分“教师原始评分”和“按学校标准录入的待核对初评”。', body),
         p('系统增强轨', h), p('在基本评价模板上按目标适配、内容组织、过程支持和教师响应四个维度进行结构化整理。增强分为 0 至 10 分，当前权重属于候选设计，页面明确提示“尚未校准”。只有已复核且完整的增强结果才使用 6 分试行参考线。', body),
         p('差异解释', h), p('系统把增强分与学校分的差异拆成“证据修正”和“权重变化”两部分，并展示每个条目的证据、原因和建议。缺失资料留空，不按 0 分处理，也不把分数差异写成因果结论。', body),
         p('课前口径锁定', h), p('教师选择课程类型、评价模板并填写本课目标、学生分层和支持约定。保存后这三类口径锁定，改变评价标准必须撤销后新建，避免同一条记录在不同口径下被悄悄重算。', body),
         PageBreak(),
         p('二、图文证据与教师操作', title),
         p('教师在评价页面按条目填写学校分、系统增强分、证据、调整原因和下一步建议。已复核的有分条目必须填写证据；增强分与学校分不一致时必须说明原因。系统只保存服务端计算结果，浏览器不自行计算权重。', body),
         Image(str(IMG), width=170*mm, height=60*mm),
         p('图 1　手动画框和教师确认的隔离测试画面。该页面用于说明“自动候选 + 教师确认”的操作逻辑，截图中的资料为合成测试内容。', small),
         p('报告展示', h), p('千字报告由指标卡、趋势图、关键时间段和文字解释组成。每张图标注时间范围、单位、样本数以及“系统初评/教师已复核”。文字只解释图中可见变化，证据不足时显示缺口。', body),
         PageBreak(),
         p('三、长期测量与数据治理', title),
         p('长期页面按每次课、每周、每月和滚动 60 天展示综合分、正确性、独立程度、重复一致性和迁移等维度。趋势图只连接有效评分点，缺失和未观察显示为空档并注明原因。群像页呈现班级支持情况，点击学生后进入个体页，避免把群体均值误读为个人结论。', body),
         p('视频与音频', h), p('系统保留上传任务、处理状态、视频版本、抽帧时间、音轨提取状态和错误原因。音频当前用于音轨保留与能量统计，不能把声音大小直接当作学生回答，也没有把 ASR 结果伪装成已完成能力。', body),
         p('存储与权限', h), p('结构化记录按课程、学生、教师、学校和版本关联；敏感资料使用加密保存。原始媒体按最长 60 天管理，到期前 15 天提醒。公司后台默认展示数量、状态、到期和存储占用等元数据，不直接开放学生资料正文。管理员不能代替学校教师完成学生身份确认。', body),
         p('四个内测账号', h), p('t1 至 t4 分别绑定四个上传通道。每个账号在同一课程下默认 5 个视频名额，后台可调整为 3 至 5 个并暂停新上传。账号之间按通道和学校范围隔离。', body),
         PageBreak(),
         p('四、DeepSeek 接入方案', title),
         p('适合接入的位置', h), p('DeepSeek 作为“匿名结构化证据的报告辅助层”：本地视频处理先生成时间段、人物确认状态、教师标注、评分、趋势和证据摘要，再由模型辅助整理千字课堂反馈、关键变化和教师改进建议。', body),
         p('明确不交给 DeepSeek 的任务', h), p('不让模型直接读取原始视频、原始音频、学生姓名、IEP、病理诊断或未脱敏身份资料；不让模型决定人脸身份、学校评分、及格结果、权限、保存期限或删除操作。模型输出必须标为“待教师审核”，审核通过后才允许保存和下载。', body),
         p('当前代码状态', h), p('报告模块已经支持本地证据模板，并预留兼容 OpenAI 接口的配置项：REHAB_REPORT_LLM_BASE_URL、REHAB_REPORT_LLM_MODEL 和可选 API Key。当前未配置真实 DeepSeek Key，因此默认不调用外部模型，Demo 仍可离线生成报告。', body),
         p('推荐调用链', h), p('本地抽取证据 → 脱敏与字段白名单 → DeepSeek 生成候选文字 → JSON 格式校验 → 禁止新增无证据事实 → 教师审核 → 版本化保存与下载。若网络、接口或模型返回异常，自动回退本地证据模板。', body),
         PageBreak(),
         p('五、验收结果与剩余边界', title),
         p('已完成并验证', h),
         Table([[p('项目', small), p('结果', small)], [p('双轨规则、缺失项和差异分解', small), p('已实现，正式测试通过', small)], [p('权限、版本、撤销和历史快照', small), p('已实现，正式测试覆盖', small)], [p('学校原表与 15 项模板', small), p('已保留，15 项不伪造增强映射', small)], [p('管理员元数据和存储期限', small), p('已有页面与数据结构', small)], [p('代码回归', small), p('149 passed', small)]], colWidths=[75*mm, 95*mm], style=TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#EAF2FB')),('GRID',(0,0),(-1,-1),0.3,colors.HexColor('#C9D6E5')),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5)])), Spacer(1, 5*mm),
         p('尚需真实部署前完成', h), p('浏览器完整点击验收仍受本机 Playwright 浏览器启动环境影响；正式公网服务还需要 HTTPS、云端对象存储、备份恢复、账号重置、短信或支付服务配置，以及真实学校授权下的准确率和报告质量评估。当前结果可用于需求沟通、软件演示和受控试点，不能表述为已完成真实学校模型准确率验证。', body),
         p('文件与入口', h), p('Demo 页面：http://127.0.0.1:8793/demo2/login<br/>接口契约：docs/dual_track_api_20260916.md<br/>报告生成器：src/rehab_affect/seewo_long_report.py', body)]

OUT.parent.mkdir(parents=True, exist_ok=True)
SimpleDocTemplate(str(OUT), pagesize=A4, rightMargin=20*mm, leftMargin=20*mm, topMargin=16*mm, bottomMargin=20*mm, title='Demo2 双轨评价整改与 DeepSeek 接入说明').build(story, onFirstPage=footer, onLaterPages=footer)
print(OUT)
