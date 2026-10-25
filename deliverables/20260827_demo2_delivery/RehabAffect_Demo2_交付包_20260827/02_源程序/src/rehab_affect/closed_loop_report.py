from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any

from .closed_loop import aggregate_closed_loop_results, run_closed_loop_path
from .demo_export import ACTION_LABELS, STATE_LABELS
from .sim_runner import DEFAULT_LEARNED_POLICY_PATH, DEFAULT_SCENARIO_DIR, build_policy


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_JSON_OUTPUT = PROJECT_ROOT / "data" / "processed" / "closed_loop_benchmark.json"
DEFAULT_HTML_OUTPUT = PROJECT_ROOT / "outputs" / "closed_loop_benchmark_report.html"


def build_closed_loop_payload(
    *,
    scenario_dir: Path = DEFAULT_SCENARIO_DIR,
    backend: str = "kinematic",
    policy: str = "learned",
    model_path: Path = DEFAULT_LEARNED_POLICY_PATH,
    smooth_window: int = 1,
) -> dict[str, Any]:
    scenario_paths = sorted(scenario_dir.glob("*.json"))
    if not scenario_paths:
        raise RuntimeError(f"No scenario JSON files found in {scenario_dir}")

    robot_policy = build_policy(policy, model_path)
    results: list[dict[str, Any]] = []
    backend_used = backend
    for path in scenario_paths:
        try:
            result = run_closed_loop_path(
                path,
                backend_name=backend,
                robot_policy=robot_policy,
                smooth_window=smooth_window,
                include_base_steps=True,
            )
        except RuntimeError:
            if backend != "mujoco":
                raise
            backend_used = "kinematic"
            result = run_closed_loop_path(
                path,
                backend_name="kinematic",
                robot_policy=robot_policy,
                smooth_window=smooth_window,
                include_base_steps=True,
            )
        results.append(result)

    return {
        "benchmark": "special_education_classroom_closed_loop",
        "backend": backend_used,
        "policy": policy,
        "scenario_count": len(results),
        "aggregate_metrics": aggregate_closed_loop_results(results),
        "results": results,
    }


def export_closed_loop_report(
    payload: dict[str, Any],
    *,
    json_output: Path = DEFAULT_JSON_OUTPUT,
    html_output: Path = DEFAULT_HTML_OUTPUT,
) -> None:
    json_output.parent.mkdir(parents=True, exist_ok=True)
    html_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    html_output.write_text(render_closed_loop_html(payload), encoding="utf-8")


def render_closed_loop_html(payload: dict[str, Any]) -> str:
    metrics = payload.get("aggregate_metrics", {})
    cards = "\n".join(_scenario_card(result) for result in payload.get("results", []))
    data_blob = html.escape(json.dumps(payload, ensure_ascii=False, indent=2))
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Closed-loop Embodied Benchmark</title>
  <style>
    :root {{
      --bg: #f6f7f2;
      --panel: #fff;
      --ink: #152019;
      --muted: #657269;
      --line: #d8dfd2;
      --blue: #2563eb;
      --green: #16813f;
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
      padding: 26px 30px 18px;
      background: #fff;
      border-bottom: 1px solid var(--line);
    }}
    h1 {{ margin: 0 0 7px; font-size: 28px; letter-spacing: 0; }}
    .subtitle {{ color: var(--muted); max-width: 1040px; font-size: 14px; }}
    main {{ padding: 20px 30px 36px; }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(6, minmax(130px, 1fr));
      gap: 10px;
      margin-bottom: 18px;
    }}
    .metric, .scenario, .step {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
    }}
    .metric {{ padding: 12px 13px; }}
    .metric .label {{ color: var(--muted); font-size: 11px; }}
    .metric .value {{ margin-top: 3px; font-weight: 750; font-size: 20px; overflow-wrap: anywhere; }}
    .scenario {{ margin: 14px 0; overflow: hidden; }}
    .scenario-head {{
      padding: 14px 16px;
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 14px;
      border-bottom: 1px solid var(--line);
      background: #fbfcf8;
    }}
    h2 {{ margin: 0 0 4px; font-size: 18px; }}
    .desc, .small {{ color: var(--muted); font-size: 12px; }}
    .badges {{ display: flex; gap: 7px; flex-wrap: wrap; justify-content: flex-end; }}
    .badge {{
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 4px 8px;
      font-size: 12px;
      background: #fff;
    }}
    .steps {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(285px, 1fr));
      gap: 10px;
      padding: 12px;
    }}
    .step {{ padding: 11px; }}
    .state-row {{
      display: grid;
      grid-template-columns: 1fr auto 1fr;
      align-items: center;
      gap: 7px;
      margin-bottom: 8px;
      font-size: 12px;
    }}
    .state {{
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 7px 8px;
      background: #fff;
      min-height: 34px;
      overflow-wrap: anywhere;
    }}
    .arrow {{ color: var(--muted); }}
    .action {{
      border-left: 3px solid var(--violet);
      padding-left: 9px;
      font-size: 12px;
      margin-top: 8px;
    }}
    .timeline {{
      display: grid;
      gap: 6px;
      margin-top: 8px;
      font-size: 12px;
    }}
    .tag {{
      display: inline-block;
      margin: 2px 4px 0 0;
      padding: 2px 6px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: #fff;
      color: var(--muted);
    }}
    .ok {{ color: var(--green); }}
    .warn {{ color: var(--amber); }}
    .risk {{ color: var(--red); }}
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
    @media (max-width: 980px) {{
      main, header {{ padding-left: 16px; padding-right: 16px; }}
      .metrics {{ grid-template-columns: repeat(2, minmax(130px, 1fr)); }}
      .scenario-head {{ grid-template-columns: 1fr; }}
      .badges {{ justify-content: flex-start; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>Closed-loop Embodied Benchmark</h1>
    <div class="subtitle">
      这份报告评估的不只是单步识别，而是机器人动作执行后对下一步学生线索和环境上下文的反馈：human_state -> robot_action -> embodied feedback -> next human_state。
      后端：{_e(payload.get("backend"))}；策略：{_e(payload.get("policy"))}。
    </div>
  </header>
  <main>
    <section class="metrics">
      {_metric("场景", metrics.get("scenario_count"))}
      {_metric("步数", metrics.get("step_count"))}
      {_metric("动作命中", _pct(metrics.get("action_match_accuracy")))}
      {_metric("恢复率", _pct(metrics.get("recovery_rate")))}
      {_metric("安全违规", metrics.get("safety_violation_count"))}
      {_metric("闭环分", metrics.get("mean_closed_loop_score"))}
    </section>
    <section class="metrics">
      {_metric("状态恢复", metrics.get("recovery_count"))}
      {_metric("风险遏制", metrics.get("risk_containment_count"))}
      {_metric("尊重拒绝", metrics.get("consent_respected_count"))}
      {_metric("停止运动", metrics.get("forced_motion_stop_count"))}
      {_metric("降低难度", metrics.get("difficulty_reduction_count"))}
      {_metric("任务成功", _pct(metrics.get("classroom_task_success_rate")))}
    </section>
    {cards}
    <details>
      <summary>完整 closed-loop JSON</summary>
      <pre>{data_blob}</pre>
    </details>
  </main>
</body>
</html>
"""


def _scenario_card(result: dict[str, Any]) -> str:
    metrics = result["metrics"]
    badges = [
        f"score {metrics['closed_loop_score']}",
        f"recoveries {metrics['recovery_count']}",
        f"risk containment {metrics['risk_containment_count']}",
        f"safety violations {metrics['safety_violation_count']}",
    ]
    return f"""
<section class="scenario">
  <div class="scenario-head">
    <div>
      <h2>{_e(result.get("scenario_id"))}</h2>
      <div class="desc">{_e(result.get("description", ""))}</div>
    </div>
    <div class="badges">{"".join(f'<span class="badge">{_e(badge)}</span>' for badge in badges)}</div>
  </div>
  <div class="steps">{"".join(_step_card(step) for step in result.get("steps", []))}</div>
</section>
"""


def _step_card(step: dict[str, Any]) -> str:
    state = step["human_state"]["state"]
    base_state = step.get("base_ground_truth_state")
    adapted_state = step.get("ground_truth_state")
    action = step["robot_action"]
    feedback = step["embodied_feedback"]
    tags = "".join(f'<span class="tag">{_e(tag)}</span>' for tag in feedback.get("effect_tags", []))
    safety_class = "risk" if step.get("safety_violation") else "ok"
    return f"""
<article class="step">
  <div class="small">step {step.get("step")} | expected {_e(step.get("expected_action_id"))}</div>
  <div class="state-row">
    <div class="state"><span class="small">base</span><br>{_state(base_state)}</div>
    <div class="arrow">-></div>
    <div class="state"><span class="small">after feedback</span><br>{_state(adapted_state)}</div>
  </div>
  <div class="state-row">
    <div class="state"><span class="small">perceived</span><br>{_state(state)}</div>
    <div class="arrow">-></div>
    <div class="state"><span class="small">action</span><br>{_action(action.get("action_id"))}</div>
  </div>
  <div class="timeline">
    <div>outcome: <b>{_e(feedback.get("outcome"))}</b></div>
    <div>motion: {_e(action.get("motion_policy"))} | safety: <span class="{safety_class}">{_e(action.get("safety_action"))}</span></div>
    <div>distance delta: {_e(feedback.get("distance_delta_m"))}</div>
    <div>{tags}</div>
  </div>
  <div class="action">
    speech: {_e(action.get("speech_action"))}<br>
    task: {_e(action.get("task_adjustment"))}<br>
    shield: {_e(action.get("metadata", {}).get("action_shield", "none"))}
  </div>
</article>
"""


def _state(state: Any) -> str:
    return _e(STATE_LABELS.get(str(state), str(state)))


def _action(action_id: Any) -> str:
    return _e(ACTION_LABELS.get(str(action_id), str(action_id)))


def _metric(label: str, value: Any) -> str:
    return f'<div class="metric"><div class="label">{_e(label)}</div><div class="value">{_e(value)}</div></div>'


def _pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "n/a"


def _e(value: Any) -> str:
    return html.escape(str(value), quote=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export a closed-loop embodied benchmark report.")
    parser.add_argument("--scenario-dir", type=Path, default=DEFAULT_SCENARIO_DIR)
    parser.add_argument("--backend", choices=("kinematic", "mujoco"), default="kinematic")
    parser.add_argument("--policy", choices=("rule", "learned"), default="learned")
    parser.add_argument("--model-path", type=Path, default=DEFAULT_LEARNED_POLICY_PATH)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--html-output", type=Path, default=DEFAULT_HTML_OUTPUT)
    parser.add_argument("--smooth-window", type=int, default=1)
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = build_closed_loop_payload(
        scenario_dir=args.scenario_dir,
        backend=args.backend,
        policy=args.policy,
        model_path=args.model_path,
        smooth_window=args.smooth_window,
    )
    export_closed_loop_report(payload, json_output=args.json_output, html_output=args.html_output)
    print(json.dumps(payload, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
