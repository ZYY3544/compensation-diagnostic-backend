"""
Skill: 薪酬结构分析

轻模式。分析各部门/职级的固浮比（固定薪酬 vs 浮动薪酬 vs 津贴）构成是否合理。
"""

SKILL = {
    "key": "pay_mix_check",
    "display_name": "薪酬结构分析",
    "mode": "light",
    "chip_label": None,

    "triggers": [
        r"固浮比",
        r"薪酬结构",
        r"固定.*浮动",
        r"工资结构",
        r"基本工资.*奖金.*比例",
        r"pay.?mix",
    ],

    "preconditions": ["has_data_snapshot"],

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
    },

    "engine": "app.engine.pay_mix.analyze",

    "narrative_prompt": "prompts/pay_mix_insight.txt",

    "render_components": [
        {
            "type": "StackedBarCard",
            "title": "各部门薪酬结构",
            "group_by": "department",
            "segments": ["固定", "浮动", "津贴"],
            "colors": ["blue", "orange", "gray"],
            "show_percentage": True,
        },
        {
            "type": "MetricGrid",
            "columns": 2,
            "metrics": [
                {"label": "全公司固定占比", "field": "summary.company_avg_fixed_ratio", "format": "percentage"},
                {"label": "全公司浮动占比", "field": "summary.company_avg_variable_ratio", "format": "percentage"},
            ],
        },
    ],

    "output_schema": {
        "pay_mix_by_group": [
            {"grade": "L5", "department": "研发", "headcount": 8, "avg_base": 300000, "avg_bonus": 60000, "avg_allowance": 24000, "fixed_ratio": 0.78, "variable_ratio": 0.16, "allowance_ratio": 0.06, "status": "normal"}
        ],
        "summary": {
            "company_avg_fixed_ratio": 0.72,
            "company_avg_variable_ratio": 0.22,
            "warnings": ["销售固定占比偏高(82%)，浮动激励不足"],
        },
    },
}
