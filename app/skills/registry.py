"""
Skill Registry

启动时自动扫描 app/skills/ 目录下所有 skill 文件，
加载每个文件导出的 SKILL 字典，校验后注册。

新增能力只需要在 skills/ 下新建一个 .py 文件并导出 SKILL 字典即可。
"""

import importlib
import os
import re
from typing import Optional
from .schema import validate_skill


class SkillRegistry:
    def __init__(self):
        self._skills = {}       # key -> skill dict
        self._keyword_rules = []  # [(compiled_pattern, skill_key), ...]

    def register(self, skill: dict) -> None:
        """注册一个 skill，校验后加入注册表"""
        validate_skill(skill)
        key = skill["key"]
        if key in self._skills:
            raise ValueError(f"Skill key 重复: {key}")
        self._skills[key] = skill

        # 编译关键词规则
        for pattern in skill["triggers"]:
            self._keyword_rules.append((re.compile(pattern, re.IGNORECASE), key))

    def get(self, key: str) -> Optional[dict]:
        """按 key 获取 skill 定义"""
        return self._skills.get(key)

    def list_all(self) -> list:
        """列出所有已注册的 skill"""
        return list(self._skills.values())

    def list_chips(self) -> list:
        """列出所有有 chip_label 的 skill（用于首屏展示）"""
        return [s for s in self._skills.values() if s.get("chip_label")]

    def match_by_keyword(self, user_message: str) -> Optional[str]:
        """用关键词规则匹配意图，返回 skill key 或 None"""
        for pattern, key in self._keyword_rules:
            if pattern.search(user_message):
                return key
        return None

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
        """
        skill = self._skills.get(skill_key)
        if not skill:
            return []
        missing = []
        for param_name, param_def in skill["input_params"].items():
            if param_def.get("required", False) and param_name not in provided_params:
                missing.append(param_name)
        return missing


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
                    _registry.register(module.SKILL)
                    print(f"[SkillRegistry] Registered: {module.SKILL['key']}")
                else:
                    print(f"[SkillRegistry] Skipped {filename}: no SKILL export")
            except Exception as e:
                print(f"[SkillRegistry] Failed to load {filename}: {e}")
