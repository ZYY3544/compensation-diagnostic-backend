"""
Skill: 内部公平性分析

轻模式。分析同职级同部门内的薪酬离散度、极差比、CR值分布、上下级倒挂。
"""

SKILL = {
    "key": "internal_equity",
    "display_name": "内部公平性分析",
    "mode": "light",
    "chip_label": None,  # 不在首屏展示

    "triggers": [
        r"内部.*公平",
        r"同岗不同酬",
        r"薪酬.*差距",
        r"离散度",
        r"CR值",
        r"倒挂",
        r"内部.*差距",
        r"同级别.*差距",
    ],

    "preconditions": [
        "has_data_snapshot",
    ],

    "input_params": {
        "scope": {
            "type": "enum",
            "options": ["全公司", "指定部门", "指定职级"],
            "default": "全公司",
            "required": False,
            "resolve": "从用户消息中提取",
        },
        "department": {
            "type": "string",
            "required": False,
            "resolve": "从用户消息中提取",
        },
        "grade": {
            "type": "string",
            "required": False,
            "resolve": "从用户消息中提取",
        },
    },

    "engine": "app.engine.internal_equity.analyze",

    "narrative_prompt": "prompts/equity_insight.txt",

    "render_components": [
        {
            "type": "MetricGrid",
            "columns": 3,
            "metrics": [
                {"label": "最异常组离散系数", "field": "worst_group.cv", "sub": "正常范围 0.15-0.25", "color_rule": ">0.25 red, 0.20-0.25 orange, <0.20 green"},
                {"label": "最异常组极差比", "field": "worst_group.max_min_ratio", "format": "{value}x", "sub_field": "worst_group.range_display"},
                {"label": "薪酬倒挂", "field": "summary.inversion_count", "format": "{value} 对"},
            ],
        },
        {
            "type": "BoxPlotCard",
            "title": "各层级薪酬分布",
            "group_by": "grade",
            "value_field": "monthly_base_salary",
            "highlight_rule": "cv > 0.25 标红",
            "footer": "色块宽度 = 薪酬分布范围 · 竖线 = 中位值",
        },
    ],

    "output_schema": {
        "equity_by_group": [
            {"grade": "L5", "department": "研发", "headcount": 8, "median": 25000, "max": 38000, "min": 18000, "cv": 0.42, "max_min_ratio": 2.11, "status": "abnormal"}
        ],
        "inversions": [
            {"subordinate_id": "E006", "subordinate_salary": 38000, "manager_id": "E043", "manager_salary": 35000}
        ],
        "summary": {"abnormal_groups": 2, "total_groups": 8, "inversion_count": 2, "avg_cv": 0.24},
    },
}
