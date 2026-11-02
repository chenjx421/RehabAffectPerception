"""Identity debug log (name-free) and the teacher-friendly video / identity page contracts."""

from __future__ import annotations

import json
import re

import pytest

from rehab_affect.demo2_identity import render_identity
from rehab_affect.demo2_identity_debug import DEBUG_LOG_DIR_ENV, identity_debug_event
from rehab_affect.demo2_video_review import render_video_review
from tests.test_demo2_identity_html import _browser
from tests.test_demo2_identity_store import binding_payload, env, login, make_task, raises_identity, student  # noqa: F401
from tests.test_demo2_portal_html import _run_page_js

TEACHER = {"role": "school_uploader", "username": "school_uploader_01", "login_alias": "t1"}


def _log_lines(folder):
    lines = []
    for path in sorted(folder.glob("identity_debug_*.jsonl")):
        lines.extend(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line)
    return lines


@pytest.fixture()
def log_dir(tmp_path, monkeypatch):
    folder = tmp_path / "identity-logs"
    monkeypatch.setenv(DEBUG_LOG_DIR_ENV, str(folder))
    return folder


def test_debug_event_keeps_only_safe_fields(log_dir):
    entry = identity_debug_event(None, "identity_confirm", "confirmed", task_id="task-1", frame_key="s0_f1",
                                 frame_index=2, role="student", display_name="张三", reason="选错了",
                                 bbox={"x": 0.1}, code="张三.mp4")
    assert entry["operation"] == "identity_confirm" and entry["frame_index"] == 2 and entry["role"] == "student"
    assert entry["code"] == "<invalid>"
    assert "display_name" not in entry and "reason" not in entry and "bbox" not in entry
    assert identity_debug_event(None, "drop_table", "ok")["operation"] == "<invalid>"
    assert identity_debug_event(None, "manual_box", "drawn", role="principal")["role"] == "<invalid>"
    lines = _log_lines(log_dir)
    assert len(lines) == 3 and all(re.match(r"\d{4}-\d{2}-\d{2}T", line["ts"]) for line in lines)
    assert "张三" not in (log_dir.glob("*.jsonl").__next__()).read_text(encoding="utf-8")


def test_confirm_and_revoke_write_frame_position_role_and_status_without_names(env, log_dir):  # noqa: F811
    task = make_task(env, count=3)
    kid = student(env, display_name="日志测试学生")
    payload = binding_payload(task, kid["student_id"], frame_key="s0_f1")
    saved = env.identity.save_binding(task.token, payload)
    raises_identity(409, "duplicate_student_binding", env.identity.save_binding, task.token, payload)
    env.identity.revoke_binding(task.token, {"task_id": task.task_id, "binding_id": saved["binding_id"],
                                            "reason": "日志测试学生框错了"})
    lines = [line for line in _log_lines(log_dir) if line["operation"] in {"identity_confirm", "identity_revoke"}]
    confirm, rejected, revoke = lines
    assert confirm == {**confirm, "operation": "identity_confirm", "result": "confirmed", "task_id": task.task_id,
                       "frame_key": "s0_f1", "frame_index": 2, "role": "student", "binding_id": saved["binding_id"]}
    assert rejected["result"] == "rejected" and rejected["code"] == "duplicate_student_binding"
    assert rejected["http_status"] == 409 and rejected["frame_index"] == 2
    assert revoke["result"] == "revoked" and revoke["frame_index"] == 2 and revoke["role"] == "student"
    text = "".join(path.read_text(encoding="utf-8") for path in log_dir.glob("*.jsonl"))
    assert "日志测试学生" not in text and "框错了" not in text and kid["student_id"] not in text


def test_client_debug_event_is_validated_and_task_scoped(env, log_dir):  # noqa: F811
    task = make_task(env, count=2)
    entry = env.identity.client_debug_event(task.token, {
        "operation": "manual_box", "task_id": task.task_id, "result": "drawn", "frame_key": "s0_f0",
        "frame_index": 1, "frame_total": 2, "box_source": "manual", "candidate_count": 0})
    assert entry["source"] == "client" and entry["operation"] == "manual_box" and entry["frame_index"] == 1
    raises_identity(400, "invalid_debug_event", env.identity.client_debug_event, task.token,
                    {"operation": "manual_box", "task_id": task.task_id, "result": "drawn", "display_name": "张三"})
    raises_identity(400, "invalid_debug_event", env.identity.client_debug_event, task.token,
                    {"operation": "identity_revoke", "task_id": task.task_id, "result": "revoked"})
    raises_identity(400, "invalid_debug_event", env.identity.client_debug_event, task.token,
                    {"operation": "redetect", "task_id": task.task_id, "result": "ok", "frame_index": -1})
    _, other = login(env, "school_uploader_02")
    raises_identity(404, "task_unavailable", env.identity.client_debug_event, other,
                    {"operation": "redetect", "task_id": task.task_id, "result": "requested"})
    assert len([line for line in _log_lines(log_dir) if line.get("source") == "client"]) == 1


@pytest.mark.parametrize("html", [render_identity(TEACHER), render_video_review(TEACHER)])
def test_every_icon_button_has_label_and_tooltip(html):
    buttons = re.findall(r"<button[^>]*class=\"[^\"]*icon-button[^\"]*\"[^>]*>", html)
    assert buttons
    for button in buttons:
        assert 'aria-label="' in button and 'title="' in button, button
    for button in re.findall(r"<button[^>]*class=\"info-tip\"[^>]*>", html):
        assert 'aria-label="' in button and 'title="' in button, button


def test_identity_page_has_three_step_guide_keyboard_hint_and_toast():
    html = render_identity(TEACHER)
    for value in ('id="identityGuide"', "在画面中点选或框选人物", "选择学生姓名", "点击确认",
                  "没有自动找到人物，可点击「手动画框」自己框选", 'aria-keyshortcuts="ArrowLeft"',
                  'aria-keyshortcuts="ArrowRight"', 'id="identityToast"', "已确认：", "/identity/debug-event",
                  "下载身份确认 JSON"):
        assert value in html


def test_video_page_levels_steps_and_folded_boundary():
    html = render_video_review(TEACHER)
    for value in ('id="processSteps"', "已上传", "已解码", "证据已就绪", "待教师复核", "清晰度", "画面变化幅度",
                  'id="sharpnessMetricTip"', 'role="tooltip"', 'id="boundaryFold"', "未生成学生学习结论"):
        assert value in html
    assert re.search(r'<details class="boundary-fold"[^>]*>.*?未生成学生学习结论.*?</details>', html, re.S)


def test_video_levels_and_slice_card_click_seeks_to_start():
    _run_page_js(render_video_review(),
        "replies.push({task:{...baseTask,analysis_status:'evidence_ready'},result:{...evidence,segments:evidence.segments.map((s,i)=>({...s,visual:{...s.visual,mean_sharpness:i===2?794.3:20,mean_brightness:222.9,mean_motion:0}}))}});",
        r"""
        video.readyState=1;video.duration=750;video.hidden=false;let played=0;video.play=()=>{played++;video.paused=false;return Promise.resolve();};
        await $('segments').fire('click',{target:{closest:()=>({dataset:{index:'2'}})}});
        assert.equal(selected,2);assert.equal(video.currentTime,60);assert.equal(played,1);
        assert.equal($('sharpnessMetric').textContent,'清晰');assert.match($('sharpnessMetricTip').textContent,/794\.3/);
        assert.equal($('brightnessMetric').textContent,'偏亮');assert.equal($('motionMetric').textContent,'几乎静止');
        assert.match($('motionMetricTip').textContent,/0\.0000/);
        selectSegment(0);assert.equal($('sharpnessMetric').textContent,'模糊');
        assert.match($('segments').innerHTML,/mini-track/);assert.match($('segments').innerHTML,/left:6\.00%;width:3\.00%/);
        """)


def test_failed_processing_marks_decode_step_as_error():
    _run_page_js(render_video_review(),
        "replies.push({task:{...baseTask,analysis_status:'failed',processing_error:'decode failed'}});",
        r"""
        assert.match($('processSteps').innerHTML,/data-state="done".*已上传/);
        assert.match($('processSteps').innerHTML,/data-state="error"[^]*已解码/);
        """)


def test_browser_no_candidates_manual_box_keyboard_and_debug_events():
    _browser(r"""
    detectionMode='empty';
    await openIdentity();await imageReady();await page.waitForFunction(()=>!document.getElementById('retryDetection').disabled);
    assert.equal(await page.locator('#drawHint').isVisible(),true);
    assert.match(await page.locator('#drawHint').textContent(),/没有自动找到人物，可点击「手动画框」自己框选/);
    assert.ok((await page.locator('#drawButton').getAttribute('class')).includes('attention'));
    assert.equal(await page.locator('#guideStep1').getAttribute('data-state'),'current');
    assert.equal(await page.locator('#guideStep2').getAttribute('data-state'),'todo');
    assert.match(await page.locator('#saveStatus').textContent(),/还差第 1 步/);
    await page.locator('#retryDetection').click();await page.waitForFunction(()=>!document.getElementById('retryDetection').disabled);
    await page.waitForFunction(()=>true);
    await drawDraft();
    assert.equal(await page.locator('#guideStep1').getAttribute('data-state'),'done');
    assert.equal(await page.locator('#guideStep2').getAttribute('data-state'),'current');
    assert.match(await page.locator('#saveStatus').textContent(),/还差第 2 步/);
    await page.locator('#studentSelect').selectOption('s1');
    assert.equal(await page.locator('#guideStep3').getAttribute('data-state'),'current');
    assert.equal(await page.locator('#guideStep3').getAttribute('aria-current'),'step');
    await page.locator('#saveBinding').click();await saved(1);
    assert.equal(await page.locator('#frameSelect').inputValue(),'1');
    assert.match(await page.locator('#toastText').textContent(),/已确认：测试同名（第 1 帧）/);
    await page.locator('#frameViewport').focus();await page.keyboard.press('ArrowLeft');
    assert.equal(await page.locator('#frameSelect').inputValue(),'0');
    await page.keyboard.press('ArrowRight');assert.equal(await page.locator('#frameSelect').inputValue(),'1');
    await imageReady();await page.waitForFunction(()=>!document.getElementById('bindingFields').disabled);
    await page.locator('#studentSearch').focus();await page.keyboard.press('ArrowLeft');assert.equal(await page.locator('#frameSelect').inputValue(),'1');
    await page.waitForFunction(()=>true);
    const events=debugEvents();
    assert.ok(events.some(e=>e.operation==='manual_box'&&e.result==='drawn'&&e.frame_index===1&&e.box_source==='manual'));
    assert.ok(events.some(e=>e.operation==='redetect'&&e.result==='requested'));
    assert.ok(events.some(e=>e.operation==='redetect'&&e.result==='no_candidates'&&e.candidate_count===0));
    assert.ok(events.some(e=>e.operation==='identity_confirm'&&e.result==='confirmed'&&e.box_source==='manual'&&e.role==='student'));
    assert.ok(events.every(e=>e.task_id==='task-1'&&typeof e.frame_total==='number'));
    assert.ok(!JSON.stringify(events).includes('测试同名'));
    const unlabeled=await page.evaluate(()=>[...document.querySelectorAll('button')].filter(b=>!b.textContent.trim()&&!(b.getAttribute('aria-label')&&b.getAttribute('title'))).map(b=>b.id));
    assert.deepEqual(unlabeled,[]);
    """)
