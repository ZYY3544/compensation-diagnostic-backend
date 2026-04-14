"""
Skill Registry

启动时自动扫描 app/skills/ 目录下所有 skill 文件，
加载每个文件导出的 SKILL 字典，校验后注册。

新增能力只需要在 skills/ 下新建一个 .py 文件并导出 SKILL 字典即可。
"""

import importlib
import os
from typing import Optional
from .schema import validate_skill


class SkillRegistry:
    """
    意图识别从关键词正则匹配切换到了全量 AI 分类；
    skill 文件里的 `triggers` 字段保留作为人类阅读的文档，
    运行时不再编译成正则、不再参与匹配。
    """

    def __init__(self):
        self._skills = {}       # key -> skill dict

    def register(self, skill: dict) -> None:
        """注册一个 skill，校验后加入注册表"""
        validate_skill(skill)
        key = skill["key"]
        if key in self._skills:
            raise ValueError(f"Skill key 重复: {key}")
        self._skills[key] = skill

    def get(self, key: str) -> Optional[dict]:
        """按 key 获取 skill 定义"""
        return self._skills.get(key)

    def list_all(self) -> list:
        """列出所有已注册的 skill"""
        return list(self._skills.values())

    def list_chips(self) -> list:
        """列出所有有 chip_label 的 skill（用于首屏展示）"""
        return [s for s in self._skills.values() if s.get("chip_label")]

    def check_preconditions(self, skill_key: str, context: dict) -> list:
        """
        检查前置条件是否满足，返回未满足的条件列表。
        context 示例: {"has_data_snapshot": True, "has_market_data": True, ...}
        """
        skill = self._skills.get(skill_key)
        if not skill:
            return [f"unknown_skill: {skill_key}"]
        unmet = []
        for pc in skill["preconditions"]:
            if not context.get(pc, False):
                unmet.append(pc)
        return unmet

    def get_missing_params(self, skill_key: str, provided_params: dict) -> list:
        """
        检查必填参数是否齐全，返回缺失的参数名列表。
        有 default 值的即使 required=True 也不算缺失。
        """
        skill = self._skills.get(skill_key)
        if not skill:
            return []
        missing = []
        for param_name, param_def in skill["input_params"].items():
            if not param_def.get("required", False):
                continue
            if param_name in provided_params:
                continue
            if "default" in param_def:
                continue  # 有默认值就不算缺失
            missing.append(param_name)
        return missing

    def apply_defaults(self, skill_key: str, provided_params: dict) -> dict:
        """用 input_params 的 default 补齐未提供的参数"""
        skill = self._skills.get(skill_key)
        if not skill:
            return provided_params
        result = dict(provided_params or {})
        for param_name, param_def in skill["input_params"].items():
            if param_name in result:
                continue
            if "default" in param_def:
                result[param_name] = param_def["default"]
        return result


# 全局单例
_registry = SkillRegistry()


def get_registry() -> SkillRegistry:
    return _registry


def auto_discover():
    """自动扫描当前目录下所有 skill 文件并注册"""
    skills_dir = os.path.dirname(__file__)
    skip_files = {"__init__.py", "schema.py", "registry.py"}

    for filename in sorted(os.listdir(skills_dir)):
        if filename.endswith(".py") and filename not in skip_files:
            module_name = filename[:-3]
            try:
                module = importlib.import_module(f".{module_name}", package=__package__)
                if hasattr(module, "SKILL"):
                    # 从模块 docstring 抽一句话作为 AI 意图识别的 description：
                    # - 按空行分段，跳过 "Skill: xxx" 标题段
                    # - 取第一段说明，合并成单行
                    skill = module.SKILL
                    if "description" not in skill and module.__doc__:
                        paragraphs = [p.strip() for p in module.__doc__.strip().split("\n\n") if p.strip()]
                        desc = ""
                        for p in paragraphs:
                            first_line = p.split("\n", 1)[0].strip().lower()
                            if first_line.startswith(("skill:", "skill ")):
                                continue
                            desc = " ".join(l.strip() for l in p.split("\n") if l.strip())
                            break
                        if desc:
                            skill["description"] = desc
                    _registry.register(skill)
                    print(f"[SkillRegistry] Registered: {skill['key']}")
                else:
                    print(f"[SkillRegistry] Skipped {filename}: no SKILL export")
            except Exception as e:
                print(f"[SkillRegistry] Failed to load {filename}: {e}")
