# 双轨课堂评价接口 v1

实现范围：课堂教学质量，与现有学生四维测量隔离。页面 /demo2/evaluation，教师角色 school_uploader。新文件 demo2_evaluation.py 提供 render_evaluation(account=None)，使用 demo2_portal._document/_WORKSPACE_STYLE/_account_payload（script参数为纯JS）。不调用语言模型API。

GET /api/v1/demo2/evaluations 返回 {ok:true,workspace:{records:[],templates:[],subjects:[],references:[],needs_school_context:bool,school_context:{},rule_version:str}}。
POST /api/v1/demo2/evaluations/preview 返回 {ok:true,result:...}，仅计算不保存。
POST /api/v1/demo2/evaluations 返回 {ok:true,record:...}。
POST /api/v1/demo2/evaluations/withdraw body {record_id,expected_version,reason} 返回 {ok:true,record:...}。
所有错误 {ok:false,error:{code,message}}。session cookie登录；退出用 /api/v1/demo2/auth/logout。

保存和preview相同payload（以下字段全部必需）：
{record_id:UUID,expected_version:0,lesson_id:string,lesson_date:YYYY-MM-DD,course_name:string,subject_id:string,template_id:string,goal_context:string,school_source:'teacher_recorded'|'rubric_initial',school_rater:string,reviewed:false,items:[{id:string,school_score:number|null,enhanced_score:number|null,evidence:string,reason:string,suggestion:string}]}
school_rater仅school_source=teacher_recorded时必填，否则空串。evidence是该条证据摘要或人工观察/教案页码/时间点，允许换行，不接受可执行HTML。每个模板全部items必须给出一次，不允许额外项。改变后的enhanced_score必须填写reason；reviewed=true时，每个有评分项必须有evidence。未评项null。仅全项有分才有总分；reviewed=false有暂算总分但status='provisional'，已复核且全项完整status='reviewed'，否则status='incomplete'。缺项不填0、不归一化。

模板结构 {id,label,source_file,version,enhanced_available,school_min,school_max,note,categories:[{id,label,school_weight,enhanced_weight,rationale}],items:[{id,label,category_id,school_weight,enhanced_weight,anchor}],rules_note}。
school_weight/enhanced_weight均是0..1，不是百分数。main模板id=basic_100，有10项id=i1..i10，原分1..10；增强分0..10。school权重均0.1，增强权重[.15,.10,.08,.07,.05,.10,.10,.20,.08,.07]。
legacy模板id=qingpu_15，有15项j1..j15，只支持原表2/3/4/5枚举输入。无增强，enhanced_score必须null。明确显示“该表尚无增强映射，切换基本评价指标可使用双轨对照”，不要伪造差值或原等第。分类权重按原项数/15；学校折算分=原均分*2，原分2..5；等级边界不完整，提示查看原表，不擅定等级。

subject结构 {id,label,focus:[string],note:string}，语文/数学/实践/体育/音乐/综合。只影响目标建议文案、不自动更改顶层权重。goal_context必填本课目标和学生分层/支持约定，不存姓名；保存创建后subject_id/template_id/goal_context锁定，不允许编辑时悄悄改口径。UI在新建选模板/学科后展示focus，课前口径锁定提示；已有记录禁用这三项。

result结构：
{rule_version,template_id,status,school:{score_10,raw_score,raw_max,teaching_score_70,coverage:{scored,total},source_label,passed:null},enhanced:{score_10,coverage:{scored,total},reference_line:6,passed:bool|null,status_label},comparison:{available:bool,evidence_delta:number|null,weight_delta:number|null,total_delta:number|null,school_weight_reviewed_score:number|null,items:[{id,label,school_score,enhanced_score,evidence_delta,weight_delta,total_delta,reason,evidence,suggestion}]},categories:[{id,label,school_score:number|null,enhanced_score:number|null,school_weight,enhanced_weight,rationale}],note}
正式及格判定仅reviewed完整增强结果使用6分试行参考线；学校passed固定null，没有凭空学校总合格规则。差值为增强-学校，evidence_delta=sum(w*(z-s)),weight_delta=sum((v-w)*z)。不足资料差值不可用。score_10可能null。全项相同学校8分、增强7分，总分学校8，增强7，evidence_delta=-1,weight_delta=0,total_delta=-1。

record是规范化payload加{version:1,status:'active',result:...,created_at,updated_at,saved_by,rule_snapshot:{...}}。编辑expected_version当前version，撤销后记录退出workspace。preview不返回record，不修改数据库；预览数据变动必须清除旧结果或明显标记重新预览。已保存记录图文解释和导出读取record.result，禁止前端重算权重。

references:[{id,title,url,support,limitation}]。科学依据仅support描述，所有具体增强权重未验证。来源链接安全且静态白名单。

前端最低验收：真实API，无硬编码课堂记录；新建/保存/选择/编辑/撤销；双标签学校标准和系统增强；原始/折算/70分单列；缺失/未复核；学校真人评分来源与按校表初评区分；条形图和分差图及每项reason/evidence/suggestion；课程focus；文献支持与限制；原15项模板；打印与JSON导出；HTML转义；400/403/409处理且错误不丢表单；320px及桌面响应式、键盘焦点、无外部资源。标题明确“课堂双轨评价”，不是学生能力评分。

2026-09-16 交付补充：`school.reference_line=6` 与 `school.reference_status` 是项目侧的参考展示，学校正式 `passed` 仍为 null；未复核显示“待教师复核”，不完整显示“评分不完整”。新增 `subject_context={id,label,focus,note,policy,calibration_status}`，明确科目只提供观察重点、尚未启用学科或五领域加权。分数公式和版本不变。旧记录若没有这些新增字段，前端读取已有快照的课程关注点，不补造历史参考判定。结果页自动恢复最近保存记录；编辑后隐藏旧预览，重新保存生成版本。学校分和增强分展示两位小数，差值精度保持两位。
