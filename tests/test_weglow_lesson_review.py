"""Focused checks for the 评课 (lesson review) page and its measurement rubric."""

import re

from rehab_affect.assessment_rubric import DIMENSION_LABELS, DIMENSION_WEIGHTS, RUBRIC_VERSION
from rehab_affect.demo2_evaluation import render_evaluation


def test_lesson_review_page_names_the_lesson_task_not_students():
    html = render_evaluation()
    assert "<h1>评课</h1>" in html
    assert "给整节课评分" in html
    assert "不涉及学生个体能力评分" in html
    assert "本次评课引用的测量口径" in html


def test_lesson_review_page_shows_the_current_measurement_rubric():
    html = render_evaluation()
    assert RUBRIC_VERSION in html
    for label, weight in zip(DIMENSION_LABELS.values(), DIMENSION_WEIGHTS.values()):
        assert f"{label} {round(weight * 100)}%" in html
    assert "观察机会不少于 2 次" in html
    assert "未观察的维度留空" in html
    assert 'href="/demo2/measurement"' in html


def test_shared_navigation_uses_the_short_lesson_review_label():
    html = render_evaluation()
    nav = re.search(r'<nav class="rx-nav".*?</nav>', html, re.S)
    assert nav is not None
    assert "评课" in nav.group(0)
    assert "课程评价" not in nav.group(0)
