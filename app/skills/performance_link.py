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
            "type": "MetricGrid",
            "columns": 2,
            "metrics": [
                {"label": "A vs C 薪酬比",   "field": "a_vs_c_ratio", "format": "{value}x",
                 "sub": "<1.2 撒胡椒面 / >1.5 区分度强",
                 "color_rule": "<1.2 red, 1.2-1.5 orange, >1.5 green"},
                {"label": "A vs B 差距",     "field": "a_vs_b_gap_pct", "format": "{value}%",
                 "sub": "<10% 差距过小",
                 "color_rule": "<10 red, 10-20 orange, >20 green"},
            ],
        },
        {
            "type": "BarHCard",
            "title": "各绩效等级平均年度总现金",
            "data_field": "tcc_by_perf",
            "bar_label": "grade",
            "bar_value": "avg_tcc",
            "color_rule": "同色系渐变，A 最深 C 最浅",
        },
    ],

    "output_schema": {
        "perf_stats": [
            {"rating": "A", "count": 8, "avg_base": 28000, "median_base": 27000}
        ],
        "tcc_by_perf": [
            {"grade": "A", "avg_tcc": 380000, "count": 8}
        ],
        "a_vs_c_ratio": 1.45,
        "a_vs_b_gap_pct": 7.7,
        "spread_adequate": False,
        "has_data": True,
        "status": "attention",
    },
}
