from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any

from .sim_runner import DEFAULT_LEARNED_POLICY_PATH, DEFAULT_SCENARIO_DIR, build_policy, run_scenario_path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = PROJECT_ROOT / "outputs" / "special_education_benchmark_demo.html"


STATE_LABELS = {
    "engaged": "专注参与",
    "neutral": "正常",
    "confused": "困惑",
    "fatigued": "疲劳/负荷高",
    "frustrated": "挫败",
    "refusing": "抗拒",
    "pain_risk": "不适风险",
    "low_attention": "注意力低",
    "needs_help": "需要帮助",
}


ACTION_LABELS = {
    "continue_and_encourage": "继续并鼓励",
    "repeat_instruction_slowly": "慢速重复说明",
    "reduce_task_load_and_offer_break": "降低任务负荷并询问休息",
    "pause_and_request_consent": "暂停并确认意愿",
    "stop_and_check_pain_risk": "停止并确认不适",
    "regain_attention": "重新吸引注意",
    "offer_help": "提供帮助/交接教师",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export a static benchmark demo page for the special-education robot project."
    )
    parser.add_argument("--scenario-dir", type=Path, default=DEFAULT_SCENARIO_DIR)
    parser.add_argument("--backend", choices=("kinematic", "mujoco"), default="mujoco")
    parser.add_argument("--policy", choices=("rule", "learned"), default="rule")
    parser.add_argument("--model-path", type=Path, default=DEFAULT_LEARNED_POLICY_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--smooth-window", type=int, default=1)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    scenario_paths = sorted(args.scenario_dir.glob("*.json"))
    if not scenario_paths:
        raise SystemExit(f"No scenario JSON files found in {args.scenario_dir}")

    results = []
    backend_used = args.backend
    robot_policy = build_policy(args.policy, args.model_path)
    for path in scenario_paths:
        try:
            result = run_scenario_path(
                path,
                backend_name=args.backend,
                robot_policy=robot_policy,
                include_cues=True,
                smooth_window=args.smooth_window,
            )
        except RuntimeError:
            if args.backend != "mujoco":
                raise
            backend_used = "kinematic"
            result = run_scenario_path(
                path,
                backend_name="kinematic",
                robot_policy=robot_policy,
                include_cues=True,
                smooth_window=args.smooth_window,
            )
        results.append(result)

    payload = {
        "benchmark": "special_education_classroom",
        "backend": backend_used,
        "policy": args.policy,
        "scenario_count": len(results),
        "aggregate_metrics": _aggregate_metrics(results),
        "results": results,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(_render_html(payload), encoding="utf-8")
    print(str(args.output))
    return 0


def _aggregate_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    step_count = sum(result["metrics"]["step_count"] for result in results)
    if not step_count:
        return {}
    return {
        "scenario_count": len(results),
        "step_count": step_count,
        "action_match_accuracy": sum(
            result["metrics"]["action_match_accuracy"] * result["metrics"]["step_count"]
            for result in results
        )
        / step_count,
        "safety_violation_count": sum(
            result["metrics"]["safety_violation_count"] for result in results
        ),
        "intervention_count": sum(result["metrics"]["intervention_count"] for result in results),
    }


def _render_html(payload: dict[str, Any]) -> str:
    metrics = payload["aggregate_metrics"]
    scenario_cards = "\n".join(_scenario_card(result) for result in payload["results"])
    data_blob = html.escape(json.dumps(payload, ensure_ascii=False, indent=2))
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Special Education Robot Benchmark Demo</title>
  <style>
    :root {{
      --bg: #f6f7f3;
      --ink: #17201c;
      --muted: #657069;
      --line: #d9ded6;
      --panel: #ffffff;
      --blue: #2563eb;
      --green: #17803d;
      --amber: #b7791f;
      --red: #c24135;
      --violet: #6d4aff;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: Inter, "Segoe UI", Arial, sans-serif;
      line-height: 1.45;
    }}
    header {{
      padding: 28px 32px 18px;
      border-bottom: 1px solid var(--line);
      background: #fff;
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 28px;
      letter-spacing: 0;
    }}
    .subtitle {{
      color: var(--muted);
      max-width: 980px;
      font-size: 15px;
    }}
    main {{ padding: 24px 32px 36px; }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(5, minmax(150px, 1fr));
      gap: 12px;
      margin-bottom: 24px;
    }}
    .metric, .scenario, .step {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
    }}
    .metric {{ padding: 14px 16px; }}
    .metric .value {{ font-size: 24px; font-weight: 700; margin-top: 4px; }}
    .metric .label, .small-label {{ color: var(--muted); font-size: 12px; }}
    .scenario {{ margin-bottom: 18px; overflow: hidden; }}
    .scenario-head {{
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 16px;
      align-items: start;
      padding: 16px 18px;
      border-bottom: 1px solid var(--line);
      background: #fbfcf9;
    }}
    .scenario h2 {{ margin: 0 0 4px; font-size: 18px; }}
    .scenario-desc {{ color: var(--muted); font-size: 13px; }}
    .badges {{ display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }}
    .badge {{
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 4px 9px;
      font-size: 12px;
      background: #fff;
    }}
    .steps {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(310px, 1fr));
      gap: 12px;
      padding: 14px;
    }}
    .step {{ padding: 12px; }}
    .step-top {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 10px;
    }}
    .state {{
      font-weight: 700;
      color: var(--blue);
    }}
    .critical {{ color: var(--red); }}
    .medium {{ color: var(--amber); }}
    .low {{ color: var(--green); }}
    .scene-svg {{
      width: 100%;
      height: auto;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #eef2ea;
      display: block;
      margin: 8px 0 10px;
    }}
    .kv {{
      display: grid;
      grid-template-columns: 108px 1fr;
      gap: 5px 10px;
      font-size: 12px;
    }}
    .kv .key {{ color: var(--muted); }}
    .action {{
      border-left: 3px solid var(--violet);
      padding-left: 9px;
      margin-top: 10px;
      font-size: 12px;
    }}
    details {{
      margin-top: 22px;
      background: #fff;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px 14px;
    }}
    pre {{
      overflow: auto;
      font-size: 12px;
      background: #111814;
      color: #e9f4ec;
      border-radius: 6px;
      padding: 12px;
    }}
    @media (max-width: 900px) {{
      header, main {{ padding-left: 18px; padding-right: 18px; }}
      .metrics {{ grid-template-columns: repeat(2, minmax(140px, 1fr)); }}
      .scenario-head {{ grid-template-columns: 1fr; }}
      .badges {{ justify-content: flex-start; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>辅读学校辅助机器人具身 Benchmark Demo</h1>
    <div class="subtitle">
      场景从学生语音、姿态、任务行为和机器人上下文生成观测线索，系统输出 human_state，并最终落到 speech、motion、task、safety 四类 robot_action。当前后端：{_e(payload["backend"])}；策略：{_e(payload.get("policy", "rule"))}。
    </div>
  </header>
  <main>
    <section class="metrics">
      {_metric("场景数", metrics.get("scenario_count"))}
      {_metric("仿真步数", metrics.get("step_count"))}
      {_metric("动作命中率", _pct(metrics.get("action_match_accuracy")))}
      {_metric("安全违规", metrics.get("safety_violation_count"))}
      {_metric("干预次数", metrics.get("intervention_count"))}
    </section>
    {scenario_cards}
    <details>
      <summary>完整 JSON 输出</summary>
      <pre>{data_blob}</pre>
    </details>
  </main>
</body>
</html>
"""


def _scenario_card(result: dict[str, Any]) -> str:
    metrics = result["metrics"]
    badges = [
        f"action {_pct(metrics['action_match_accuracy'])}",
        f"safety violations {metrics['safety_violation_count']}",
        f"min student distance {_fmt(metrics['minimum_robot_student_distance_m'])}m",
        f"min obstacle {_fmt(metrics['minimum_obstacle_distance_m'])}m",
    ]
    steps = "\n".join(_step_card(step) for step in result["steps"])
    return f"""
<section class="scenario">
  <div class="scenario-head">
    <div>
      <h2>{_e(result["scenario_id"])}</h2>
      <div class="scenario-desc">{_e(result.get("description", ""))}</div>
    </div>
    <div class="badges">{"".join(f'<span class="badge">{_e(badge)}</span>' for badge in badges)}</div>
  </div>
  <div class="steps">{steps}</div>
</section>
"""


def _step_card(step: dict[str, Any]) -> str:
    human_state = step["human_state"]
    action = step["robot_action"]
    context = step["robot_context"]
    cues = step.get("observable_cues", {})
    priority = action.get("priority", "low")
    state = human_state["state"]
    return f"""
<article class="step">
  <div class="step-top">
    <div>
      <div class="small-label">Step {step["step"]} / ground truth</div>
      <div class="state {priority}">{_e(STATE_LABELS.get(step["ground_truth_state"], step["ground_truth_state"]))}</div>
    </div>
    <div>
      <div class="small-label">predicted</div>
      <div class="state {priority}">{_e(STATE_LABELS.get(state, state))}</div>
    </div>
  </div>
  {_scene_svg(context, step["post_action_context"], state)}
  <div class="kv">
    <div class="key">speech</div><div>{_e(cues.get("speech_text", "") or "(silent)")}</div>
    <div class="key">evidence</div><div>{_e(", ".join(human_state.get("evidence", [])))}</div>
    <div class="key">confidence</div><div>{_fmt(human_state.get("confidence"))}</div>
    <div class="key">risk</div><div>{_e(human_state.get("risk_level", ""))}</div>
  </div>
  <div class="action">
    <b>{_e(ACTION_LABELS.get(action["action_id"], action["action_id"]))}</b><br>
    speech: {_e(action["speech_action"])}<br>
    motion: {_e(action["motion_policy"])}<br>
    task: {_e(action["task_adjustment"])}<br>
    safety: {_e(action["safety_action"])}
  </div>
</article>
"""


def _scene_svg(context: dict[str, Any], post_context: dict[str, Any], state: str) -> str:
    robot_x = _map_distance(post_context.get("robot_distance_m", context.get("robot_distance_m")))
    obstacle_x = _map_distance(context.get("obstacle_distance_m"), origin=250)
    robot_color = "#2563eb" if not post_context.get("is_robot_moving") else "#7c3aed"
    state_color = {
        "engaged": "#17803d",
        "confused": "#b7791f",
        "fatigued": "#b7791f",
        "refusing": "#c24135",
        "pain_risk": "#c24135",
        "low_attention": "#c24135",
        "needs_help": "#c24135",
    }.get(state, "#657069")
    return f"""
<svg class="scene-svg" viewBox="0 0 520 240" role="img" aria-label="classroom top-down simulation">
  <rect x="16" y="16" width="488" height="208" rx="8" fill="#f8faf5" stroke="#d9ded6"/>
  <rect x="290" y="148" width="136" height="48" rx="5" fill="#c89f68" opacity="0.85"/>
  <text x="318" y="177" font-size="13" fill="#17201c">desk / task</text>
  <rect x="{obstacle_x}" y="44" width="42" height="42" rx="5" fill="#e0a51b"/>
  <text x="{obstacle_x - 8}" y="100" font-size="12" fill="#17201c">obstacle</text>
  <circle cx="330" cy="104" r="25" fill="{state_color}"/>
  <text x="306" y="110" font-size="12" fill="#fff">student</text>
  <circle cx="438" cy="66" r="22" fill="#22864b"/>
  <text x="418" y="71" font-size="12" fill="#fff">teacher</text>
  <circle cx="{robot_x}" cy="110" r="24" fill="{robot_color}"/>
  <text x="{robot_x - 17}" y="115" font-size="12" fill="#fff">robot</text>
  <line x1="{robot_x + 24}" y1="110" x2="305" y2="106" stroke="#8f9a92" stroke-dasharray="5 5"/>
  <text x="24" y="214" font-size="12" fill="#657069">top-down classroom proxy, post-action robot pose</text>
</svg>
"""


def _map_distance(value: Any, origin: int = 330) -> int:
    try:
        distance = float(value)
    except (TypeError, ValueError):
        distance = 1.0
    return max(48, min(300, int(origin - distance * 170)))


def _metric(label: str, value: Any) -> str:
    return f'<div class="metric"><div class="label">{_e(label)}</div><div class="value">{_e(str(value))}</div></div>'


def _pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "n/a"


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _e(value: Any) -> str:
    return html.escape(str(value), quote=True)


if __name__ == "__main__":
    raise SystemExit(main())
