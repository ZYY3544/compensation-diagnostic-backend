"""
Skill: 外部市场对标

轻模式。查询指定部门/职级/职能的薪酬在市场中的分位值。
用户问"研发 L5 跟市场比怎么样"就触发这个。
"""

SKILL = {
    "key": "external_benchmark",
    "display_name": "外部市场对标",
    "mode": "light",
    "chip_label": "🔍 查一下市场薪酬水平",

    "triggers": [
        r"市场.*对标",
        r"跟市场.*比",
        r"市场.*水平",
        r"薪酬.*竞争力",
        r"P\d+",
        r"分位",
        r"有没有竞争力",
        r"比市场.*高|低",
        r"外部.*竞争",
    ],

    "preconditions": [
        "has_data_snapshot",
        "has_market_data",
    ],

    "input_params": {
        "scope": {
            "type": "enum",
            "options": ["全公司", "指定部门", "指定职级", "指定职能"],
            "default": "全公司",
            "required": False,
            "resolve": "从用户消息中提取，提取不到默认全公司",
        },
        "department": {
            "type": "string",
            "required": False,
            "resolve": "从用户消息中提取部门名称",
            "example": "研发",
        },
        "grade": {
            "type": "string",
            "required": False,
            "resolve": "从用户消息中提取职级",
            "example": "L5",
        },
        "function": {
            "type": "string",
            "required": False,
            "resolve": "从用户消息中提取职能",
            "example": "软件开发",
        },
    },

    "engine": "app.engine.external_competitiveness.analyze",

    "narrative_prompt": "prompts/benchmark_insight.txt",

    "render_components": [
        {
            "type": "MetricGrid",
            "columns": 3,
            "metrics": [
                {"label": "整体市场分位", "field": "summary.avg_percentile", "format": "P{value}", "color_rule": "<25 red, 25-50 orange, >50 green"},
                {"label": "低于P25人数", "field": "summary.below_p25_count", "sub_field": "summary.below_p25_pct", "sub_format": "占比 {value}%"},
                {"label": "分析人数", "field": "summary.total_headcount"},
            ],
        },
        {
            "type": "BarHCard",
            "title": "各层级市场分位值",
            "group_by": "department",
            "bar_label": "grade",
            "bar_value": "percentile",
            "bar_max": 100,
            "marker": 50,
            "color_rule": "<25 red, 25-50 orange, >50 green",
            "footer": "竖线 = 市场 P50 · 低于 P25 标红",
        },
    ],

    "output_schema": {
        "benchmark_results": [
            {
                "grade": "L5",
                "function": "软件开发",
                "headcount": 8,
                "company_median": 300000,
                "market_p25": 336000,
                "market_p50": 420000,
                "market_p75": 528000,
                "percentile": 23,
                "gap_to_p50": -120000,
                "status": "below_p25",
            }
        ],
        "summary": {
            "total_headcount": 49,
            "below_p25_count": 22,
            "below_p25_pct": 44.9,
            "avg_percentile": 38,
        },
    },
}
