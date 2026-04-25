"""
AI 岗位库生成。

输入：组织画像（行业、规模、部门、管理层级、现有职级体系）
输出：20-40 个推荐岗位的结构化列表（name/department/function/8因子/职责描述）

设计要点：
- 单次 LLM 调用生成全部岗位（控制成本和时延 ~$0.05-0.10、~10-30 秒）
- LLM 直接给 8 因子档位，由 evaluate_with_factors 算分数 + 职级（确保跟用户后续手改时口径一致）
- 因子非法时不丢弃岗位，保留并标记 invalid_factors=True，前端展示但用 fallback 职级
- 职能必须落在 function_catalog 内，不在的岗位自动 mapping 到"通用职能"

不在本服务范围:
- 因子合法性的细粒度校验（PK ≥ TE ≥ FTA 约束）— 由 evaluate_with_factors 算分时
  抛异常隐式校验；细的"修正建议"放 P1 阶段做
- 流式输出 — 前端不需要看到岗位逐条出现，等 30 秒一次性返回更简单
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Optional

from app.tools.je.evaluator import evaluate_with_factors
from app.tools.je.function_catalog import FUNCTION_CATALOG, is_valid_function
from app.utils.openrouter import call_openrouter


_FACTOR_KEYS = (
    'practical_knowledge', 'managerial_knowledge', 'communication',
    'thinking_challenge', 'thinking_environment',
    'freedom_to_act', 'magnitude', 'nature_of_impact',
)


def generate_library(profile: dict, model: Optional[str] = None) -> dict:
    """
    根据组织画像调 LLM 生成推荐岗位库。

    Args:
        profile: {industry, headcount, departments, layers, department_layers?,
                  existing_grade_system}
        model:   可选，覆盖默认 LLM model

    Returns:
        {
          'entries': [{id, name, department, function, factors, hay_grade,
                       total_score, kh_score, ps_score, acc_score,
                       responsibilities, invalid_factors}],
          'generated_at': ISO 字符串,
          'model_used': str,
        }
    """
    raw_text = _call_llm(profile, model=model)
    parsed = _parse_json(raw_text)
    raw_entries = parsed.get('entries') or parsed.get('jobs') or []

    if not isinstance(raw_entries, list):
        raise ValueError(f'LLM 输出格式异常：entries 不是数组（raw: {raw_text[:300]}）')

    entries: list[dict] = []
    for i, e in enumerate(raw_entries):
        try:
            entries.append(_normalize_entry(e, i))
        except Exception as ex:
            # 单条异常不阻塞整批 — 这是 LLM 偶尔 hallucinate 单条不规范导致
            print(f'[je-library] 跳过非法 entry #{i}: {ex}')
            continue

    return {
        'entries': entries,
        'generated_at': datetime.utcnow().isoformat(),
        'model_used': model or os.getenv('OPENROUTER_MODEL', 'openai/gpt-5.4-mini'),
    }


# ---------------------------------------------------------------------------

def _normalize_entry(raw: dict, idx: int) -> dict:
    """规范化单条岗位 + 用 evaluate_with_factors 算分数和职级。"""
    name = (raw.get('name') or raw.get('title') or '').strip()
    department = (raw.get('department') or '').strip()
    function = (raw.get('function') or '').strip()
    if not name:
        raise ValueError('岗位名为空')
    if not is_valid_function(function):
        # LLM 偶尔会瞎编一个不在字典内的职能，回落到通用职能
        print(f'[je-library] 职能 {function!r} 不在字典，回落到"通用职能"')
        function = '通用职能'

    factors_raw = raw.get('factors') or {}
    factors = {k: str(factors_raw.get(k, '')).strip() for k in _FACTOR_KEYS}
    missing = [k for k in _FACTOR_KEYS if not factors[k]]
    if missing:
        raise ValueError(f'8 因子缺失: {missing}')

    invalid = False
    try:
        scored = evaluate_with_factors(factors)
    except Exception as ex:
        print(f'[je-library] 因子组合非法（{name}）: {ex}')
        invalid = True
        scored = {'kh_score': 0, 'ps_score': 0, 'acc_score': 0,
                  'total_score': 0, 'job_grade': None, 'profile': None}

    responsibilities = raw.get('responsibilities') or []
    if not isinstance(responsibilities, list):
        responsibilities = []

    return {
        'id': f'lib_{idx}',
        'name': name,
        'department': department or None,
        'function': function,
        'factors': factors,
        'hay_grade': scored.get('job_grade'),
        'total_score': scored.get('total_score'),
        'kh_score': scored.get('kh_score'),
        'ps_score': scored.get('ps_score'),
        'acc_score': scored.get('acc_score'),
        'profile': scored.get('profile'),
        'responsibilities': [str(r).strip() for r in responsibilities if r][:6],
        'invalid_factors': invalid,
    }


# ---------------------------------------------------------------------------
# LLM Prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """你是 Hay 岗位价值评估方法论专家，精通 Know-How / Problem Solving / Accountability 三维度评估。

任务：根据用户给的组织画像（行业 / 规模 / 部门 / 管理层级），为这家公司生成一套推荐岗位库。

输出要求：
- 严格输出 JSON，不要 markdown 包裹、不要任何解释文字
- 顶层是 {"entries": [...]}，每个 entry 包含：
    name: 岗位名（中文，要具体，如"高级产品经理"而不是"高级岗位"）
    department: 部门名（必须是用户给的 departments 之一）
    function: 业务职能（必须是下面"职能字典"中的一项）
    factors: { 8 因子档位，必须严格遵循 Hay 档位定义 }
    responsibilities: [3-5 条典型职责描述，每条 15-30 字]

- 岗位数量：根据规模动态决定
    < 50 人：覆盖每个部门主要层级，10-15 个岗位
    50-200 人：每个部门 3-5 个岗位，总 20-30 个
    200-500 人：每个部门 4-6 个岗位，总 25-40 个
    > 500 人：每个部门 5-8 个岗位，总 35-50 个
- 每个部门覆盖该部门可能的层级（不强求每层都有，可结合管理层级）
- 不同岗位之间要有合理的职级阶梯（如同部门 经理 > 高级专员 > 专员）

8 因子档位定义（严格使用这些值，不要额外加符号）：
  practical_knowledge: A-/A/A+/B-/B/B+/C-/C/C+/D-/D/D+/E-/E/E+/F-/F/F+/G-/G/G+/H-/H/H+/I-/I/I+
  managerial_knowledge: T-/T/T+/I-/I/I+/II-/II/II+/III-/III/III+/IV-/IV/IV+/V-/V/V+/VI-/VI/VI+/VII-/VII/VII+/VIII-/VIII/VIII+/IX-/IX/IX+
  communication: 1-/1/1+/2-/2/2+/3-/3/3+
  thinking_challenge: 1-/1/1+/2-/2/2+/3-/3/3+/4-/4/4+/5-/5/5+
  thinking_environment: A-/A/A+/B-/B/B+/C-/C/C+/D-/D/D+/E-/E/E+/F-/F/F+/G-/G/G+/H-/H/H+
  freedom_to_act: A-/A/A+/B-/B/B+/C-/C/C+/D-/D/D+/E-/E/E+/F-/F/F+/G-/G/G+/H-/H/H+/I-/I/I+
  magnitude: 取值 N（不可量化）/ 1- 到 5+ （根据岗位影响金额量级）
  nature_of_impact: 不可量化用 I-VI，可量化用 R/C/S/P

约束链（这是 Hay 的核心规则，违反会导致评估异常）：
- 专业知识 (PK) ≥ 思维环境 (TE) ≥ 行动自由度 (FTA)
- 三者在序列中的相对位置必须严格满足"PK 紧邻在 TE 上方一格 / TE 紧邻在 FTA 上方一格"
- 例：PK=D 时 TE 应该取 D- 或 C+，FTA 应该取 D- 的下一格 C+ 或更低
- 操作工 / 流水线类岗位用低档（A-C 区间），专业骨干用 D-E，VP+ 用 F-G

档位粗略锚点（仅供参考，需结合岗位实际职责）：
  专员 / 操作类：PK=B-C，MK=I，Comm=1-2，TC=1-2，TE=B-C，FTA=B-C
  经理 / 主管：    PK=D，MK=II-III，Comm=2，TC=3，TE=D-，FTA=C+
  总监 / VP：      PK=E-F，MK=III-V，Comm=2-3，TC=3-4，TE=E-，FTA=D+
  CXO / 总裁：     PK=G+，MK=VI+，Comm=3，TC=4-5，TE=F-，FTA=E+"""


def _call_llm(profile: dict, model: Optional[str] = None) -> str:
    user_msg = _build_user_message(profile)
    return call_openrouter(
        messages=[
            {'role': 'system', 'content': _SYSTEM_PROMPT},
            {'role': 'user', 'content': user_msg},
        ],
        model=model,
        temperature=0.3,
    )


def _build_user_message(profile: dict) -> str:
    industry = profile.get('industry') or '未知行业'
    headcount = profile.get('headcount') or 0
    departments = profile.get('departments') or []
    layers = profile.get('layers') or []
    existing = profile.get('existing_grade_system') or '暂无正式职级'

    function_catalog_str = '\n'.join(
        f'  {group}: {", ".join(funcs)}'
        for group, funcs in FUNCTION_CATALOG.items()
    )

    return f"""组织画像：
- 行业：{industry}
- 员工规模：{headcount} 人
- 部门：{', '.join(departments) if departments else '（未提供）'}
- 管理层级：{' → '.join(layers) if layers else '（未提供）'}
- 现有职级体系：{existing}

可选职能（function 字段必须从这里取）：
{function_catalog_str}

请生成这家公司的推荐岗位库，严格输出 JSON：
{{"entries": [{{"name": "...", "department": "...", "function": "...", "factors": {{...}}, "responsibilities": [...]}}]}}"""


def _parse_json(raw: str) -> dict:
    """LLM 偶尔包 markdown 或加前后文字，做点容错。"""
    raw = raw.strip()
    fence = re.search(r'```(?:json)?\s*(\{.+\})\s*```', raw, re.DOTALL)
    if fence:
        raw = fence.group(1).strip()
    brace_match = re.search(r'\{.*\}', raw, re.DOTALL)
    if brace_match:
        raw = brace_match.group(0)
    return json.loads(raw)
