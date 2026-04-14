"""
Skill: 绩效薪酬关联分析

轻模式。分析绩效等级与薪酬水平的关联度，
检测是否存在"高绩效未获差异化回报"（撒胡椒面式调薪）。
"""

SKILL = {
    "key": "performance_link",
    "display_name": "绩效薪酬关联分析",
    "mode": "light",
    "chip_label": None,

    "triggers": [
        r"绩效.*薪酬",
        r"绩效.*关联",
        r"绩效.*挂钩",
        r"调薪.*绩效",
        r"高绩效.*低绩效",
        r"撒胡椒面",
        r"绩效.*差距",
    ],

    "preconditions": [
        "has_data_snapshot",
        "has_performance_data",
    ],

    "input_params": {
        "scope": {
            "type": "enum",
            "options": ["全公司", "指定部门", "指定职级"],
            "default": "全公司",
            "required": False,
            "resolve": "从用户消息中提取",
        },
    },

    "engine": "app.engine.performance_link.analyze",

    "narrative_prompt": "prompts/performance_insight.txt",

    "render_components": [
        {
            "type": "BarHCard",
            "title": "各绩效等级平均薪酬",
            "bar_label": "rating",
            "bar_value": "avg_salary",
            "color_rule": "同色系渐变，A最深C最浅",
        },
        {
            "type": "MetricGrid",
            "columns": 2,
            "metrics": [
                {"label": "绩效-薪酬相关系数", "field": "summary.correlation", "sub": "<0.3 弱 / 0.3-0.6 中 / >0.6 强", "color_rule": "<0.3 red, 0.3-0.6 orange, >0.6 green"},
                {"label": "A/C 薪酬比", "field": "summary.a_vs_c_ratio", "format": "{value}x"},
            ],
        },
    ],

    "output_schema": {
        "pay_by_rating": [
            {"rating": "A", "headcount": 8, "pct": 16.3, "avg_salary": 32000, "median_salary": 30000}
        ],
        "within_grade_diff": [
            {"grade": "L5", "a_avg": 28000, "b_avg": 26000, "diff_pct": 7.7, "status": "weak"}
        ],
        "summary": {"correlation": 0.31, "a_vs_c_ratio": 1.45, "weak_diff_grades": ["L4", "L5"]},
    },
}
