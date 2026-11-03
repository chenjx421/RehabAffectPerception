from rehab_affect.demo2_long_term import render_long_term
from rehab_affect.demo2_lesson_workbench import render_lesson


ACCOUNT = {'username': 'school_uploader_01', 'login_alias': 't1'}


def test_long_term_page_shows_iep_status_and_timeline():
    work = {
        'students': [{'student_id': 's1', 'display_name': '左', 'student_code': 'L', 'class_name': '音乐课'}],
        'records': [{'student_id': 's1', 'lesson_date': '2026-10-30', 'task_id': 't1', 'course_name': '松江音乐课',
                     'goal_id': 'G-01', 'source_type': 'classroom_observation', 'reviewed': True,
                     'scores': {'accuracy': 7, 'independence': 7, 'consistency': 6, 'transfer': 6},
                     'assessment': {'score': 6.65}}],
    }
    page = render_long_term(ACCOUNT, 'token', 's1', work, {'status': 'not_found', 'reason': 'iep_not_found'})
    assert '长期观测' in page and '尚未上传 IEP' in page
    assert '松江音乐课' in page and 'G-01' in page and '6.65' in page
    assert '长期观测只汇总教师复核记录' in page


def test_workbench_has_four_steps_and_links():
    work = {
        'course_name': '松江音乐课', 'course_id': 'music', 'school_context': {'school_name': '辅读学校'},
        'summary': {'students': 3, 'records': 3, 'reviewed': 3, 'scored': 3},
        'media': {'duration_sec': 2223}, 'report': {'ready': True},
        'people': [{'student_id': 's1', 'display_name': '左', 'iep_context': {'status': 'available'}}],
    }
    page = render_lesson(ACCOUNT, 'task-1', work, [{'record_id': 'e1'}])
    for label in ('视频与学生身份', '学生测量', '本课评课', '课堂报告'):
        assert label in page
    assert '/demo2/long-term?student_id=s1' in page
    assert '/demo2/evaluation?task_id=task-1' in page
    assert 'IEP 1/1' in page
