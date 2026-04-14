"""
Skill: 完整薪酬诊断

重模式。引导用户走完访谈→数据上传→数据确认→五模块分析→诊断建议→导出的完整流程。
"""

SKILL = {
    "key": "full_diagnosis",
    "display_name": "完整薪酬诊断",
    "mode": "heavy",
    "chip_label": "📊 做一次完整的薪酬诊断",

    "triggers": [
        r"完整.*诊断",
        r"全面.*诊断",
        r"薪酬诊断",
        r"薪酬体检",
        r"帮我.*看看.*薪酬体系",
        r"做.*诊断",
        r"薪酬.*有没有问题",
        r"薪酬.*哪里有问题",
    ],

    "preconditions": [],  # 流程内引导上传，不需要预置条件

    "input_params": {},  # 流程内逐步收集，不需要预置参数

    "engine": "app.engine.full_diagnosis.run_all",

    "narrative_prompt": "prompts/diagnosis_summary.txt",

    "render_components": [
        {
            "type": "SummaryCard",
            "description": "诊断摘要，3-5 条核心发现，带 P1/P2/P3 优先级标签",
        },
        {
            "type": "ModuleCards",
            "description": "五个模块各自的证据卡片，按优先级顺序出现",
        },
        {
            "type": "RecommendationCard",
            "description": "3-5 条行动建议，具体到可执行",
        },
        {
            "type": "ExportButton",
            "description": "导出 PDF 报告",
        },
    ],

    # ---- 文档字段（不参与运行时逻辑）----

    "output_schema": {
        "full_analysis_json": {
            "external": "外部竞争力全量结果",
            "internal_equity": "内部公平性全量结果",
            "pay_mix": "薪酬结构全量结果",
            "performance": "绩效关联全量结果",
            "cost_trend": "人工成本趋势全量结果",
        }
    },
}
