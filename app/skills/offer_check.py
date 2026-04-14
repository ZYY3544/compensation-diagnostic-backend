"""
Skill: 候选人定薪建议

轻模式。给出候选人薪资在市场和公司内部中的定位，以及建议薪资范围。
不需要已上传数据也能用（只对标市场），有数据的话额外对标内部。
"""

SKILL = {
    "key": "offer_check",
    "display_name": "候选人定薪建议",
    "mode": "light",
    "chip_label": "🤝 候选人定薪建议",

    "triggers": [
        r"候选人.*多少钱",
        r"给多少.*合适",
        r"要价.*给不给",
        r"offer.*薪酬",
        r"定薪",
        r"能不能给.*[kK万]",
        r"新人.*定多少",
    ],

    "preconditions": [
        "has_market_data",
        # has_data_snapshot 不是必须的，没有的话只做市场对标
    ],

    "input_params": {
        "job_title": {
            "type": "string",
            "required": True,
            "resolve": "从用户消息中提取，提取不到就追问",
            "example": "高级前端工程师",
        },
        "grade": {
            "type": "string",
            "required": True,
            "resolve": "从用户消息中提取，提取不到就追问",
            "example": "L5",
        },
        "city": {
            "type": "string",
            "required": True,
            "resolve": "从用户资料或已上传数据中取，取不到就追问",
            "default": "全国",
        },
        "candidate_ask": {
            "type": "number",
            "required": False,
            "resolve": "从用户消息中提取，有就分析，没有就只给市场范围",
            "example": 35000,
        },
    },

    "engine": "app.engine.offer_check.analyze",

    "narrative_prompt": "prompts/offer_insight.txt",

    "render_components": [
        {
            "type": "MetricGrid",
            "columns": 3,
            "metrics": [
                {"label": "市场 P25", "field": "market.p25", "format": "currency"},
                {"label": "市场 P50", "field": "market.p50", "format": "currency", "highlight": True},
                {"label": "市场 P75", "field": "market.p75", "format": "currency"},
            ],
        },
        {
            "type": "RangeCard",
            "title": "候选人定位",
            "description": "仅在有候选人期望薪资时展示",
            "range_min": "market.p25",
            "range_max": "market.p75",
            "marker": "candidate.ask",
            "internal_median": "internal.same_grade_median",
        },
    ],

    "output_schema": {
        "market": {"function": "软件开发", "standard_grade": "高级专业人员", "city": "深圳", "p25": 28000, "p50": 35000, "p75": 45000},
        "internal": {"same_grade_median": 25000, "same_grade_range": [18000, 38000], "headcount": 8},
        "candidate": {"ask": 35000, "market_percentile": 50, "internal_percentile": 78},
        "recommendation": {"suggested_range": [30000, 38000], "rationale": "市场P50附近，内部不会严重倒挂"},
    },
}
