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
                {"label": "离散度偏高层级数", "field": "summary.high_dispersion_count",
                 "sub_field": "summary.total_groups", "sub_format": "共 {value} 个层级"},
                {"label": "最高离散系数",       "field": "summary.max_cv",
                 "sub_field": "summary.max_cv_grade", "sub_format": "{value} 层级",
                 "color_rule": ">0.30 red, 0.20-0.30 orange, <0.20 green"},
                {"label": "最大极差比",         "field": "summary.max_range_ratio", "format": "{value}x",
                 "sub_field": "summary.max_range_ratio_grade", "sub_format": "{value} 层级"},
            ],
        },
        {
            "type": "BoxPlotCard",
            "title": "各层级薪酬分布",
            "data_field": "boxplot",
            "x_field": "grade",
            "footer": "盒子 = P25-P75（中间 50% 员工）· 中线 = P50",
        },
    ],

    "output_schema": {
        "dispersion": [
            {"grade": "L5", "count": 8, "mean": 25000, "min": 18000, "max": 38000,
             "coefficient": 0.42, "range_ratio": 2.11, "status": "high"}
        ],
        "boxplot": [
            {"grade": "L5", "min": 18000, "q1": 22000, "median": 25000, "q3": 32000, "max": 38000}
        ],
        "summary": {
            "total_groups": 8, "high_dispersion_count": 2,
            "max_cv_grade": "L5", "max_cv": 0.42,
            "max_range_ratio_grade": "L5", "max_range_ratio": 2.11,
        },
    },
}
