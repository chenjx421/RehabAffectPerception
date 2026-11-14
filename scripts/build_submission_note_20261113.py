from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

OUT='/Users/chenjia/Downloads/WeGlow_学生检测报告_送审_20261113/00_学生检测报告送审说明.docx'
INK=RGBColor(0x17,0x2b,0x4d); BLUE=RGBColor(0x1f,0x63,0xc6); MUTED=RGBColor(0x5f,0x71,0x86)

def shade(cell,color):
    tcPr=cell._tc.get_or_add_tcPr();shd=OxmlElement('w:shd');shd.set(qn('w:fill'),color);tcPr.append(shd)

def cell(cell,text,bold=False,size=9,color=INK):
    cell.text='';p=cell.paragraphs[0];p.paragraph_format.space_after=Pt(1)
    r=p.add_run(text);r.bold=bold;r.font.size=Pt(size);r.font.color.rgb=color;r.font.name='Arial';r._element.rPr.rFonts.set(qn('w:eastAsia'),'Heiti SC')

def table(doc,headers,rows,widths):
    t=doc.add_table(rows=1,cols=len(headers));t.style='Table Grid';t.alignment=WD_TABLE_ALIGNMENT.CENTER
    for i,h in enumerate(headers):cell(t.rows[0].cells[i],h,True,8.5);shade(t.rows[0].cells[i],'E8EEF7')
    for row in rows:
        cells=t.add_row().cells
        for i,v in enumerate(row):cell(cells[i],v,size=8.5)
    for row in t.rows:
        for i,w in enumerate(widths):row.cells[i].width=Cm(w)

doc=Document();s=doc.sections[0];s.top_margin=Cm(1.6);s.bottom_margin=Cm(1.5);s.left_margin=Cm(1.9);s.right_margin=Cm(1.9)
n=doc.styles['Normal'];n.font.name='Arial';n.font.size=Pt(10);n._element.rPr.rFonts.set(qn('w:eastAsia'),'Heiti SC');n.paragraph_format.space_after=Pt(4)
p=doc.add_paragraph();r=p.add_run('WeGlow 微光系统');r.bold=True;r.font.size=Pt(11);r.font.color.rgb=BLUE
p=doc.add_paragraph();r=p.add_run('学生检测报告送审说明');r.bold=True;r.font.size=Pt(24);r.font.color.rgb=INK
p=doc.add_paragraph('2026-11-13 · 5 名学生完整课堂测试');p.runs[0].font.color.rgb=MUTED
p=doc.add_paragraph('本说明用于核对报告是否符合四点要求；5 份学生报告为附件。')

doc.add_heading('一、本次测试使用的完整材料',level=1)
for text in [
    '课堂视频：5 人“好吃的水果”课堂视频，任务 2647da990ff44c66a76f0c535fe65ef7，课堂日期 2026-11-09。',
    '学生身份：张恒宇、虞顾超、阮睿煜、李晟睿、邓之呈，均为二（1）班；课堂中使用教师确认的 5 个座位。',
    'IEP：5 名学生各有 1 份真实 IEP 原件，报告中的 IEP 支持摘要来自对应材料。',
    '课程教案：1 份《好吃的水果》验收测试教案。',
    '目标与测量：5 份长期/短期目标，15 条已复核测量。',
    '总览结果：课程总览 71.7 良好，学生短期目标均分 5.7/10。',
]:
    p=doc.add_paragraph(text,style='List Bullet');p.paragraph_format.space_after=Pt(2)

doc.add_heading('二、四点要求在报告中的位置',level=1)
table(doc,['报告目的','报告位置','可见证据'],[
    ['1. 了解本次课程学习状态','第 1 部分','稳定参与/回应较低/离开比例、课堂状态图、切片复核表、3 张证据帧'],
    ['2. 是否达成课程目标与评分','第 2 部分','3 条短期目标、6 分参考线判断、学生均分 5.7、课程总览 71.7'],
    ['3. 集中度与评分偏差解释','第 3 部分','四维得分、权重、加权贡献、低于/高于 6 分的解释'],
    ['4. IEP 与长期教学规划建议','第 4 部分','IEP 支持摘要、每条目标建议、1/2/4/8 周复测、快慢节奏建议'],
],[4.4,3.0,9.0])

doc.add_heading('三、报告完整性核对',level=1)
table(doc,['核对项','结果'],[
    ['学生报告数量','5 份'],
    ['每份图片','6 张（学生画面 + 状态图 + 目标图 + 3 张证据帧）'],
    ['每份表格','4–5 个'],
    ['课程总览','71.7 良好，5 份均写入'],
    ['目标与测量','5/5 目标确认，15/15 测量已复核'],
    ['切片复核','按原始视频时间列出状态与片段参考分'],
],[6.0,10.0])

doc.add_heading('四、需要说明的边界',level=1)
for text in [
    '5 份长期/短期目标是验收测试草案，不是学校正式 IEP；正式使用前仍需特教老师逐条确认。',
    '5 人以上不输入人数的全自动成人/背景排除尚未完成；本次使用教师确认的 5 个座位。',
    '扫描/手写 OCR 已用仿真样本验证，真实学校手写件还需用真实样本复测。',
    '学习速度预测没有训练模型；只有同目标两个以上课堂日期时才计算趋势。',
    '教学计划是规则建议草案，不是完整正式教案。',
]:
    p=doc.add_paragraph(text,style='List Bullet');p.paragraph_format.space_after=Pt(2)

doc.add_heading('五、附件',level=1)
table(doc,['文件','说明'],[
    ['张恒宇_学生检测报告.docx','单份样例'],
    ['虞顾超_学生检测报告.docx','学生报告'],
    ['阮睿煜_学生检测报告.docx','学生报告'],
    ['李晟睿_学生检测报告.docx','学生报告'],
    ['邓之呈_学生检测报告.docx','学生报告'],
],[6.5,9.5])
p=doc.add_paragraph('报告中的分数用于教师回看与教学改进，不替代正式 IEP、医学或心理诊断。')
p.runs[0].font.size=Pt(9);p.runs[0].font.color.rgb=MUTED
doc.save(OUT);print(OUT)
