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
            "type": "MetricGrid",
            "columns": 3,
            "metrics": [
                {"label": "人工成本占比",     "field": "kpi.cost_revenue_ratio", "format": "percentage",
                 "sub": "成本 / 营收"},
                {"label": "人均营收",         "field": "kpi.revenue_per_head",
                 "sub": "万元/人"},
                {"label": "成本同比增速",     "field": "kpi.cost_growth_pct", "format": "{value}%",
                 "sub_field": "kpi.revenue_growth_pct", "sub_format": "营收同比 {value}%",
                 "color_rule": "> revenue_growth_pct red"},
            ],
        },
        {
            "type": "LineChartCard",
            "title": "人工成本与营收逐年走势",
            "data_field": "trend",
            "x_field": "year",
            "series": [
                {"label": "营收 (万)",     "field": "revenue", "color": "#2563eb"},
                {"label": "人工成本 (万)", "field": "cost",    "color": "#dc3545"},
            ],
        },
    ],

    "output_schema": {
        "trend": [
            {"year": 2022, "revenue": 200000, "cost": 52000, "headcount": 5200}
        ],
        "kpi": {
            "cost_revenue_ratio": 0.31,
            "revenue_per_head": 38.5,
            "profit_per_head": 8.2,
            "cost_growth_pct": 18.0,
            "revenue_growth_pct": 12.0,
        },
        "current_headcount": 5200,
        "current_total_cost": 520000000,
        "has_trend_data": True,
        "status": "normal",
    },
}
