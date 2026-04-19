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
            "type": "MetricGrid",
            "columns": 2,
            "metrics": [
                {"label": "全公司固定占比", "field": "overall_fix_pct", "format": "{value}%",
                 "color_rule": ">85 orange, <60 orange"},
                {"label": "全公司浮动占比", "field": "overall_var_pct", "format": "{value}%"},
            ],
        },
        {
            "type": "BarHCard",
            "title": "各部门固定薪酬占比",
            "data_field": "pay_mix_by_dept",
            "bar_label": "department",
            "bar_value": "fix_pct",
            "bar_max": 100,
            "marker": 70,
            "color_rule": ">85 orange, 60-85 green, <60 red",
            "footer": "竖线 = 70%（行业典型固定占比参考）",
        },
    ],

    "output_schema": {
        "pay_mix_by_grade": [
            {"grade": "L5", "headcount": 8, "fix_pct": 78, "var_pct": 22}
        ],
        "pay_mix_by_dept": [
            {"department": "研发", "headcount": 12, "fix_pct": 78, "var_pct": 22}
        ],
        "overall_fix_pct": 75,
        "overall_var_pct": 25,
        "status": "normal",
    },
}
