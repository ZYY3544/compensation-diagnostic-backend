"""
Skill: 人工成本趋势分析

轻模式。基于 Sheet 2 经营数据，分析人工成本占比、人效、增速趋势。
"""

SKILL = {
    "key": "cost_trend",
    "display_name": "人工成本趋势分析",
    "mode": "light",
    "chip_label": None,

    "triggers": [
        r"人工成本",
        r"人效",
        r"人均.*营收",
        r"人均.*成本",
        r"成本.*增速",
        r"成本.*占比",
        r"人力成本",
    ],

    "preconditions": [
        "has_data_snapshot",
        "has_business_data",
    ],

    "input_params": {},  # 直接用 Sheet 2 数据，不需要额外参数

    "engine": "app.engine.cost_trend.analyze",

    "narrative_prompt": "prompts/cost_trend_insight.txt",

    "render_components": [
        {
            "type": "LineChartCard",
            "title": "人工成本 vs 营收增长趋势",
            "lines": [
                {"label": "营收增速", "field": "yearly.revenue_growth", "color": "blue"},
                {"label": "人工成本增速", "field": "yearly.labor_cost_growth", "color": "red"},
            ],
            "x_axis": "year",
        },
        {
            "type": "MetricGrid",
            "columns": 3,
            "metrics": [
                {"label": "最新人工成本占比", "field": "summary.latest_cost_ratio", "format": "percentage"},
                {"label": "营收年复合增速", "field": "summary.revenue_cagr", "format": "percentage"},
                {"label": "人工成本年复合增速", "field": "summary.labor_cost_cagr", "format": "percentage", "color_rule": "> revenue_cagr red"},
            ],
        },
    ],

    "output_schema": {
        "yearly": [
            {"year": 2022, "revenue": 2e9, "headcount": 5200, "labor_cost": 5.2e8, "cost_ratio": 0.26, "per_capita_revenue": 384615}
        ],
        "summary": {
            "revenue_cagr": 0.12,
            "labor_cost_cagr": 0.18,
            "cost_exceeds_revenue": True,
            "latest_cost_ratio": 0.31,
            "trend": "deteriorating",
        },
    },
}
