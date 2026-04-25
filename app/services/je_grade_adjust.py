"""
拖拽职级反推：用户在图谱里把岗位卡从 G12 拖到 G14，由后端算出对应的 8 因子。

策略（粗-细两步）：
1. 单维粗调 — 遍历 PK (Practical Knowledge) 27 个档位，找出让 job_grade 最接近
   target_grade 的那个；其他 7 个因子保持不变
2. 如果单调 PK 还差距 ≥ 2 → 同步调 MK（Managerial Knowledge）30 档，二维搜索

约束链 (PK ≥ TE ≥ FTA) 在算分时引擎不强制校验（evaluate_with_factors 只查表算分），
偶尔会出现"PK 提了 TE 没跟上"的情况。这种情况算出的总分仍然有效，但 profile_match
可能不理想。本 v1 不做约束链联动调整 — 拖拽是"快速近似"，用户对结果不满意可以
进岗位详情页手动校准。

返回结构跟 evaluate_with_factors 一致 + factors 字段。
"""
from __future__ import annotations

from typing import Optional

from app.tools.je.evaluator import evaluate_with_factors


_PK_LEVELS = [
    'A-', 'A', 'A+', 'B-', 'B', 'B+', 'C-', 'C', 'C+',
    'D-', 'D', 'D+', 'E-', 'E', 'E+', 'F-', 'F', 'F+',
    'G-', 'G', 'G+', 'H-', 'H', 'H+', 'I-', 'I', 'I+',
]
_MK_LEVELS = [
    'T-', 'T', 'T+', 'I-', 'I', 'I+', 'II-', 'II', 'II+',
    'III-', 'III', 'III+', 'IV-', 'IV', 'IV+', 'V-', 'V', 'V+',
    'VI-', 'VI', 'VI+', 'VII-', 'VII', 'VII+', 'VIII-', 'VIII', 'VIII+',
    'IX-', 'IX', 'IX+',
]


def adjust_to_target_grade(current_factors: dict, target_grade: int) -> dict:
    """
    Args:
        current_factors: 当前 8 因子档位
        target_grade:    用户拖到的目标 Hay 职级（数字，如 14）

    Returns:
        {
          'factors': {新的 8 因子},
          'result':  evaluate_with_factors 返回结构（含 kh/ps/acc/total/job_grade...）,
          'achieved': bool,           # 是否精确命中 target_grade
          'diff': int,                # 实际职级 - target_grade
          'changed_factors': [...],   # 跟原 factors 不同的因子名
        }
    """
    base = dict(current_factors)
    base_result = _safe_eval(base)
    if base_result.get('job_grade') == target_grade:
        return _build_response(base, base_result, current_factors, target_grade)

    # Step 1: 单维 PK 搜索
    best_factors = dict(base)
    best_result = base_result
    best_diff = abs((base_result.get('job_grade') or 0) - target_grade)

    for pk in _PK_LEVELS:
        if pk == base.get('practical_knowledge'):
            continue
        trial = {**base, 'practical_knowledge': pk}
        r = _safe_eval(trial)
        if r is None:
            continue
        diff = abs((r.get('job_grade') or 0) - target_grade)
        if diff < best_diff or (diff == best_diff and _closer_to_base(trial, base, best_factors)):
            best_diff = diff
            best_factors = trial
            best_result = r
        if best_diff == 0:
            return _build_response(best_factors, best_result, current_factors, target_grade)

    # Step 2: 如果还差 ≥ 2，二维搜索 PK + MK（成本：27 × 30 = 810 次纯计算，毫秒级）
    if best_diff >= 2:
        for pk in _PK_LEVELS:
            for mk in _MK_LEVELS:
                trial = {**base, 'practical_knowledge': pk, 'managerial_knowledge': mk}
                r = _safe_eval(trial)
                if r is None:
                    continue
                diff = abs((r.get('job_grade') or 0) - target_grade)
                if diff < best_diff or (diff == best_diff and _closer_to_base(trial, base, best_factors)):
                    best_diff = diff
                    best_factors = trial
                    best_result = r
                if best_diff == 0:
                    return _build_response(best_factors, best_result, current_factors, target_grade)

    return _build_response(best_factors, best_result, current_factors, target_grade)


def _safe_eval(factors: dict) -> Optional[dict]:
    try:
        return evaluate_with_factors(factors)
    except Exception:
        return None


def _build_response(new_factors: dict, result: dict, original: dict, target: int) -> dict:
    actual_grade = result.get('job_grade')
    changed = [k for k in new_factors if new_factors.get(k) != original.get(k)]
    return {
        'factors': new_factors,
        'result': {k: v for k, v in result.items() if k != 'factors'},
        'achieved': actual_grade == target,
        'diff': (actual_grade - target) if actual_grade is not None else None,
        'changed_factors': changed,
    }


# 当多个 trial 让 best_diff 一样小时，优先选"改动最小"的（跟 base 差异因子最少）
def _closer_to_base(trial: dict, base: dict, current_best: dict) -> bool:
    trial_diff_count = sum(1 for k, v in trial.items() if base.get(k) != v)
    best_diff_count = sum(1 for k, v in current_best.items() if base.get(k) != v)
    return trial_diff_count < best_diff_count
