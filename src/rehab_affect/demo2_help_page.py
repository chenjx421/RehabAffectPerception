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
@media (max-width:820px) {
  .help-hero { grid-template-columns:1fr; gap:18px; }
  .help-layout { grid-template-columns:1fr; gap:8px; }
  .help-toc { position:static; display:flex; gap:4px; overflow-x:auto; padding-bottom:10px; border-bottom:1px solid var(--line); }
  .help-toc strong { display:none; }
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
    <nav aria-label="帮助页导航"><a href="/demo2/login">返回登录</a><a href="/demo2/upload">进入工作台</a></nav>
  </div>
</header>
<main class="help-main" id="mainContent">
  <section class="help-hero" aria-labelledby="helpTitle">
    <div><span class="eyebrow">使用帮助 · 教师操作版</span><h1 id="helpTitle">从上传视频到看懂学生课堂状态</h1><p>这套平台用于把一节课堂视频整理成可回看的学生状态线索。老师只需要完成上传，分析完成后按人物查看时间轴；姓名绑定、课堂总结和 IEP 支持摘要可以在结果页补充。</p></div>
    <div class="help-callout" style="margin:0"><strong>先记住一件事</strong>上传成功后不要关闭页面。后台处理完成会自动出现“查看学生状态”，结果页才是本次使用的重点。</div>
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
    <aside class="help-toc" aria-label="帮助内容目录"><strong>本页内容</strong><a href="#screenshots">截图教学</a><a href="#start">开始使用</a><a href="#upload">上传视频</a><a href="#result">查看结果</a><a href="#archive">绑定与归档</a><a href="#faq">常见问题</a></aside>
    <div>
      <section class="help-section" id="start"><h2>1. 开始使用</h2><p>打开网址后选择“用户登录”，输入学校测试账号和密码。首次进入时按页面提示确认城市、区县和学校信息，保存后进入上传工作台。</p><div class="help-card-grid"><article class="help-card"><h3>登录后看到什么</h3><p>上传任务、学生名册、学校信息和会员中心属于工作台入口。当前测试的主线只需要“上传任务”。</p></article><article class="help-card"><h3>不知道点哪里</h3><p>直接点击“上传视频”，不要先进入高级功能、课堂复核或其他管理页面。帮助页可以随时从顶部入口返回。</p></article></div></section>
      <section class="help-section" id="upload"><h2>2. 上传视频</h2><p>在上传页完成以下内容即可开始：课程名称可以填写，也可以留空；选择一个当前可用的上传通道；选择课堂视频；点击“开始上传并分析”。</p><table class="help-table"><thead><tr><th>项目</th><th>怎么填</th><th>是否必填</th></tr></thead><tbody><tr><td>课程名称</td><td>例如“生活语文”“生活数学”，不确定时可先留空。</td><td>可选</td></tr><tr><td>上传通道</td><td>选择页面列出的可用通道，不要自行填写。</td><td>必填</td></tr><tr><td>课堂视频</td><td>优先使用 MP4；画面尽量彩色、光线充足、学生可见。</td><td>必填</td></tr></tbody></table><div class="help-callout"><strong>视频建议</strong>支持 MP4、MOV、WebM；测试阶段单节课不超过 60 分钟、单文件不超过 1 GiB，推荐 720p 或 1080p。视频越大，上传和分析时间越长。</div></section>
      <section class="help-section" id="result"><h2>3. 查看学生状态</h2><p>后台处理完成后，页面会出现“查看学生状态”。结果页不会把整段视频压成一个分数，而是按检测到的人物分别整理课堂状态。</p><div class="help-card-grid"><article class="help-card"><h3>人物切换</h3><p>点击“人物1 / 人物2 / 人物3”查看对应人物的截图、主要状态和参考分。人物截图用于确认当前看的对象。</p></article><article class="help-card"><h3>状态时间轴</h3><p>当前人物的状态按时间片排列，每段包含时间、截图、状态、证据和参考分。点击时间片，视频会跳到对应时刻。</p></article><article class="help-card"><h3>结果怎么理解</h3><p>状态是视频中的可见线索，例如投入、注意力下降、困惑或暂不可见；参考分用于课堂回看，不是诊断结论，也不是学校正式成绩。</p></article><article class="help-card"><h3>人物没有出现</h3><p>先刷新结果；仍没有稳定人物时，检查视频是否能看清学生、是否有长时间遮挡或光线过暗，再换视频重试。</p></article></div></section>
      <section class="help-section" id="archive"><h2>4. 绑定姓名与归档本课表现</h2><p>结果页可以先看分析，再处理归档。选择当前人物后，在“绑定姓名并归档本课表现”区域输入学生姓名；如果还没有学生档案，系统会创建一个最小档案。</p><div class="help-card-grid"><article class="help-card"><h3>姓名绑定</h3><ol><li>看人物截图，确认当前人物。</li><li>输入或选择学生姓名。</li><li>点击“绑定并保存本课记录”。</li></ol></article><article class="help-card"><h3>本课总结</h3><p>系统会带出一份简短总结，老师可以直接保存，也可以按课堂实际情况修改。每次课堂的总结会作为一条记录写入对应学生档案。</p></article><article class="help-card"><h3>IEP 支持摘要</h3><p>只填写本节课需要的支持方式，例如“需要视觉提示、分步骤指令”。不要把完整诊断原文粘贴到这里。</p></article><article class="help-card"><h3>暂时不想建档</h3><p>可以先点击“暂不绑定，先看分析”。人物截图和时间轴仍然可用，之后回到结果页再补充姓名。</p></article></div><div class="help-callout"><strong>数据边界</strong>结果页面展示的是当前上传视频产生的分析线索。学生档案和 IEP 摘要只有在姓名绑定并保存后才会建立对应关系。</div></section>
      <section class="help-section" id="faq"><h2>5. 常见问题</h2><div class="help-faq"><details><summary>上传到 100% 后为什么还要等？</summary><p>100% 表示文件传输完成，服务器还需要读取视频、抽取画面并生成每个人物的状态时间片。处理完成后才会开放结果页。</p></details><details><summary>视频是彩色的，页面截图却不正常怎么办？</summary><p>先刷新结果页并检查视频播放器本身。如果播放器也是异常，重新上传原始彩色视频；如果播放器正常而人物截图异常，记录任务编号后联系项目方排查采样帧。</p></details><details><summary>系统是不是已经知道每个人的真实姓名？</summary><p>没有绑定前，结果页只显示“人物1、人物2、人物3”等匿名人物。老师根据截图确认后，再把人物和学生姓名关联。</p></details><details><summary>结果分数能不能直接当成诊断或正式评价？</summary><p>不能。当前结果用于课堂回看、状态线索整理和本课表现记录，不替代专业诊断、IEP 决策或学校正式评价。</p></details><details><summary>遇到错误怎么处理？</summary><p>先不要重复提交同一个视频。记下页面提示、任务编号和发生步骤，刷新一次确认任务状态；仍失败时把这些信息交给项目方。</p></details></div></section>
    </div>
  </div>
</main>
<footer class="help-footer">云图智航 · RehabAffect 课堂学习分析平台 · 帮助内容对应当前测试版流程</footer>
"""
    return _document(title="使用帮助 · 课堂学习分析平台", body=body, page_style=HELP_STYLE)
