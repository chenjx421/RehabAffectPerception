from __future__ import annotations

import re

import pytest

from rehab_affect.demo2_portal import render_demo2_page_error_html

TEACHER = {"account_id": "acct-1", "username": "school_uploader_01", "role": "school_uploader"}
ADMIN = {"account_id": "acct-9", "username": "company_admin", "role": "company_admin"}


@pytest.mark.parametrize("status,code,title", [
    (403, "student_forbidden", "你没有查看此内容的权限"),
    (404, "student_unavailable", "内容不存在或已被删除"),
    (400, "invalid_request", "链接参数有误"),
])
def test_page_error_shows_chinese_text_and_original_code(status, code, title):
    html = render_demo2_page_error_html(status, code, TEACHER, back_href="/demo2/students", back_label="返回学生名册")
    assert f"<title>WeGlow微光系统 · {title}</title>" in html
    assert f"错误码：{status} · {code}" in html
    assert 'href="/demo2/students"' in html and "返回学生名册" in html
    assert 'data-rx-scope="teacher"' in html or "教师工作台导航" in html
    assert '"ok": false' not in html


def test_page_error_code_is_sanitised_and_admin_gets_admin_nav():
    html = render_demo2_page_error_html(403, "<script>x</script>", ADMIN, back_href="/demo2/admin#taskQueryTitle",
                                        back_label="前往任务查询")
    assert "<script>x" not in html and "错误码：403 · scriptxscript" in html
    assert "公司后台导航" in html and "前往任务查询" in html


def test_page_error_unknown_status_has_generic_text_and_small_radius():
    html = render_demo2_page_error_html(418, "", TEACHER)
    assert "页面暂时无法打开" in html and "错误码：418 · error" in html
    assert all(int(value) <= 8 for value in re.findall(r"border-radius:\s*(\d+)px", html))
    assert "http://" not in html


def test_page_error_503_keeps_code_and_hides_internal_message():
    html = render_demo2_page_error_html(503, "vault_unavailable", TEACHER, back_href="/demo2/students",
                                        back_label="返回学生名册")
    assert "服务暂时不可用，请稍后重试" in html and "错误码：503 · vault_unavailable" in html
    assert "加密服务" not in html
