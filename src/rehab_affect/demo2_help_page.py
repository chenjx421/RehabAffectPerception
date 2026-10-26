"""Teacher-facing help page for the Demo2 classroom analysis workflow."""

from __future__ import annotations

from .demo2_portal import _BOOK_ICON, _COMMON_STYLE, _document


HELP_STYLE = _COMMON_STYLE + r"""
body { background:#f7f9fc; }
.help-header { border-bottom:1px solid var(--line); background:#fff; }
.help-header-inner { width:min(1180px,calc(100% - 40px)); min-height:72px; margin:auto; display:flex; align-items:center; gap:24px; }
.help-header .brand { text-decoration:none; }
.help-header .brand-icon { width:38px; height:38px; padding:7px; }
.help-header .brand-copy strong { font-size:17px; }
.help-header .brand-copy span { font-size:11px; }
.help-header nav { margin-left:auto; display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
.help-header nav a { min-height:42px; display:inline-flex; align-items:center; padding:8px 12px; color:var(--muted); text-decoration:none; font-size:13px; }
.help-header nav a:hover { color:var(--blue); background:var(--blue-pale); }
.help-main { width:min(1120px,calc(100% - 40px)); margin:0 auto; padding:42px 0 72px; }
.help-hero { display:grid; grid-template-columns:minmax(0,1fr) 330px; gap:34px; align-items:end; padding-bottom:30px; border-bottom:1px solid var(--line); }
.help-hero h1 { max-width:700px; font-size:34px; line-height:1.25; margin:0; }
.help-hero p { max-width:720px; margin-top:12px; color:var(--muted); line-height:1.8; }
.help-steps { display:grid; grid-template-columns:repeat(4,1fr); gap:8px; margin:24px 0 34px; }
.help-step { min-height:88px; padding:14px; border-top:3px solid var(--blue); background:#fff; }
.help-step b { display:block; color:var(--blue); font:700 22px/1 "Segoe UI",sans-serif; }
.help-step strong { display:block; margin-top:8px; font-size:14px; }
.help-step span { display:block; margin-top:3px; color:var(--muted); font-size:12px; }
.help-layout { display:grid; grid-template-columns:210px minmax(0,1fr); gap:32px; align-items:start; }
.help-toc { position:sticky; top:18px; padding:4px 0; }
.help-toc strong { display:block; margin-bottom:9px; font-size:13px; color:var(--blue-deep); }
.help-toc a { display:block; padding:8px 10px; border-left:2px solid transparent; color:var(--muted); font-size:13px; text-decoration:none; }
.help-toc a:hover { border-left-color:var(--blue); color:var(--blue); background:var(--blue-pale); }
.help-section { padding:0 0 30px; margin-bottom:30px; border-bottom:1px solid var(--line); scroll-margin-top:20px; }
.help-section:last-child { margin-bottom:0; border-bottom:0; }
.help-section h2 { margin:0 0 8px; font-size:21px; }
.help-section > p { color:var(--muted); line-height:1.8; }
.help-card-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; margin-top:18px; }
.help-card { min-width:0; padding:18px; border:1px solid var(--line); background:#fff; }
.help-card h3 { margin:0 0 7px; font-size:16px; }
.help-card p { margin:0; color:#56687c; font-size:13px; line-height:1.75; }
.help-card ol,.help-card ul { margin:9px 0 0; padding-left:20px; color:#56687c; font-size:13px; line-height:1.8; }
.help-callout { margin-top:18px; padding:14px 16px; border-left:3px solid var(--blue); background:var(--blue-soft); color:var(--blue-deep); font-size:13px; line-height:1.8; }
.help-callout strong { display:block; margin-bottom:3px; }
.help-shot-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:14px; margin:18px 0 34px; }
.help-shot { min-width:0; border:1px solid var(--line); background:#fff; padding:10px; }
.help-shot h3 { margin:10px 2px 3px; font-size:15px; }
.help-shot > p { margin:0 2px; color:var(--muted); font-size:12px; line-height:1.65; }
.shot-browser { min-height:230px; overflow:hidden; border:1px solid #cfd9e4; border-radius:5px; background:#f7f9fc; box-shadow:0 2px 7px #1b355a12; }
.shot-bar { display:flex; align-items:center; gap:5px; height:22px; padding:0 8px; background:#e9eef4; border-bottom:1px solid #d7e0e9; }
.shot-dot { width:6px; height:6px; border-radius:50%; background:#aab8c6; }
.shot-url { flex:1; height:12px; margin-left:4px; border-radius:2px; background:#fff; color:#7c8998; font:9px/12px Consolas,monospace; padding-left:6px; }
.shot-content { min-height:208px; padding:16px; color:#263b52; font-size:10px; }
.shot-brand { color:var(--blue); font-size:13px; font-weight:800; margin-bottom:12px; }
.shot-login { width:70%; margin:0 auto; padding:12px; border:1px solid #dce5ee; background:#fff; }
.shot-login strong { display:block; font-size:14px; margin-bottom:10px; }
.shot-input { height:22px; margin:7px 0; padding:5px 7px; border:1px solid #cdd9e5; color:#9ba7b4; background:#fff; }
.shot-button { display:inline-flex; align-items:center; justify-content:center; min-height:23px; padding:0 9px; border-radius:3px; background:var(--blue); color:#fff; font-size:10px; font-weight:700; }
.shot-button.quiet { background:#eef4fb; color:var(--blue-deep); }
.shot-heading { display:flex; align-items:center; justify-content:space-between; gap:8px; border-bottom:1px solid #dce5ee; padding-bottom:8px; margin-bottom:10px; }
.shot-heading strong { font-size:14px; }
.shot-form { display:grid; grid-template-columns:1fr 1fr; gap:7px; }
.shot-field { min-height:25px; padding:6px 7px; border:1px solid #cdd9e5; background:#fff; color:#8997a5; }
.shot-field.wide { grid-column:1/-1; }
.shot-progress { height:8px; overflow:hidden; margin:10px 0 5px; border-radius:3px; background:#e5edf5; }
.shot-progress i { display:block; width:78%; height:100%; background:#2c7cc7; }
.shot-status { color:#3f6b60; font-size:10px; }
.shot-person-tabs { display:flex; gap:5px; margin:9px 0; }
.shot-person { flex:1; padding:5px; border:1px solid #d6e0ea; background:#fff; color:#31465c; text-align:center; font-size:10px; }
.shot-person.active { border-color:var(--blue); background:#eaf2fc; color:var(--blue-deep); font-weight:700; }
.shot-face { height:34px; margin-bottom:4px; background:#dbe7ef; position:relative; }
.shot-face:before { content:''; position:absolute; width:16px; height:18px; left:calc(50% - 8px); top:6px; border-radius:50%; background:#7d9ab1; }
.shot-face:after { content:''; position:absolute; width:25px; height:11px; left:calc(50% - 12px); bottom:0; border-radius:12px 12px 0 0; background:#54748f; }
.shot-result { display:grid; grid-template-columns:34% 1fr; gap:9px; }
.shot-preview { min-height:112px; border:1px solid #d4e0ea; background:#edf3f7; position:relative; }
.shot-preview:before { content:'人物1'; position:absolute; left:5px; top:5px; padding:2px 4px; color:#fff; background:#2163c4; font-size:9px; }
.shot-preview:after { content:''; position:absolute; width:40px; height:50px; left:calc(50% - 20px); top:30px; border-radius:20px 20px 10px 10px; background:#6f8da4; box-shadow:0 -13px 0 -3px #5e7281; }
.shot-timeline { min-width:0; }
.shot-timeline strong { display:block; margin-bottom:5px; font-size:12px; }
.shot-event { display:grid; grid-template-columns:45px 30px 1fr; gap:5px; align-items:center; min-height:25px; border-top:1px solid #e5ebf1; color:#53697c; font-size:9px; }
.shot-event img { width:30px; height:20px; background:#dbe7ef; }
.shot-event b { color:#17684f; font-size:9px; }
.shot-download { margin-top:8px; text-align:right; }
.help-table { width:100%; margin-top:18px; border-collapse:collapse; background:#fff; font-size:13px; }
.help-table th,.help-table td { padding:11px 12px; border:1px solid var(--line); text-align:left; vertical-align:top; }
.help-table th { background:var(--blue-pale); color:var(--blue-deep); font-weight:700; }
.help-faq { border-top:1px solid var(--line); background:#fff; }
.help-faq details { padding:13px 14px; border-bottom:1px solid var(--line); }
.help-faq summary { cursor:pointer; color:var(--blue-deep); font-weight:700; }
.help-faq p { margin:9px 0 2px; color:var(--muted); font-size:13px; line-height:1.8; }
.help-footer { width:min(1120px,calc(100% - 40px)); margin:0 auto; padding:22px 0; color:var(--muted); font-size:12px; border-top:1px solid var(--line); }
.help-roles { display:flex; flex-wrap:wrap; gap:8px; margin-top:16px; }
.help-roles a { display:inline-flex; align-items:center; min-height:38px; padding:7px 14px; border:1px solid var(--line-strong); border-radius:4px; background:#fff; color:var(--blue-deep); font-size:13px; font-weight:700; text-decoration:none; }
.help-roles a:hover { border-color:var(--blue); background:var(--blue-pale); }
.help-tag { display:inline-block; margin-left:6px; padding:1px 7px; border-radius:3px; background:var(--blue-pale); color:var(--blue-deep); font-size:12px; font-weight:700; vertical-align:2px; }
.help-tag.admin { background:#fff7e8; color:#9a5a08; }
.help-table code,.help-card code,.help-section > p code { padding:1px 5px; border-radius:3px; background:#eef3f8; color:#28415e; font:12px Consolas,monospace; word-break:break-all; }
.help-table td:first-child { white-space:nowrap; font-weight:700; color:#28415e; }
.help-flow { margin:18px 0 0; padding:0; list-style:none; counter-reset:flow; display:grid; gap:8px; }
.help-flow li { counter-increment:flow; position:relative; padding:12px 14px 12px 52px; border:1px solid var(--line); background:#fff; font-size:13px; line-height:1.75; color:#56687c; }
.help-flow li:before { content:counter(flow,decimal-leading-zero); position:absolute; left:14px; top:12px; color:var(--blue); font:700 16px/1.6 "Segoe UI",sans-serif; }
.help-flow li strong { color:#28415e; }
.help-callout.warn { border-left-color:#c27a12; background:#fff7e8; color:#6b4106; }
.help-toc .toc-group { display:block; margin:12px 0 4px; padding-left:10px; color:#8394a7; font-size:12px; font-weight:400; }
.help-table-wrap { overflow-x:auto; -webkit-overflow-scrolling:touch; }
.help-layout > * { min-width:0; }
@media (max-width:820px) {
  .help-hero { grid-template-columns:1fr; gap:18px; }
  .help-layout { grid-template-columns:1fr; gap:8px; }
  .help-toc { position:static; display:flex; gap:4px; overflow-x:auto; padding-bottom:10px; border-bottom:1px solid var(--line); }
  .help-toc strong,.help-toc .toc-group { display:none; }
  .help-toc a { flex:0 0 auto; border-left:0; border-bottom:2px solid transparent; }
  .help-toc a:hover { border-bottom-color:var(--blue); border-left:0; }
}
@media (max-width:620px) {
  .help-header-inner,.help-main,.help-footer { width:min(100% - 28px,1120px); }
  .help-header-inner { min-height:64px; flex-wrap:wrap; padding:10px 0; }
  .help-header nav { width:100%; margin-left:0; border-top:1px solid var(--line); }
  .help-header nav a { min-height:38px; padding-left:0; padding-right:16px; }
  .help-main { padding-top:28px; }
  .help-hero h1 { font-size:28px; }
  .help-steps,.help-card-grid,.help-shot-grid { grid-template-columns:1fr 1fr; }
  .help-step { min-height:82px; }
}
@media (max-width:420px) {
  .help-steps,.help-card-grid,.help-shot-grid { grid-template-columns:1fr; }
}
"""


def render_help() -> str:
    body = f"""
<header class="help-header">
  <div class="help-header-inner">
    <a class="brand" href="/demo2/login">{_BOOK_ICON}<span class="brand-copy"><strong>课堂学习分析平台</strong><span>RehabAffect · 云图智航</span></span></a>
    <nav aria-label="帮助页导航"><a href="/demo2/login">返回登录</a><a href="/demo2/upload">进入工作台</a><a href="/demo2/admin">公司后台</a></nav>
  </div>
</header>
<main class="help-main" id="mainContent">
  <section class="help-hero" aria-labelledby="helpTitle">
    <div><span class="eyebrow">使用帮助 · 完整功能说明</span><h1 id="helpTitle">从上传视频到看懂学生课堂状态</h1><p>这套平台用于把一节课堂视频整理成可回看的学生状态线索，并支持教师复核、课堂双轨评价、学生长期测量和课堂报告。第一次使用只需走“登录 → 上传 → 查看学生状态”主线；其他功能按需要再用，本页逐一说明在哪里、怎么用。</p><div class="help-roles" aria-label="按身份快速跳转"><a href="#screenshots">我是老师：先看三步上手</a><a href="#map">查看全部功能</a><a href="#full-flow">完整闭环怎么走</a><a href="#admin">我是公司管理员</a></div></div>
    <div class="help-callout" style="margin:0"><strong>先记住一件事</strong>上传成功后不要关闭页面。后台处理完成会自动跳到“学生状态结果”，结果页才是本次使用的重点。</div>
  </section>
  <section class="help-steps" aria-label="基本操作流程">
    <div class="help-step"><b>01</b><strong>登录</strong><span>学校账号进入工作台</span></div>
    <div class="help-step"><b>02</b><strong>上传视频</strong><span>填写少量课程信息</span></div>
    <div class="help-step"><b>03</b><strong>等待分析</strong><span>上传和后台处理连续进行</span></div>
    <div class="help-step"><b>04</b><strong>查看结果</strong><span>切换人物看状态时间轴</span></div>
  </section>
  <section class="help-section" id="screenshots"><h2>操作截图式教学</h2><p>按下面三张图操作即可。老师只需要走完“登录 → 上传并等待 → 查看结果并下载”这条主线，姓名绑定和 IEP 摘要可以在结果页有需要时再补。</p><div class="help-shot-grid">
    <article class="help-shot"><div class="shot-browser"><div class="shot-bar"><i class="shot-dot"></i><i class="shot-dot"></i><i class="shot-dot"></i><span class="shot-url">课堂学习分析平台 / 登录</span></div><div class="shot-content"><div class="shot-brand">课堂学习分析平台</div><div class="shot-login"><strong>用户登录</strong><div class="shot-input">账号</div><div class="shot-input">密码</div><span class="shot-button">登录</span></div></div></div><h3>01 · 登录</h3><p>输入学校测试账号和密码，进入上传工作台。</p></article>
    <article class="help-shot"><div class="shot-browser"><div class="shot-bar"><i class="shot-dot"></i><i class="shot-dot"></i><i class="shot-dot"></i><span class="shot-url">课堂学习分析平台 / 上传视频</span></div><div class="shot-content"><div class="shot-heading"><strong>上传课程视频</strong><span class="shot-button quiet">选择文件</span></div><div class="shot-form"><div class="shot-field">课程名称（可选）</div><div class="shot-field">上传通道</div><div class="shot-field wide">课堂视频：lesson.mp4</div></div><div class="shot-progress"><i></i></div><div class="shot-status">上传完成，后台处理中，请稍候…</div></div></div><h3>02 · 上传并等待</h3><p>文件到100%后仍要等后台处理，完成后点击“查看学生状态”。</p></article>
    <article class="help-shot"><div class="shot-browser"><div class="shot-bar"><i class="shot-dot"></i><i class="shot-dot"></i><i class="shot-dot"></i><span class="shot-url">课堂学习分析平台 / 学生状态结果</span></div><div class="shot-content"><div class="shot-person-tabs"><div class="shot-person active"><div class="shot-face"></div>人物1</div><div class="shot-person"><div class="shot-face"></div>人物2</div><div class="shot-person"><div class="shot-face"></div>人物3</div></div><div class="shot-result"><div class="shot-preview"></div><div class="shot-timeline"><strong>人物1的状态时间轴</strong><div class="shot-event"><span>00:00</span><img alt=""><b>持续活动线索</b></div><div class="shot-event"><span>00:30</span><img alt=""><b>安静 / 动作较少</b></div><div class="shot-event"><span>01:00</span><img alt=""><b>困惑 / 停滞</b></div></div></div><div class="shot-download"><span class="shot-button">下载结果</span></div></div></div><h3>03 · 查看并下载</h3><p>点击人物切换独立时间轴；确认结果后下载本任务报告。</p></article>
  </div><div class="help-callout"><strong>下载前看一眼</strong>结果页显示“分析完成”后再下载。下载文件应对应当前任务；若页面提示处理失败或任务编号不一致，不要把文件当作本次结果。</div></section>
  <div class="help-layout">
    <aside class="help-toc" aria-label="帮助内容目录"><strong>本页内容</strong><a href="#screenshots">截图教学</a><a href="#map">功能总览</a><a href="#full-flow">完整闭环顺序</a><span class="toc-group">日常使用</span><a href="#start">登录与工作台</a><a href="#upload">上传视频</a><a href="#capture">录制课堂</a><a href="#result">查看学生状态</a><a href="#archive">绑定与归档</a><span class="toc-group">深入复核</span><a href="#roster">学生名册与资料授权</a><a href="#review">课堂复核与图文报告</a><a href="#evaluation">课堂双轨评价</a><a href="#measurement">学生测量与趋势</a><a href="#safety">安全事件核查</a><a href="#membership">会员中心</a><span class="toc-group">管理与规则</span><a href="#admin">公司后台</a><a href="#privacy">数据与隐私</a><a href="#faq">常见问题</a></aside>
    <div>
      <section class="help-section" id="map"><h2>功能总览</h2><p>下表列出平台全部功能入口。老师账号登录后，顶部导航有“上传任务、学生名册、学校信息、会员中心”，右侧工具栏有“使用帮助、课堂双轨评价、测量与报告、录制课堂”；其余页面从任务记录或学生名册里进入。</p><div class="help-table-wrap"><table class="help-table"><thead><tr><th>功能</th><th>从哪里进入</th><th>用来做什么</th></tr></thead><tbody>
<tr><td>上传视频</td><td>顶部“上传任务”</td><td>填写课程信息、上传课堂视频并自动分析；查看本课程任务、名额和处理状态。</td></tr>
<tr><td>录制课堂</td><td>右侧“录制课堂”</td><td>用电脑摄像头和麦克风直接录一段课堂，回放确认后保存到课程，随后自动分析。</td></tr>
<tr><td>学生状态结果</td><td>上传完成自动跳转；或任务记录“查看学生状态结果”</td><td>按人物查看截图、状态时间轴、本节课概览与分析报告，下载结果，绑定姓名并归档本课表现。</td></tr>
<tr><td>学生名册</td><td>顶部“学生名册”</td><td>建立本校学生名单（姓名、校内编号、班级）。</td></tr>
<tr><td>资料与授权</td><td>学生名册中某位学生的“资料与授权”</td><td>登记授权、上传 IEP / 专业评估 / 五领域评估 / 安全与支持资料，查看课堂引用历史。</td></tr>
<tr><td>公司留存摘要</td><td>学生名册中某位学生的“公司留存摘要”</td><td>在授权范围内，把教师核对的学习目标、支持方法和五领域观察整理成摘要供公司查看。</td></tr>
<tr><td>确认学生身份</td><td>任务记录或复核页“确认学生身份”</td><td>把视频中的人物与名册学生对应，作为后续复核、测量和报告的依据。</td></tr>
<tr><td>课堂复核与报告</td><td>任务记录“课堂复核与报告”</td><td>群像概览、个体观察、片段复核、图文报告四个标签；生成并下载图文报告。</td></tr>
<tr><td>课程关联资料</td><td>复核页“课程关联资料”</td><td>为本节课已确认身份的学生选择要引用的资料版本（如 IEP）。</td></tr>
<tr><td>同课多视频汇总</td><td>复核页“同课多视频汇总”</td><td>同一课程批次的多个视频合并查看，核准本课学生目标结论。</td></tr>
<tr><td>教学支持</td><td>复核页“教学支持与上传测试”</td><td>上传前的试跑检查清单、按支持需求选择教学办法、记录每节课的改进点。</td></tr>
<tr><td>视频证据详情</td><td>任务记录点击文件名；或复核页“视频证据详情”</td><td>逐时间切片回看画面记录和同期声音，可重新处理任务。</td></tr>
<tr><td>课堂双轨评价</td><td>右侧“课堂双轨评价”；或任务记录“教师评分”</td><td>同时记录学校标准评分和系统增强评分，查看分差说明和下一课建议。</td></tr>
<tr><td>测量与报告</td><td>右侧“测量与报告”</td><td>按学习目标记录四维测量分，查看纵向趋势，生成单次记录报告。</td></tr>
<tr><td>安全事件核查</td><td>双轨评价页顶部“安全核查”</td><td>记录课堂中的安全相关客观观察，指定核查人并人工记录核查结论。</td></tr>
<tr><td>学校信息</td><td>顶部“学校信息”</td><td>确认所属地区和学校；首次使用需先完成。</td></tr>
<tr><td>会员中心</td><td>顶部“会员中心”</td><td>查看会员状态、服务套餐和订单记录。</td></tr>
<tr><td>公司后台<span class="help-tag admin">管理员</span></td><td>登录页选择“管理员登录”</td><td>运行总览、任务查询、报告与视频下载、上传通道设置、资料与测量汇总、学生摘要归档。</td></tr>
</tbody></table></div></section>
      <section class="help-section" id="full-flow"><h2>完整闭环顺序</h2><p>只看学生状态时，走前面的三步即可。如果要把一节课做成“有身份、有复核、有评分、有报告”的完整记录，请按下面顺序操作，前一步没做时后一步会提示无法保存。</p><ol class="help-flow">
<li><strong>学校信息</strong>：首次登录确认城市、区县和学校并保存。</li>
<li><strong>学生名册</strong>：新增本节课要关注的学生。</li>
<li><strong>资料与授权</strong>（需要 IEP 时）：先登记授权，再新增 IEP 等资料。</li>
<li><strong>上传视频</strong>：上传课堂视频，等待后台处理完成。</li>
<li><strong>确认学生身份</strong>：在“确认画面中的人员”页把人物和名册学生对应，所选画面时刻要落在要测量的片段内。</li>
<li><strong>视频适用性</strong>：在“课堂复核与报告”页先确认视频内容类型与教学目标，之后才能保存已复核或带分数的测量。</li>
<li><strong>片段复核 / 学生测量</strong>：回看片段，记录目标观察和四维测量。</li>
<li><strong>课堂双轨评价</strong>：录入学校评分，查看系统增强评分和分差说明。</li>
<li><strong>图文报告</strong>：在复核页“图文报告”标签生成报告，下载 HTML / Markdown / JSON 或打印为 PDF。</li>
</ol></section>
      <section class="help-section" id="start"><h2>1. 登录与工作台</h2><p>打开网址后在登录页选择“用户登录”，输入学校测试账号和密码（新用户也可以用“手机号注册”）。公司人员请选择“管理员登录”。首次进入时按页面提示到“学校信息”确认城市、区县和学校，保存后进入上传工作台。</p><div class="help-card-grid"><article class="help-card"><h3>工作台导航</h3><ul><li>上传任务：上传视频和查看任务记录。</li><li>学生名册：管理本校学生。</li><li>学校信息：地区与学校确认。</li><li>会员中心：会员状态和订单。</li><li>右侧工具：使用帮助、课堂双轨评价、测量与报告、录制课堂。</li></ul></article><article class="help-card"><h3>学校信息怎么填</h3><p>选择学校来源和地区，可以按名称筛选学校，也可以手动填写省市区、街道、学校全称和地址。勾选确认后点击“保存学校信息”。确认学校信息不会让你看到其他学校的数据。</p></article><article class="help-card"><h3>不知道点哪里</h3><p>直接点击“上传视频”。上传页默认只显示主线功能，点顶部“更多功能”可展开任务筛选、名额等完整内容。帮助页可随时从顶部“使用帮助”打开。</p></article><article class="help-card"><h3>退出登录</h3><p>每个页面右上角都有“退出”。在公共电脑上使用后请务必退出；改密码后旧登录会失效，需要重新登录。</p></article></div></section>
      <section class="help-section" id="upload"><h2>2. 上传视频</h2><p>在上传页填写课程信息、选择上传通道和课堂视频，点击“开始上传并分析”。上传和后台处理连续进行，完成后自动跳到学生状态结果。</p><div class="help-table-wrap"><table class="help-table"><thead><tr><th>项目</th><th>怎么填</th><th>是否必填</th></tr></thead><tbody><tr><td>课程名称</td><td>例如“生活语文”“生活数学”，不超过 200 字，不确定时可先留空。</td><td>可选</td></tr><tr><td>课程批次号</td><td>在“更多功能”中显示，不填时系统按日期自动生成。同一节课的多个视频用同一个批次号，便于“同课多视频汇总”；不超过 120 字。</td><td>可选</td></tr><tr><td>上课日期</td><td>默认当天，可按实际上课日期修改。</td><td>可选</td></tr><tr><td>上传通道</td><td>选择页面列出的可用通道，不要自行填写。通道被暂停时会显示出来但不能上传，请联系项目方。</td><td>必填</td></tr><tr><td>计划关注学生</td><td>在“更多功能”中显示，可从学生名册中选择本节课重点关注的学生；默认“暂不指定”，学生身份在结果页再确认。</td><td>可选</td></tr><tr><td>课堂视频</td><td>优先使用 MP4；画面尽量彩色、光线充足、学生可见。</td><td>必填</td></tr></tbody></table></div><div class="help-card-grid"><article class="help-card"><h3>暂停与继续</h3><p>网络不稳时可点“暂停上传”，恢复后点“继续上传”，会从已上传的位置接着传，不必从头开始。</p></article><article class="help-card"><h3>五个视频名额</h3><p>每个课程最多 5 个视频，名额按课程分别计算，在“更多功能”中可看到已用和剩余名额。传错的视频可在任务记录里点“取消并释放名额”。</p></article><article class="help-card"><h3>本课程任务</h3><p>任务记录支持搜索文件名 / 任务编号、按状态筛选、“刷新任务”。每条任务有“查看学生状态结果”“课堂复核与报告”“教师评分”等入口。</p></article><article class="help-card"><h3>数据使用与保存设置</h3><p>展开后可查看数据保存范围。“脱敏结构化结果长期归档”默认不勾选，只有学校另行授权时才勾选。</p></article></div><div class="help-callout"><strong>视频建议</strong>支持 MP4、MOV、WebM；测试阶段单节课不超过 60 分钟、单文件不超过 1 GiB，推荐 720p 或 1080p。视频越大，上传和分析时间越长。建议先用一段短视频试跑，确认能识别到学生后再上传整节课。</div></section>
      <section class="help-section" id="capture"><h2>3. 录制课堂</h2><p>没有现成视频时，可以点右侧“录制课堂”直接用电脑摄像头录制。</p><div class="help-card-grid"><article class="help-card"><h3>操作步骤</h3><ol><li>勾选“我已获准录制本次课堂画面与声音”。</li><li>点击“检查摄像头与麦克风”，浏览器询问时选择允许，可选择麦克风输入。</li><li>点击“开始录制”，结束时点“结束录制”。</li><li>回放确认后，填写课程批次号和课程名称，勾选确认并点击“保存到课程”。</li></ol></article><article class="help-card"><h3>注意事项</h3><p>录制需要浏览器允许摄像头和麦克风；保存后按 60 天保存期上传到当前账号的课程，与普通上传一样占用课程名额并自动分析。录制中不要关闭或刷新页面。</p></article></div></section>
      <section class="help-section" id="result"><h2>4. 查看学生状态</h2><p>后台处理完成后，页面会自动跳到学生状态结果。结果页不会把整段视频压成一个分数，而是按检测到的人物分别整理课堂状态。</p><div class="help-card-grid"><article class="help-card"><h3>本节课概览与报告</h3><p>页面上方显示课堂视频、本节课概览和“本节课分析报告”，汇总整节课的总体情况。报告生成需要几秒，显示“正在生成报告”时稍等即可。</p></article><article class="help-card"><h3>人物切换</h3><p>人物按画面从左到右编号。点击“人物1 / 人物2 / 人物3”查看对应人物的截图、主要状态和参考分，截图用于确认当前看的对象。</p></article><article class="help-card"><h3>状态时间轴</h3><p>当前人物的状态按时间片排列，每段包含时间、截图、状态、证据和参考分。点击时间片，视频会跳到对应时刻。</p></article><article class="help-card"><h3>下载结果</h3><p>点击“下载结果”保存本任务的分析结果。下载前确认页面已显示分析完成、任务编号与本次上传一致。</p></article><article class="help-card"><h3>结果怎么理解</h3><p>状态是视频中的可见线索，例如投入、注意力下降、困惑或暂不可见；参考分用于课堂回看，不是诊断结论，也不是学校正式成绩。</p></article><article class="help-card"><h3>人物没有出现</h3><p>先点“刷新结果”；仍没有稳定人物时，检查视频是否能看清学生正脸、是否有长时间遮挡或光线过暗，再换视频重试。</p></article></div></section>
      <section class="help-section" id="archive"><h2>5. 绑定姓名与归档本课表现</h2><p>结果页可以先看分析，再处理归档。选择当前人物后，在“绑定姓名并归档本课表现”区域输入学生姓名；如果还没有学生档案，系统会创建一个最小档案。</p><div class="help-card-grid"><article class="help-card"><h3>姓名绑定</h3><ol><li>看人物截图，确认当前人物。</li><li>输入或选择学生姓名。</li><li>点击“绑定并保存本课记录”，已绑定的可点“更新本课归档”。</li></ol></article><article class="help-card"><h3>本课总结</h3><p>系统会带出一份简短总结，老师可以直接保存，也可以按课堂实际情况修改。每次课堂的总结会作为一条记录写入对应学生档案。</p></article><article class="help-card"><h3>IEP 支持摘要</h3><p>只填写本节课需要的支持方式，例如“需要视觉提示、分步骤指令”。不要把完整诊断原文粘贴到这里。</p></article><article class="help-card"><h3>暂时不想建档</h3><p>可以先点击“暂不绑定，先看分析”。人物截图和时间轴仍然可用，之后回到结果页再补充姓名。</p></article></div><div class="help-callout"><strong>数据边界</strong>结果页面展示的是当前上传视频产生的分析线索。学生档案和 IEP 摘要只有在姓名绑定并保存后才会建立对应关系。</div></section>
      <section class="help-section" id="roster"><h2>6. 学生名册与资料授权</h2><p>需要长期跟踪某位学生、或希望报告引用 IEP 时使用。所有资料只在本校账号内可见，其他学校无法查看。</p><div class="help-card-grid"><article class="help-card"><h3>学生名册</h3><p>顶部“学生名册”→“新增本校学生”：填写学生姓名（必填）、校内编号、班级和备注，点击“创建学生”。可按姓名、编号或班级查找。每位学生都有“资料与授权”和“公司留存摘要”入口。</p></article><article class="help-card"><h3>登记授权（第一步）</h3><ol><li>先核对学生信息。</li><li>填写授权依据（授权记录编号、签署日期、保管部门）。</li><li>选择获准保存的范围：仅摘要，或摘要及原件。</li><li>填写授权有效期（内测最多 60 天），勾选确认后“登记授权”。</li></ol></article><article class="help-card"><h3>新增资料（第二步）</h3><p>有效授权登记后才能新增资料。资料类型可选：个别化教育计划（IEP）、专业评估、五领域评估、安全与支持资料。填写资料日期、来源（不超过 200 字）和保存期限，保存期限不能晚于授权截止日期。每次更新会新建版本，不覆盖旧版本。</p></article><article class="help-card"><h3>课堂引用与撤回</h3><p>“课堂引用历史”记录哪节课用了哪个资料版本。撤回授权、授权到期或删除资料后，相关资料不再参与分析，已生成的报告会标为“已过期”，重新打开报告即可按最新授权重新生成。</p></article><article class="help-card"><h3>同一学生多份 IEP</h3><p>同一学生同时有多份有效 IEP 时，系统不会自动挑选，会提示需要老师处理。请保留一份当前有效版本，其余撤回或让其过期。</p></article><article class="help-card"><h3>公司留存摘要</h3><p>核对学生后，可设置后续课程自动归档、登记摘要授权依据和有效期，并新增“教师核对记录”（学习目标、支持方法、认知/沟通/运动/感知/社会适应五领域观察）。保存前需再次核对；可随时“撤回摘要授权”。摘要不包含诊断或专业结论。</p></article></div></section>
      <section class="help-section" id="review"><h2>7. 课堂复核与图文报告</h2><p>在任务记录点击“课堂复核与报告”进入。页面顶部可切换视频，并提供“确认学生身份、课程关联资料、同课多视频汇总、教学支持与上传测试、视频证据详情”等入口。</p><div class="help-card-grid"><article class="help-card"><h3>确认学生身份</h3><p>在“确认画面中的人员”页把视频人物和名册学生对应，可查看确认记录、下载身份确认 JSON。身份确认后，测量、资料引用和报告才会关联到具体学生。</p></article><article class="help-card"><h3>视频适用性（必须先做）</h3><p>首次进入会提示“视频适用性待确认”：选择视频内容类型（特教课堂、普通学校课堂、非课堂、无法判断、证据不足），核对教学目标后“保存适用性确认”。未确认时不能保存已复核或带分数的观察。</p></article><article class="help-card"><h3>四个标签页</h3><ul><li>群像概览：全班整体情况和本次视频中的学生。</li><li>个体观察：单个学生的目标与支持。</li><li>片段复核：设定开始 / 结束时间回看片段，新增或编辑目标观察（可记录沟通方式与音频、四维测量），支持“沿用目标新增”。</li><li>图文报告：自动生成本课报告。</li></ul></article><article class="help-card"><h3>图文报告下载</h3><p>在“图文报告”标签可下载图文报告（HTML）、结构化记录（JSON）、报告文本（Markdown），或“打印 / 保存PDF”。复核内容变化后点“重新生成报告”。报告标“已过期”时说明评分或授权已变化，重新打开或重新生成即可。</p></article><article class="help-card"><h3>课程关联资料</h3><p>选择本节课已确认身份的学生，再勾选 1–10 个资料版本（如 IEP），勾选核对后“保存课堂引用记录”。新资料版本不会改动已保存的引用。</p></article><article class="help-card"><h3>同课多视频汇总</h3><p>同一课程批次上传了多个视频时，在这里合并查看本批次视频，逐个学生“核准本课结论”，可下载核准记录或打印汇总。</p></article><article class="help-card"><h3>教学支持与上传测试</h3><p>提供上传前的试跑清单（学生可见、音轨可听、身份可确认）、按支持需求选择教学办法，以及每节课只推进一个改进点的“本课改进记录”。</p></article><article class="help-card"><h3>视频证据详情</h3><p>按时间切片查看画面记录和同期声音，可勾选“只看当前片段 / 循环本片段”。处理失败或需要重算时可点“重新处理”。</p></article></div></section>
      <section class="help-section" id="evaluation"><h2>8. 课堂双轨评价</h2><p>评价的是这节课的教学质量，不给学生个人能力打分。同一节课同时记录“学校标准”评分和“系统增强”评分，并说明两者差异。</p><div class="help-card-grid"><article class="help-card"><h3>新建评价</h3><ol><li>点“新建”，填写课堂编号、上课日期、课程名称、学科、评价模板。</li><li>填写本课目标与学生分层支持约定（不要写学生姓名）。</li><li>逐项填写学校分、证据摘要、改分理由和改进建议。</li><li>点“预览评分”查看结果，勾选核对声明后“保存记录”。</li></ol></article><article class="help-card"><h3>查看结果</h3><p>结果分“学校标准 / 系统增强 / 双轨对照 / 文献依据”四个视图，包含逐项分差、差异与下一课建议、权重敏感性检查。可“导出 JSON”或“打印”。保存错误的记录可“撤销此记录”。</p></article><article class="help-card"><h3>核对勾选会自动取消</h3><p>改动任何字段后，“我已逐项核对证据与情境…”勾选会自动取消。请改完后重新勾选再保存，否则只能保存为草稿，增强修正不计分。</p></article><article class="help-card"><h3>目标里不能写学生姓名</h3><p>“本课目标与学生分层支持约定”中出现名册里的学生姓名时会被拒绝并标红，请改用“A组 / 需视觉提示的学生”等描述。</p></article></div></section>
      <section class="help-section" id="measurement"><h2>9. 学生测量与趋势</h2><p>右侧“测量与报告”用于按学习目标长期记录学生表现。页面有“总览、记录测量、纵向趋势、单次报告、评分标准”五个视图。</p><div class="help-card-grid"><article class="help-card"><h3>新增测量记录</h3><ol><li>在学生名册中选择学生，点“+ 新增记录”。</li><li>填写上课日期、课节编号、数据来源；视频复核来源需填上传任务编号和片段起止秒数。</li><li>填写学习目标编号、测量条件和具体通过标准。</li><li>填写四维评分、观察次数和观察摘要，勾选“教师已完成复核”后保存。</li></ol></article><article class="help-card"><h3>四维评分</h3><p>准确性（权重 35%）、独立性（30%）、一致性（20%）、泛化性（15%），每项 0–10 分。本次没有观察到的维度请留空，不要填 0。详细口径见“评分标准”视图。</p></article><article class="help-card"><h3>纵向趋势与报告</h3><p>“查看趋势”按同一目标、条件和标准显示历次综合得分，可切换按课次或按周期查看。“单次报告”可“打印 / PDF”或“下载 HTML”。</p></article><article class="help-card"><h3>编辑与撤销</h3><p>已保存的记录可“编辑”或“撤销”，历史版本保留用于核对。视频复核来源的记录需要先完成身份确认和视频适用性确认。</p></article></div></section>
      <section class="help-section" id="safety"><h2>10. 安全事件核查</h2><p>从双轨评价页顶部“安全核查”进入，用于记录课堂视频里与安全相关的客观观察，并由指定核查人人工给出结论。</p><div class="help-card-grid"><article class="help-card"><h3>记录观察</h3><ol><li>选择课堂视频，用“当前位置设为开始 / 结束”定位时间段。</li><li>填写观察到的具体情况和现场已采取的措施。</li><li>点“保存为待核查”。</li></ol></article><article class="help-card"><h3>核查流程</h3><p>指定同校账号为核查人（需填写授权依据），核查人回看事件前后，记录“已核实 / 已排除 / 无法判断”和处理依据。结果可补充材料或申请重新核查，所有处理记录都会保留。</p></article></div><div class="help-callout warn"><strong>重要</strong>现场存在即时危险时，请按学校安全流程立即处理，不要等待平台核查。本页不会自动认定伤害，也不会自动扣分。</div></section>
      <section class="help-section" id="membership"><h2>11. 会员中心</h2><p>顶部“会员中心”可查看当前会员状态、有效期、服务套餐和订单记录，点“刷新状态”更新。内测阶段在线支付尚未开通，按钮显示“支付暂未配置”，开通事宜请联系项目方。注册账号与开通会员分别办理。</p></section>
      <section class="help-section" id="admin"><h2>12. 公司后台<span class="help-tag admin">管理员</span></h2><p>在登录页选择“管理员登录”进入“学校内测运行状态”。后台只用于运营查询，不能修改学校的课堂数据。</p><div class="help-card-grid"><article class="help-card"><h3>运行总览</h3><p>显示账号与通道状态、账号所属学校、会员与订单、开通申请、每课程名额使用、任务状态、保存与到期提醒、安全授权确认和近期上传。点“刷新数据”更新。</p></article><article class="help-card"><h3>任务查询</h3><p>按任务编号、课程、文件名或账号搜索，并按处理状态筛选，点“查询任务”。结果可翻页，每行可查看视频、下载视频和结果、查看报告。</p></article><article class="help-card"><h3>课程报告</h3><p>在“课程报告”列表点“查看”，可下载 MD 或 JSON 留档。为保护隐私，管理员看到的报告不包含 IEP 关联细节。</p></article><article class="help-card"><h3>上传通道设置</h3><p>“管理上传通道”可修改通道名称、负责人、上传状态（暂停 / 开放）和每课程名额。若他人同时修改，会提示“重新核对配置”，确认后再保存。</p></article><article class="help-card"><h3>资料与测量汇总</h3><p>“学生资料运行状态”只显示数量、存储占用和清理状态，可下载课堂引用记录或撤回本课引用授权；“测量记录汇总”按渠道显示记录总数、已复核和待复核数量。</p></article><article class="help-card"><h3>学生档案摘要库</h3><p>从课程报告卡片进入，按公开编号或通道查询仍在授权期内的学生摘要，查看课程历史、课堂线索趋势和教师核对摘要，可“导出授权 JSON”。</p></article></div><div class="help-callout"><strong>访问边界</strong>管理员从“课堂分析”入口直接进入时只会看到“请从任务记录进入”的引导；需要查看某个任务时，请从任务查询结果进入。管理员不能读取教师的课堂复核工作区。</div></section>
      <section class="help-section" id="privacy"><h2>13. 数据与隐私</h2><div class="help-card-grid"><article class="help-card"><h3>数据只在本校可见</h3><p>学生、资料、任务和报告都按学校和账号隔离。访问其他学校的数据会被拒绝。</p></article><article class="help-card"><h3>不要上传多余敏感信息</h3><p>不要在课程名称、备注、评价目标里写学生姓名或诊断原文；IEP 只填本课需要的支持方式。</p></article><article class="help-card"><h3>授权有期限</h3><p>资料授权和摘要授权到期、撤回或删除后，资料立即停止使用，相关报告标为过期。</p></article><article class="help-card"><h3>结果的定位</h3><p>状态线索、参考分和评价结果用于课堂回看与教学改进，不替代专业诊断、IEP 决策或学校正式评价。</p></article></div><p style="margin-top:14px">完整说明见 <a href="/demo2/privacy">数据安全与隐私说明</a>。</p></section>
      <section class="help-section" id="faq"><h2>14. 常见问题</h2><div class="help-faq"><details><summary>上传到 100% 后为什么还要等？</summary><p>100% 表示文件传输完成，服务器还需要读取视频、抽取画面并生成每个人物的状态时间片。处理完成后才会开放结果页。</p></details><details><summary>结果页显示“0 已定位人物”怎么办？</summary><p>说明画面中没有识别到清晰的人脸。请换一段学生正脸可见、光线充足、镜头不过远的视频再试。</p></details><details><summary>视频是彩色的，页面截图却不正常怎么办？</summary><p>先刷新结果页并检查视频播放器本身。如果播放器也是异常，重新上传原始彩色视频；如果播放器正常而人物截图异常，记录任务编号后联系项目方排查采样帧。</p></details><details><summary>提示名额已满，不能再上传？</summary><p>每个课程最多 5 个视频。在任务记录中对不需要的任务点“取消并释放名额”，或换一个课程批次号上传。</p></details><details><summary>上传通道显示“已暂停”？</summary><p>通道由公司后台统一管理，暂停时不能上传，也不会自动换成其他通道。请联系项目方重新开放。</p></details><details><summary>保存测量或片段观察时提示需要先确认适用性？</summary><p>先在“课堂复核与报告”页完成“视频适用性”确认，并在“确认学生身份”页确认学生，再回来保存。</p></details><details><summary>双轨评价保存后增强修正没有计分？</summary><p>改动字段后核对勾选会自动取消，记录被保存为草稿。请重新勾选“我已逐项核对证据与情境…”后再保存。</p></details><details><summary>报告显示“已过期”、无法下载？</summary><p>评分、复核内容或资料授权发生了变化。重新打开该任务的“图文报告”标签或点“重新生成报告”，即可得到按最新数据生成的报告。</p></details><details><summary>系统是不是已经知道每个人的真实姓名？</summary><p>没有绑定前，结果页只显示“人物1、人物2、人物3”等匿名人物。老师根据截图确认后，再把人物和学生姓名关联。</p></details><details><summary>结果分数能不能直接当成诊断或正式评价？</summary><p>不能。当前结果用于课堂回看、状态线索整理和本课表现记录，不替代专业诊断、IEP 决策或学校正式评价。</p></details><details><summary>遇到错误怎么处理？</summary><p>先不要重复提交同一个视频。记下页面提示、任务编号和发生步骤，刷新一次确认任务状态；仍失败时把这些信息交给项目方。</p></details></div></section>
    </div>
  </div>
</main>
<footer class="help-footer">云图智航 · RehabAffect 课堂学习分析平台 · 帮助内容对应当前测试版功能</footer>
"""
    return _document(title="使用帮助 · 课堂学习分析平台", body=body, page_style=HELP_STYLE)
