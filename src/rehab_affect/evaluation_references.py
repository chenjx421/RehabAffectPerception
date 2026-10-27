"""Authoritative references behind the classroom evaluation dimensions.

These sources explain where the rubric dimensions and support language come
from.  They are not evidence that the enhanced track has been validated; the
10% adjustment remains a conservative pilot choice that needs school
calibration.
"""

from copy import deepcopy

REFERENCES = [
    dict(
        id="moe_2016_curriculum",
        title="《培智学校义务教育课程标准（2016年版）》",
        issuer="教育部",
        year="2016",
        url="http://www.moe.gov.cn:8080/srcsite/A06/s3331/201612/t20161213_291722.html",
        scope="课程目标、内容与教学建议",
        note="评分维度关注分层目标、生活适应与支持条件，与该课标的课程理念一致。",
    ),
    dict(
        id="moe_2007_curriculum_plan",
        title="《培智学校义务教育课程设置实验方案》",
        issuer="教育部",
        year="2007",
        url="https://hudong.moe.gov.cn/srcsite/A06/s3331/200702/t20070202_128271.html",
        scope="课程结构与课时安排",
        note="用于解释课程类型与学科差异，不直接决定分值。",
    ),
    dict(
        id="who_icf_cy",
        title="ICF-CY：儿童和青少年国际功能、残疾和健康分类",
        issuer="世界卫生组织（WHO）",
        year="2007",
        url="https://www.who.int/news/item/23-10-2007-who-publishes-new-standard-for-documenting-the-health-of-children-and-youth",
        scope="功能与支持需求描述",
        note="只用于支持需求的表述口径，不用于打分，也不用于诊断。",
    ),
    dict(
        id="school_rubric",
        title="学校课堂教学基本评价指标（100 分原表）",
        issuer="学校提供",
        year="",
        url="",
        scope="学校轨评分表",
        note="学校原始量表；学校轨评分以该表为准，系统不改动其权重。",
    ),
]

NOTE = (
    "参考资料只说明评分维度与表述口径的来源；增强轨为试行规则，"
    "10% 调整为保守工程值，须校方校准，不等于已验证的教学效果。"
)


def catalog() -> dict:
    return {"version": "2026-10-27.references-v1", "items": deepcopy(REFERENCES), "note": NOTE}
