"""
Skill Schema 定义与校验

每个 skill 必须导出一个 SKILL 字典，符合以下 schema。
注册时自动校验，缺字段或类型不对直接报错。
"""

REQUIRED_FIELDS = {
    "key": str,
    "display_name": str,
    "mode": str,            # "light" | "heavy"
    "triggers": list,       # 关键词匹配规则（正则字符串列表）
    "preconditions": list,  # 前置条件检查项，如 ["has_data_snapshot", "has_market_data"]
    "input_params": dict,   # 需要的输入参数定义
    "engine": str,          # 分析引擎函数路径，如 "app.engine.external.analyze"，纯问答类填 "none"
    "narrative_prompt": str, # 叙事 prompt 文件路径，如 "prompts/benchmark_insight.txt"
    "render_components": list, # 渲染组件声明列表，无右侧面板填 []
}

OPTIONAL_FIELDS = {
    "chip_label": str,       # 首屏 chip 文案，None 表示不在首屏展示
    "output_schema": dict,   # 输出结构示例（文档用途，不做运行时校验）
    "description": str,      # 给 AI 意图识别看的一句话说明；未显式填会自动从 module docstring 抽
}

VALID_MODES = {"light", "heavy"}

VALID_PRECONDITIONS = {
    "has_data_snapshot",     # 用户已上传过薪酬数据
    "has_market_data",       # 系统有市场薪酬数据
    "has_performance_data",  # 上传数据中绩效字段非空
    "has_business_data",     # Sheet 2 经营数据非空
}


def validate_skill(skill: dict) -> None:
    """校验 skill 字典是否符合 schema，不符合直接抛异常"""

    # 检查必填字段
    for field, expected_type in REQUIRED_FIELDS.items():
        if field not in skill:
            raise ValueError(f"Skill '{skill.get('key', '?')}' 缺少必填字段: {field}")
        if not isinstance(skill[field], expected_type):
            raise TypeError(
                f"Skill '{skill['key']}' 字段 '{field}' 类型错误: "
                f"期望 {expected_type.__name__}，实际 {type(skill[field]).__name__}"
            )

    # 检查 mode 合法性
    if skill["mode"] not in VALID_MODES:
        raise ValueError(f"Skill '{skill['key']}' mode 不合法: {skill['mode']}，必须是 {VALID_MODES}")

    # 检查 preconditions 合法性
    for pc in skill["preconditions"]:
        if pc not in VALID_PRECONDITIONS:
            raise ValueError(f"Skill '{skill['key']}' 未知的 precondition: {pc}")

    # 检查 input_params 中每个参数的定义
    for param_name, param_def in skill["input_params"].items():
        if not isinstance(param_def, dict):
            raise TypeError(f"Skill '{skill['key']}' input_params.{param_name} 必须是 dict")
        if "type" not in param_def:
            raise ValueError(f"Skill '{skill['key']}' input_params.{param_name} 缺少 'type'")
