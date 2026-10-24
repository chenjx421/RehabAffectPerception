from __future__ import annotations

import argparse
import html
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from .sim_runner import DEFAULT_LEARNED_POLICY_PATH, DEFAULT_SCENARIO_DIR


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = PROJECT_ROOT / "outputs" / "precloud_release_manifest.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "outputs" / "demo_index.html"
DEFAULT_SCENARIO_LAB_URL = "http://127.0.0.1:8787"
DEFAULT_SHOWCASE_SCREENSHOT = PROJECT_ROOT / "outputs" / "playwright" / "classroom_showcase_mujoco.png"
DEFAULT_SHOWCASE_CLOSED_LOOP_SCREENSHOT = (
    PROJECT_ROOT / "outputs" / "playwright" / "classroom_showcase_mujoco_closed_loop.png"
)


def export_demo_index(
    *,
    output: Path = DEFAULT_OUTPUT,
    manifest: dict[str, Any] | None = None,
    manifest_path: Path = DEFAULT_MANIFEST,
    scenario_lab_url: str = DEFAULT_SCENARIO_LAB_URL,
) -> dict[str, Any]:
    payload = build_demo_index_payload(
        manifest=manifest,
        manifest_path=manifest_path,
        scenario_lab_url=scenario_lab_url,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_demo_index_html(payload), encoding="utf-8")
    return {
        "output": str(output),
        "scenario_lab_url": scenario_lab_url,
        "artifact_count": len(payload["artifacts"]),
    }


def build_demo_index_payload(
    *,
    manifest: dict[str, Any] | None = None,
    manifest_path: Path = DEFAULT_MANIFEST,
    scenario_lab_url: str = DEFAULT_SCENARIO_LAB_URL,
) -> dict[str, Any]:
    manifest = manifest or _load_manifest(manifest_path)
    artifacts = manifest.get("artifacts", {})
    live_links = [
        {
            "title": "Education Review Demo",
            "description": "30 日沟通用：课堂切片识别、时间线分析、人物状态库和动作输出。",
            "href": f"{scenario_lab_url}/education_demo",
        },
        {
            "title": "Classroom Showcase",
            "description": "学生端、教师端、仿真课堂和机器人动作输出的一屏展示。",
            "href": f"{scenario_lab_url}/showcase",
        },
        {
            "title": "Scenario Lab",
            "description": "编辑学生线索和机器人上下文，实时调用 Python pipeline。",
            "href": scenario_lab_url,
        },
        {
            "title": "Pain-risk Safety Preset",
            "description": "疼痛风险输入直接触发 stop_motion 和教师交接。",
            "href": f"{scenario_lab_url}?preset=pain",
        },
        {
            "title": "Closed-loop Scenario Lab",
            "description": "整段场景运行：动作反馈到下一步学生状态。",
            "href": f"{scenario_lab_url}?scenario=shape_sorting_confused&loop=1",
        },
    ]
    artifact_cards = [
        _artifact("Demo Index", artifacts.get("demo_index")),
        _artifact("Closed-loop Report", artifacts.get("closed_loop_report")),
        _artifact("Interactive Console", artifacts.get("interactive_console")),
        _artifact("Static Benchmark Demo", artifacts.get("demo_html")),
        _artifact("Final Precloud Report", artifacts.get("final_report")),
        _artifact("Release Manifest", str(manifest_path)),
        _artifact("Training Metrics", artifacts.get("training_metrics")),
        _artifact("Closed-loop JSON", artifacts.get("closed_loop_benchmark")),
        _artifact("Policy Comparison", artifacts.get("policy_comparison")),
        _artifact("Robustness Eval", artifacts.get("robustness_eval")),
        _artifact("WebSocket JSONL", artifacts.get("websocket_sample")),
        _artifact("ROS2 Mock JSONL", artifacts.get("ros2_mock_messages")),
    ]
    screenshots = [
        _screenshot("Classroom Showcase", artifacts.get("classroom_showcase_screenshot")),
        _screenshot(
            "Classroom Closed Loop",
            artifacts.get("classroom_showcase_closed_loop_screenshot"),
        ),
        _screenshot("Scenario Lab", artifacts.get("scenario_lab_screenshot")),
        _screenshot("Pain-risk Action", artifacts.get("scenario_lab_pain_risk_screenshot")),
        _screenshot("Closed-loop Trajectory", artifacts.get("scenario_lab_closed_loop_screenshot")),
        _screenshot("Benchmark Console", artifacts.get("interactive_console_screenshot")),
        _screenshot("MuJoCo Contact Sheet", artifacts.get("mujoco_contact_sheet")),
        _screenshot("Static Demo", artifacts.get("demo_screenshot")),
    ]
    return {
        "project": manifest.get("project", "RehabAffectPerception"),
        "release": manifest.get("release", "local"),
        "positioning": manifest.get("positioning", ""),
        "training": manifest.get("training", {}),
        "benchmark": manifest.get("benchmark", {}),
        "closed_loop": manifest.get("closed_loop", {}),
        "robustness": manifest.get("robustness", {}),
        "live_links": live_links,
        "artifacts": [card for card in artifact_cards if card["path"]],
        "screenshots": [shot for shot in screenshots if shot["path"]],
    }


def start_scenario_lab_if_needed(
    *,
    host: str = "127.0.0.1",
    port: int = 8787,
    scenario_dir: Path = DEFAULT_SCENARIO_DIR,
    model_path: Path = DEFAULT_LEARNED_POLICY_PATH,
    policy: str = "learned",
    startup_timeout_sec: float = 8.0,
) -> dict[str, Any]:
    url = f"http://{host}:{port}"
    if _service_ok(f"{url}/api/health"):
        return {"started": False, "url": url, "reason": "already_running"}

    log = PROJECT_ROOT / "outputs" / "scenario_lab_server.log"
    err = PROJECT_ROOT / "outputs" / "scenario_lab_server.err.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("ab") as stdout, err.open("ab") as stderr:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "src.rehab_affect.scenario_lab_server",
                "--host",
                host,
                "--port",
                str(port),
                "--scenario-dir",
                str(scenario_dir),
                "--model-path",
                str(model_path),
                "--policy",
                policy,
            ],
            cwd=PROJECT_ROOT,
            stdout=stdout,
            stderr=stderr,
        )

    deadline = time.time() + startup_timeout_sec
    while time.time() < deadline:
        if _service_ok(f"{url}/api/health"):
            return {"started": True, "url": url, "pid": process.pid}
        time.sleep(0.25)
    return {"started": True, "url": url, "pid": process.pid, "warning": "health_check_timeout"}


def _service_ok(url: str) -> bool:
    try:
        with urlopen(url, timeout=0.6) as response:
            return response.status == 200
    except Exception:
        return False


def _load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "project": "RehabAffectPerception",
            "release": "manifest_missing",
            "artifacts": {},
        }
    return json.loads(path.read_text(encoding="utf-8"))


def _artifact(title: str, path: str | None) -> dict[str, str | None]:
    return {
        "title": title,
        "path": path,
        "href": _href(path),
        "exists": str(_exists(path)),
    }


def _screenshot(title: str, path: str | None) -> dict[str, str | None]:
    return {
        "title": title,
        "path": path,
        "href": _href(path),
        "exists": str(_exists(path)),
    }


def _href(path: str | None) -> str | None:
    if not path:
        return None
    try:
        candidate = Path(path)
        if candidate.is_absolute():
            return candidate.as_uri()
    except (OSError, ValueError):
        return path
    return path.replace("\\", "/")


def _exists(path: str | None) -> bool:
    if not path:
        return False
    try:
        return Path(path).exists()
    except (OSError, ValueError):
        return False


def render_demo_index_html(payload: dict[str, Any]) -> str:
    training = payload.get("training", {})
    benchmark = payload.get("benchmark", {})
    closed_loop = payload.get("closed_loop", {})
    links = "\n".join(_live_link_card(link) for link in payload["live_links"])
    artifacts = "\n".join(_artifact_card(card) for card in payload["artifacts"])
    screenshots = "\n".join(_screenshot_card(shot) for shot in payload["screenshots"])
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>RehabAffectPerception Demo Index</title>
  <style>
    :root {{
      --bg: #f6f7f2;
      --panel: #fff;
      --ink: #14201a;
      --muted: #607068;
      --line: #d7dfd1;
      --blue: #2563eb;
      --green: #16783a;
      --red: #c24135;
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
      background: #fff;
      border-bottom: 1px solid var(--line);
      padding: 26px 30px 18px;
    }}
    h1 {{ margin: 0 0 6px; font-size: 28px; letter-spacing: 0; }}
    .subtitle {{ color: var(--muted); max-width: 1080px; font-size: 14px; }}
    main {{ padding: 20px 30px 38px; display: grid; gap: 20px; }}
    .metrics, .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
      gap: 10px;
    }}
    .metric, .card, .shot {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 13px;
      min-width: 0;
    }}
    .metric .label, .small {{ color: var(--muted); font-size: 12px; }}
    .metric .value {{ margin-top: 4px; font-size: 22px; font-weight: 750; }}
    h2 {{ margin: 0 0 10px; font-size: 18px; }}
    h3 {{ margin: 0 0 5px; font-size: 15px; }}
    a {{ color: var(--blue); text-decoration: none; overflow-wrap: anywhere; }}
    .path {{ color: var(--muted); font-size: 11px; overflow-wrap: anywhere; }}
    .ok {{ color: var(--green); }}
    .missing {{ color: var(--red); }}
    .shot img {{
      width: 100%;
      max-height: 230px;
      object-fit: contain;
      display: block;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #f8faf5;
      margin-top: 8px;
    }}
    @media (max-width: 760px) {{
      header, main {{ padding-left: 16px; padding-right: 16px; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>{_e(payload.get("project"))} Demo Index</h1>
    <div class="subtitle">
      面向辅读学校辅助机器人的具身学生状态感知与动作决策演示入口。release: {_e(payload.get("release"))}
    </div>
  </header>
  <main>
    <section>
      <h2>Key Metrics</h2>
      <div class="metrics">
        {_metric("训练样本", training.get("row_count"))}
        {_metric("holdout 动作准确率", _pct(training.get("holdout_action_accuracy")))}
        {_metric("MuJoCo 动作命中", _pct(benchmark.get("action_match_accuracy")))}
        {_metric("闭环动作命中", _pct(closed_loop.get("action_match_accuracy")))}
        {_metric("闭环状态恢复", closed_loop.get("recovery_count"))}
        {_metric("安全违规", closed_loop.get("safety_violation_count", benchmark.get("safety_violation_count")))}
      </div>
    </section>
    <section>
      <h2>Live Entrypoints</h2>
      <div class="grid">{links}</div>
    </section>
    <section>
      <h2>Artifacts</h2>
      <div class="grid">{artifacts}</div>
    </section>
    <section>
      <h2>Screenshots</h2>
      <div class="grid">{screenshots}</div>
    </section>
  </main>
</body>
</html>
"""


def _live_link_card(link: dict[str, str]) -> str:
    return f"""
<article class="card">
  <h3>{_e(link["title"])}</h3>
  <div class="small">{_e(link["description"])}</div>
  <a href="{_e(link["href"])}">{_e(link["href"])}</a>
</article>
"""


def _artifact_card(card: dict[str, str | None]) -> str:
    status_class = "ok" if card["exists"] == "True" else "missing"
    status = "exists" if card["exists"] == "True" else "missing"
    href = card["href"] or "#"
    return f"""
<article class="card">
  <h3><a href="{_e(href)}">{_e(card["title"])}</a></h3>
  <div class="{status_class} small">{status}</div>
  <div class="path">{_e(card.get("path"))}</div>
</article>
"""


def _screenshot_card(shot: dict[str, str | None]) -> str:
    status_class = "ok" if shot["exists"] == "True" else "missing"
    status = "exists" if shot["exists"] == "True" else "missing"
    href = shot["href"] or "#"
    image = f'<img src="{_e(href)}" alt="{_e(shot["title"])}">' if shot["exists"] == "True" else ""
    return f"""
<article class="shot">
  <h3><a href="{_e(href)}">{_e(shot["title"])}</a></h3>
  <div class="{status_class} small">{status}</div>
  {image}
</article>
"""


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
    parser = argparse.ArgumentParser(description="Build a local demo index and optionally start Scenario Lab.")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--scenario-lab-url", default=DEFAULT_SCENARIO_LAB_URL)
    parser.add_argument("--start-scenario-lab", action="store_true")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--scenario-dir", type=Path, default=DEFAULT_SCENARIO_DIR)
    parser.add_argument("--model-path", type=Path, default=DEFAULT_LEARNED_POLICY_PATH)
    parser.add_argument("--policy", choices=("rule", "learned"), default="learned")
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    service: dict[str, Any] | None = None
    scenario_lab_url = args.scenario_lab_url
    if args.start_scenario_lab:
        service = start_scenario_lab_if_needed(
            host=args.host,
            port=args.port,
            scenario_dir=args.scenario_dir,
            model_path=args.model_path,
            policy=args.policy,
        )
        scenario_lab_url = service["url"]
    result = export_demo_index(
        output=args.output,
        manifest_path=args.manifest,
        scenario_lab_url=scenario_lab_url,
    )
    if service is not None:
        result["scenario_lab_service"] = service
    print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
