from __future__ import annotations


def render_showcase_html() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>辅读学校具身智能课堂 Demo</title>
  <style>
    :root {
      --bg: #f4f6f1;
      --panel: #ffffff;
      --ink: #18201b;
      --muted: #5e6b62;
      --line: #d9e0d3;
      --blue: #2563eb;
      --green: #16783a;
      --amber: #aa6a12;
      --red: #c24135;
      --violet: #6d4aff;
      --soft: #edf3e9;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: Inter, "Segoe UI", Arial, sans-serif;
      line-height: 1.42;
    }
    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 18px;
      padding: 18px 24px;
      background: #fff;
      border-bottom: 1px solid var(--line);
    }
    h1 {
      margin: 0 0 4px;
      font-size: 24px;
      letter-spacing: 0;
    }
    .subtitle {
      color: var(--muted);
      font-size: 13px;
    }
    .toolbar {
      display: flex;
      gap: 8px;
      align-items: center;
      flex-wrap: wrap;
    }
    select, button {
      border: 1px solid var(--line);
      border-radius: 7px;
      background: #fff;
      color: var(--ink);
      padding: 8px 10px;
      font: inherit;
      min-height: 38px;
    }
    button {
      cursor: pointer;
      font-weight: 650;
    }
    .primary {
      background: var(--blue);
      border-color: var(--blue);
      color: #fff;
    }
    main {
      display: grid;
      grid-template-columns: minmax(260px, 0.9fr) minmax(430px, 1.45fr) minmax(320px, 1.05fr);
      gap: 14px;
      padding: 14px;
    }
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      min-width: 0;
      overflow: hidden;
    }
    .head {
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
      font-weight: 750;
    }
    .body {
      padding: 12px;
      display: grid;
      gap: 12px;
    }
    .task-screen {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fbfcfa;
      padding: 13px;
      min-height: 260px;
      display: grid;
      align-content: start;
      gap: 12px;
    }
    .task-title {
      font-size: 18px;
      font-weight: 800;
    }
    .task-prompt {
      color: var(--muted);
      font-size: 13px;
    }
    .choice-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
    }
    .choice {
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 11px;
      background: #fff;
      min-height: 58px;
      display: grid;
      align-content: center;
      text-align: center;
      font-weight: 700;
    }
    .choice.active {
      border-color: var(--blue);
      color: var(--blue);
      background: #f4f7ff;
    }
    .cue-grid, .metric-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
    }
    .cue, .metric, .event {
      border: 1px solid var(--line);
      border-radius: 7px;
      background: #fff;
      padding: 9px;
      min-width: 0;
    }
    .label {
      color: var(--muted);
      font-size: 11px;
      margin-bottom: 3px;
    }
    .value {
      font-size: 18px;
      font-weight: 800;
      overflow-wrap: anywhere;
    }
    .scene {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--soft);
      min-height: 400px;
      overflow: hidden;
    }
    .scene svg {
      width: 100%;
      min-height: 400px;
      display: block;
    }
    .mujoco-proof {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      overflow: hidden;
    }
    .proof-head {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
      padding: 9px 11px;
      border-bottom: 1px solid var(--line);
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
    }
    .proof-head a {
      color: var(--blue);
      text-decoration: none;
    }
    .mujoco-frame {
      width: 100%;
      aspect-ratio: 16 / 9;
      object-fit: contain;
      display: block;
      background: #10120f;
    }
    .proof-missing {
      padding: 18px;
      color: var(--muted);
      font-size: 12px;
      background: #fbfcfa;
    }
    .robot-action {
      border-left: 4px solid var(--violet);
      border-radius: 0 7px 7px 0;
      background: #fbfaff;
      padding: 11px 12px;
      display: grid;
      gap: 5px;
    }
    .state-pill {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border-radius: 999px;
      padding: 4px 9px;
      font-size: 12px;
      font-weight: 800;
      color: #fff;
      background: var(--green);
    }
    .state-pill.warn { background: var(--amber); }
    .state-pill.risk { background: var(--red); }
    .state-pill.help { background: var(--blue); }
    .timeline {
      display: grid;
      gap: 8px;
      max-height: 330px;
      overflow: auto;
      padding-right: 3px;
    }
    .event {
      font-size: 12px;
    }
    .event strong {
      color: var(--blue);
    }
    .json-tabs {
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
    }
    .tab.active {
      border-color: var(--blue);
      color: var(--blue);
    }
    pre {
      margin: 0;
      min-height: 250px;
      max-height: 420px;
      overflow: auto;
      border-radius: 7px;
      background: #101812;
      color: #e9f6ed;
      padding: 12px;
      font-size: 11px;
      line-height: 1.45;
    }
    .status {
      color: var(--muted);
      font-size: 12px;
      min-width: 120px;
      text-align: right;
    }
    @media (max-width: 1180px) {
      main { grid-template-columns: 1fr; }
      header { align-items: flex-start; flex-direction: column; }
      .status { text-align: left; }
    }
    @media (max-width: 620px) {
      main { padding: 10px; }
      header { padding: 14px; }
      .choice-grid, .cue-grid, .metric-grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>辅读学校具身智能课堂 Demo</h1>
      <div class="subtitle">课堂状态感知 -> 学生状态估计 -> 机器人动作响应 -> 教师复盘</div>
    </div>
    <div class="toolbar">
      <select id="scenario"></select>
      <button id="prev">上一步</button>
      <button class="primary" id="next">下一步</button>
      <button id="loop">整节课闭环</button>
      <div class="status" id="status">ready</div>
    </div>
  </header>
  <main>
    <section class="panel">
      <div class="head">学生端 <span id="stepLabel" class="state-pill">Step 0</span></div>
      <div class="body">
        <div class="task-screen">
          <div class="task-title" id="taskTitle">课堂任务</div>
          <div class="task-prompt" id="taskPrompt">加载中</div>
          <div class="choice-grid" id="choices"></div>
        </div>
        <div class="cue-grid">
          <div class="cue"><div class="label">speech</div><div class="value" id="speech">n/a</div></div>
          <div class="cue"><div class="label">attention</div><div class="value" id="attention">n/a</div></div>
          <div class="cue"><div class="label">movement</div><div class="value" id="movement">n/a</div></div>
          <div class="cue"><div class="label">failure</div><div class="value" id="failure">n/a</div></div>
        </div>
      </div>
    </section>

    <section class="panel">
      <div class="head">仿真课堂 <span id="match" class="state-pill help">pending</span></div>
      <div class="body">
        <div class="scene" id="scene"></div>
        <div class="mujoco-proof" id="mujocoProof">
          <div class="proof-head">
            <span id="mujocoTitle">MuJoCo 实渲染</span>
            <a id="mujocoSheet" href="#" target="_blank" rel="noreferrer">contact sheet</a>
          </div>
          <img class="mujoco-frame" id="mujocoFrame" alt="MuJoCo classroom rendered frame">
          <div class="proof-missing" id="mujocoMissing">等待 MuJoCo 场景资产</div>
        </div>
        <div class="metric-grid">
          <div class="metric"><div class="label">human_state</div><div class="value" id="humanState">n/a</div></div>
          <div class="metric"><div class="label">confidence</div><div class="value" id="confidence">n/a</div></div>
          <div class="metric"><div class="label">risk_level</div><div class="value" id="risk">n/a</div></div>
          <div class="metric"><div class="label">robot_action</div><div class="value" id="action">n/a</div></div>
        </div>
        <div class="robot-action" id="robotAction">等待运行</div>
      </div>
    </section>

    <section class="panel">
      <div class="head">教师端 <span id="handoff" class="state-pill">observe</span></div>
      <div class="body">
        <div class="timeline" id="timeline"></div>
        <div class="json-tabs">
          <button class="tab active" data-tab="human_state">human_state</button>
          <button class="tab" data-tab="robot_action">robot_action</button>
          <button class="tab" data-tab="report">report</button>
        </div>
        <pre id="json">等待运行</pre>
      </div>
    </section>
  </main>

  <script>
    const el = (id) => document.getElementById(id);
    const fmt = (value) => typeof value === 'number' ? value.toFixed(2) : String(value ?? 'n/a');
    const taskNames = {
      shape_sorting: '物品分类任务',
      low_attention: '课堂注意任务',
      needs_help: '求助训练任务',
      pain_risk: '安全暂停任务',
      refusal: '选择与暂停任务',
      fatigue: '任务负荷调节'
    };
    const scenarioText = {
      shape_sorting_confused: '学生开始能跟随任务，随后在分类步骤中出现困惑，需要机器人放慢说明。',
      low_attention_obstacle: '学生注意力下降，同时机器人附近存在障碍物，需要先保证安全再拉回注意。',
      needs_help_handoff: '学生多次卡住并请求帮助，系统需要提示教师关注。',
      pain_risk_safety: '学生出现不适风险线索，机器人必须停止动作并交由教师处理。',
      refusal_respect: '学生拒绝继续任务，机器人需要尊重选择并降低压力。',
      task_load_fatigue: '学生出现疲劳或负荷过高线索，系统需要降低任务难度。'
    };
    const stateLabels = {
      engaged: '参与',
      neutral: '正常',
      confused: '困惑',
      fatigued: '疲劳',
      frustrated: '挫败',
      refusing: '抗拒',
      pain_risk: '不适风险',
      low_attention: '注意力下降',
      needs_help: '需要帮助'
    };
    const actionLabels = {
      continue_and_encourage: '继续鼓励',
      continue_current_plan: '保持当前计划',
      repeat_instruction_slowly: '慢速重复说明',
      reduce_task_load_and_offer_break: '降低难度并询问休息',
      pause_and_request_consent: '暂停并征求意愿',
      pause_and_reduce_pressure: '暂停催促并降低压力',
      stop_and_check_pain_risk: '停止动作并确认不适',
      regain_attention: '温和拉回注意',
      offer_help: '提供帮助并提示教师'
    };
    const speechLabels = {
      positive_feedback: '正向反馈',
      neutral_prompt: '中性提示',
      repeat_instruction_slowly: '慢速重复',
      offer_break: '询问休息',
      ask_consent_and_offer_choice: '询问意愿并给选择',
      acknowledge_and_encourage: '承认困难并鼓励',
      ask_discomfort_and_reassure: '询问不适并安抚',
      regain_attention: '温和唤回注意',
      offer_help_and_confirm_need: '确认是否需要帮助'
    };
    const motionLabels = {
      continue_planned_motion: '继续原动作',
      continue_cautiously: '谨慎继续',
      hold_position: '保持位置',
      slow_down: '减速',
      stop_motion: '停止动作',
      increase_personal_space: '拉开距离'
    };
    const taskAdjustmentLabels = {
      maintain_or_slightly_progress: '保持或轻微推进',
      maintain_current_difficulty: '保持当前难度',
      simplify_next_step: '简化下一步',
      reduce_task_load: '减少任务负荷',
      pause_task: '暂停任务',
      reduce_pressure: '降低互动压力'
    };
    const safetyLabels = {
      monitor: '持续观察',
      avoid_new_motion_until_confirmed: '确认前不新增动作',
      monitor_fatigue: '观察疲劳',
      respect_refusal: '尊重拒绝',
      alert_teacher_or_caregiver: '提醒教师',
      notify_teacher_or_caregiver_if_unresolved: '未恢复则提醒教师',
      avoid_repeated_prompting: '避免反复催促',
      confirm_attention_before_motion: '确认注意后再动作'
    };
    let scenarios = [];
    let currentScenario = null;
    let mujocoAssets = null;
    let stepIndex = 0;
    let result = null;
    let loopResult = null;
    let activeTab = 'human_state';

    async function api(path, options = {}) {
      const response = await fetch(path, options);
      const data = await response.json();
      if (!response.ok || data.error) throw new Error(data.error || response.statusText);
      return data;
    }

    async function init() {
      const payload = await api('/api/scenarios');
      scenarios = payload.scenarios;
      el('scenario').innerHTML = scenarios.map((item) => `<option value="${item.scenario_id}">${item.scenario_id}</option>`).join('');
      const params = new URLSearchParams(window.location.search);
      const preferred = params.get('scenario') || 'shape_sorting_confused';
      el('scenario').value = scenarios.some((item) => item.scenario_id === preferred) ? preferred : scenarios[0].scenario_id;
      await loadScenario(el('scenario').value);
      await runStep();
    }

    async function loadScenario(id) {
      currentScenario = await api('/api/scenario?id=' + encodeURIComponent(id));
      mujocoAssets = await api('/api/mujoco_assets?scenario_id=' + encodeURIComponent(id));
      stepIndex = 0;
      result = null;
      loopResult = null;
      renderStudentStep();
      renderScene();
      renderMujocoProof();
      renderTimeline([]);
    }

    function currentStep() {
      return currentScenario.steps[stepIndex];
    }

    function renderStudentStep() {
      const step = currentStep();
      const cues = step.observable_cues || {};
      const task = currentScenario.task || 'classroom_task';
      el('taskTitle').textContent = taskNames[task] || task.replaceAll('_', ' ');
      el('taskPrompt').textContent = scenarioText[currentScenario.scenario_id] || currentScenario.description || '课堂任务';
      el('stepLabel').textContent = `Step ${stepIndex + 1}/${currentScenario.steps.length}`;
      el('speech').textContent = cues.speech_text || 'n/a';
      el('attention').textContent = fmt(cues.attention_score);
      el('movement').textContent = fmt(cues.movement_speed);
      el('failure').textContent = cues.recent_failure_count ?? 0;
      const options = optionsForState(step.ground_truth_state);
      el('choices').innerHTML = options.map((item, index) => `<div class="choice ${index === 0 ? 'active' : ''}">${item}</div>`).join('');
    }

    function optionsForState(state) {
      const map = {
        engaged: ['继续完成', '看示例', '请求帮助', '休息一下'],
        confused: ['我不会', '再听一遍', '换简单点', '找老师'],
        low_attention: ['看屏幕', '看同伴', '离开座位', '重新开始'],
        fatigued: ['休息一下', '继续做', '减少题目', '找老师'],
        refusing: ['不想做', '换任务', '暂停', '找老师'],
        pain_risk: ['不舒服', '停止动作', '告诉老师', '坐下等待'],
        needs_help: ['需要帮助', '看提示', '举手', '继续尝试']
      };
      return map[state] || ['继续', '提示', '暂停', '求助'];
    }

    async function runStep() {
      el('status').textContent = 'running';
      renderStudentStep();
      result = await api('/api/process_step', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          scenario_id: currentScenario.scenario_id,
          step_index: stepIndex,
          policy: 'rule',
          updates: {}
        })
      });
      loopResult = null;
      el('status').textContent = result.action_match ? 'action match' : 'action changed';
      renderResult();
    }

    async function runLoop() {
      el('status').textContent = 'closed loop';
      loopResult = await api('/api/run_closed_loop', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          scenario_id: currentScenario.scenario_id,
          policy: 'rule'
        })
      });
      const last = loopResult.steps[loopResult.steps.length - 1];
      result = last;
      stepIndex = Math.max(0, currentScenario.steps.length - 1);
      el('status').textContent = `score ${fmt(loopResult.metrics?.closed_loop_score)}`;
      renderStudentStep();
      renderResult();
      renderTimeline(loopResult.steps || []);
      activeTab = 'report';
      updateTabs();
      renderJson();
    }

    function renderResult() {
      const human = result.human_state || {};
      const action = result.robot_action || {};
      el('humanState').textContent = label(stateLabels, human.state);
      el('confidence').textContent = fmt(human.confidence);
      el('risk').textContent = riskLabel(human.risk_level);
      el('action').textContent = label(actionLabels, action.action_id);
      el('match').textContent = result.action_match ? 'match' : 'changed';
      el('match').className = result.action_match ? 'state-pill' : 'state-pill warn';
      el('handoff').textContent = action.handoff_required ? 'teacher' : 'observe';
      el('handoff').className = action.handoff_required ? 'state-pill risk' : 'state-pill';
      el('robotAction').innerHTML = `
        <strong>${label(actionLabels, action.action_id)}</strong>
        <span>语音：${label(speechLabels, action.speech_action)}</span>
        <span>动作：${label(motionLabels, action.motion_policy)}</span>
        <span>任务：${label(taskAdjustmentLabels, action.task_adjustment)}</span>
        <span>安全：${label(safetyLabels, action.safety_action)}</span>
      `;
      el('humanState').style.color = stateColor(human.state);
      renderScene();
      renderMujocoProof();
      renderTimeline([result]);
      renderJson();
    }

    function renderScene() {
      const step = currentStep();
      const cues = step.observable_cues || {};
      const context = result?.post_action_context || result?.robot_context || step.robot_context || {};
      const human = result?.human_state || {state: step.ground_truth_state};
      const action = result?.robot_action || {};
      const robotX = mapDistance(context.robot_distance_m ?? 1.1);
      const student = {x: 520, y: 210};
      const robotColor = action.motion_policy === 'stop_motion' ? '#c24135' : action.motion_policy === 'hold_position' ? '#2563eb' : '#6d4aff';
      const studentColor = stateColor(human.state);
      const gaze = cues.attention_score >= 0.65 ? '任务屏幕' : '偏离';
      const prompt = action.speech_action || 'monitor';
      el('scene').innerHTML = `<svg viewBox="0 0 820 460" role="img" aria-label="classroom simulation">
        <rect x="24" y="24" width="772" height="412" rx="8" fill="#f8faf4" stroke="#d8dfd1"/>
        <rect x="60" y="62" width="210" height="96" rx="8" fill="#ffffff" stroke="#cfd8c8"/>
        <text x="82" y="98" font-size="19" font-weight="700">教师端屏幕</text>
        <text x="82" y="128" font-size="14" fill="#5e6b62">${label(stateLabels, human.state)} / ${label(actionLabels, action.action_id)}</text>
        <rect x="430" y="310" width="230" height="74" rx="8" fill="#c69a67"/>
        <rect x="462" y="278" width="166" height="70" rx="6" fill="#ffffff" stroke="#cfd8c8"/>
        <text x="498" y="318" font-size="17">学生任务屏</text>
        <circle cx="${student.x}" cy="${student.y}" r="46" fill="${studentColor}"/>
        <text x="${student.x - 27}" y="${student.y + 6}" font-size="17" fill="#fff">学生</text>
        <circle cx="690" cy="124" r="38" fill="#16783a"/>
        <text x="665" y="130" font-size="16" fill="#fff">教师</text>
        <circle cx="${robotX}" cy="225" r="42" fill="${robotColor}"/>
        <text x="${robotX - 30}" y="232" font-size="17" fill="#fff">机器人</text>
        <line x1="${robotX + 42}" y1="225" x2="${student.x - 46}" y2="${student.y}" stroke="#87938a" stroke-width="2" stroke-dasharray="7 7"/>
        <rect x="256" y="92" width="58" height="58" rx="7" fill="#e3aa1b"/>
        <text x="236" y="174" font-size="14" fill="#5e6b62">安全边界物</text>
        <rect x="70" y="348" width="270" height="54" rx="8" fill="#fff" stroke="#cfd8c8"/>
        <text x="88" y="373" font-size="15" fill="#5e6b62">gaze: ${gaze}</text>
        <text x="88" y="394" font-size="15" fill="#5e6b62">robot cue: ${label(speechLabels, prompt)}</text>
      </svg>`;
    }

    function renderMujocoProof() {
      const frame = (mujocoAssets?.frames || []).find((item) => item.step === stepIndex);
      const sheet = mujocoAssets?.contact_sheet || {};
      const image = el('mujocoFrame');
      const missing = el('mujocoMissing');
      const link = el('mujocoSheet');
      el('mujocoTitle').textContent = `MuJoCo 实渲染：${currentScenario?.scenario_id || 'scenario'} / step ${stepIndex}`;
      if (sheet.exists) {
        link.href = sheet.url;
        link.style.visibility = 'visible';
      } else {
        link.href = '#';
        link.style.visibility = 'hidden';
      }
      if (frame?.exists) {
        image.src = `${frame.url}?t=${Date.now()}`;
        image.style.display = 'block';
        missing.style.display = 'none';
      } else {
        image.removeAttribute('src');
        image.style.display = 'none';
        missing.style.display = 'block';
        missing.textContent = '未找到该场景的 MuJoCo 渲染帧；可运行 mujoco_snapshot 生成。';
      }
    }

    function renderTimeline(steps) {
      if (!steps.length) {
        el('timeline').innerHTML = '<div class="event">暂无课堂事件</div>';
        return;
      }
      el('timeline').innerHTML = steps.map((item, index) => {
        const human = item.human_state || {};
        const action = item.robot_action || {};
        const feedback = item.embodied_feedback || {};
        return `<div class="event">
          <strong>${index + 1}. ${label(stateLabels, human.state || item.ground_truth_state)}</strong>
          <div>动作：${label(actionLabels, action.action_id)}</div>
          <div>移动：${label(motionLabels, action.motion_policy)}</div>
          <div>教师介入：${action.handoff_required ? '需要' : '不需要'}</div>
          ${feedback.outcome ? `<div>反馈：${feedback.outcome}</div>` : ''}
        </div>`;
      }).join('');
    }

    function renderJson() {
      const report = loopResult ? {
        scenario_id: loopResult.scenario_id,
        metrics: loopResult.metrics,
        summary: (loopResult.steps || []).map((step) => ({
          step: step.step,
          state: step.human_state?.state,
          action: step.robot_action?.action_id,
          outcome: step.embodied_feedback?.outcome
        }))
      } : {
        scenario_id: currentScenario?.scenario_id,
        step: stepIndex,
        state: result?.human_state?.state,
        action: result?.robot_action?.action_id
      };
      const data = activeTab === 'human_state'
        ? result?.human_state
        : activeTab === 'robot_action'
          ? result?.robot_action
          : report;
      el('json').textContent = JSON.stringify(data || {}, null, 2);
    }

    function updateTabs() {
      document.querySelectorAll('.tab').forEach((tab) => {
        tab.classList.toggle('active', tab.dataset.tab === activeTab);
      });
    }

    function mapDistance(value) {
      return Math.max(92, Math.min(394, Math.round(420 - Number(value ?? 1) * 205)));
    }

    function stateColor(state) {
      return {
        engaged: '#16783a',
        confused: '#aa6a12',
        fatigued: '#aa6a12',
        frustrated: '#c24135',
        refusing: '#c24135',
        pain_risk: '#c24135',
        low_attention: '#c24135',
        needs_help: '#2563eb'
      }[state] || '#607068';
    }

    function classForState(state) {
      if (state === 'pain_risk' || state === 'refusing' || state === 'low_attention') return 'risk';
      if (state === 'confused' || state === 'fatigued' || state === 'frustrated') return 'warn';
      if (state === 'needs_help') return 'help';
      return '';
    }

    function label(map, value) {
      return map[value] || value || 'n/a';
    }

    function riskLabel(value) {
      return {low: '低', medium: '中', high: '高', critical: '紧急'}[value] || value || 'n/a';
    }

    el('scenario').addEventListener('change', async () => {
      await loadScenario(el('scenario').value);
      await runStep();
    });
    el('prev').addEventListener('click', async () => {
      stepIndex = Math.max(0, stepIndex - 1);
      await runStep();
    });
    el('next').addEventListener('click', async () => {
      stepIndex = Math.min(currentScenario.steps.length - 1, stepIndex + 1);
      await runStep();
    });
    el('loop').addEventListener('click', runLoop);
    document.querySelectorAll('.tab').forEach((tab) => {
      tab.addEventListener('click', () => {
        activeTab = tab.dataset.tab;
        updateTabs();
        renderJson();
      });
    });

    init().catch((error) => {
      el('status').textContent = error.message;
      el('json').textContent = error.stack || error.message;
    });
  </script>
</body>
</html>
"""
