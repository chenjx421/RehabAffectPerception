from rehab_affect.demo2_measurement import render_measurement


def test_teacher_measurement_page_has_required_views_and_valid_script_contract():
    html = render_measurement({"role": "school_uploader", "username": "synthetic-teacher"})
    assert "逐课" in html and "周汇总" in html and "月汇总" in html and "60天滚动" in html
    assert "评分标准说明" in html and "35%" in html and "6分为参考合格线" in html
    assert "课堂录制" in html and "单次记录报告" in html
    assert html.count("<script") == html.count("</script>") == 1
    assert "j.error?.message" in html
    assert "至少2个维度" not in html
    assert "”" not in html and "“" not in html


def test_company_admin_page_contains_aggregate_only_copy():
    html = render_measurement({"role": "company_admin", "username": "synthetic-admin"})
    assert "仅显示聚合数量" in html
    assert "不含学生姓名、分数或原文" in html
    assert "studentList" not in html
