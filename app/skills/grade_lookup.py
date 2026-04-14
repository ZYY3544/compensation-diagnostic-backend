"""
Skill: 市场薪酬查询

轻模式。纯查询，不需要用户上传数据。
查某个职能+职级+城市的市场薪酬分位值。
"""

SKILL = {
    "key": "grade_lookup",
    "display_name": "市场薪酬查询",
    "mode": "light",
    "chip_label": None,

    "triggers": [
        r".*多少钱$",
        r".*市场.*薪酬$",
        r".*行情",
        r".*什么水平$",
        r"市场价",
        r"薪资范围",
    ],

    "preconditions": [
        "has_market_data",
    ],

    "input_params": {
        "function": {
            "type": "string",
            "required": True,
            "resolve": "从用户消息中提取岗位/职能名称，映射到标准职能",
            "example": "软件开发",
        },
        "grade": {
            "type": "string",
            "required": True,
            "resolve": "从用户消息中提取职级",
            "example": "L5",
        },
        "city": {
            "type": "string",
            "required": False,
            "default": "全国",
            "resolve": "从用户消息中提取，没有就用全国",
        },
    },

    "engine": "app.engine.grade_lookup.query",

    "narrative_prompt": "prompts/lookup_insight.txt",

    "render_components": [
        {
            "type": "MetricGrid",
            "columns": 5,
            "metrics": [
                {"label": "P10", "field": "lookup.p10", "format": "currency"},
                {"label": "P25", "field": "lookup.p25", "format": "currency"},
                {"label": "P50", "field": "lookup.p50", "format": "currency", "highlight": True},
                {"label": "P75", "field": "lookup.p75", "format": "currency"},
                {"label": "P90", "field": "lookup.p90", "format": "currency"},
            ],
            "footer": "样本量 {lookup.sample_size} · 数据周期 {lookup.data_period}",
        },
    ],

    "output_schema": {
        "lookup": {
            "function": "软件开发",
            "standard_grade": "高级专业人员",
            "city": "深圳",
            "p10": 20000, "p25": 28000, "p50": 35000, "p75": 45000, "p90": 58000,
            "sample_size": 1240,
            "data_period": "2025 Q1",
        },
    },
}
