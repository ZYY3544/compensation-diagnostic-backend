"""
Skill: 调薪预算模拟

轻模式。根据目标分位值，模拟调薪所需预算，支持统一调整和分层调整两种方案对比。
"""

SKILL = {
    "key": "salary_simulation",
    "display_name": "调薪预算模拟",
    "mode": "light",
    "chip_label": "💰 调薪预算怎么分配",

    "triggers": [
        r"调薪.*预算",
        r"调到P\d+.*多少钱",
        r"调薪.*模拟",
        r"涨薪.*成本",
        r"调整.*需要多少",
        r"预算.*怎么分",
        r"调到.*分位.*要多少",
    ],

    "preconditions": [
        "has_data_snapshot",
        "has_market_data",
    ],

    "input_params": {
        "scope": {
            "type": "enum",
            "options": ["全公司", "指定部门", "指定职级"],
            "required": False,
            "default": "全公司",
            "resolve": "从用户消息中提取，如'研发调到P50'提取出部门=研发",
        },
        "department": {
            "type": "string",
            "required": False,
            "resolve": "从用户消息中提取",
        },
        "target_percentile": {
            "type": "integer",
            "required": False,
            "default": 50,
            "resolve": "从用户消息中提取，如'调到P50'提取出50",
        },
    },

    "engine": "app.engine.salary_simulation.simulate",

    "narrative_prompt": "prompts/simulation_insight.txt",

    "render_components": [
        {
            "type": "MetricGrid",
            "columns": 2,
            "metrics": [
                {"label": "方案一：统一调至 P{target}", "field": "plan_a.total_budget", "format": "currency", "sub_field": "plan_a.pct_of_payroll", "sub_format": "占薪酬总盘 {value}%"},
                {"label": "方案二：分层调整（推荐）", "field": "plan_b.total_budget", "format": "currency", "sub_field": "plan_b.savings", "sub_format": "节省 {value}%", "highlight": True},
            ],
        },
        {
            "type": "ComparisonTable",
            "title": "分层明细",
            "columns": ["层级", "当前分位", "方案一目标", "方案二目标", "人数", "预算"],
            "data_field": "plan_b.details",
            "highlight_rule": "核心骨干层高亮",
        },
    ],

    "output_schema": {
        "plan_a": {
            "name": "统一调至 P50",
            "total_budget": 1870000,
            "headcount_affected": 18,
            "pct_of_payroll": 12.3,
        },
        "plan_b": {
            "name": "分层调整",
            "total_budget": 1260000,
            "savings": 33,
            "details": [
                {"grade": "L5", "current": 23, "target": 50, "headcount": 8, "budget": 640000}
            ],
        },
    },
}
