from rehab_affect.demo2_measurement import render_measurement


def test_teacher_measurement_page_has_required_views_and_valid_script_contract():
    html = render_measurement({"role": "school_uploader", "username": "synthetic-teacher"})
    assert "逐课" in html and "周汇总" in html and "月汇总" in html and "60天滚动" in html
    assert "评分标准说明" in html and "35%" in html and "6分为参考合格线" in html
    assert "课堂录制" in html and "单次记录报告" in html
    # One page script plus the shared, tagged interface-kit script.
    assert html.count("<script>") == 1 and html.count("<script data-rx-kit>") == 1
    assert html.count("<script") == html.count("</script>") == 2
    assert "j.error?.message" in html
    assert "至少2个维度" not in html
    assert "”" not in html and "“" not in html


def test_company_admin_page_contains_aggregate_only_copy():
    html = render_measurement({"role": "company_admin", "username": "synthetic-admin"})
    assert "仅显示聚合数量" in html
    assert "不含学生姓名、分数或原文" in html
    assert "studentList" not in html


def test_record_row_inline_handlers_escape_json_quotes():
    html = render_measurement({"role": "school_uploader", "username": "synthetic-teacher"})
    # JSON.stringify emits double quotes; inside a double-quoted onclick attribute
    # they must be HTML-escaped or the handler is cut off ("Unexpected end of input").
    assert 'onclick="editRecord(${JSON.stringify(' not in html
    assert 'onclick="promptWithdraw(${JSON.stringify(' not in html
    assert 'onclick="editRecord(${esc(JSON.stringify(r.record_id))})"' in html
    assert 'onclick="promptWithdraw(${esc(JSON.stringify(r.record_id))},${Number(r.version)})"' in html


def test_measurement_page_redesign_contract():
    html = render_measurement({"role": "school_uploader", "username": "synthetic-teacher"})
    # Global portal CSS shrinks every <svg> to 20px; the trend chart must override it.
    assert "svg.chart-svg{display:block;width:100%;height:auto;min-height:280px" in html
    assert "至少需要 2 次已复核记录才能看趋势" in html and "trend_insufficient" in html
    for section in ("课堂信息", "目标与条件", "四维评分", "观察次数与复核"):
        assert section in html
    assert 'class="sec-no"' in html and "未观察" in html and 'type="range"' in html
    assert 'id="studentSearch"' in html and "rx-avatar" in html and "rx-kpi" in html
    assert "无障碍数据表格" in html and "dim-ring" in html and "point-list" in html
    # Print view hides navigation and every control.
    assert ".rx-header" in html.split("@media print{", 1)[1].split("}", 1)[0]
    assert "button,select,nav{display:none!important;}" in html
