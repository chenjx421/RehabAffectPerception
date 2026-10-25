from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any

from .demo_export import ACTION_LABELS, STATE_LABELS
from .policy_compare import compare_policies
from .sim_runner import DEFAULT_LEARNED_POLICY_PATH, DEFAULT_SCENARIO_DIR, build_policy, run_scenario_path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = PROJECT_ROOT / "outputs" / "interactive_benchmark_console.html"


def build_console_payload(
    *,
    scenario_dir: Path = DEFAULT_SCENARIO_DIR,
    backend: str = "mujoco",
    policy: str = "learned",
    model_path: Path = DEFAULT_LEARNED_POLICY_PATH,
    smooth_window: int = 1,
    compare_backend: str = "kinematic",
) -> dict[str, Any]:
    robot_policy = build_policy(policy, model_path)
    results = [
        run_scenario_path(
            path,
            backend_name=backend,
            robot_policy=robot_policy,
            smooth_window=smooth_window,
            include_cues=True,
        )
        for path in sorted(scenario_dir.glob("*.json"))
    ]
    comparison = compare_policies(
        scenario_dir=scenario_dir,
        model_path=model_path,
        backend_name=compare_backend,
        augmentations_per_scenario=1,
        smooth_window=smooth_window,
    )
    return {
        "benchmark": "special_education_interactive_console",
        "backend": backend,
        "policy": policy,
        "state_labels": STATE_LABELS,
        "action_labels": ACTION_LABELS,
        "results": results,
        "comparison": comparison,
    }


def export_console(payload: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_console_html(payload), encoding="utf-8")


def render_console_html(payload: dict[str, Any]) -> str:
    data = json.dumps(payload, ensure_ascii=False)
    escaped_data = data.replace("</", "<\\/")
    comparison_rows = "\n".join(
        _comparison_row(variant) for variant in payload["comparison"]["variants"]
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Interactive Special Education Robot Console</title>
  <style>
    :root {{
      --bg: #f4f6f0;
      --ink: #151f1a;
      --muted: #617069;
      --panel: #ffffff;
      --line: #d8dfd3;
      --blue: #2563eb;
      --green: #16783a;
      --amber: #b7791f;
      --red: #c24135;
      --violet: #6d4aff;
      --shadow: 0 10px 26px rgba(21, 31, 26, 0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: Inter, "Segoe UI", Arial, sans-serif;
      line-height: 1.42;
    }}
    header {{
      background: #fff;
      border-bottom: 1px solid var(--line);
      padding: 20px 28px 16px;
    }}
    h1 {{
      font-size: 26px;
      margin: 0 0 6px;
      letter-spacing: 0;
    }}
    .subtitle {{
      color: var(--muted);
      max-width: 1040px;
      font-size: 14px;
    }}
    main {{
      display: grid;
      grid-template-columns: 260px minmax(460px, 1fr) 390px;
      gap: 14px;
      padding: 16px;
      min-height: calc(100vh - 92px);
    }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
      min-width: 0;
    }}
    .panel-head {{
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
      font-weight: 700;
      display: flex;
      justify-content: space-between;
      gap: 10px;
      align-items: center;
    }}
    .scenario-list {{
      padding: 8px;
      display: grid;
      gap: 8px;
    }}
    button {{
      font: inherit;
      border: 1px solid var(--line);
      background: #fff;
      color: var(--ink);
      border-radius: 7px;
      cursor: pointer;
    }}
    .scenario-btn {{
      text-align: left;
      padding: 10px;
      display: grid;
      gap: 4px;
    }}
    .scenario-btn.active {{
      border-color: var(--blue);
      box-shadow: inset 3px 0 0 var(--blue);
      background: #f7fbff;
    }}
    .scenario-btn strong {{
      font-size: 13px;
    }}
    .scenario-btn span {{
      color: var(--muted);
      font-size: 12px;
    }}
    .stage {{
      padding: 14px;
      display: grid;
      gap: 12px;
    }}
    .scene {{
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #eef3ea;
      min-height: 330px;
      position: relative;
      overflow: hidden;
    }}
    .scene svg {{
      width: 100%;
      height: 100%;
      min-height: 330px;
      display: block;
    }}
    .step-controls {{
      display: flex;
      gap: 8px;
      align-items: center;
      flex-wrap: wrap;
    }}
    .icon-btn {{
      width: 38px;
      height: 34px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-weight: 700;
    }}
    .step-chip {{
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 6px 10px;
      font-size: 12px;
      color: var(--muted);
      background: #fff;
    }}
    .status-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 8px;
    }}
    .metric {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px;
      background: #fff;
    }}
    .metric .label {{
      color: var(--muted);
      font-size: 11px;
    }}
    .metric .value {{
      margin-top: 3px;
      font-weight: 700;
      font-size: 17px;
      overflow-wrap: anywhere;
    }}
    .details {{
      padding: 12px;
      display: grid;
      gap: 10px;
    }}
    .kv {{
      display: grid;
      grid-template-columns: 118px 1fr;
      gap: 6px 10px;
      font-size: 12px;
    }}
    .key {{ color: var(--muted); }}
    .action-box {{
      border-left: 3px solid var(--violet);
      background: #fbfaff;
      padding: 10px 12px;
      border-radius: 0 7px 7px 0;
      font-size: 12px;
    }}
    .json-tabs {{
      display: flex;
      gap: 6px;
      padding: 10px 10px 0;
    }}
    .tab.active {{
      border-color: var(--blue);
      color: var(--blue);
    }}
    pre {{
      margin: 10px;
      background: #101812;
      color: #e7f5eb;
      padding: 12px;
      border-radius: 7px;
      overflow: auto;
      max-height: 360px;
      font-size: 11px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 12px;
    }}
    th, td {{
      text-align: left;
      border-bottom: 1px solid var(--line);
      padding: 8px 6px;
      vertical-align: top;
    }}
    th {{ color: var(--muted); font-weight: 600; }}
    .comparison {{
      padding: 10px 12px 14px;
    }}
    .ok {{ color: var(--green); }}
    .warn {{ color: var(--amber); }}
    .danger {{ color: var(--red); }}
    @media (max-width: 1120px) {{
      main {{ grid-template-columns: 1fr; }}
      .status-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>辅读学校辅助机器人交互式 Benchmark 控制台</h1>
    <div class="subtitle">选择场景并播放 step，观察学生状态估计、机器人上下文、动作策略、action shield 以及 WebSocket / ROS2-style JSON。当前后端：{_e(payload["backend"])}；策略：{_e(payload["policy"])}。</div>
  </header>
  <main>
    <section class="panel">
      <div class="panel-head">场景</div>
      <div class="scenario-list" id="scenarioList"></div>
    </section>
    <section class="panel">
      <div class="panel-head">
        <span id="scenarioTitle">Scenario</span>
        <span class="step-chip" id="matchChip">match</span>
      </div>
      <div class="stage">
        <div class="scene" id="scene"></div>
        <div class="step-controls">
          <button class="icon-btn" id="prevBtn" title="Previous step">‹</button>
          <button class="icon-btn" id="playBtn" title="Play or pause">▶</button>
          <button class="icon-btn" id="nextBtn" title="Next step">›</button>
          <span class="step-chip" id="stepChip">Step 0</span>
          <span class="step-chip" id="speechChip">speech</span>
        </div>
        <div class="status-grid">
          <div class="metric"><div class="label">ground truth</div><div class="value" id="gtState"></div></div>
          <div class="metric"><div class="label">human_state</div><div class="value" id="predState"></div></div>
          <div class="metric"><div class="label">confidence</div><div class="value" id="confidence"></div></div>
          <div class="metric"><div class="label">robot action</div><div class="value" id="actionId"></div></div>
        </div>
        <div class="comparison">
          <table>
            <thead><tr><th>Policy</th><th>Action Acc.</th><th>Safety</th><th>Interventions</th><th>Shield</th></tr></thead>
            <tbody>
              {comparison_rows}
            </tbody>
          </table>
        </div>
      </div>
    </section>
    <section class="panel">
      <div class="panel-head">决策细节</div>
      <div class="details">
        <div class="kv" id="stateKv"></div>
        <div class="action-box" id="actionBox"></div>
      </div>
      <div class="json-tabs">
        <button class="tab active" data-tab="human_state">human_state</button>
        <button class="tab" data-tab="robot_action">robot_action</button>
        <button class="tab" data-tab="websocket">WebSocket</button>
        <button class="tab" data-tab="ros2">ROS2</button>
      </div>
      <pre id="jsonView"></pre>
    </section>
  </main>
  <script id="payload" type="application/json">{escaped_data}</script>
  <script>
    const payload = JSON.parse(document.getElementById('payload').textContent);
    const stateLabels = payload.state_labels;
    const actionLabels = payload.action_labels;
    let scenarioIndex = 0;
    let stepIndex = 0;
    let playing = false;
    let timer = null;
    let activeTab = 'human_state';

    const el = (id) => document.getElementById(id);
    const fmt = (value) => typeof value === 'number' ? value.toFixed(2) : String(value ?? 'n/a');
    const pct = (value) => (Number(value || 0) * 100).toFixed(1) + '%';
    const labelState = (value) => stateLabels[value] || value || 'n/a';
    const labelAction = (value) => actionLabels[value] || value || 'n/a';

    function currentScenario() {{ return payload.results[scenarioIndex]; }}
    function currentStep() {{ return currentScenario().steps[stepIndex]; }}

    function renderScenarioList() {{
      el('scenarioList').innerHTML = payload.results.map((scenario, index) => `
        <button class="scenario-btn ${{index === scenarioIndex ? 'active' : ''}}" data-index="${{index}}">
          <strong>${{scenario.scenario_id}}</strong>
          <span>${{scenario.description || ''}}</span>
        </button>
      `).join('');
      document.querySelectorAll('.scenario-btn').forEach((button) => {{
        button.addEventListener('click', () => {{
          scenarioIndex = Number(button.dataset.index);
          stepIndex = 0;
          stopPlayback();
          render();
        }});
      }});
    }}

    function renderScene(step) {{
      const context = step.robot_context;
      const post = step.post_action_context;
      const state = step.human_state.state;
      const robotX = mapDistance(post.robot_distance_m ?? context.robot_distance_m, 340);
      const obstacleX = mapDistance(context.obstacle_distance_m, 250);
      const moving = post.is_robot_moving;
      const studentColor = {{
        engaged: '#16783a',
        confused: '#b7791f',
        fatigued: '#b7791f',
        refusing: '#c24135',
        pain_risk: '#c24135',
        low_attention: '#c24135',
        needs_help: '#2563eb'
      }}[state] || '#657069';
      const robotColor = moving ? '#6d4aff' : '#2563eb';
      el('scene').innerHTML = `
        <svg viewBox="0 0 760 430" role="img" aria-label="classroom simulation">
          <rect x="22" y="22" width="716" height="386" rx="8" fill="#f7faf4" stroke="#d8dfd3"/>
          <rect x="460" y="268" width="190" height="76" rx="6" fill="#c99e69"/>
          <text x="512" y="312" font-size="18" fill="#151f1a">desk / task</text>
          <rect x="${{obstacleX}}" y="88" width="58" height="58" rx="6" fill="#e3aa1b"/>
          <text x="${{obstacleX - 2}}" y="166" font-size="15" fill="#151f1a">obstacle</text>
          <circle cx="505" cy="190" r="42" fill="${{studentColor}}"/>
          <text x="473" y="197" font-size="16" fill="#fff">student</text>
          <circle cx="650" cy="112" r="34" fill="#16783a"/>
          <text x="624" y="118" font-size="15" fill="#fff">teacher</text>
          <circle cx="${{robotX}}" cy="202" r="40" fill="${{robotColor}}"/>
          <text x="${{robotX - 25}}" y="209" font-size="16" fill="#fff">robot</text>
          <line x1="${{robotX + 40}}" y1="202" x2="463" y2="193" stroke="#8f9a92" stroke-width="2" stroke-dasharray="7 7"/>
          <text x="38" y="392" font-size="15" fill="#617069">post-action pose, top-down classroom proxy</text>
        </svg>`;
    }}

    function mapDistance(value, origin) {{
      const distance = Number(value ?? 1.0);
      return Math.max(70, Math.min(430, Math.round(origin - distance * 190)));
    }}

    function renderJson(step) {{
      const wsMessage = {{
        type: 'perception_decision',
        scenario_id: currentScenario().scenario_id,
        step: step.step,
        payload: {{
          human_state: step.human_state,
          robot_context: step.robot_context,
          robot_action: step.robot_action
        }}
      }};
      const ros2Message = {{
        topic: '/rehab_affect/robot_action',
        msg_type: 'std_msgs/msg/String',
        data: JSON.stringify(step.robot_action)
      }};
      const data = {{
        human_state: step.human_state,
        robot_action: step.robot_action,
        websocket: wsMessage,
        ros2: ros2Message
      }}[activeTab];
      el('jsonView').textContent = JSON.stringify(data, null, 2);
    }}

    function render() {{
      renderScenarioList();
      const scenario = currentScenario();
      const step = currentStep();
      const action = step.robot_action;
      const state = step.human_state;
      el('scenarioTitle').textContent = scenario.scenario_id;
      el('matchChip').textContent = step.action_match ? 'action match' : 'action mismatch';
      el('matchChip').className = `step-chip ${{step.action_match ? 'ok' : 'danger'}}`;
      el('stepChip').textContent = `Step ${{stepIndex + 1}} / ${{scenario.steps.length}}`;
      el('speechChip').textContent = (step.observable_cues?.speech_text || '(silent)').slice(0, 42);
      el('gtState').textContent = labelState(step.ground_truth_state);
      el('predState').textContent = labelState(state.state);
      el('confidence').textContent = fmt(state.confidence);
      el('actionId').textContent = labelAction(action.action_id);
      renderScene(step);
      el('stateKv').innerHTML = `
        <div class="key">evidence</div><div>${{(state.evidence || []).join(', ') || 'n/a'}}</div>
        <div class="key">risk</div><div>${{state.risk_level}}</div>
        <div class="key">handoff</div><div>${{state.handoff_required}}</div>
        <div class="key">robot distance</div><div>${{fmt(step.robot_context.robot_distance_m)}} m</div>
        <div class="key">obstacle</div><div>${{fmt(step.robot_context.obstacle_distance_m)}} m</div>
        <div class="key">moving</div><div>${{step.robot_context.is_robot_moving}}</div>
      `;
      el('actionBox').innerHTML = `
        <strong>${{labelAction(action.action_id)}}</strong><br>
        speech: ${{action.speech_action}}<br>
        motion: ${{action.motion_policy}}<br>
        task: ${{action.task_adjustment}}<br>
        safety: ${{action.safety_action}}<br>
        shield: ${{action.metadata?.action_shield || 'none'}}
      `;
      renderJson(step);
    }}

    function stopPlayback() {{
      playing = false;
      el('playBtn').textContent = '▶';
      if (timer) clearInterval(timer);
      timer = null;
    }}

    el('prevBtn').addEventListener('click', () => {{
      stepIndex = Math.max(0, stepIndex - 1);
      stopPlayback();
      render();
    }});
    el('nextBtn').addEventListener('click', () => {{
      stepIndex = Math.min(currentScenario().steps.length - 1, stepIndex + 1);
      stopPlayback();
      render();
    }});
    el('playBtn').addEventListener('click', () => {{
      if (playing) {{
        stopPlayback();
        return;
      }}
      playing = true;
      el('playBtn').textContent = 'Ⅱ';
      timer = setInterval(() => {{
        if (stepIndex < currentScenario().steps.length - 1) {{
          stepIndex += 1;
        }} else {{
          stepIndex = 0;
        }}
        render();
      }}, 1100);
    }});
    document.querySelectorAll('.tab').forEach((button) => {{
      button.addEventListener('click', () => {{
        activeTab = button.dataset.tab;
        document.querySelectorAll('.tab').forEach((tab) => tab.classList.remove('active'));
        button.classList.add('active');
        renderJson(currentStep());
      }});
    }});
    render();
  </script>
</body>
</html>
"""


def _comparison_row(variant: dict[str, Any]) -> str:
    metrics = variant["aggregate_metrics"]
    shield_counts = variant.get("shield_counts", {})
    shield_text = ", ".join(f"{key}: {value}" for key, value in shield_counts.items()) or "none"
    return (
        "<tr>"
        f"<td>{_e(variant['variant'])}</td>"
        f"<td>{_pct(metrics.get('action_match_accuracy'))}</td>"
        f"<td>{_e(metrics.get('safety_violation_count'))}</td>"
        f"<td>{_e(metrics.get('intervention_count'))}</td>"
        f"<td>{_e(shield_text)}</td>"
        "</tr>"
    )


def _pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "n/a"


def _e(value: Any) -> str:
    return html.escape(str(value), quote=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export an interactive special-education benchmark console."
    )
    parser.add_argument("--scenario-dir", type=Path, default=DEFAULT_SCENARIO_DIR)
    parser.add_argument("--backend", choices=("kinematic", "mujoco"), default="mujoco")
    parser.add_argument("--policy", choices=("rule", "learned"), default="learned")
    parser.add_argument("--model-path", type=Path, default=DEFAULT_LEARNED_POLICY_PATH)
    parser.add_argument("--smooth-window", type=int, default=1)
    parser.add_argument("--compare-backend", choices=("kinematic", "mujoco"), default="kinematic")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.smooth_window <= 0:
        raise SystemExit("--smooth-window must be positive")
    payload = build_console_payload(
        scenario_dir=args.scenario_dir,
        backend=args.backend,
        policy=args.policy,
        model_path=args.model_path,
        smooth_window=args.smooth_window,
        compare_backend=args.compare_backend,
    )
    export_console(payload, args.output)
    print(str(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
